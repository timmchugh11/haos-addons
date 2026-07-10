#!/usr/bin/env python3
"""Read Garmin GLO 2 NMEA data from RFCOMM and publish it to Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
import json
import logging
import os
import select
import socket
import time as time_module
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pynmea2

LOGGER = logging.getLogger("garmin_glo2")


@dataclass
class GpsState:
    """Latest Garmin GLO 2 GPS state."""

    fix: bool = False
    latitude: float | None = None
    longitude: float | None = None
    speed_knots: float | None = None
    course: float | None = None
    altitude: float | None = None
    satellites: int | None = None
    hdop: float | None = None
    timestamp: str | None = None
    last_sentence: str | None = None
    source: str = "Garmin GLO 2"


class Publisher:
    """Publish GPS state to the Home Assistant Core API."""

    def __init__(self) -> None:
        self._token = os.getenv("SUPERVISOR_TOKEN") or os.getenv("HASSIO_TOKEN")
        self._base_url = "http://supervisor/core/api"
        if not self._token:
            LOGGER.warning("SUPERVISOR_TOKEN is missing; cannot publish to Home Assistant")

    def publish(self, state: GpsState) -> None:
        """Publish the current GPS state."""
        self._publish_homeassistant_api(state)

    def close(self) -> None:
        """Close publisher resources."""
        return

    def _publish_homeassistant_api(self, state: GpsState) -> None:
        if not self._token:
            return

        attrs: dict[str, Any] = {
            "source_type": "gps",
            "friendly_name": "Garmin GLO2",
            "icon": "mdi:crosshairs-gps",
            "satellites": state.satellites,
            "hdop": state.hdop,
            "altitude": state.altitude,
            "speed_knots": state.speed_knots,
            "course": state.course,
            "timestamp": state.timestamp,
        }
        if state.fix and state.latitude is not None and state.longitude is not None:
            attrs["latitude"] = state.latitude
            attrs["longitude"] = state.longitude
            attrs["gps_accuracy"] = int(state.hdop * 10) if state.hdop else 50

        self._post_state(
            "device_tracker.garmin_glo2",
            EntityState(
                state="not_home" if state.fix else "unknown",
                attributes=attrs,
            ),
        )

    def _post_state(self, entity_id: str, entity_state: EntityState) -> None:
        payload = json.dumps(
            {
                "state": _ha_state_value(entity_state.state),
                "attributes": entity_state.attributes,
            }
        ).encode()
        request = Request(
            f"{self._base_url}/states/{entity_id}",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                response.read()
        except URLError as err:
            LOGGER.warning("Failed to publish %s through HA API: %s", entity_id, err)


@dataclass(frozen=True)
class EntityState:
    """Home Assistant state API payload values."""

    state: Any
    attributes: dict[str, Any]


def parse_message(line: str, state: GpsState) -> bool:
    """Parse one NMEA line into state. Return true when publish-worthy."""
    # Pre-filter: only parse sentence types we actually use, avoiding the
    # overhead of pynmea2.parse() on GSV, GSA, VTG, GLL, etc.
    sentence_type = line[3:6] if len(line) > 6 else ""
    if sentence_type not in ("RMC", "GGA"):
        return False
    try:
        message = pynmea2.parse(line)
    except pynmea2.ParseError:
        return False

    updated = False
    state.last_sentence = line

    if message.sentence_type == "RMC":
        state.fix = getattr(message, "status", None) == "A"
        state.timestamp = _timestamp_from_rmc(message) or datetime.now(UTC).isoformat()
        if state.fix:
            state.latitude = _float_or_none(getattr(message, "latitude", None))
            state.longitude = _float_or_none(getattr(message, "longitude", None))
            state.speed_knots = _float_or_none(getattr(message, "spd_over_grnd", None))
            state.course = _float_or_none(getattr(message, "true_course", None))
        updated = True

    elif message.sentence_type == "GGA":
        quality = _int_or_none(getattr(message, "gps_qual", None)) or 0
        state.fix = quality > 0
        state.altitude = _float_or_none(getattr(message, "altitude", None))
        state.satellites = _int_or_none(getattr(message, "num_sats", None))
        state.hdop = _float_or_none(getattr(message, "horizontal_dil", None))
        updated = True

    return updated


def reader_loop() -> None:
    """Poll NMEA data over Bluetooth RFCOMM, disconnecting between updates."""
    mac = os.getenv("BLUETOOTH_MAC", "AA:BB:CC:DD:EE:FF")
    channel = int(os.getenv("RFCOMM_CHANNEL", "1"))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    poll_interval = max(5, int(os.getenv("POLL_INTERVAL", "30")))
    read_timeout = max(1, int(os.getenv("READ_TIMEOUT", "8")))
    publisher = Publisher()

    try:
        while True:
            cycle_started = time_module.monotonic()
            state = GpsState()
            updated = False
            published = False
            sock = None
            try:
                LOGGER.info("Connecting to %s channel %s", mac, channel)
                sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                sock.settimeout(10.0)
                sock.connect((mac, channel))
                sock.setblocking(True)
                LOGGER.info("RFCOMM connected")
                buf = b""
                read_deadline = time_module.monotonic() + read_timeout
                while time_module.monotonic() < read_deadline:
                    timeout = max(0.1, min(1.0, read_deadline - time_module.monotonic()))
                    readable, _, _ = select.select([sock], [], [], timeout)
                    if not readable:
                        continue
                    chunk = sock.recv(4096)
                    if not chunk:
                        LOGGER.warning("Connection closed by device")
                        break
                    buf += chunk
                    while b"\n" in buf:
                        raw_line, buf = buf.split(b"\n", 1)
                        line = raw_line.decode("ascii", errors="ignore").strip()
                        if not line.startswith("$"):
                            continue
                        if debug:
                            LOGGER.info("NMEA: %s", line)
                        if parse_message(line, state):
                            updated = True
                            if state.fix and state.latitude is not None and state.longitude is not None:
                                publisher.publish(state)
                                published = True
                                break
                    if published:
                        break
                if updated and not published:
                    publisher.publish(state)
                    published = True
                if not published:
                    LOGGER.warning("No publish-worthy NMEA data received during %ss read window", read_timeout)
            except OSError as err:
                LOGGER.warning("RFCOMM error: %s", err)
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                    LOGGER.info("RFCOMM disconnected")
            elapsed = time_module.monotonic() - cycle_started
            sleep_for = max(0.0, poll_interval - elapsed)
            if sleep_for > 0:
                time_module.sleep(sleep_for)
    finally:
        publisher.close()


def _timestamp_from_rmc(message: pynmea2.NMEASentence) -> str | None:
    msg_date = getattr(message, "datestamp", None)
    msg_time = getattr(message, "timestamp", None)
    if isinstance(msg_date, date) and isinstance(msg_time, time):
        return datetime.combine(msg_date, msg_time, tzinfo=UTC).isoformat()
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ha_state_value(value: Any) -> str:
    """Convert a Python value to a Home Assistant state string."""
    if value is None:
        return "unknown"
    return str(value)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    reader_loop()


if __name__ == "__main__":
    main()
