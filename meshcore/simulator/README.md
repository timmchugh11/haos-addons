# ESP32-C6 MeshCore Serial Simulator

This Arduino sketch emulates just enough of the MeshCore Companion serial
protocol for `meshcore_py` and the Home Assistant MeshCore GUI add-on to pass
startup.

It is useful for testing the add-on without a real MeshCore node.

## What It Simulates

- Serial frame parsing: `<` + little-endian payload length + payload
- `appstart` reply with `SELF_INFO`
- `device_query` reply with `DEVICE_INFO`
- one `Public` channel via `CHANNEL_INFO`
- empty contacts list
- private-key export disabled
- no queued messages
- simple OK replies for a few write commands

It does not implement LoRa, real contacts, routing, cryptography, RF logs, BBS,
BLE, or actual MeshCore firmware behavior.

## Arduino IDE

1. Install ESP32 Arduino core.
2. Select an ESP32-C6 board target, such as `ESP32C6 Dev Module`.
3. Enable `USB CDC On Boot` if your board uses native USB CDC.
4. Flash `ESP32C6_MeshCore_Simulator/ESP32C6_MeshCore_Simulator.ino`.
5. In the Home Assistant add-on, set:

```yaml
transport: serial
serial_port: /dev/ttyACM1
baudrate: 115200
serial_cx_delay: 2.0
debug: true
```

Use the actual `/dev/ttyACM*`, `/dev/ttyUSB*`, or `/dev/serial/by-id/*` path
that Home Assistant exposes for the ESP32-C6.
