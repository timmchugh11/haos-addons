# MeshCore GUI Add-on Documentation

This add-on runs the upstream MeshCore GUI inside Home Assistant.

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
nodes, messages and channels. These are provided by the upstream application.

## References Used

- MeshCore Companion Protocol, firmware v1.12.0+: https://docs.meshcore.io/companion_protocol/
- Home Assistant add-on configuration reference: https://developers.home-assistant.io/docs/apps/configuration/
- Upstream MeshCore GUI README: https://github.com/pe1hvh/meshcore-gui
