# MeshCore GUI

MeshCore GUI packages the upstream all-in-one MeshCore web interface as a Home
Assistant add-on with ingress support.

It is intended for MeshCore Companion firmware devices connected to the Home
Assistant host by USB serial or Bluetooth LE.

## Features

- Real-time MeshCore dashboard
- Contacts and node management
- Channel messages and direct messages
- Channel management, backup and restore
- Message archive and RX log
- Route visualization and map views
- Room Server support
- Offline BBS
- Keyword bot
- Cross-frequency bridge support in the bundled upstream application
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

Use the Home Assistant sidebar entry named **MeshCore**. It opens the custom
Starlink-style dashboard at `/custom`. The upstream DOMCA/NiceGUI interface is
still available at `/` when using direct access.

Optional direct access can be enabled by mapping port `8081/tcp` in the add-on
network settings.

## Persistent Data

The upstream GUI normally stores state under `~/.meshcore-gui`. This add-on sets
`HOME=/data`, so archives, caches, pins, BBS data, bot configuration, channel
backups and logs persist in the add-on data volume.

## Transport Notes

Serial mode is the recommended default for a Home Assistant appliance. It uses
the USB/UART devices exposed by the Supervisor.

BLE mode requires the host Bluetooth stack, D-Bus and BlueZ to be available to
the add-on. BLE support is included, but serial is usually more reliable for a
permanent Home Assistant install.

## Upstream

- MeshCore docs: https://docs.meshcore.io/
- Companion Protocol: https://docs.meshcore.io/companion_protocol/
- MeshCore GUI: https://github.com/pe1hvh/meshcore-gui
- MeshCore Python protocol library: https://github.com/meshcore-dev/meshcore_py

## Version

Current add-on version: `0.2.2`
