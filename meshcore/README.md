# MeshCore GUI

MeshCore GUI is a custom Home Assistant add-on for MeshCore companion radios.

It is intended for MeshCore Companion firmware devices connected to the Home
Assistant host by USB serial or Bluetooth LE.

## Features

- Real-time MeshCore dashboard
- Contacts and node management
- Channel messages and direct messages with send support
- Channel management, backup and restore
- Read-only public REST API at `/api/v1/*`
- USB serial and BLE transports

## Configuration

| Option | Default | Description |
|---|---:|---|
| `transport` | `serial` | `serial` or `ble` |
| `serial_port` | `/dev/ttyACM0` | MeshCore USB serial device |
| `baudrate` | `115200` | Serial baud rate |
| `serial_cx_delay` | `2.0` | Delay after opening the serial port before sending the first MeshCore command |
| `ble_address` | `literal:AA:BB:CC:DD:EE:FF` | BLE device address. Keep the `literal:` prefix for a fixed MAC address. |
| `ble_pin` | `123456` | BLE pairing PIN |
| `debug` | `false` | Enables verbose MeshCore GUI and protocol logging |

## Access

Use the Home Assistant sidebar entry named **MeshCore**. The custom dashboard is
served at `/`.

Optional direct access can be enabled by mapping port `8081/tcp` in the add-on
network settings.

## Persistent Data

The add-on sets `HOME=/data`, so runtime state persists in the add-on data
volume.

## Transport Notes

Serial mode is the recommended default for a Home Assistant appliance. It uses
the USB/UART devices exposed by the Supervisor.

BLE mode requires the host Bluetooth stack, D-Bus and BlueZ to be available to
the add-on. BLE support is included, but serial is usually more reliable for a
permanent Home Assistant install.

## Upstream

- MeshCore docs: https://docs.meshcore.io/
- Companion Protocol: https://docs.meshcore.io/companion_protocol/
- MeshCore Python protocol library: https://github.com/meshcore-dev/meshcore_py

## Roadmap

See [TODO.md](TODO.md) for the remaining work toward a full-featured MeshCore
companion GUI.

## Version

Current add-on version: `0.9.2`
