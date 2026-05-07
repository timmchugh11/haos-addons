import asyncio
import os
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from meshcore import EventType, MeshCore


APP_DIR = Path("/app")
UI_DIR = APP_DIR / "custom-ui"

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


def public_channel(idx: Optional[int], name: str) -> bool:
    return idx == 0 or bool(name and name.startswith("#"))


def channel_name(idx: Optional[int]) -> str:
    with state.lock:
        for ch in state.channels:
            if ch.get("idx") == idx:
                return ch.get("name", "")
    return "Public" if idx == 0 else ""


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
        if not public_channel(idx, name):
            return
        with state.lock:
            state.messages.insert(0, {
                "id": len(state.messages) + 1,
                "channel_idx": idx,
                "channel_name": name,
                "sender": payload.get("sender", "") or payload.get("pubkey_prefix", ""),
                "sender_pubkey": payload.get("sender_pubkey", "") or payload.get("pubkey_prefix", ""),
                "text": payload.get("text", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hops": payload.get("path_len", 0) or 0,
                "path_hashes": payload.get("path_hashes") or [],
                "path_names": payload.get("path_names") or [],
            })
            state.messages = state.messages[:1000]

    async def on_contact_msg(event) -> None:
        payload = event.payload or {}
        with state.lock:
            state.messages.insert(0, {
                "id": len(state.messages) + 1,
                "channel_idx": None,
                "channel_name": "Direct",
                "sender": payload.get("sender", "") or payload.get("pubkey_prefix", ""),
                "sender_pubkey": payload.get("pubkey_prefix", ""),
                "text": payload.get("text", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hops": payload.get("path_len", 0) or 0,
                "path_hashes": [],
                "path_names": [],
            })
            state.messages = state.messages[:1000]

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
) -> Dict[str, Any]:
    with state.lock:
        public = [
            m for m in state.messages
            if public_channel(m.get("channel_idx"), m.get("channel_name", ""))
        ]
        page = public[offset:offset + limit]
        return {"total": len(public), "limit": limit, "offset": offset, "items": page}


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
