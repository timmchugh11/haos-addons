# Hostapd AP

WiFi access point managed via a built-in web UI. Uses `hostapd` for AP mode and bridges
WiFi clients directly onto your existing network — no separate DHCP server, no NAT.
Supports independent 2.4 GHz, 5 GHz, and 6 GHz radios.

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
| **6 GHz Radio** | Toggle, interface selector, SSID, channel (1/5/9/13…233), WPA3-SAE only. |

The interface dropdown shows each detected wireless interface with an inline warning if
AP mode is not supported, and displays USB device info and USB bus speed on selection.

---

## Networking

WiFi clients are **bridged directly to your existing network**. The add-on automatically
detects your host's uplink interface, creates a Linux bridge (`br-ap-2g` / `br-ap-5g`),
`br-ap-6g`), and attaches both the uplink and the WiFi interface to it.

- WiFi clients get their IP, gateway, and DNS from **your existing router's DHCP server**
- No separate subnet, no NAT, no dnsmasq required
- Clients appear on the same LAN as every other device

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

For 6 GHz AP mode, the add-on writes a WPA3-SAE configuration and expects the adapter
and driver to expose valid 6 GHz channels.

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

