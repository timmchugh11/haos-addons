# Hostapd AP

WiFi access point managed via a built-in web UI. Uses `hostapd` for AP mode and
`dnsmasq` for DHCP. Supports independent 2.4 GHz and 5 GHz radios.

---

## Requirements

- A WiFi adapter whose driver supports AP mode (see [Adapter compatibility](#adapter-compatibility))
- `amd64` or `aarch64` host (works on `armv7`/`armhf`/`i386` too but untested)
- Protection mode must be **disabled** on the add-on Info tab (required for `NET_ADMIN` / `SYS_ADMIN` and `host_network`)

---

## Quick start

1. Install the add-on and turn off **Protection mode** in the Info tab.
2. Start the add-on and open the **Web UI** via the sidebar or the panel button.
3. Select your WiFi interface(s), set your SSID and password, and click **Save Config**.
4. Click **Apply & Start**.

Configuration is stored in `/data/hostapd_config.json` — there are no options to set
in the Home Assistant add-on configuration page.

---

## Web UI

Accessible via HA ingress (sidebar) or directly at `http://<ha-ip>:8080`.

| Section | Description |
|---|---|
| **Status** | Live indicator (updates every 5 s). Apply & Start / Stop AP buttons. |
| **Shared Settings** | Password (shared across both radios) and country code. |
| **2.4 GHz Radio** | Toggle, interface selector, SSID, channel (1–13). |
| **5 GHz Radio** | Toggle, interface selector, SSID, channel (36/40/44/48…). |

The interface dropdown shows each detected wireless interface with an inline warning if
AP mode is not supported, and displays USB device info and USB bus speed on selection.

---

## Adapter compatibility

The add-on checks AP mode support on startup and logs the result. To be usable as an AP,
the adapter's driver must include `AP` in its supported interface modes.

**Quick check in the add-on log:**
```
AP mode: SUPPORTED
```
or
```
AP mode: NOT SUPPORTED — this adapter cannot be used as an access point
```

## Networking

| Band | AP gateway IP | DHCP range |
|---|---|---|
| 2.4 GHz | `192.168.50.1` | `192.168.50.10` – `192.168.50.100` |
| 5 GHz | `192.168.51.1` | `192.168.51.10` – `192.168.51.100` |

Connected clients are NAT-masqueraded through the HAOS host's upstream connection.
DNS is set to `1.1.1.1` / `8.8.8.8`.
