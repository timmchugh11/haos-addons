# MeshCore GUI

MeshCore GUI is a custom Home Assistant add-on for MeshCore companion radios.
It runs a standalone FastAPI backend and a custom single-page web UI served at
`/`, with Home Assistant ingress support and direct access on port
`8081`.

The add-on is intended for MeshCore Companion firmware devices connected to the
Home Assistant host by USB serial.

## Current Status

This project is functional but still experimental. The dashboard, messaging,
contacts, channels, map, diagnostics, admin safety controls, and REST API are in
place. Some advanced MeshCore firmware features depend on the connected device,
firmware build, and the command support exposed by `meshcore_py`.

## Features

- Custom dark web UI with Dashboard, Messages, Nodes, Channels, Room Servers,
  Diagnostics, Map, Identity, and Admin pages.
- USB serial transport.
- Channel and direct message history with compact chat layout, scrollable
  conversations, reply actions, composer, retry/resend, delivery state, ACK
  tracking, filters, pagination, browser notifications, and JSON/CSV export.
- Contact/node management with manual add, metadata, trust flags, removal,
  `meshcore://` contact import, and contact-card export.
- Channel management with name updates, private channel key/password support,
  local pin/mute/sort metadata, and backup/restore.
- Room server discovery, login/history sync where supported, ACL/read-only
  display where supported, and guarded room posting.
- Leaflet map with role-based markers, browser-local location, stale/live
  coordinate handling, clustering, heat layer, labels, and own-node location
  display.
- Identity page with local name/advertised coordinates, battery/storage/radio
  status, contact-card export, radio controls, GPS/power-saving toggles,
  routing controls, reboot, clock sync, and advert commands.
- Diagnostics page with connection health, serial port discovery, event logs,
  sensor telemetry, and connection test endpoint.
- Admin page with persisted write-safety toggles, maintenance mode, and browser
  confirmation prompts for write actions.
- Firmware flasher for serial `.bin` uploads using `esptool`, with optional
  erase-first mode guarded by a disabled-by-default admin safety toggle.
- REST API under `/api/v1/*` for the custom UI and external automations.

## Configuration

| Option | Default | Description |
|---|---:|---|
| `serial_port` | `/dev/ttyACM0` | MeshCore USB serial device |
| `baudrate` | `115200` | Serial baud rate |
| `serial_cx_delay` | `2.0` | Delay after opening the serial port before sending the first MeshCore command |
| `debug` | `false` | Enables verbose MeshCore GUI and protocol logging |

## Access

Use the Home Assistant sidebar entry named **MeshCore**. The custom dashboard is
served at `/` through ingress.

Direct access is mapped by default on `8081/tcp`, so the UI and REST API are
also available at `http://<home-assistant-host>:8081/` when the add-on is
running.

## Persistent Data

Runtime state is stored under `/data/.meshcore` inside the add-on data volume.
This includes message history, contact metadata, channel metadata, and admin
safety settings.

## API

The add-on exposes a REST API under `/api/v1/*`. Key endpoints include:

- `GET /api/v1/status`
- `GET /api/v1/stats`
- `GET /api/v1/identity`
- `PATCH /api/v1/identity`
- `GET /api/v1/messages`
- `POST /api/v1/messages`
- `POST /api/v1/messages/{message_id}/resend`
- `GET /api/v1/messages/export`
- `GET /api/v1/conversations`
- `GET /api/v1/nodes`
- `POST /api/v1/contacts`
- `PATCH /api/v1/contacts/{key}`
- `DELETE /api/v1/contacts/{key}`
- `GET /api/v1/channels`
- `PATCH /api/v1/channels/{idx}`
- `GET /api/v1/channels/backup`
- `POST /api/v1/channels/restore`
- `GET /api/v1/rooms`
- `POST /api/v1/rooms/{key}/sync`
- `POST /api/v1/rooms/{key}/posts`
- `GET /api/v1/map`
- `GET /api/v1/ha/location`
- `GET /api/v1/ha/locations`
- `GET /api/v1/diagnostics`
- `GET /api/v1/diagnostics/logs`
- `GET /api/v1/sensors`
- `PATCH /api/v1/radio`
- `PATCH /api/v1/routing`
- `GET /api/v1/admin/settings`
- `PUT /api/v1/admin/settings`

Write-capable endpoints are guarded by the Admin safety settings. Room posts,
contact imports, and channel restore are disabled by default until enabled from
the Admin page.

## Home Assistant REST Location

The add-on exposes a small stable endpoint for Home Assistant REST sensors:

```yaml
rest:
  - resource: http://a0d7b954-meshcore:8081/api/v1/ha/location
    scan_interval: 30
    sensor:
      - name: MeshCore Location
        value_template: "{{ value_json.ha_state }}"
        json_attributes:
          - latitude
          - longitude
          - altitude
          - gps_accuracy
          - battery_voltage
          - updated_at
          - freshness
          - source
```

## Transport Notes

Serial mode is the recommended default for a Home Assistant appliance. It uses
the USB/UART devices exposed by the Supervisor.

Bluetooth support is disabled for now while the serial GUI is stabilised.

## Known Limitations

- Some radio, routing, room server, ACL, and telemetry commands depend on
  firmware support and the command names exposed by the installed
  `meshcore_py` version.
- Firmware flashing pauses the live serial worker while `esptool` uses the
  selected port. The device must be in bootloader/flash mode if the board
  requires it.
- Enabling GPS uses companion custom variables (`gps=1`, `gps_interval=1`) and
  advert-location sharing where the firmware supports them.
- Map tiles are loaded from external tile providers in the browser; offline tile
  caching is not implemented yet.
- API auth/rate limiting for direct non-ingress access is still on the roadmap.

## Upstream

- MeshCore docs: https://docs.meshcore.io/
- Companion Protocol: https://docs.meshcore.io/companion_protocol/
- MeshCore Python protocol library: https://github.com/meshcore-dev/meshcore_py

## Roadmap

See [TODO.md](TODO.md) for the remaining work toward a full-featured MeshCore
companion GUI.

## Version

Current add-on version: `0.10.8`
