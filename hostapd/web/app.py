#!/usr/bin/env python3
"""Hostapd AP web management backend."""

import json
import os
import subprocess

from flask import Flask, jsonify, request, send_from_directory

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

    # Fallback: include all /sys/class/net interfaces so adapters show up even
    # when iw hasn't registered them (useful for testing).
    all_ifaces = []
    try:
        all_ifaces = os.listdir("/sys/class/net")
    except Exception:
        pass

    combined = list(dict.fromkeys(iw_ifaces + all_ifaces))  # iw-reported first, then the rest
    return combined if combined else iw_ifaces


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


def _setup_bridge(bridge, uplink, wifi_iface):
    """Create bridge, attach uplink + wifi iface.  Move uplink IP to bridge."""
    # Grab current IP/prefix from uplink before we touch it
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

    cmds = [
        ["ip", "link", "add", "name", bridge, "type", "bridge"],
        ["ip", "link", "set", uplink, "master", bridge],
        ["ip", "link", "set", bridge, "up"],
    ]
    if ip_prefix:
        cmds += [
            ["ip", "addr", "flush", "dev", uplink],
            ["ip", "addr", "add", ip_prefix, "dev", bridge],
            ["ip", "route", "add", "default", "via",
             str(ip_prefix.rsplit(".", 1)[0] + ".1"), "dev", bridge],
        ]
    for cmd in cmds:
        subprocess.run(cmd, capture_output=True)


def _teardown_bridge(bridge, uplink):
    """Move uplink back out of bridge and delete bridge."""
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
        uplink = _procs.pop(key, None)  # stored uplink name
        if uplink:
            _teardown_bridge(_bridge_name(band), uplink)


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
        _setup_bridge(bridge, uplink, iface)
        _procs[f"bridge_{band}"] = uplink  # remember uplink for teardown

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
    return send_from_directory("/web", "index.html")


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
    return jsonify({
        "ap_running": running,
        "processes": {k: (v.poll() is None) for k, v in _procs.items()},
    })


@app.route("/api/interfaces", methods=["GET"])
def api_interfaces():
    ifaces = get_wireless_interfaces()
    return jsonify({iface: get_interface_info(iface) for iface in ifaces})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Startup — runs on import (gunicorn) and on direct execution
# ---------------------------------------------------------------------------
def _startup():
    print("==> Hostapd AP web manager starting...")
    if os.path.exists(CONFIG_FILE):
        print("==> Saved config found — applying on startup...")
        result = apply_config(load_config())
        print(f"==> {result['message']}")
    else:
        print("==> No saved config yet — open the web UI to configure.")

_startup()

if __name__ == "__main__":
    pass
