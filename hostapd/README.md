# Hostapd AP

> Warning: This is a personal project and is not production-hardened. It can and will break the host's network configuration while testing or applying AP/NAT/bridge changes. Do not use it unless you are comfortable recovering the host from a lost network connection.

WiFi access point managed via a built-in web UI. Uses `hostapd` for AP mode and supports
either routed/NAT mode or experimental bridge mode. 5 GHz radios can optionally enable
Wi-Fi 6 / 802.11ax when the adapter, driver, and hostapd build support it.
Supports independent 2.4 GHz and 5 GHz radios. 6 GHz detection remains in the backend
and logs, and can now be exposed through an explicit experimental UI toggle when the
adapter reports enough 6 GHz AP capability to justify testing. 6 GHz should still be
treated as experimental only.

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
| **Shared Settings** | Password, country code, and network mode. |
| **2.4 GHz Radio** | Toggle, interface selector, SSID, channel (1–13), WPA3 toggle. |
| **5 GHz Radio** | Toggle, interface selector, SSID, channel (36/40/44/48…), channel width, AX toggle, WPA3 toggle. |
| **6 GHz Radio (Experimental)** | Hidden by default. Only shown when `Enable Experimental 6 GHz UI` is on and the adapter reports Band 4 + HE AP + SAE + START_AP capability. Limited to detected 20 MHz channels with WPA3-SAE. |
| **DHCP** | Private subnet, gateway, lease range, and lease duration for NAT mode. |
| **Debug** | Shows diagnostics, generated hostapd config snippets, recent hostapd logs, and a command runner inside the add-on container. |

The interface dropdown shows each detected wireless interface with an inline warning if
AP mode is not supported, and displays USB device info and USB bus speed on selection.

**6 GHz status:** the add-on still treats 6 GHz as experimental. The normal workflow
keeps it hidden. A dedicated experimental toggle can reveal the 6 GHz radio section,
but only when the detected adapter reports Band 4 presence, HE AP support, SAE support,
and `START_AP` capability. Even then, 6 GHz AP startup may still fail depending on
kernel, firmware, hostapd build, and regulatory state.

**5 GHz Wi-Fi 6 status:** when enabled in the UI, the add-on writes `ieee80211ax=1`
plus conservative HE operating settings that match the selected 20/40/80 MHz width.
If the adapter or hostapd build rejects those settings, startup will fail and the
hostapd log will show the reason.

**2.4 GHz status:** the current UI does not expose a 2.4 GHz AX toggle. On 2.4 GHz,
the add-on currently exposes WPA3 transition mode but otherwise keeps the radio on the
existing non-AX path.

---

## Networking

The add-on supports two network modes:

- `NAT (Recommended)`: clients are placed on a dedicated AP subnet behind the add-on. The add-on creates an internal bridge (`br-ap`) for the AP radios, runs `dnsmasq` for DHCP/DNS, and NATs client traffic out through the detected host uplink.
- `Bridge (Experimental)`: clients are bridged onto the upstream LAN. This is better for same-LAN use cases, but it is less reliable and can fail to pass DHCP/client traffic depending on the host, adapter, and driver.

For non-6 GHz radios, enabling **Use WPA3** puts the radio into WPA2/WPA3 transition
mode (`WPA-PSK` + `SAE`) with optional PMF for compatibility. 6 GHz remains SAE-only
with required PMF and should still be treated as experimental.

For the first 6 GHz implementation, the add-on intentionally constrains startup to:

- `20 MHz` only
- detected enabled 6 GHz channels only
- WPA3-SAE only
- required PMF
- AX/HE enabled

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
identified quickly. The UI can expose 6 GHz for experimental testing only when the
adapter appears to meet the minimum capability threshold described above.

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

