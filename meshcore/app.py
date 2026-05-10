import asyncio
import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

try:
    from serial.tools import list_ports
except ImportError:
    list_ports = None  # type: ignore

from meshcore import EventType, MeshCore


APP_DIR = Path("/app")
UI_DIR = APP_DIR / "custom-ui"
DATA_DIR = Path(os.environ.get("MESHCORE_DATA_DIR", "/data/.meshcore"))
MESSAGE_ARCHIVE = DATA_DIR / "messages.json"
CONTACT_META_FILE = DATA_DIR / "contacts_meta.json"
CHANNEL_META_FILE = DATA_DIR / "channels_meta.json"
ADMIN_SETTINGS_FILE = DATA_DIR / "admin_settings.json"
FIRMWARE_UPLOAD_DIR = DATA_DIR / "firmware"
LOCATION_STALE_SECONDS = int(os.environ.get("MESHCORE_LOCATION_STALE_SECONDS", str(7 * 24 * 60 * 60)))

DEVICE = os.environ.get("MESHCORE_DEVICE", "/dev/ttyACM0")
TRANSPORT = os.environ.get("MESHCORE_TRANSPORT", "serial")
BAUDRATE = int(os.environ.get("MESHCORE_BAUDRATE", "115200"))
SERIAL_CX_DELAY = float(os.environ.get("MESHCORE_SERIAL_CX_DELAY", "2.0"))
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
        self.channel_meta: Dict[str, Dict[str, Any]] = {}
        self.contacts: Dict[str, Dict[str, Any]] = {}
        self.contact_meta: Dict[str, Dict[str, Any]] = {}
        self.admin_settings: Dict[str, Any] = {}
        self.self_telemetry: Dict[str, Any] = {}
        self.messages: List[Dict[str, Any]] = []
        self.event_logs: List[Dict[str, Any]] = []
        self.next_message_id = 1
        self.started_at = datetime.now(timezone.utc)
        self.last_connect_at: Optional[datetime] = None
        self.last_disconnect_at: Optional[datetime] = None
        self.last_disconnect_reason: Optional[str] = None
        self.reconnect_attempts = 0
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
flash_lock = threading.Lock()
flashing_until = 0.0


def discover_serial_ports() -> List[Dict[str, str]]:
    if list_ports is None:
        return []
    try:
        return [
            {"device": str(port.device), "description": str(port.description), "hwid": str(port.hwid)}
            for port in list_ports.comports()
        ]
    except Exception:
        return []


def serial_ports_safe() -> List[Dict[str, str]]:
    try:
        return discover_serial_ports()
    except Exception:
        return []


class SendMessageRequest(BaseModel):
    target_type: Literal["channel", "direct"]
    text: str = Field(min_length=1, max_length=512)
    channel_idx: Optional[int] = Field(default=None, ge=0, le=255)
    contact: Optional[str] = Field(default=None, min_length=6, max_length=128)
    retry: bool = True
    resend_of: Optional[int] = None


class ContactMetaRequest(BaseModel):
    alias: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=500)
    trusted: bool = False


class ContactCreateRequest(ContactMetaRequest):
    public_key: str = Field(min_length=64, max_length=64)
    name: str = Field(min_length=1, max_length=32)
    node_type: int = Field(default=0, ge=0, le=255)
    flags: int = Field(default=0, ge=0, le=255)
    adv_lat: float = 0.0
    adv_lon: float = 0.0


class ContactImportRequest(ContactMetaRequest):
    uri: str = Field(min_length=16, max_length=512)


class IdentityUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=32)
    adv_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    adv_lon: Optional[float] = Field(default=None, ge=-180, le=180)


class ChannelUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    secret_hex: str = Field(default="", max_length=32)
    password: str = Field(default="", max_length=128)
    pinned: bool = False
    muted: bool = False
    sort_order: int = 0


class ChannelMetaRequest(BaseModel):
    pinned: bool = False
    muted: bool = False
    sort_order: int = 0


class ChannelBackupRestoreRequest(BaseModel):
    channels: List[Dict[str, Any]]


class RoomSyncRequest(BaseModel):
    start: int = Field(default=0, ge=0)
    end: int = Field(default_factory=lambda: int(time.time()), ge=0)
    password: str = Field(default="", max_length=128)


class RoomPostRequest(BaseModel):
    text: str = Field(min_length=1, max_length=512)
    password: str = Field(default="", max_length=128)


class RadioUpdateRequest(BaseModel):
    radio_freq: Optional[float] = None
    radio_bw: Optional[float] = None
    radio_sf: Optional[int] = None
    radio_cr: Optional[int] = None
    tx_power: Optional[int] = None
    duty_cycle: Optional[float] = None
    airtime_factor: Optional[float] = None
    rx_delay: Optional[int] = None
    af: Optional[int] = None
    gps_enabled: Optional[bool] = None
    power_saving: Optional[bool] = None


class RoutingUpdateRequest(BaseModel):
    flood_scope: Optional[str] = None
    multi_acks: Optional[int] = None
    hop_limit: Optional[int] = None


class ContactLoginRequest(BaseModel):
    password: str = Field(default="", max_length=128)


class AdminSettingsRequest(BaseModel):
    allow_channel_messages: bool = True
    allow_direct_messages: bool = True
    allow_room_posts: bool = False
    allow_channel_config_writes: bool = True
    allow_contact_writes: bool = True
    allow_identity_writes: bool = True
    allow_room_sync: bool = True
    allow_channel_restore: bool = False
    allow_contact_import: bool = False
    allow_radio_writes: bool = True
    allow_device_actions: bool = True
    allow_firmware_flash: bool = False
    require_confirm_for_writes: bool = True
    maintenance_mode: bool = False
    admin_note: str = Field(default="", max_length=500)


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


def update_message(message_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with state.lock:
        for message in state.messages:
            if int(message.get("id", 0) or 0) == message_id:
                message.update(updates)
                message["updated_at"] = utcnow()
                state.updated_at = datetime.now(timezone.utc)
                save_messages()
                return dict(message)
    return None


def append_event_log(event: Any) -> None:
    if event is None:
        return
    log_entry = {
        "timestamp": utcnow(),
        "type": event_type_value(event),
        "payload": event_payload(event),
    }
    with state.lock:
        state.event_logs.insert(0, log_entry)
        state.event_logs = state.event_logs[:200]
        state.updated_at = datetime.now(timezone.utc)


def find_message(message_id: int) -> Optional[Dict[str, Any]]:
    with state.lock:
        for message in state.messages:
            if int(message.get("id", 0) or 0) == message_id:
                return dict(message)
    return None


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


def save_contact_meta() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with state.lock:
            payload = state.contact_meta
        CONTACT_META_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_contact_meta() -> None:
    try:
        data = json.loads(CONTACT_META_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with state.lock:
                state.contact_meta = data
    except FileNotFoundError:
        return
    except Exception:
        return


load_contact_meta()


def save_channel_meta() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with state.lock:
            payload = state.channel_meta
        CHANNEL_META_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_channel_meta() -> None:
    try:
        data = json.loads(CHANNEL_META_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with state.lock:
                state.channel_meta = data
    except FileNotFoundError:
        return
    except Exception:
        return


load_channel_meta()


DEFAULT_ADMIN_SETTINGS: Dict[str, Any] = {
    "allow_channel_messages": True,
    "allow_direct_messages": True,
    "allow_room_posts": False,
    "allow_channel_config_writes": True,
    "allow_contact_writes": True,
    "allow_identity_writes": True,
    "allow_room_sync": True,
    "allow_channel_restore": False,
    "allow_contact_import": False,
    "allow_radio_writes": True,
    "allow_device_actions": True,
    "allow_firmware_flash": False,
    "require_confirm_for_writes": True,
    "maintenance_mode": False,
    "admin_note": "",
}


def save_admin_settings() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with state.lock:
            payload = {**DEFAULT_ADMIN_SETTINGS, **state.admin_settings}
        ADMIN_SETTINGS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_admin_settings() -> None:
    try:
        data = json.loads(ADMIN_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with state.lock:
                state.admin_settings = {**DEFAULT_ADMIN_SETTINGS, **data}
                return
    except FileNotFoundError:
        pass
    except Exception:
        pass
    with state.lock:
        state.admin_settings = dict(DEFAULT_ADMIN_SETTINGS)


def admin_settings() -> Dict[str, Any]:
    with state.lock:
        return {**DEFAULT_ADMIN_SETTINGS, **state.admin_settings}


def enforce_write(setting: str, action: str) -> None:
    settings = admin_settings()
    if settings.get("maintenance_mode") and setting != "maintenance_mode":
        raise HTTPException(status_code=423, detail=f"{action} blocked: maintenance mode is enabled")
    if not settings.get(setting, False):
        raise HTTPException(status_code=403, detail=f"{action} blocked by admin safety setting: {setting}")


def enforce_firmware_flash() -> None:
    if not admin_settings().get("allow_firmware_flash", False):
        raise HTTPException(status_code=403, detail="firmware flashing is disabled by admin safety setting: allow_firmware_flash")


load_admin_settings()


def get_command_by_names(commands: Any, *names: str) -> Optional[Any]:
    for name in names:
        command = getattr(commands, name, None)
        if command:
            return command
    return None


def call_command_compat(command: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return command(*args, **kwargs)
    except TypeError:
        if "min_timeout" not in kwargs:
            raise
        alt_kwargs = dict(kwargs)
        alt_kwargs["timeout"] = alt_kwargs.pop("min_timeout")
        try:
            return command(*args, **alt_kwargs)
        except TypeError:
            alt_kwargs.pop("timeout", None)
            return command(*args, **alt_kwargs)


async def run_cli_command(command: str) -> Any:
    if not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    command = command.strip()
    if not command:
        raise HTTPException(status_code=400, detail="empty CLI command")
    return await run_device_command(meshcore_client.commands.send(b"\x13" + command.encode("utf-8")))


async def run_named_command(commands: Any, names: tuple[str, ...], *args: Any, **kwargs: Any) -> Any:
    command = get_command_by_names(commands, *names)
    if not command:
        raise HTTPException(status_code=501, detail=f"command not supported: {'/'.join(names)}")
    return await run_device_command(call_command_compat(command, *args, **kwargs))


def event_type_or_none(name: str) -> Optional[EventType]:
    return getattr(EventType, name, None)


def public_channel(idx: Optional[int], name: str) -> bool:
    return idx == 0 or bool(name and name.startswith("#"))


def channel_name(idx: Optional[int]) -> str:
    with state.lock:
        for ch in state.channels:
            if ch.get("idx") == idx:
                return ch.get("name", "")
    return "Public" if idx == 0 else ""


def channel_display(channel: Dict[str, Any]) -> Dict[str, Any]:
    idx = int(channel.get("idx", channel.get("index", 0)) or 0)
    meta = state.channel_meta.get(str(idx), {})
    secret = channel.get("channel_secret")
    secret_hex = secret.hex() if isinstance(secret, (bytes, bytearray)) else str(secret or "")
    name = channel.get("name") or channel.get("channel_name") or f"Channel {idx}"
    return {
        "idx": idx,
        "name": name,
        "is_private": not public_channel(idx, name),
        "secret_hex": secret_hex,
        "has_secret": bool(secret_hex),
        "pinned": bool(meta.get("pinned", False)),
        "muted": bool(meta.get("muted", False)),
        "sort_order": int(meta.get("sort_order", 0) or 0),
    }


def sorted_channels() -> List[Dict[str, Any]]:
    with state.lock:
        channels = [channel_display(channel) for channel in state.channels]
    return sorted(channels, key=lambda c: (-int(c["pinned"]), int(c["sort_order"]), int(c["idx"])))


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


def contact_display(pubkey: str, contact: Dict[str, Any]) -> Dict[str, Any]:
    meta = state.contact_meta.get(pubkey, {})
    raw_type = int(contact.get("type", 0) or contact.get("adv_type", 0) or 0)
    location = extract_location(contact, "contact_advert")
    name = contact.get("adv_name") or pubkey[:12]
    return {
        "name": meta.get("alias") or name,
        "raw_name": name,
        "alias": meta.get("alias", ""),
        "notes": meta.get("notes", ""),
        "trusted": bool(meta.get("trusted", False)),
        "public_key": pubkey,
        "pubkey_prefix": pubkey[:12],
        "type": {2: "repeater", 3: "room_server", 4: "sensor"}.get(raw_type, "companion" if raw_type in {0, 1} else "unknown"),
        "raw_type": raw_type,
        "flags": contact.get("flags"),
        "out_path_len": contact.get("out_path_len"),
        "out_path": contact.get("out_path"),
        "last_seen": contact.get("last_seen") or contact.get("last_advert"),
        "adv_lat": location["lat"],
        "adv_lon": location["lon"],
        "battery_mv": contact.get("battery_mv"),
        "location": location,
    }


def valid_coord(lat: Any, lon: Any) -> bool:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    if lat_f == 0.0 and lon_f == 0.0:
        return False
    return -90 <= lat_f <= 90 and -180 <= lon_f <= 180


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value in {None, ""}:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def normalize_location(lat: Any, lon: Any, updated: Any, source: str) -> Dict[str, Any]:
    valid = valid_coord(lat, lon)
    updated_at = parse_timestamp(updated)
    age_seconds = None
    freshness = "unknown"
    if updated_at:
        age_seconds = max(0, int((datetime.now(timezone.utc) - updated_at).total_seconds()))
        freshness = "stale" if age_seconds > LOCATION_STALE_SECONDS else "live"
    return {
        "valid": valid,
        "lat": float(lat) if valid else None,
        "lon": float(lon) if valid else None,
        "source": source,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "age_seconds": age_seconds,
        "freshness": freshness if valid else "invalid",
        "stale_after_seconds": LOCATION_STALE_SECONDS,
    }


def extract_location(entity: Dict[str, Any], default_source: str) -> Dict[str, Any]:
    candidates = [
        ("telemetry", "telemetry_lat", "telemetry_lon", "telemetry_time"),
        ("telemetry", "lat", "lon", "timestamp"),
        ("gps", "gps_lat", "gps_lon", "gps_time"),
        ("gps", "latitude", "longitude", "timestamp"),
        (default_source, "adv_lat", "adv_lon", "last_advert"),
    ]
    fallback_time = entity.get("last_seen") or entity.get("last_advert") or entity.get("timestamp")
    for source, lat_key, lon_key, time_key in candidates:
        lat = entity.get(lat_key)
        lon = entity.get(lon_key)
        if valid_coord(lat, lon):
            return normalize_location(lat, lon, entity.get(time_key) or fallback_time, source)
    return normalize_location(None, None, fallback_time, default_source)


def parse_lpp_telemetry(payload: Dict[str, Any]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {
        "pubkey_prefix": payload.get("pubkey_pre") or payload.get("pubkey_prefix") or "",
        "voltage": None,
        "battery_mv": None,
        "latitude": None,
        "longitude": None,
        "altitude": None,
    }
    for item in payload.get("lpp", []) or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).lower()
        value = item.get("value")
        if item_type == "voltage":
            try:
                parsed["voltage"] = float(value)
                parsed["battery_mv"] = int(float(value) * 1000)
            except (TypeError, ValueError):
                pass
        elif item_type == "gps" and isinstance(value, dict):
            parsed["latitude"] = value.get("latitude")
            parsed["longitude"] = value.get("longitude")
            parsed["altitude"] = value.get("altitude")
    return parsed


def update_self_telemetry(payload: Dict[str, Any]) -> None:
    parsed = parse_lpp_telemetry(payload)
    timestamp = utcnow()
    telemetry = {**json_safe(payload), **parsed, "updated_at": timestamp}
    with state.lock:
        state.self_telemetry = telemetry
        if valid_coord(parsed.get("latitude"), parsed.get("longitude")):
            state.device.update({
                "telemetry_lat": parsed["latitude"],
                "telemetry_lon": parsed["longitude"],
                "telemetry_time": timestamp,
                "gps_altitude": parsed.get("altitude"),
            })
        if parsed.get("battery_mv") is not None:
            state.device["battery_mv"] = parsed["battery_mv"]
            state.device["battery_voltage"] = parsed["voltage"]
        state.updated_at = datetime.now(timezone.utc)


def ha_location_payload(marker: Dict[str, Any], telemetry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    location = marker.get("location", {})
    battery_mv = marker.get("battery_mv")
    if battery_mv is None and telemetry:
        battery_mv = telemetry.get("battery_mv")
    battery_voltage = None
    try:
        battery_voltage = round(float(battery_mv) / 1000, 3) if battery_mv is not None else None
    except (TypeError, ValueError):
        pass
    altitude = None
    if telemetry:
        altitude = telemetry.get("altitude")
    return {
        "name": marker.get("name"),
        "kind": marker.get("kind"),
        "node_type": marker.get("node_type"),
        "public_key": marker.get("public_key"),
        "pubkey_prefix": marker.get("pubkey_prefix") or (telemetry or {}).get("pubkey_prefix", ""),
        "valid": bool(location.get("valid")),
        "latitude": location.get("lat"),
        "longitude": location.get("lon"),
        "altitude": altitude,
        "gps_accuracy": 50 if location.get("valid") else None,
        "source_type": "gps" if location.get("valid") else None,
        "source": location.get("source"),
        "freshness": location.get("freshness"),
        "updated_at": location.get("updated_at"),
        "age_seconds": location.get("age_seconds"),
        "battery_mv": battery_mv,
        "battery_voltage": battery_voltage,
        "last_seen": marker.get("last_seen"),
        "ha_state": "not_home" if location.get("valid") else "unknown",
    }


def map_marker_for_contact(pubkey: str, contact: Dict[str, Any]) -> Dict[str, Any]:
    display = contact_display(pubkey, contact)
    location = display["location"]
    return {
        "id": f"contact:{pubkey}",
        "kind": "contact",
        "name": display["name"],
        "raw_name": display["raw_name"],
        "public_key": pubkey,
        "pubkey_prefix": display["pubkey_prefix"],
        "node_type": display["type"],
        "trusted": display["trusted"],
        "notes": display["notes"],
        "location": location,
        "last_seen": display["last_seen"],
        "battery_mv": display["battery_mv"],
    }


def map_marker_for_self() -> Dict[str, Any]:
    with state.lock:
        self_info = dict(state.device)
    location = extract_location({**self_info, "timestamp": state.updated_at}, "self_info")
    return {
        "id": "self",
        "kind": "self",
        "name": self_info.get("name") or "This node",
        "public_key": self_info.get("public_key") or self_info.get("pubkey") or self_info.get("key"),
        "pubkey_prefix": str(self_info.get("public_key") or self_info.get("pubkey") or "")[:12],
        "node_type": "self",
        "trusted": True,
        "location": location,
        "adv_loc_policy": self_info.get("adv_loc_policy"),
        "telemetry_mode_loc": self_info.get("telemetry_mode_loc"),
        "radio_freq": self_info.get("radio_freq"),
        "radio_bw": self_info.get("radio_bw"),
    }


def contact_by_key(key: str) -> tuple[str, Dict[str, Any]]:
    pubkey = resolve_contact(key)
    with state.lock:
        contact = state.contacts.get(pubkey)
        if not contact:
            raise ValueError(f"unknown contact: {key}")
        return pubkey, dict(contact)


async def run_device_command(coro) -> Any:
    if not state.connected or not meshcore_client or not worker_loop:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    future = asyncio.run_coroutine_threadsafe(coro, worker_loop)
    try:
        result = future.result(timeout=30)
    except concurrent.futures.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="command timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"command failed: {exc}") from exc
    if result and event_type_value(result) == EventType.ERROR.value:
        raise HTTPException(status_code=502, detail=event_payload(result))
    return result


async def set_companion_other_params(
    *,
    advert_loc_policy: Optional[int] = None,
    telemetry_mode_loc: Optional[int] = None,
) -> None:
    if not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    result = await run_device_command(meshcore_client.commands.send_appstart())
    infos = dict(result.payload or {})
    if advert_loc_policy is not None:
        infos["adv_loc_policy"] = int(advert_loc_policy)
    if telemetry_mode_loc is not None:
        infos["telemetry_mode_loc"] = int(telemetry_mode_loc)

    manual_add_contacts = 1 if infos.get("manual_add_contacts") else 0
    telemetry_mode_base = int(infos.get("telemetry_mode_base", 0) or 0) & 0b11
    telemetry_mode_loc_value = int(infos.get("telemetry_mode_loc", 0) or 0) & 0b11
    telemetry_mode_env = int(infos.get("telemetry_mode_env", 0) or 0) & 0b11
    adv_loc_policy = int(infos.get("adv_loc_policy", 0) or 0) & 0xFF
    multi_acks = int(infos.get("multi_acks", 0) or 0) & 0xFF
    telemetry_byte = telemetry_mode_base | (telemetry_mode_loc_value << 2) | (telemetry_mode_env << 4)

    payload = (
        b"\x26"
        + manual_add_contacts.to_bytes(1, "little")
        + telemetry_byte.to_bytes(1, "little")
        + adv_loc_policy.to_bytes(1, "little")
        + multi_acks.to_bytes(1, "little")
    )
    await run_device_command(meshcore_client.commands.send(payload, [EventType.OK, EventType.ERROR]))


async def pause_meshcore_for_flash(seconds: int = 300) -> None:
    global flashing_until, meshcore_client
    flashing_until = time.monotonic() + seconds
    client = meshcore_client
    meshcore_client = None
    state.set_status("Firmware flashing in progress", False)
    if client and worker_loop:
        try:
            future = asyncio.run_coroutine_threadsafe(client.disconnect(), worker_loop)
            future.result(timeout=10)
        except Exception:
            pass


def run_esptool_command(args: List[str], timeout: int = 180) -> Dict[str, Any]:
    command = [sys.executable, "-m", "esptool", *args]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    return {"command": command, "returncode": completed.returncode, "output": output[-12000:]}


async def refresh_contacts() -> None:
    if not meshcore_client:
        return
    result = await meshcore_client.commands.get_contacts(timeout=10)
    if result and result.type != EventType.ERROR and result.payload:
        with state.lock:
            state.contacts = dict(result.payload)


def client_reports_connected(mc: MeshCore) -> Optional[bool]:
    for obj in (mc, getattr(mc, "connection", None)):
        if obj is None:
            continue
        for attr in ("connected", "is_connected"):
            value = getattr(obj, attr, None)
            if isinstance(value, bool):
                return value
            if callable(value):
                try:
                    result = value()
                except Exception:
                    continue
                if isinstance(result, bool):
                    return result
    return None


async def mark_disconnected(reason: str) -> None:
    global meshcore_client
    with state.lock:
        state.last_disconnect_at = datetime.now(timezone.utc)
        state.last_disconnect_reason = reason
    state.set_status(f"Disconnected: {reason}", False)
    meshcore_client = None


async def meshcore_health_check(mc: MeshCore) -> None:
    command = get_command_by_names(mc.commands, "get_time", "get_bat")
    if not command:
        return
    result = await asyncio.wait_for(command(), timeout=15)
    if result and event_type_value(result) == EventType.ERROR.value:
        raise ConnectionError(f"health check failed: {event_payload(result)}")


def message_matches(
    message: Dict[str, Any],
    scope: str,
    query: str,
    status: str,
    direction: str,
    conversation: str,
) -> bool:
    if scope == "public":
        if message.get("conversation_type", "channel") != "channel":
            return False
        if not public_channel(message.get("channel_idx"), message.get("channel_name", "")):
            return False
    elif scope in {"channel", "direct"}:
        if message.get("conversation_type", "channel") != scope:
            return False
    if status != "all" and message.get("status", "received") != status:
        return False
    if direction != "all" and message.get("direction", "incoming") != direction:
        return False
    if conversation and conversation_id_for_message(message) != conversation:
        return False
    if query:
        haystack = " ".join(str(message.get(key, "")) for key in (
            "text", "sender", "sender_pubkey", "recipient", "contact", "channel_name", "status"
        )).lower()
        if query.lower() not in haystack:
            return False
    return True


def conversation_id_for_message(message: Dict[str, Any]) -> str:
    if message.get("conversation_type") == "direct":
        contact = message.get("contact") or message.get("sender_pubkey") or message.get("sender") or message.get("recipient") or ""
        return f"direct:{contact}"
    return f"channel:{message.get('channel_idx', 0)}"


def messages_for_filters(
    scope: str,
    query: str = "",
    status: str = "all",
    direction: str = "all",
    conversation: str = "",
) -> List[Dict[str, Any]]:
    with state.lock:
        return [
            dict(message)
            for message in state.messages
            if message_matches(message, scope, query, status, direction, conversation)
        ]


async def connect_meshcore() -> None:
    global meshcore_client

    while True:
        mc: Optional[MeshCore] = None
        try:
            if time.monotonic() < flashing_until:
                state.set_status("Firmware flashing in progress", False)
                await asyncio.sleep(min(5, max(1, flashing_until - time.monotonic())))
                continue
            with state.lock:
                state.reconnect_attempts += 1
                attempt = state.reconnect_attempts
            state.set_status(f"Connecting to {DEVICE} (attempt {attempt})", False)
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
            with state.lock:
                state.last_connect_at = datetime.now(timezone.utc)
                state.reconnect_attempts = 0
            state.set_status("Connected", True)
            last_health_check = time.monotonic()

            while True:
                await asyncio.sleep(5)
                if time.monotonic() < flashing_until:
                    raise ConnectionError("firmware flashing in progress")
                if not state.connected:
                    raise ConnectionError(state.last_disconnect_reason or "device disconnected")
                if meshcore_client is not mc:
                    raise ConnectionError("MeshCore client was cleared")
                connected = client_reports_connected(mc)
                if connected is False:
                    raise ConnectionError("transport reported disconnected")
                if time.monotonic() - last_health_check >= 30:
                    await meshcore_health_check(mc)
                    last_health_check = time.monotonic()
        except Exception as exc:
            await mark_disconnected(str(exc))
            try:
                if mc:
                    await mc.disconnect()
            except Exception:
                pass
            with state.lock:
                attempts = state.reconnect_attempts
            delay = min(30, 5 + attempts * 5)
            state.set_status(f"Reconnecting in {delay}s: {exc}", False)
            await asyncio.sleep(delay)


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
        reason = (event.payload or {}).get('reason', 'unknown')
        await mark_disconnected(str(reason))
        append_event_log(event)

    async def on_connect(event) -> None:
        with state.lock:
            state.last_connect_at = datetime.now(timezone.utc)
        state.set_status("Connected", True)
        append_event_log(event)

    async def on_new_contact(event) -> None:
        payload = event.payload or {}
        pubkey = payload.get("public_key")
        if pubkey:
            with state.lock:
                state.contacts[pubkey] = dict(payload)
                state.updated_at = datetime.now(timezone.utc)
        append_event_log(event)

    async def on_ack(event) -> None:
        payload = event.payload or {}
        code = payload.get("code", "")
        if not code:
            return
        with state.lock:
            matched = []
            for message in state.messages:
                if message.get("expected_ack") == code:
                    acks = message.setdefault("acks", [])
                    acks.append({"code": code, "timestamp": utcnow(), "payload": json_safe(payload)})
                    message["ack_count"] = len(acks)
                    message["status"] = "acknowledged"
                    message["updated_at"] = utcnow()
                    matched.append(message.get("id"))
            if matched:
                state.updated_at = datetime.now(timezone.utc)
        if matched:
            save_messages()
        append_event_log(event)

    async def on_diagnostic_event(event) -> None:
        if str(event_type_value(event)).lower() == "telemetry_response":
            payload = event_payload(event)
            if isinstance(payload, dict):
                update_self_telemetry(payload)
        append_event_log(event)

    def subscribe_if_present(name: str, callback: Any) -> None:
        event_type = event_type_or_none(name)
        if event_type is not None:
            mc.subscribe(event_type, callback)

    subscribe_if_present("CHANNEL_MSG_RECV", on_channel_msg)
    subscribe_if_present("CONTACT_MSG_RECV", on_contact_msg)
    subscribe_if_present("NEW_CONTACT", on_new_contact)
    subscribe_if_present("DISCONNECTED", on_disconnect)
    subscribe_if_present("ACK", on_ack)
    subscribe_if_present("CONNECTED", on_connect)
    for event_name in (
        "LOG_DATA",
        "RAW_DATA",
        "RX_LOG_DATA",
        "TELEMETRY_RESPONSE",
        "STATUS_RESPONSE",
        "ACL_RESPONSE",
        "MMA_RESPONSE",
        "ADVERTISEMENT",
        "PATH_UPDATE",
        "PATH_RESPONSE",
        "TRACE_DATA",
        "BINARY_RESPONSE",
    ):
        subscribe_if_present(event_name, on_diagnostic_event)


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
        channels.append({
            "idx": idx,
            "name": name,
            "is_private": not public_channel(idx, name),
            "channel_secret": payload.get("channel_secret", b""),
        })

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
    return FileResponse(
        str(UI_DIR / "index.html"),
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/v1/status")
async def api_status() -> Dict[str, Any]:
    with state.lock:
        return {
            "connected": state.connected,
            "status": state.status,
            "device": state.device,
            "device_info": state.device_info,
            "last_connect_at": state.last_connect_at.isoformat() if state.last_connect_at else None,
            "last_disconnect_at": state.last_disconnect_at.isoformat() if state.last_disconnect_at else None,
            "last_disconnect_reason": state.last_disconnect_reason,
            "reconnect_attempts": state.reconnect_attempts,
            "updated_at": state.updated_at.isoformat(),
        }


@app.get("/api/v1/admin/settings")
async def api_admin_settings() -> Dict[str, Any]:
    return {
        "settings": admin_settings(),
        "storage": str(ADMIN_SETTINGS_FILE),
        "write_categories": {
            "allow_channel_messages": "Send messages to public/private channels",
            "allow_direct_messages": "Send direct messages to contacts",
            "allow_room_posts": "Send posts/messages into room servers",
            "allow_channel_config_writes": "Change channel names, secrets, pin/mute/sort metadata",
            "allow_contact_writes": "Add, remove, import, or edit contacts",
            "allow_identity_writes": "Change local node name or advertised coordinates",
            "allow_room_sync": "Login/sync room server history and ACL/status",
            "allow_channel_restore": "Bulk restore channel configuration from backup JSON",
            "allow_contact_import": "Import meshcore:// contact cards",
            "allow_radio_writes": "Configure radio parameters like frequency, bandwidth, spreading factor, coding rate, and TX power",
            "allow_device_actions": "Perform device actions such as reboot, clock sync, and adverts",
            "allow_firmware_flash": "Upload and flash firmware binaries over serial using esptool; disabled by default",
            "maintenance_mode": "Block all write operations except changing admin settings",
        },
    }


@app.put("/api/v1/admin/settings")
async def api_update_admin_settings(request: AdminSettingsRequest) -> Dict[str, Any]:
    with state.lock:
        state.admin_settings = request.model_dump() if hasattr(request, "model_dump") else request.dict()
        state.updated_at = datetime.now(timezone.utc)
    save_admin_settings()
    return await api_admin_settings()


@app.get("/api/v1/identity")
async def api_identity() -> Dict[str, Any]:
    battery = None
    core_stats = radio_stats = packet_stats = None
    if state.connected and meshcore_client and worker_loop:
        for name, command_factory in [
            ("battery", meshcore_client.commands.get_bat),
            ("core_stats", meshcore_client.commands.get_stats_core),
            ("radio_stats", meshcore_client.commands.get_stats_radio),
            ("packet_stats", meshcore_client.commands.get_stats_packets),
        ]:
            try:
                result = await run_device_command(command_factory())
                if name == "battery":
                    battery = event_payload(result)
                elif name == "core_stats":
                    core_stats = event_payload(result)
                elif name == "radio_stats":
                    radio_stats = event_payload(result)
                elif name == "packet_stats":
                    packet_stats = event_payload(result)
            except HTTPException:
                pass
    with state.lock:
        return {
            "connected": state.connected,
            "status": state.status,
            "self": state.device,
            "device_info": state.device_info,
            "battery": battery,
            "core_stats": core_stats,
            "radio_stats": radio_stats,
            "packet_stats": packet_stats,
        }


@app.get("/api/v1/diagnostics")
async def api_diagnostics() -> Dict[str, Any]:
    with state.lock:
        event_counts: Dict[str, int] = {}
        for entry in state.event_logs:
            event_counts[entry["type"]] = event_counts.get(entry["type"], 0) + 1
        transport_info: Dict[str, Any] = {"type": TRANSPORT, "device": DEVICE}
        if TRANSPORT == "serial":
            transport_info["serial_ports"] = serial_ports_safe()
        return {
            "connected": state.connected,
            "status": state.status,
            "device": state.device,
            "device_info": state.device_info,
            "started_at": state.started_at.isoformat(),
            "last_updated": state.updated_at.isoformat(),
            "last_connect_at": state.last_connect_at.isoformat() if state.last_connect_at else None,
            "last_disconnect_at": state.last_disconnect_at.isoformat() if state.last_disconnect_at else None,
            "last_disconnect_reason": state.last_disconnect_reason,
            "reconnect_attempts": state.reconnect_attempts,
            "log_count": len(state.event_logs),
            "connect_count": event_counts.get("connected", 0) + event_counts.get("CONNECTED", 0),
            "disconnect_count": event_counts.get("disconnected", 0) + event_counts.get("DISCONNECTED", 0),
            "transport": transport_info,
            "event_counts": event_counts,
        }


@app.get("/api/v1/diagnostics/logs")
async def api_diagnostics_logs(limit: int = Query(default=100, ge=1, le=200)) -> Dict[str, Any]:
    with state.lock:
        return {
            "total": len(state.event_logs),
            "limit": limit,
            "items": state.event_logs[:limit],
        }


@app.get("/api/v1/sensors")
async def api_sensors() -> Dict[str, Any]:
    sensors = []
    with state.lock:
        for pubkey, contact in state.contacts.items():
            raw_type = int(contact.get("type", 0) or contact.get("adv_type", 0) or 0)
            if raw_type == 4:
                sensors.append(contact_display(pubkey, contact))
        self_info = dict(state.device)
    self_telemetry = None
    custom_vars = None
    if state.connected and meshcore_client and worker_loop:
        try:
            command = get_command_by_names(meshcore_client.commands, "get_self_telemetry", "get_telemetry", "get_status")
            if command:
                result = await run_device_command(command())
            else:
                result = None
            self_telemetry = event_payload(result)
        except HTTPException:
            pass
        try:
            command = get_command_by_names(meshcore_client.commands, "get_custom_vars", "get_custom_vars_query")
            if command:
                result = await run_device_command(command())
            else:
                result = None
            custom_vars = event_payload(result)
        except HTTPException:
            pass
    return {
        "self": self_info,
        "self_telemetry": self_telemetry,
        "custom_vars": custom_vars,
        "sensors": sensors,
    }


@app.post("/api/v1/diagnostics/test")
async def api_diagnostics_test() -> Dict[str, Any]:
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    try:
        result = await run_device_command(meshcore_client.commands.get_time())
    except HTTPException:
        result = await run_device_command(meshcore_client.commands.get_bat())
    return {"ok": True, "result": event_payload(result)}


@app.patch("/api/v1/identity")
async def api_update_identity(request: IdentityUpdateRequest) -> Dict[str, Any]:
    enforce_write("allow_identity_writes", "identity update")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    if request.name is not None:
        await run_device_command(meshcore_client.commands.set_name(request.name))
    if request.adv_lat is not None or request.adv_lon is not None:
        with state.lock:
            current_lat = state.device.get("adv_lat", 0.0)
            current_lon = state.device.get("adv_lon", 0.0)
        await run_device_command(meshcore_client.commands.set_coords(
            request.adv_lat if request.adv_lat is not None else current_lat,
            request.adv_lon if request.adv_lon is not None else current_lon,
        ))
    if meshcore_client:
        result = await run_device_command(meshcore_client.commands.send_appstart())
        if result and result.payload:
            with state.lock:
                state.device = dict(result.payload)
    return await api_identity()


@app.patch("/api/v1/radio")
async def api_update_radio(request: RadioUpdateRequest) -> Dict[str, Any]:
    enforce_write("allow_radio_writes", "radio update")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    if request.radio_freq is not None or request.radio_bw is not None or request.radio_sf is not None or request.radio_cr is not None:
        if None in (request.radio_freq, request.radio_bw, request.radio_sf, request.radio_cr):
            raise HTTPException(status_code=400, detail="radio_freq, radio_bw, radio_sf, and radio_cr must all be provided together")
        if request.radio_freq <= 0 or request.radio_bw <= 0:
            raise HTTPException(status_code=400, detail="radio_freq and radio_bw must be greater than zero")
        if request.radio_sf < 5 or request.radio_sf > 12:
            raise HTTPException(status_code=400, detail="radio_sf must be between 5 and 12")
        if request.radio_cr < 5 or request.radio_cr > 8:
            raise HTTPException(status_code=400, detail="radio_cr must be between 5 and 8")
        await run_device_command(meshcore_client.commands.set_radio(request.radio_freq, request.radio_bw, request.radio_sf, request.radio_cr))
    if request.tx_power is not None:
        await run_device_command(meshcore_client.commands.set_tx_power(request.tx_power))
    if request.duty_cycle is not None:
        if request.duty_cycle < 0 or request.duty_cycle > 100:
            raise HTTPException(status_code=400, detail="duty_cycle must be between 0 and 100")
        command = get_command_by_names(meshcore_client.commands, "set_duty_cycle", "set_dutycycle")
        if not command:
            raise HTTPException(status_code=501, detail="Duty cycle configuration is not supported by this MeshCore library")
        await run_device_command(command(request.duty_cycle))
    if request.airtime_factor is not None:
        if request.airtime_factor <= 0 or request.airtime_factor > 100:
            raise HTTPException(status_code=400, detail="airtime_factor must be greater than 0 and at most 100")
        command = get_command_by_names(meshcore_client.commands, "set_airtime_factor", "set_airtimefactor", "set_airtime")
        if not command:
            raise HTTPException(status_code=501, detail="Airtime factor configuration is not supported by this MeshCore library")
        await run_device_command(command(request.airtime_factor))
    if request.rx_delay is not None or request.af is not None:
        rx_delay = int(request.rx_delay or 0)
        af = int(request.af or 0)
        await run_device_command(meshcore_client.commands.set_tuning(rx_delay, af))
    if request.gps_enabled is not None:
        if request.gps_enabled:
            if not hasattr(meshcore_client.commands, "set_custom_var"):
                raise HTTPException(status_code=501, detail="GPS configuration is not supported by this MeshCore library")
            await run_device_command(meshcore_client.commands.set_custom_var("gps", "1"))
            await run_device_command(meshcore_client.commands.set_custom_var("gps_interval", "1"))
            await set_companion_other_params(advert_loc_policy=1, telemetry_mode_loc=2)
        else:
            if not hasattr(meshcore_client.commands, "set_custom_var"):
                raise HTTPException(status_code=501, detail="GPS configuration is not supported by this MeshCore library")
            await run_device_command(meshcore_client.commands.set_custom_var("gps", "0"))
            await set_companion_other_params(advert_loc_policy=0)
    if request.power_saving is not None:
        await run_cli_command(f"powersaving {'on' if request.power_saving else 'off'}")
    if meshcore_client:
        result = await run_device_command(meshcore_client.commands.send_appstart())
        if result and result.payload:
            with state.lock:
                state.device = dict(result.payload)
    return await api_identity()


@app.patch("/api/v1/routing")
async def api_update_routing(request: RoutingUpdateRequest) -> Dict[str, Any]:
    enforce_write("allow_radio_writes", "routing update")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    updated: List[str] = []
    if request.flood_scope is not None:
        if not hasattr(meshcore_client.commands, "set_flood_scope"):
            raise HTTPException(status_code=501, detail="Flood scope configuration is not supported by this MeshCore library")
        await run_device_command(meshcore_client.commands.set_flood_scope(request.flood_scope))
        updated.append("flood_scope")
    if request.multi_acks is not None:
        if request.multi_acks < 0 or request.multi_acks > 8:
            raise HTTPException(status_code=400, detail="multi_acks must be between 0 and 8")
        if not hasattr(meshcore_client.commands, "set_multi_acks"):
            raise HTTPException(status_code=501, detail="Multi-ACK configuration is not supported by this MeshCore library")
        await run_device_command(meshcore_client.commands.set_multi_acks(request.multi_acks))
        updated.append("multi_acks")
    if request.hop_limit is not None:
        if request.hop_limit < 1 or request.hop_limit > 32:
            raise HTTPException(status_code=400, detail="hop_limit must be between 1 and 32")
        hop_cmd = None
        for name in ("set_hop_limit", "set_flood_hop_limit", "set_hoplimit"):
            if hasattr(meshcore_client.commands, name):
                hop_cmd = getattr(meshcore_client.commands, name)
                break
        if not hop_cmd:
            raise HTTPException(status_code=501, detail="Hop limit configuration is not supported by this MeshCore library")
        await run_device_command(hop_cmd(request.hop_limit))
        updated.append("hop_limit")
    if not updated:
        raise HTTPException(status_code=400, detail="no routing configuration provided")
    return {"ok": True, "updated": updated}


@app.post("/api/v1/admin/reboot")
async def api_reboot_device() -> Dict[str, Any]:
    enforce_write("allow_device_actions", "device reboot")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    await run_device_command(meshcore_client.commands.reboot())
    return {"ok": True, "action": "reboot_requested"}


@app.post("/api/v1/admin/clock-sync")
async def api_clock_sync() -> Dict[str, Any]:
    enforce_write("allow_device_actions", "clock sync")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    timestamp = int(time.time())
    await run_device_command(meshcore_client.commands.set_time(timestamp))
    return {"ok": True, "timestamp": timestamp}


@app.post("/api/v1/admin/advert")
async def api_send_advert(flood: bool = Query(default=False)) -> Dict[str, Any]:
    enforce_write("allow_device_actions", "send advert")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    result = await run_device_command(meshcore_client.commands.send_advert(flood=flood))
    return {"ok": True, "flood": bool(flood), "result": event_payload(result)}


@app.post("/api/v1/admin/flash")
async def api_flash_firmware(
    port: str = Form(default=DEVICE),
    baud: int = Form(default=921600),
    offset: str = Form(default="0x0"),
    erase: bool = Form(default=False),
    firmware: UploadFile = File(...),
) -> Dict[str, Any]:
    global flashing_until
    enforce_firmware_flash()
    if not port.startswith("/dev/"):
        raise HTTPException(status_code=400, detail="port must be a /dev serial device")
    if baud < 1200 or baud > 3000000:
        raise HTTPException(status_code=400, detail="baud must be between 1200 and 3000000")
    try:
        offset_value = int(str(offset).strip(), 0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="offset must be a decimal or hex value, for example 0x0") from exc
    if offset_value < 0 or offset_value > 0x1000000:
        raise HTTPException(status_code=400, detail="offset is outside the accepted flash range")
    if not firmware.filename or not firmware.filename.lower().endswith(".bin"):
        raise HTTPException(status_code=400, detail="firmware upload must be a .bin file")
    if not flash_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="another firmware flash is already running")

    try:
        max_bytes = 32 * 1024 * 1024
        data = await firmware.read(max_bytes + 1)
        if not data:
            raise HTTPException(status_code=400, detail="firmware file is empty")
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail="firmware file is larger than 32 MB")
        FIRMWARE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        firmware_path = FIRMWARE_UPLOAD_DIR / f"upload-{int(time.time())}.bin"
        firmware_path.write_bytes(data)
        await pause_meshcore_for_flash()

        logs: List[Dict[str, Any]] = []
        try:
            if erase:
                erase_result = await asyncio.to_thread(
                    run_esptool_command,
                    ["--chip", "auto", "--port", port, "--baud", str(baud), "erase_flash"],
                    240,
                )
                logs.append({"step": "erase_flash", **erase_result})
                if erase_result["returncode"] != 0:
                    raise HTTPException(status_code=502, detail={"step": "erase_flash", "output": erase_result["output"]})
            write_result = await asyncio.to_thread(
                run_esptool_command,
                ["--chip", "auto", "--port", port, "--baud", str(baud), "write_flash", "-z", hex(offset_value), str(firmware_path)],
                300,
            )
            logs.append({"step": "write_flash", **write_result})
            if write_result["returncode"] != 0:
                raise HTTPException(status_code=502, detail={"step": "write_flash", "output": write_result["output"]})
            return {
                "ok": True,
                "port": port,
                "baud": baud,
                "offset": hex(offset_value),
                "erase": erase,
                "size": len(data),
                "logs": logs,
            }
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail=f"esptool timed out: {exc}") from exc
        finally:
            try:
                firmware_path.unlink(missing_ok=True)
            except Exception:
                pass
            flashing_until = time.monotonic() + 5
    finally:
        flash_lock.release()


@app.post("/api/v1/contacts/{key}/login")
async def api_contact_login(key: str, request: ContactLoginRequest) -> Dict[str, Any]:
    enforce_write("allow_room_sync", "contact login")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    pubkey, contact = contact_by_key(key)
    await run_device_command(meshcore_client.commands.send_login(contact, request.password))
    return {"ok": True, "contact": pubkey}


@app.get("/api/v1/contacts/{key}/acl")
async def api_contact_acl(key: str) -> Dict[str, Any]:
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    pubkey, contact = contact_by_key(key)
    acl_event = await run_named_command(meshcore_client.commands, ("req_acl_sync", "req_acl"), contact, min_timeout=5)
    payload = event_payload(acl_event)
    return {"acl": payload, "read_only": infer_room_read_only(payload)}


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
            nodes.append(contact_display(pubkey, contact))
    return sorted(nodes, key=lambda n: (n["type"], n["name"]))


@app.get("/api/v1/map")
async def api_map() -> Dict[str, Any]:
    with state.lock:
        contact_markers = [map_marker_for_contact(pubkey, contact) for pubkey, contact in state.contacts.items()]
    self_marker = map_marker_for_self()
    markers = [self_marker, *contact_markers]
    valid_markers = [m for m in markers if m["location"]["valid"]]
    live_markers = [m for m in valid_markers if m["location"]["freshness"] == "live"]
    stale_markers = [m for m in valid_markers if m["location"]["freshness"] == "stale"]
    invalid_markers = [m for m in markers if not m["location"]["valid"]]
    return {
        "generated_at": utcnow(),
        "stale_after_seconds": LOCATION_STALE_SECONDS,
        "tile_requirement": "Internet access is required for the default OpenStreetMap, OpenTopoMap, and Esri tile layers.",
        "markers": markers,
        "counts": {
            "total": len(markers),
            "valid": len(valid_markers),
            "live": len(live_markers),
            "stale": len(stale_markers),
            "invalid": len(invalid_markers),
        },
    }


@app.get("/api/v1/ha/location")
async def api_ha_location() -> Dict[str, Any]:
    marker = map_marker_for_self()
    with state.lock:
        telemetry = dict(state.self_telemetry)
        connected = state.connected
        status = state.status
    return {
        "generated_at": utcnow(),
        "connected": connected,
        "status": status,
        **ha_location_payload(marker, telemetry),
        "telemetry": telemetry,
    }


@app.get("/api/v1/ha/locations")
async def api_ha_locations() -> Dict[str, Any]:
    with state.lock:
        contact_markers = [map_marker_for_contact(pubkey, contact) for pubkey, contact in state.contacts.items()]
        telemetry = dict(state.self_telemetry)
        connected = state.connected
        status = state.status
    self_marker = map_marker_for_self()
    markers = [self_marker, *contact_markers]
    locations = [
        ha_location_payload(marker, telemetry if marker.get("kind") == "self" else None)
        for marker in markers
        if marker.get("location", {}).get("valid")
    ]
    return {
        "generated_at": utcnow(),
        "connected": connected,
        "status": status,
        "total": len(locations),
        "locations": locations,
    }


@app.post("/api/v1/contacts")
async def api_create_contact(request: ContactCreateRequest) -> Dict[str, Any]:
    enforce_write("allow_contact_writes", "contact add")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    pubkey = request.public_key.lower()
    if not all(c in "0123456789abcdef" for c in pubkey):
        raise HTTPException(status_code=400, detail="public_key must be hex")
    contact = {
        "public_key": pubkey,
        "type": request.node_type,
        "flags": request.flags,
        "out_path_len": -1,
        "out_path": "",
        "adv_name": request.name,
        "last_advert": int(time.time()),
        "adv_lat": request.adv_lat,
        "adv_lon": request.adv_lon,
    }
    await run_device_command(meshcore_client.commands.add_contact(contact))
    with state.lock:
        state.contacts[pubkey] = contact
        state.contact_meta[pubkey] = {
            "alias": request.alias,
            "notes": request.notes,
            "trusted": request.trusted,
        }
    save_contact_meta()
    return contact_display(pubkey, contact)


@app.patch("/api/v1/contacts/{key}")
async def api_update_contact_meta(key: str, request: ContactMetaRequest) -> Dict[str, Any]:
    enforce_write("allow_contact_writes", "contact metadata update")
    pubkey, contact = contact_by_key(key)
    with state.lock:
        state.contact_meta[pubkey] = {
            "alias": request.alias,
            "notes": request.notes,
            "trusted": request.trusted,
        }
    save_contact_meta()
    return contact_display(pubkey, contact)


@app.delete("/api/v1/contacts/{key}")
async def api_remove_contact(key: str) -> Dict[str, Any]:
    enforce_write("allow_contact_writes", "contact remove")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    pubkey, _ = contact_by_key(key)
    await run_device_command(meshcore_client.commands.remove_contact(pubkey))
    with state.lock:
        state.contacts.pop(pubkey, None)
        state.contact_meta.pop(pubkey, None)
    save_contact_meta()
    return {"ok": True, "removed": pubkey}


@app.get("/api/v1/contacts/{key}/export")
async def api_export_contact(key: str) -> Dict[str, Any]:
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    pubkey, _ = contact_by_key(key)
    result = await run_device_command(meshcore_client.commands.export_contact(pubkey))
    return event_payload(result)


@app.get("/api/v1/contact-card/self")
async def api_export_self_contact() -> Dict[str, Any]:
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    result = await run_device_command(meshcore_client.commands.export_contact())
    return event_payload(result)


@app.post("/api/v1/contacts/import")
async def api_import_contact(request: ContactImportRequest) -> Dict[str, Any]:
    enforce_write("allow_contact_import", "contact import")
    enforce_write("allow_contact_writes", "contact import")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    uri = request.uri.strip()
    hex_data = uri.removeprefix("meshcore://")
    if not all(c in "0123456789abcdefABCDEF" for c in hex_data) or len(hex_data) % 2:
        raise HTTPException(status_code=400, detail="contact URI must be meshcore:// hex data")
    await run_device_command(meshcore_client.commands.import_contact(bytes.fromhex(hex_data)))
    contacts_result = await run_device_command(meshcore_client.commands.get_contacts(timeout=10))
    if contacts_result and contacts_result.payload:
        with state.lock:
            state.contacts = dict(contacts_result.payload)
    if request.alias or request.notes or request.trusted:
        with state.lock:
            newest = max(state.contacts.keys(), key=lambda k: state.contacts[k].get("last_advert", 0), default="")
            if newest:
                state.contact_meta[newest] = {
                    "alias": request.alias,
                    "notes": request.notes,
                    "trusted": request.trusted,
                }
        save_contact_meta()
    return {"ok": True}


@app.get("/api/v1/messages")
async def api_messages(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    scope: str = Query(default="all", pattern="^(all|public|channel|direct)$"),
    q: str = Query(default="", max_length=128),
    status: str = Query(default="all", pattern="^(all|queued|sending|sent|acknowledged|ack_timeout|failed|received)$"),
    direction: str = Query(default="all", pattern="^(all|incoming|outgoing)$"),
    conversation: str = Query(default="", max_length=160),
) -> Dict[str, Any]:
    messages = messages_for_filters(scope, q, status, direction, conversation)
    page = messages[offset:offset + limit]
    return {
        "total": len(messages),
        "limit": limit,
        "offset": offset,
        "scope": scope,
        "q": q,
        "status": status,
        "direction": direction,
        "conversation": conversation,
        "items": page,
    }


@app.get("/api/v1/messages/export")
async def api_export_messages(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    scope: str = Query(default="all", pattern="^(all|public|channel|direct)$"),
    q: str = Query(default="", max_length=128),
    status: str = Query(default="all", pattern="^(all|queued|sending|sent|acknowledged|ack_timeout|failed|received)$"),
    direction: str = Query(default="all", pattern="^(all|incoming|outgoing)$"),
    conversation: str = Query(default="", max_length=160),
) -> Response:
    messages = messages_for_filters(scope, q, status, direction, conversation)
    if format == "json":
        return Response(
            json.dumps({"exported_at": utcnow(), "total": len(messages), "items": messages}, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=meshcore-messages.json"},
        )
    columns = ["id", "timestamp", "direction", "conversation_type", "channel_name", "sender", "recipient", "status", "ack_count", "text"]
    rows = [",".join(csv_cell(col) for col in columns)]
    for message in messages:
        rows.append(",".join(csv_cell(message.get(col, "")) for col in columns))
    return Response(
        "\n".join(rows) + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=meshcore-messages.csv"},
    )


@app.get("/api/v1/conversations")
async def api_conversations() -> List[Dict[str, Any]]:
    conversations: Dict[str, Dict[str, Any]] = {}
    with state.lock:
        for channel in sorted_channels():
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
    if request.target_type == "channel":
        enforce_write("allow_channel_messages", "channel message send")
    else:
        enforce_write("allow_direct_messages", "direct message send")
    if not state.connected or not meshcore_client or not worker_loop:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message text is required")

    message: Dict[str, Any] = {
        "direction": "outgoing",
        "status": "queued",
        "conversation_type": request.target_type,
        "text": text,
        "timestamp": utcnow(),
        "hops": 0,
        "retry_enabled": request.retry,
        "resend_of": request.resend_of,
    }
    if request.target_type == "channel":
        if request.channel_idx is None:
            raise HTTPException(status_code=400, detail="channel_idx is required")
        message["channel_idx"] = request.channel_idx
        message["channel_name"] = channel_name(request.channel_idx)
        message["is_private"] = not public_channel(request.channel_idx, message["channel_name"])
    else:
        try:
            contact_key = resolve_contact(request.contact or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        message["channel_idx"] = None
        message["channel_name"] = "Direct"
        message["contact"] = contact_key
        message["recipient"] = contact_key[:12]

    append_message(message)
    update_message(int(message["id"]), {"status": "sending", "send_started_at": utcnow()})

    async def send() -> Any:
        if request.target_type == "channel":
            return await meshcore_client.commands.send_chan_msg(request.channel_idx, text)
        if request.retry:
            return await meshcore_client.commands.send_msg_with_retry(message["contact"], text, min_timeout=3)
        return await meshcore_client.commands.send_msg(message["contact"], text)

    future = asyncio.run_coroutine_threadsafe(send(), worker_loop)
    try:
        result = future.result(timeout=45)
    except ValueError as exc:
        update_message(int(message["id"]), {"status": "failed", "error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except concurrent.futures.TimeoutError as exc:
        update_message(int(message["id"]), {"status": "failed", "error": "message send timed out"})
        raise HTTPException(status_code=504, detail="message send timed out") from exc
    except Exception as exc:
        update_message(int(message["id"]), {"status": "failed", "error": str(exc)})
        raise HTTPException(status_code=500, detail=f"message send failed: {exc}") from exc

    if result is None:
        status = "ack_timeout"
        payload = {}
        result_type = "ack_timeout"
    else:
        result_type = event_type_value(result)
        payload = event_payload(result)
        status = "acknowledged" if request.target_type == "direct" and request.retry and result_type == EventType.MSG_SENT.value else "sent"
        success_types = {EventType.OK.value, EventType.MSG_SENT.value, "message_ok", "msg_ok", "channel_msg_sent"}
        msg_ok = event_type_or_none("MSG_OK")
        if msg_ok is not None:
            success_types.add(msg_ok.value)
        if result_type not in success_types:
            status = "failed"
        if result_type == EventType.ERROR.value:
            update_message(int(message["id"]), {"status": status, "send_result": {"event": result_type, "payload": payload}})
            raise HTTPException(status_code=502, detail={"status": status, "event": result_type, "payload": payload})

    updates = {
        "status": status,
        "sent_at": utcnow(),
        "send_result": {"event": result_type, "payload": payload},
        "expected_ack": payload.get("expected_ack") if isinstance(payload, dict) else None,
        "suggested_timeout_ms": payload.get("suggested_timeout") if isinstance(payload, dict) else None,
        "ack_count": 1 if status == "acknowledged" else 0,
    }
    if status == "acknowledged":
        updates["acks"] = [{"code": updates["expected_ack"], "timestamp": utcnow(), "source": "send_msg_with_retry"}]
    updated = update_message(int(message["id"]), updates) or message
    return {"ok": status != "failed", "status": status, "message": updated}


@app.post("/api/v1/messages/{message_id}/resend")
async def api_resend_message(message_id: int) -> Dict[str, Any]:
    original = find_message(message_id)
    if not original:
        raise HTTPException(status_code=404, detail="message not found")
    if original.get("direction") != "outgoing":
        raise HTTPException(status_code=400, detail="only outgoing messages can be resent")
    request = SendMessageRequest(
        target_type=original.get("conversation_type", "channel"),
        text=original.get("text", ""),
        channel_idx=original.get("channel_idx"),
        contact=original.get("contact"),
        retry=bool(original.get("retry_enabled", True)),
        resend_of=message_id,
    )
    return await api_send_message(request)


@app.get("/api/v1/channels")
async def api_channels() -> List[Dict[str, Any]]:
    return sorted_channels()


@app.patch("/api/v1/channels/{idx:int}")
async def api_update_channel(idx: int, request: ChannelUpdateRequest) -> Dict[str, Any]:
    enforce_write("allow_channel_config_writes", "channel update")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    secret = None
    if request.secret_hex:
        if len(request.secret_hex) != 32 or not all(c in "0123456789abcdefABCDEF" for c in request.secret_hex):
            raise HTTPException(status_code=400, detail="secret_hex must be 16 bytes / 32 hex characters")
        secret = bytes.fromhex(request.secret_hex)
    elif request.password:
        import hashlib
        secret = hashlib.sha256(request.password.encode("utf-8")).digest()[:16]
    await run_device_command(meshcore_client.commands.set_channel(idx, request.name, secret))
    result = await run_device_command(meshcore_client.commands.get_channel(idx))
    payload = result.payload or {}
    name = payload.get("channel_name") or payload.get("name") or request.name
    with state.lock:
        updated = {
            "idx": idx,
            "name": name,
            "is_private": not public_channel(idx, name),
            "channel_secret": payload.get("channel_secret", secret or b""),
        }
        state.channels = [ch for ch in state.channels if int(ch.get("idx", -1)) != idx]
        state.channels.append(updated)
        state.channel_meta[str(idx)] = {
            "pinned": request.pinned,
            "muted": request.muted,
            "sort_order": request.sort_order,
        }
    save_channel_meta()
    return channel_display(updated)


@app.patch("/api/v1/channels/{idx:int}/meta")
async def api_update_channel_meta(idx: int, request: ChannelMetaRequest) -> Dict[str, Any]:
    enforce_write("allow_channel_config_writes", "channel metadata update")
    with state.lock:
        state.channel_meta[str(idx)] = {
            "pinned": request.pinned,
            "muted": request.muted,
            "sort_order": request.sort_order,
        }
        channel = next((ch for ch in state.channels if int(ch.get("idx", -1)) == idx), {"idx": idx, "name": f"Channel {idx}"})
    save_channel_meta()
    return channel_display(channel)


@app.get("/api/v1/channels/backup")
async def api_channel_backup() -> Dict[str, Any]:
    return {"exported_at": utcnow(), "channels": sorted_channels()}


@app.post("/api/v1/channels/restore")
async def api_channel_restore(request: ChannelBackupRestoreRequest) -> Dict[str, Any]:
    enforce_write("allow_channel_restore", "channel restore")
    enforce_write("allow_channel_config_writes", "channel restore")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    restored = []
    for item in request.channels:
        idx = int(item.get("idx", 0))
        name = str(item.get("name") or f"Channel {idx}")[:32]
        secret_hex = str(item.get("secret_hex") or "")
        secret = bytes.fromhex(secret_hex) if len(secret_hex) == 32 and all(c in "0123456789abcdefABCDEF" for c in secret_hex) else None
        await run_device_command(meshcore_client.commands.set_channel(idx, name, secret))
        with state.lock:
            state.channel_meta[str(idx)] = {
                "pinned": bool(item.get("pinned", False)),
                "muted": bool(item.get("muted", False)),
                "sort_order": int(item.get("sort_order", 0) or 0),
            }
        restored.append(idx)
    save_channel_meta()
    await load_initial_data(meshcore_client)
    return {"ok": True, "restored": restored}


@app.get("/api/v1/rooms")
async def api_rooms() -> List[Dict[str, Any]]:
    with state.lock:
        rooms = [
            contact_display(pubkey, contact)
            for pubkey, contact in state.contacts.items()
            if int(contact.get("type", 0) or contact.get("adv_type", 0) or 0) == 3
        ]
    return sorted(rooms, key=lambda r: r["name"])


@app.post("/api/v1/rooms/{key}/sync")
async def api_room_sync(key: str, request: RoomSyncRequest) -> Dict[str, Any]:
    enforce_write("allow_room_sync", "room sync")
    if not state.connected or not meshcore_client:
        raise HTTPException(status_code=503, detail="MeshCore device is not connected")
    pubkey, contact = contact_by_key(key)
    if request.password:
        await run_device_command(meshcore_client.commands.send_login(pubkey, request.password))
    mma_event = await run_named_command(meshcore_client.commands, ("req_mma_sync", "req_mma"), contact, request.start, request.end, min_timeout=5)
    mma = event_payload(mma_event)
    acl = None
    try:
        acl_event = await run_named_command(meshcore_client.commands, ("req_acl_sync", "req_acl"), contact, min_timeout=5)
        acl = event_payload(acl_event)
    except HTTPException:
        acl = None
    return {
        "room": contact_display(pubkey, contact),
        "history": mma,
        "acl": acl,
        "read_only": infer_room_read_only(acl),
        "synced_at": utcnow(),
        "note": "Room history support depends on room-server firmware and meshcore_py binary responses.",
    }


@app.post("/api/v1/rooms/{key}/posts")
async def api_room_post(key: str, request: RoomPostRequest) -> Dict[str, Any]:
    enforce_write("allow_room_posts", "room post")
    pubkey, _ = contact_by_key(key)
    if request.password:
        await run_device_command(meshcore_client.commands.send_login(pubkey, request.password))
    send_request = SendMessageRequest(target_type="direct", contact=pubkey, text=request.text, retry=True)
    return await api_send_message(send_request)


def infer_room_read_only(acl: Any) -> Optional[bool]:
    if isinstance(acl, dict):
        value = acl.get("read_only") or acl.get("allow_read_only")
        if isinstance(value, bool):
            return value
    return None


def parse_time(value: Any) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(0, timezone.utc)


def csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return '"' + text.replace('"', '""') + '"'
