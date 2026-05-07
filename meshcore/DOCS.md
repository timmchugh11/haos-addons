# MeshCore GUI Add-on Documentation

This add-on runs a custom MeshCore web GUI inside Home Assistant.

## Quick Start

1. Flash a supported MeshCore device with Companion firmware.
2. Plug the device into the Home Assistant host by USB.
3. Set `transport` to `serial`.
4. Select the correct `serial_port`.
5. Start the add-on and open **MeshCore** from the sidebar.

For Bluetooth, set `transport` to `ble`, set `ble_address` to the paired device
address, and confirm the host Bluetooth adapter is working.

## API

The bundled GUI exposes read-only endpoints under `/api/v1/`, including stats,
nodes, messages and channels.

## Roadmap

See [TODO.md](TODO.md) for the remaining work toward full MeshCore companion
feature coverage.

## References Used

- MeshCore Companion Protocol, firmware v1.12.0+: https://docs.meshcore.io/companion_protocol/
- Home Assistant add-on configuration reference: https://developers.home-assistant.io/docs/apps/configuration/
- MeshCore Python protocol library: https://github.com/meshcore-dev/meshcore_py
