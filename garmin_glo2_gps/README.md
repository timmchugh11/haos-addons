# Garmin GLO2 GPS add-on

Home Assistant OS add-on for the Garmin GLO 2 Bluetooth GPS receiver. Connects over Bluetooth RFCOMM, reads NMEA sentences, and publishes a single `device_tracker` entity through the Home Assistant Core API.

## Install

1. In Home Assistant, go to **Settings > Add-ons > Add-on Store**.
2. Open the three-dot menu and choose **Repositories**.
3. Add this repository URL.
4. Install **Garmin GLO2 GPS** and start it.

## Configure

| Option | Default | Description |
| --- | --- | --- |
| `bluetooth_mac` | `AA:BB:CC:DD:EE:FF` | Bluetooth MAC address of the Garmin GLO 2 |
| `rfcomm_channel` | `1` | RFCOMM/SPP channel number |
| `debug` | `true` | Log every raw NMEA sentence |

## Pair the Garmin first

The Garmin must be paired with the HAOS host before the add-on can connect. Use the SSH add-on:

```bash
bluetoothctl
power on
agent on
default-agent
scan on
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
quit
```

## Home Assistant entity

The add-on creates and updates a single entity:

```text
device_tracker.garmin_glo2
```

When a GPS fix is active, it carries `latitude`, `longitude`, and `gps_accuracy` attributes so it appears on the Home Assistant map and participates in zone automation. Additional attributes include `altitude`, `speed_knots`, `course`, `satellites`, `hdop`, and `timestamp`.

State is `not_home` with a fix, `unknown` without one.

## Requirements

- Home Assistant OS (HAOS)
- Garmin GLO 2 paired to the HAOS host via Bluetooth Classic
- Add-on config: `host_network: true`, `host_dbus: true`, `NET_ADMIN` / `NET_RAW` / `SYS_ADMIN` privileges
