# timmchugh11's Home Assistant Add-on Repository

A collection of Home Assistant add-ons.

## Installation

1. Navigate to **Settings → Add-ons → Add-on Store** in Home Assistant.
2. Click the three-dot menu (⋮) in the top-right and choose **Repositories**.
3. Paste the URL of this repository and click **Add**.
4. Refresh the page, then find any of the add-ons below and click **Install**.

## Add-ons

### copyparty

[![version](https://img.shields.io/badge/version-1.0.4-blue.svg)](copyparty/config.yaml)

Portable file server with resumable uploads, dedup, WebDAV, FTP, SFTP, media indexer,
thumbnails and more — accessible from any web browser.

**[Documentation](copyparty/DOCS.md)** · Upstream: [github.com/9001/copyparty](https://github.com/9001/copyparty)

---

### Starlink GUI

[![version](https://img.shields.io/badge/version-1.1.4-blue.svg)](starlink_gui/config.yaml)

Full router-style admin interface for your local Starlink dish and WiFi router. Connects
directly to the dish via gRPC — no Starlink account or internet access required.
Includes a bypass mode to hide all router pages when the Starlink router is not in use.

**[Documentation](starlink_gui/README.md)**

---

### Hostapd AP

[![version](https://img.shields.io/badge/version-0.9.4-blue.svg)](hostapd/config.yaml)

WiFi access point managed via a built-in web UI. Bridges WiFi clients directly onto your
existing network — clients get DHCP from your router with no separate subnet or NAT.
Supports independent 2.4 GHz and 5 GHz radios. Requires a WiFi adapter with AP mode support.

**[Documentation](hostapd/README.md)**

---

## Support

For issues with any add-on, open an issue in this repository.
