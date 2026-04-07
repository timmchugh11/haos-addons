# Hostapd AP

> Warning: This is a personal project and is not production-hardened. It can and will break the host's network configuration while testing or applying AP/NAT/bridge changes. Do not use it unless you are comfortable recovering the host from a lost network connection.

WiFi access point managed via a built-in web UI. Uses `hostapd` for AP mode and supports
either routed/NAT mode or experimental bridge mode.
Supports independent 2.4 GHz and 5 GHz radios. 6 GHz detection remains in the backend
and logs, but 6 GHz AP configuration is currently hidden in the UI while support is
being revisited.

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

**6 GHz status:** the add-on still detects and logs 6 GHz-capable adapters, but the
6 GHz radio controls are currently hidden because 6 GHz AP broadcasting is not working
reliably yet.

---

## Networking

The add-on supports two network modes:

- `NAT (Recommended)`: clients are placed on a dedicated AP subnet behind the add-on. The add-on creates an internal bridge (`br-ap`) for the AP radios, runs `dnsmasq` for DHCP/DNS, and NATs client traffic out through the detected host uplink.
- `Bridge (Experimental)`: clients are bridged onto the upstream LAN. This is better for same-LAN use cases, but it is less reliable and can fail to pass DHCP/client traffic depending on the host, adapter, and driver.

---

## Adapter compatibility

The add-on checks AP mode and band support on startup and logs the result. To be usable
as an AP, the adapter's driver must include `AP` in its supported interface modes.

**Quick check in the add-on log:**
```
    wlan0  AP:yes  6GHz:no  bands=2.4GHz/5GHz
```
or
```
    wlan1  AP:yes  6GHz:yes  bands=2.4GHz/5GHz/6GHz
```

6 GHz capability is still reported in startup logs so compatible adapters can be
identified quickly, but 6 GHz AP mode is currently disabled in the web UI.

### Recommended chipsets

| Chipset | Band | Notes |
|---|---|---|
| **Mediatek MT7612U** | 5 GHz | In-kernel `mt76` driver. Most adapters pair with a MT7603U for 2.4 GHz. |
| **Mediatek MT7603U** | 2.4 GHz | In-kernel `mt76` driver, reliable AP mode. |
| **Mediatek MT7921AU** | 2.4 + 5 GHz | In-kernel, WiFi 6, single chip dual-band. 6 GHz support depends on chipset/driver variant. |
| **Ralink RT5572** | 2.4 + 5 GHz | Older but well-supported. |

### Adapters to avoid

- Most **Realtek RTL8188 / RTL8192** nano adapters — client mode only
- Generic "AC600 nano" sticks — usually no AP mode

---

## Dual-band with a single USB adapter

Many adapters labelled "dual-band" contain two chips on one USB dongle — for example a
MT7612U (5 GHz) paired with a MT7603U (2.4 GHz). Linux exposes these as two separate
interfaces (e.g. `wlan0` and `wlan1`). Assign each to the corresponding radio in the UI.

**Note:** both radios share the same USB bus bandwidth. For light home use this is fine.

