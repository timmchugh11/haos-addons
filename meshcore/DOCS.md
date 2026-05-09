 # MeshCore GUI Add-on Documentation

This add-on runs a custom MeshCore web GUI inside Home Assistant. It provides a
FastAPI backend, a custom browser UI, USB serial MeshCore connectivity, and a
REST API under `/api/v1/*`.

## Quick Start

1. Flash a supported MeshCore device with Companion firmware.
2. Plug the device into the Home Assistant host by USB.
3. Select the correct `serial_port`.
4. Start the add-on and open **MeshCore** from the sidebar.

## Main Pages

- **Dashboard**: public traffic stats and recent messages.
- **Messages**: channel/direct conversations, compact chat layout, reply
  actions, selected-chat composer, resend, filters, and export.
- **Nodes**: contacts, trust flags, metadata, contact-card import/export.
- **Channels**: channel editor, private keys/passwords, backup and restore.
- **Room Servers**: room discovery, history/status sync, ACL/read-only display,
  and guarded posts.
- **Diagnostics**: connection health, event logs, sensors, and connection test.
- **Map**: Leaflet markers, browser-local location, clustering, heatmap,
  labels, stale/live locations.
- **Identity**: local identity, radio status, radio controls, GPS/power-saving
  toggles, routing controls, reboot, clock sync, and adverts.
- **Admin**: write-safety toggles and maintenance mode.

## Write Safety

The Admin page controls write-capable features. Room posts, contact imports, and
channel restore are disabled by default. Maintenance mode blocks write-capable
API actions while still allowing admin settings to be changed.

## API

The bundled GUI uses endpoints under `/api/v1/`, including status, stats,
identity, messages, conversations, nodes, contacts, channels, rooms, map,
diagnostics, sensors, radio/routing, and admin settings.

Write-capable endpoints are available for supported actions and are guarded by
the Admin safety policy.

GPS and power-saving controls use the MeshCore serial CLI commands exposed by
firmware that supports them (`gps on/off` and `powersaving on/off`).

## Persistent Data

Runtime state is stored under `/data/.meshcore` in the add-on data volume. This
includes message history, contact metadata, channel metadata, and admin safety
settings.

## Roadmap

See [TODO.md](TODO.md) for the remaining work toward full MeshCore companion
feature coverage.

Bluetooth transport is intentionally disabled for now while the serial GUI is
stabilised.

## References Used

- MeshCore Companion Protocol, firmware v1.12.0+: https://docs.meshcore.io/companion_protocol/
- Home Assistant add-on configuration reference: https://developers.home-assistant.io/docs/apps/configuration/
- MeshCore Python protocol library: https://github.com/meshcore-dev/meshcore_py
