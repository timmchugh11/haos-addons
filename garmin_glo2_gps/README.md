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
| `publish_interval` | `1` | Minimum seconds between published RMC fixes; Bluetooth stays connected. |
| `poll_interval` | `30` | Legacy option retained for upgrades; ignored since 0.5.0. |
| `read_timeout` | `8` | Reconnect after this many seconds without NMEA data. |
| `debug` | `true` | Log a concise summary for each published fix |

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

By default the add-on connects to the Garmin every 30 seconds, reads fresh NMEA data for up to 8 seconds, publishes one Home Assistant update, and then disconnects. This keeps the Bluetooth adapter free between GPS updates for other Bluetooth devices.

## Requirements

- Home Assistant OS (HAOS)
- Garmin GLO 2 paired to the HAOS host via Bluetooth Classic
- Add-on config: `host_network: true`, `host_dbus: true`, `NET_ADMIN` / `NET_RAW` / `SYS_ADMIN` privileges

## Continuous tracking (0.5.0)

The RFCOMM connection stays open. RMC fixes are published at most once per `publish_interval` seconds; GGA enriches altitude, satellites and HDOP. Disconnects reconnect with 1–30 second backoff. Input buffering is limited to 64 KiB. The receiver must supply fresh RMC timestamps; stale fixes are never retimestamped.

Offline stream tests: `python garmin_glo2_gps/test_stream.py`. Revert to 0.4.3 to restore the previous intermittent connection behaviour.
