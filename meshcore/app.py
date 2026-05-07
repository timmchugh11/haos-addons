import asyncio
import concurrent.futures
import json
import os
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from meshcore import EventType, MeshCore


APP_DIR = Path("/app")
UI_DIR = APP_DIR / "custom-ui"
DATA_DIR = Path(os.environ.get("MESHCORE_DATA_DIR", "/data/.meshcore"))
MESSAGE_ARCHIVE = DATA_DIR / "messages.json"

DEVICE = os.environ.get("MESHCORE_DEVICE", "/dev/ttyACM0")
TRANSPORT = os.environ.get("MESHCORE_TRANSPORT", "serial")
BAUDRATE = int(os.environ.get("MESHCORE_BAUDRATE", "115200"))
SERIAL_CX_DELAY = float(os.environ.get("MESHCORE_SERIAL_CX_DELAY", "2.0"))
BLE_PIN = os.environ.get("MESHCORE_BLE_PIN", "123456")
DEBUG = os.environ.get("MESHCORE_DEBUG", "false").lower() in {"1", "true", "yes", "on"}


app = FastAPI(title="MeshCore Add-on")
app.mount("/custom-ui", StaticFiles(directory=str(UI_DIR)), name="custom-ui")


class MeshState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.connected = False
        self.status = "Starting"
        self.device: Dict[str, Any] = {}
        self.device_info: Dict[str, Any] = {}
        self.channels: List[Dict[str, Any]] = []
        self.contacts: Dict[str, Dict[str, Any]] = {}
        self.messages: List[Dict[str, Any]] = []
        self.next_message_id = 1
        self.started_at = datetime.now(timezone.utc)
        self.updated_at = self.started_at

    def set_status(self, status: str, connected: Optional[bool] = None) -> None:
        with self.lock:
            self.status = status
            if connected is not None:
                self.connected = connected
            self.updated_at = datetime.now(timezone.utc)


state = MeshState()
worker_loop: Optional[asyncio.AbstractEventLoop] = None
meshcore_client: Optional[MeshCore] = None


class SendMessageRequest(BaseModel):
    target_type: Literal["channel", "direct"]
    text: str = Field(min_length=1, max_length=512)
    channel_idx: Optional[int] = Field(default=None, ge=0, le=255)
    contact: Optional[str] = Field(default=None, min_length=6, max_length=128)
    retry: bool = True


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def event_type_value(event: Any) -> str:
    value = getattr(event, "type", None)
    return getattr(value, "value", str(value))


def event_payload(event: Any) -> Any:
    return json_safe(getattr(event, "payload", None))


def json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, bytearray):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    return value


def next_message_id() -> int:
    with state.lock:
        message_id = state.next_message_id
        state.next_message_id += 1
        return message_id


def append_message(message: Dict[str, Any]) -> Dict[str, Any]:
    if "id" not in message:
        message["id"] = next_message_id()
    with state.lock:
        state.messages.insert(0, message)
        state.messages = state.messages[:1000]
        state.updated_at = datetime.now(timezone.utc)
    save_messages()
    return message


def save_messages() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with state.lock:
            payload = {
                "next_message_id": state.next_message_id,
                "messages": state.messages[:1000],
            }
        MESSAGE_ARCHIVE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_messages() -> None:
    try:
        data = json.loads(MESSAGE_ARCHIVE.read_text(encoding="utf-8"))
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            return
        with state.lock:
            state.messages = messages[:1000]
            max_id = max((int(m.get("id", 0) or 0) for m in state.messages), default=0)
            state.next_message_id = max(int(data.get("next_message_id", 0) or 0), max_id + 1, 1)
    except FileNotFoundError:
        return
    except Exception:
        return


load_messages()


def public_channel(idx: Optional[int], name: str) -> bool:
    return idx == 0 or bool(name and name.startswith("#"))


def channel_name(idx: Optional[int]) -> str:
    with state.lock:
        for ch in state.channels:
            if ch.get("idx") == idx:
                return ch.get("name", "")
    return "Public" if idx == 0 else ""


def resolve_contact(value: str) -> str:
    needle = value.strip().lower()
    if not needle:
        raise ValueError("contact is required")
    with state.lock:
        for pubkey, contact in state.contacts.items():
            pubkey_l = pubkey.lower()
            name = str(contact.get("adv_name") or "").lower()
            if pubkey_l == needle or pubkey_l.startswith(needle) or name == needle:
                return pubkey
    if all(c in "0123456789abcdef" for c in needle) and len(needle) >= 6:
        return needle
    raise ValueError(f"unknown contact: {value}")


async def connect_meshcore() -> None:
    global meshcore_client

    while True:
        try:
            state.set_status(f"Connecting to {DEVICE}", False)
            if TRANSPORT == "ble":
                mc = await MeshCore.create_ble(
                    DEVICE,
                    pin=BLE_PIN,
                    debug=DEBUG,
                    default_timeout=10,
                    auto_reconnect=False,
                )
            else:
                mc = await MeshCore.create_serial(
                    DEVICE,
                    baudrate=BAUDRATE,
                    debug=DEBUG,
                    default_timeout=10,
                    auto_reconnect=False,
                    cx_dly=SERIAL_CX_DELAY,
                )

            meshcore_client = mc
            await wire_events(mc)
            await load_initial_data(mc)
            await mc.start_auto_message_fetching()
            state.set_status("Connected", True)

            while True:
                await asyncio.sleep(5)
        except Exception as exc:
            state.set_status(f"Connection error: {exc}", False)
            try:
                if meshcore_client:
                    await meshcore_client.disconnect()
            except Exception:
                pass
            meshcore_client = None
            await asyncio.sleep(15)


async def wire_events(mc: MeshCore) -> None:
    async def on_channel_msg(event) -> None:
        payload = event.payload or {}
        idx = payload.get("channel_idx")
        name = channel_name(idx)
        append_message({
            "direction": "incoming",
            "status": "received",
            "conversation_type": "channel",
            "channel_idx": idx,
            "channel_name": name,
            "is_private": not public_channel(idx, name),
            "sender": payload.get("sender", "") or payload.get("pubkey_prefix", ""),
            "sender_pubkey": payload.get("sender_pubkey", "") or payload.get("pubkey_prefix", ""),
            "text": payload.get("text", ""),
            "timestamp": utcnow(),
            "sender_timestamp": payload.get("sender_timestamp"),
            "hops": payload.get("path_len", 0) or 0,
            "path_hashes": payload.get("path_hashes") or [],
            "path_names": payload.get("path_names") or [],
        })

    async def on_contact_msg(event) -> None:
        payload = event.payload or {}
        append_message({
            "direction": "incoming",
            "status": "received",
            "conversation_type": "direct",
            "channel_idx": None,
            "channel_name": "Direct",
            "sender": payload.get("sender", "") or payload.get("pubkey_prefix", ""),
            "sender_pubkey": payload.get("pubkey_prefix", ""),
            "contact": payload.get("pubkey_prefix", ""),
            "text": payload.get("text", ""),
            "timestamp": utcnow(),
            "sender_timestamp": payload.get("sender_timestamp"),
            "hops": payload.get("path_len", 0) or 0,
            "path_hashes": [],
            "path_names": [],
        })

    async def on_disconnect(event) -> None:
        state.set_status(f"Disconnected: {(event.payload or {}).get('reason', 'unknown')}", False)

    mc.subscribe(EventType.CHANNEL_MSG_RECV, on_channel_msg)
    mc.subscribe(EventType.CONTACT_MSG_RECV, on_contact_msg)
    mc.subscribe(EventType.DISCONNECTED, on_disconnect)


async def load_initial_data(mc: MeshCore) -> None:
    with state.lock:
        state.device = dict(mc.self_info or {})

    device_query = await mc.commands.send_device_query()
    if device_query and device_query.type != EventType.ERROR:
        with state.lock:
            state.device_info = dict(device_query.payload or {})

    channels: List[Dict[str, Any]] = []
    empty_count = 0
    for idx in range(8):
        try:
            result = await mc.commands.get_channel(idx)
        except Exception:
            result = None
        if not result or result.type == EventType.ERROR:
            empty_count += 1
            if empty_count >= 3 and channels:
                break
            continue
        empty_count = 0
        payload = result.payload or {}
        name = payload.get("channel_name") or payload.get("name") or f"Channel {idx}"
        channels.append({"idx": idx, "name": name, "is_private": not public_channel(idx, name)})

    if not channels:
        channels = [{"idx": 0, "name": "Public", "is_private": False}]
    with state.lock:
        state.channels = channels

    contacts_result = await mc.commands.get_contacts(timeout=10)
    if contacts_result and contacts_result.type != EventType.ERROR and contacts_result.payload:
        with state.lock:
            state.contacts = dict(contacts_result.payload)

    try:
        await mc.commands.export_private_key()
    except Exception:
        pass


def start_worker() -> None:
    global worker_loop
    worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(worker_loop)
    worker_loop.run_until_complete(connect_meshcore())


@app.on_event("startup")
async def startup() -> None:
    thread = threading.Thread(target=start_worker, daemon=True)
    thread.start()


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(str(UI_DIR / "index.html"))


@app.get("/api/v1/status")
async def api_status() -> Dict[str, Any]:
    with state.lock:
        return {
            "connected": state.connected,
            "status": state.status,
            "device": state.device,
            "device_info": state.device_info,
            "updated_at": state.updated_at.isoformat(),
        }


@app.get("/api/v1/stats")
async def api_stats() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=72)
    with state.lock:
        messages = [
            m for m in state.messages
            if public_channel(m.get("channel_idx"), m.get("channel_name", ""))
            and parse_time(m.get("timestamp")) >= cutoff
        ]
        unique_senders = {m.get("sender") or m.get("sender_pubkey") for m in messages if m.get("sender") or m.get("sender_pubkey")}
        hops = [m.get("hops", 0) or 0 for m in messages if (m.get("hops", 0) or 0) > 0]
        hours = Counter(parse_time(m.get("timestamp")).hour for m in messages if m.get("timestamp"))
        clients = repeaters = rooms = 0
        for contact in state.contacts.values():
            node_type = int(contact.get("type", 0) or 0)
            if node_type == 2:
                repeaters += 1
            elif node_type == 3:
                rooms += 1
            else:
                clients += 1
        return {
            "generated_at": now.isoformat(),
            "period_hours": 72,
            "connected": state.connected,
            "status": state.status,
            "total_messages": len(messages),
            "unique_senders": len(unique_senders),
            "active_clients": clients,
            "active_repeaters": repeaters,
            "active_room_servers": rooms,
            "avg_hops": round(sum(hops) / len(hops), 2) if hops else 0.0,
            "peak_hour": hours.most_common(1)[0][0] if hours else None,
        }


@app.get("/api/v1/nodes")
async def api_nodes() -> List[Dict[str, Any]]:
    nodes = []
    with state.lock:
        for pubkey, contact in state.contacts.items():
            raw_type = int(contact.get("type", 0) or 0)
            adv_lat = contact.get("adv_lat") or None
            adv_lon = contact.get("adv_lon") or None
            if adv_lat == 0.0 and adv_lon == 0.0:
                adv_lat = adv_lon = None
            nodes.append({
                "name": contact.get("adv_name") or pubkey[:12],
                "public_key": pubkey,
                "pubkey_prefix": pubkey[:12],
                "type": {2: "repeater", 3: "room_server"}.get(raw_type, "client"),
                "last_seen": contact.get("last_seen") or contact.get("last_advert"),
                "adv_lat": adv_lat,
                "adv_lon": adv_lon,
                "battery_mv": contact.get("battery_mv"),
            })
    return sorted(nodes, key=lambda n: (n["type"], n["name"]))


@app.get("/api/v1/messages")
async def api_messages(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: str = Query(default="all", pattern="^(all|public|channel|direct)$"),
) -> Dict[str, Any]:
    with state.lock:
        messages = list(state.messages)
        if scope == "public":
            messages = [
                m for m in messages
                if m.get("conversation_type", "channel") == "channel"
                and public_channel(m.get("channel_idx"), m.get("channel_name", ""))
            ]
        elif scope in {"channel", "direct"}:
            messages = [m for m in messages if m.get("conversation_type", "channel") == scope]
        page = messages[offset:offset + limit]
        return {"total": len(messages), "limit": limit, "offset": offset, "scope": scope, "items": page}


@app.get("/api/v1/conversations")
async def api_conversations() -> List[Dict[str, Any]]:
    conversations: Dict[str, Dict[str, Any]] = {}
    with state.lock:
        for channel in state.channels:
            key = f"channel:{channel.get('idx')}"
            conversations[key] = {
                "id": key,
                "type": "channel",
                "label": channel.get("name") or f"Channel {channel.get('idx')}",
                "channel_idx": channel.get("idx"),
                "is_private": channel.get("is_private", False),
                "last_message": "",
                "last_timestamp": None,
                "unread": 0,
            }
        for pubkey, contact in state.contacts.items():
            key = f"direct:{pubkey}"
            conversations[key] = {
                "id": key,
                "type": "direct",
                "label": contact.get("adv_name") or pubkey[:12],
                "contact": pubkey,
                "pubkey_prefix": pubkey[:12],
                "last_message": "",
                "last_timestamp": None,
                "unread": 0,
            }
        for message in reversed(state.messages):
            if message.get("conversation_type") == "direct":
                contact = message.get("contact") or message.get("sender_pubkey") or message.get("sender")
                key = f"direct:{contact}"
                if key not in conversations:
                    conversations[key] = {
                        "id": key,
                        "type": "direct",
                        "label": str(contact or "Direct")[:12],
                        "contact": contact,
                        "pubkey_prefix": str(contact or "")[:12],
                        "last_message": "",
                        "last_timestamp": None,
                        "unread": 0,
                    }
            else:
                key = f"channel:{message.get('channel_idx', 0)}"
                if key not in conversations:
                    conversations[key] = {
                        "id": key,
                        "type": "channel",
                        "label": message.get("channel_name") or "Public",
                        "channel_idx": message.get("channel_idx", 0),
                        "is_private": message.get("is_private", False),
                        "last_message": "",
                        "last_timestamp": None,
                        "unread": 0,
                    }
            conv = conversations[key]
            conv["last_message"] = message.get("text", "")
            conv["last_timestamp"] = message.get("timestamp")
            if message.get("direction") == "incoming":
                conv["unread"] += 1
        return sorted(conversations.values(), key=lambda c: c.get("last_timestamp") or "", reverse=True)


@app.post("/api/v1/messages")
async def api_send_message(request: SendMessageRequest) -> Dict[str, Any]:
    if not state.connected or not meshcore_client or not worker_loop:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message text is required")

    async def send() -> Any:
        if request.target_type == "channel":
            if request.channel_idx is None:
                raise ValueError("channel_idx is required")
            return await meshcore_client.commands.send_chan_msg(request.channel_idx, text)
        contact = resolve_contact(request.contact or "")
        if request.retry:
            return await meshcore_client.commands.send_msg_with_retry(contact, text, min_timeout=3)
        return await meshcore_client.commands.send_msg(contact, text)

    future = asyncio.run_coroutine_threadsafe(send(), worker_loop)
    try:
        result = future.result(timeout=45)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except concurrent.futures.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="message send timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"message send failed: {exc}") from exc

    if result is None:
        status = "ack_timeout"
        payload = {}
        result_type = "ack_timeout"
    else:
        result_type = event_type_value(result)
        payload = event_payload(result)
        status = "sent" if result_type in {EventType.OK.value, EventType.MSG_SENT.value} else "failed"
        if result_type == EventType.ERROR.value:
            raise HTTPException(status_code=502, detail={"status": status, "event": result_type, "payload": payload})

    message: Dict[str, Any] = {
        "direction": "outgoing",
        "status": status,
        "conversation_type": request.target_type,
        "text": text,
        "timestamp": utcnow(),
        "hops": 0,
        "send_result": {"event": result_type, "payload": payload},
    }
    if request.target_type == "channel":
        message["channel_idx"] = request.channel_idx
        message["channel_name"] = channel_name(request.channel_idx)
        message["is_private"] = not public_channel(request.channel_idx, message["channel_name"])
    else:
        contact_key = resolve_contact(request.contact or "")
        message["channel_idx"] = None
        message["channel_name"] = "Direct"
        message["contact"] = contact_key
        message["recipient"] = contact_key[:12]

    append_message(message)
    return {"ok": status != "failed", "status": status, "message": message}


@app.get("/api/v1/channels")
async def api_channels() -> List[Dict[str, Any]]:
    with state.lock:
        return list(state.channels)


def parse_time(value: Any) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)
