#!/usr/bin/env python3
"""Hostapd AP web management backend."""

import json
import os
import subprocess

from flask import Flask, jsonify, request, make_response

app = Flask(__name__, static_folder="/web", static_url_path="")

CONFIG_FILE = "/data/hostapd_config.json"

DEFAULT_CONFIG = {
    "country_code": "US",
    "password": "changeme123",
    "radios": [
        {"band": "2g", "enabled": True,  "interface": "wlan0", "ssid": "HomeAssistant-AP",    "channel": 6},
        {"band": "5g", "enabled": False, "interface": "wlan1", "ssid": "HomeAssistant-AP-5G", "channel": 36},
    ],
}

# Tracks running subprocesses keyed by name
_procs = {}

HW_MODE = {"2g": "g", "5g": "a"}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ---------------------------------------------------------------------------
# Interface discovery
# ---------------------------------------------------------------------------

def _phy_for(iface):
    try:
        out = subprocess.check_output(["iw", "dev", iface, "info"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if "wiphy" in line:
                return "phy" + line.strip().split()[-1]
    except Exception:
        pass
    return None


def get_wireless_interfaces():
    """Return list of wireless interface names."""
    # TODO: revert to iw-only for production
    iw_ifaces = []
    try:
        out = subprocess.check_output(["iw", "dev"], text=True, stderr=subprocess.DEVNULL)
        iw_ifaces = [l.strip().split()[1] for l in out.splitlines() if l.strip().startswith("Interface ")]
    except Exception:
        pass

    if iw_ifaces:
        return iw_ifaces

    # Fallback: if iw returned nothing, include wl* interfaces from /sys/class/net
    # so adapters show up even when iw hasn't registered them (useful for testing).
    try:
        return [i for i in os.listdir("/sys/class/net") if i.startswith("wl")]
    except Exception:
        return []


def get_interface_info(iface):
    info = {"ap_supported": False, "bands": [], "usb_info": None, "usb_speed": None}
    phy = _phy_for(iface)
    if not phy:
        info["error"] = "Interface not found"
        return info

    # AP mode + band support
    try:
        raw = subprocess.check_output(["iw", "list"], text=True, stderr=subprocess.DEVNULL)
        in_phy = False
        in_modes = False
        for line in raw.splitlines():
            if line.startswith(f"Wiphy {phy}"):
                in_phy = True
            elif line.startswith("Wiphy ") and in_phy:
                break
            if in_phy:
                stripped = line.strip()
                if "Supported interface modes" in line:
                    in_modes = True
                elif in_modes:
                    if stripped.startswith("*"):
                        mode = stripped.lstrip("* ").strip()
                        if mode == "AP":
                            info["ap_supported"] = True
                    else:
                        in_modes = False
                if "Band 1:" in line:
                    info["bands"].append("2.4GHz")
                if "Band 2:" in line or "Band 4:" in line:
                    if "5GHz" not in info["bands"]:
                        info["bands"].append("5GHz")
    except Exception as e:
        info["error"] = str(e)

    # USB device info
    sys_dev = f"/sys/class/ieee80211/{phy}/device"
    vid_path = os.path.join(sys_dev, "idVendor")
    if os.path.exists(vid_path):
        try:
            vid = open(vid_path).read().strip()
            pid = open(os.path.join(sys_dev, "idProduct")).read().strip()
            speed_path = os.path.join(sys_dev, "speed")
            if os.path.exists(speed_path):
                info["usb_speed"] = open(speed_path).read().strip() + " Mbit/s"
            lsusb = subprocess.check_output(["lsusb"], text=True, stderr=subprocess.DEVNULL)
            for line in lsusb.splitlines():
                if f"{vid}:{pid}".lower() in line.lower():
                    info["usb_info"] = line.strip()
                    break
        except Exception:
            pass

    return info


def get_station_dump(iface):
    """Return list of stations from `iw dev <iface> station dump`."""
    stations = []
    try:
        out = subprocess.check_output(
            ["iw", "dev", iface, "station", "dump"], text=True, stderr=subprocess.DEVNULL
        )
    except Exception:
        return stations
    current = None
    for line in out.splitlines():
        if line.startswith("Station "):
            if current:
                stations.append(current)
            current = {"mac": line.split()[1], "iface": iface}
        elif current is None:
            continue
        elif ":" in line:
            key, _, val = line.strip().partition(":")
            current[key.strip().lower().replace(" ", "_")] = val.strip()
    if current:
        stations.append(current)
    return stations


def _uplink_interface():
    """Return the host's default-route network interface."""
    try:
        out = subprocess.check_output(["ip", "route"], text=True)
        for line in out.splitlines():
            if line.startswith("default"):
                parts = line.split()
                idx = parts.index("dev") + 1
                return parts[idx]
    except Exception:
        pass
    return None


def _bridge_name(band):
    return f"br-ap-{band}"


def _get_default_gateway(iface=None):
    """Return the current default gateway IP, optionally for a specific device."""
    try:
        out = subprocess.check_output(["ip", "route"], text=True)
        for line in out.splitlines():
            if not line.startswith("default"):
                continue
            if iface and f"dev {iface}" not in line:
                continue
            parts = line.split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except Exception:
        pass
    return None


def _setup_bridge(bridge, uplink, wifi_iface):
    """Create bridge, attach uplink.  Move uplink IP/gateway to bridge."""
    # Snapshot IP and gateway BEFORE touching anything
    ip_prefix = None
    try:
        out = subprocess.check_output(["ip", "-o", "-4", "addr", "show", uplink], text=True)
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                ip_prefix = parts[parts.index("inet") + 1]
                break
    except Exception:
        pass

    gateway = _get_default_gateway()

    cmds = [
        ["ip", "link", "add", "name", bridge, "type", "bridge"],
        ["ip", "link", "set", uplink, "master", bridge],
        ["ip", "link", "set", bridge, "up"],
    ]
    if ip_prefix:
        cmds += [
            ["ip", "addr", "flush", "dev", uplink],
            ["ip", "addr", "add", ip_prefix, "dev", bridge],
        ]
    if gateway:
        # Remove old default route first (it may be tied to uplink), then re-add via bridge
        cmds += [
            ["ip", "route", "del", "default"],
            ["ip", "route", "add", "default", "via", gateway, "dev", bridge],
        ]
    for cmd in cmds:
        subprocess.run(cmd, capture_output=True)

    return gateway  # caller stores this for teardown


def _teardown_bridge(bridge, uplink, gateway=None):
    """Move uplink back out of bridge, delete bridge, restore default route."""
    ip_prefix = None
    try:
        out = subprocess.check_output(["ip", "-o", "-4", "addr", "show", bridge], text=True)
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                ip_prefix = parts[parts.index("inet") + 1]
                break
    except Exception:
        pass

    # Restore default route via uplink before dismantling the bridge
    if gateway:
        subprocess.run(["ip", "route", "del", "default"], capture_output=True)
        subprocess.run(["ip", "route", "add", "default", "via", gateway, "dev", uplink],
                       capture_output=True)

    cmds = [
        ["ip", "link", "set", uplink, "nomaster"],
        ["ip", "link", "set", bridge, "down"],
        ["ip", "link", "del", bridge],
    ]
    if ip_prefix:
        cmds += [
            ["ip", "addr", "add", ip_prefix, "dev", uplink],
        ]
    for cmd in cmds:
        subprocess.run(cmd, capture_output=True)



# ---------------------------------------------------------------------------
# AP lifecycle
# ---------------------------------------------------------------------------
def _kill(name):
    proc = _procs.get(name)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def stop_ap():
    _kill("hostapd")
    # Tear down bridges
    for key in [k for k in list(_procs.keys()) if k.startswith("bridge_")]:
        band = key[len("bridge_"):]
        val = _procs.pop(key, None)
        if val:
            uplink, gateway = val if isinstance(val, tuple) else (val, None)
            _teardown_bridge(_bridge_name(band), uplink, gateway)


def apply_config(cfg):
    stop_ap()
    country = cfg.get("country_code", "US")
    password = cfg.get("password", "changeme123")
    hostapd_confs = []

    uplink = _uplink_interface()
    if not uplink:
        return {"ok": False, "message": "Could not determine host uplink interface"}
    print(f"==> Uplink interface: {uplink}")

    for radio in cfg.get("radios", []):
        if not radio.get("enabled"):
            continue
        band = radio["band"]
        iface = radio["interface"]
        ssid = radio["ssid"]
        channel = int(radio["channel"])
        hw_mode = HW_MODE.get(band, "g")
        bridge = _bridge_name(band)

        # Create bridge and attach uplink
        gateway = _setup_bridge(bridge, uplink, iface)
        _procs[f"bridge_{band}"] = (uplink, gateway)  # remember for teardown

        # Bring wifi iface up without IP — hostapd manages it via the bridge
        for cmd in [
            ["ip", "link", "set", iface, "down"],
            ["iw", "dev", iface, "set", "type", "__ap"],
            ["ip", "addr", "flush", "dev", iface],
            ["ip", "link", "set", iface, "up"],
        ]:
            subprocess.run(cmd, capture_output=True)

        # hostapd config — bridge= hands client traffic to the bridge
        conf_path = f"/tmp/hostapd_{band}.conf"
        with open(conf_path, "w") as f:
            f.write(f"interface={iface}\n")
            f.write(f"bridge={bridge}\n")
            f.write(f"driver=nl80211\n")
            f.write(f"ssid={ssid}\n")
            f.write(f"hw_mode={hw_mode}\n")
            f.write(f"channel={channel}\n")
            f.write(f"country_code={country}\n")
            f.write(f"ieee80211n=1\n")
            if hw_mode == "a":
                f.write("ieee80211ac=1\n")
            f.write(f"wpa=2\n")
            f.write(f"wpa_key_mgmt=WPA-PSK\n")
            f.write(f"rsn_pairwise=CCMP\n")
            f.write(f"wpa_passphrase={password}\n")
        hostapd_confs.append(conf_path)

    if hostapd_confs:
        _procs["hostapd"] = subprocess.Popen(["hostapd"] + hostapd_confs)
        return {"ok": True, "message": f"AP started ({len(hostapd_confs)} radio(s)) — bridged to {uplink}"}

    return {"ok": False, "message": "No radios enabled — nothing to start"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    base = request.headers.get("X-Ingress-Path", "")
    with open("/web/index.html", "r") as f:
        html = f.read()
    html = html.replace("</head>", f"<script>window.__BASE__={json.dumps(base)};</script></head>", 1)
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route("/api/config", methods=["GET"])
def api_get_config():
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def api_save_config():
    cfg = request.get_json(force=True)
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/apply", methods=["POST"])
def api_apply():
    cfg = load_config()
    result = apply_config(cfg)
    return jsonify(result)


@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_ap()
    return jsonify({"ok": True, "message": "AP stopped"})


@app.route("/api/status", methods=["GET"])
def api_status():
    hostapd_proc = _procs.get("hostapd")
    running = bool(hostapd_proc and hostapd_proc.poll() is None)
    cfg = load_config()
    radios = []
    for radio in cfg.get("radios", []):
        if not radio.get("enabled"):
            continue
        iface = radio.get("interface", "")
        clients = get_station_dump(iface) if running else []
        radios.append({
            "band":         radio.get("band"),
            "ssid":         radio.get("ssid"),
            "channel":      radio.get("channel"),
            "interface":    iface,
            "client_count": len(clients),
        })
    return jsonify({"ap_running": running, "radios": radios})


@app.route("/api/interfaces", methods=["GET"])
def api_interfaces():
    ifaces = get_wireless_interfaces()
    return jsonify({iface: get_interface_info(iface) for iface in ifaces})


@app.route("/api/clients", methods=["GET"])
def api_clients():
    cfg = load_config()
    result = []
    for radio in cfg.get("radios", []):
        if not radio.get("enabled") or not radio.get("interface"):
            continue
        for sta in get_station_dump(radio["interface"]):
            sta["band"] = radio.get("band", "?")
            sta["ssid"] = radio.get("ssid", "?")
            result.append(sta)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Startup — runs on import (gunicorn) and on direct execution
# ---------------------------------------------------------------------------
def _startup():
    print("==> Hostapd AP web manager starting...")

    print("==> Scanning interfaces...")
    ifaces = get_wireless_interfaces()
    if ifaces:
        for iface in ifaces:
            info = get_interface_info(iface)
            ap   = "AP:yes" if info.get("ap_supported") else "AP:no"
            bands = "/".join(info.get("bands", [])) or "?"
            usb  = f"  USB: {info['usb_info']}" if info.get("usb_info") else ""
            spd  = f"  Speed: {info['usb_speed']}" if info.get("usb_speed") else ""
            err  = f"  ERR: {info['error']}" if info.get("error") else ""
            print(f"    {iface}  {ap}  bands={bands}{usb}{spd}{err}")
    else:
        print("    (no interfaces found)")

    if os.path.exists(CONFIG_FILE):
        print("==> Saved config found — applying on startup...")
        result = apply_config(load_config())
        print(f"==> {result['message']}")
    else:
        print("==> No saved config yet — open the web UI to configure.")

_startup()

if __name__ == "__main__":
    pass
