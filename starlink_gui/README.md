# Starlink GUI

Starlink GUI is a Home Assistant add-on that exposes a local web interface for a
Starlink dish and Starlink router over the local gRPC APIs.

It is designed to run inside Home Assistant with ingress enabled, so the UI can
open directly from the HA sidebar without publishing a separate public endpoint.

## What It Does

- Live dashboard with dish and router summary cards
- Dish pages for:
  - status
  - diagnostics
  - history and signal charts
  - obstruction map
  - location
  - basic controls (`reboot`, `stow`, `unstow`)
- Router pages for:
  - status
  - connected clients
  - interfaces
  - ping metrics
  - diagnostics
- Auto-refresh support in the web UI
- Home Assistant ingress support plus optional direct access on port `3000`

The UI is read-heavy by design. Dish control actions are available, but router
write/config actions are not exposed in the frontend.

## Requirements

- Home Assistant must be able to reach your Starlink devices on the local network
- The dish and router gRPC interfaces must be reachable from the HA host
- Typical defaults are:
  - dish: `192.168.100.1:9200`
  - router: `192.168.1.1:9000`

If Starlink is in bypass mode, or Home Assistant is on a different subnet, you
may need static routes or different IP settings.

## Add-on Configuration

The add-on supports these options in `config.yaml`:

| Option | Default | Description |
|---|---|---|
| `dish_host` | `192.168.100.1` | Starlink dish IP address |
| `dish_port` | `9200` | Dish gRPC port |
| `router_host` | `192.168.1.1` | Starlink router IP address |
| `router_port` | `9000` | Router gRPC port |

These values are used as defaults in the UI. The settings page also allows
per-session overrides in the browser.

## Access

- Preferred: open through Home Assistant ingress / sidebar
- Optional: direct access on port `3000`

Port `3000/tcp` is declared in the add-on config. Depending on your HA setup,
you can leave it internal and use ingress only.

## UI Notes

- The default UI auto-refresh interval is `3` seconds
- Device address overrides in the settings page are session-only
- Router pages are based on the fields your Starlink firmware actually returns;
  some fields may be sparse depending on hardware and firmware version

## API Surface In This Add-on

The backend exposes internal JSON endpoints used by the frontend, including:

- Dish:
  - `/api/dishy/status`
  - `/api/dishy/diagnostics`
  - `/api/dishy/history`
  - `/api/dishy/location`
  - `/api/dishy/obstruction-map`
  - `/api/dishy/reboot`
  - `/api/dishy/stow`
  - `/api/dishy/unstow`
- Router:
  - `/api/router/status`
  - `/api/router/clients`
  - `/api/router/networks`
  - `/api/router/interfaces`
  - `/api/router/ping-metrics`
  - `/api/router/diagnostics`

There are also additional read/debug endpoints in the backend, including router
and dish dump/config/history routes, but those are not part of the normal UI.

## Local Development

The add-on is a small Node/Express app using:

- `express`
- `cors`
- `@gibme/starlink`

Basic run flow:

```bash
npm install
npm start
```

The server serves the UI from `public/index.html` and proxies requests to the
local Starlink devices.

## Current Version

The add-on version is `1.0.7`.
