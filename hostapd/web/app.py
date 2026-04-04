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

IP_MAP = {
    "2g": ("192.168.50.1", "192.168.50.10", "192.168.50.100"),
    "5g": ("192.168.51.1", "192.168.51.10", "192.168.51.100"),
}

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
    try:
        out = subprocess.check_output(["iw", "dev"], text=True, stderr=subprocess.DEVNULL)
        return [l.strip().split()[1] for l in out.splitlines() if l.strip().startswith("Interface ")]
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


# ---------------------------------------------------------------------------
# AP lifecycle
# ---------------------------------------------------------------------------

def _kill(name):
    proc = _procs.pop(name, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def stop_ap():
    for name in list(_procs.keys()):
        _kill(name)


def apply_config(cfg):
    stop_ap()
    country = cfg.get("country_code", "US")
    password = cfg.get("password", "changeme123")
    hostapd_confs = []
    errors = []

    for radio in cfg.get("radios", []):
        if not radio.get("enabled"):
            continue
        band = radio["band"]
        iface = radio["interface"]
        ssid = radio["ssid"]
        channel = int(radio["channel"])
        hw_mode = HW_MODE.get(band, "g")
        ap_ip, dhcp_start, dhcp_end = IP_MAP.get(band, IP_MAP["2g"])
        subnet = ".".join(ap_ip.split(".")[:3]) + ".0/24"

        # Configure interface
        for cmd in [
            ["ip", "link", "set", iface, "down"],
            ["iw", "dev", iface, "set", "type", "ap"],
            ["ip", "addr", "flush", "dev", iface],
            ["ip", "addr", "add", f"{ap_ip}/24", "dev", iface],
            ["ip", "link", "set", iface, "up"],
            ["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", subnet, "!", "-d", subnet, "-j", "MASQUERADE"],
        ]:
            subprocess.run(cmd, capture_output=True)

        # hostapd config
        conf_path = f"/tmp/hostapd_{band}.conf"
        with open(conf_path, "w") as f:
            f.write(f"interface={iface}\n")
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

        # dnsmasq config
        dns_conf = f"/tmp/dnsmasq_{band}.conf"
        with open(dns_conf, "w") as f:
            f.write(f"interface={iface}\n")
            f.write(f"bind-interfaces\n")
            f.write(f"dhcp-range={dhcp_start},{dhcp_end},12h\n")
            f.write(f"dhcp-option=3,{ap_ip}\n")
            f.write(f"dhcp-option=6,1.1.1.1,8.8.8.8\n")
        _procs[f"dnsmasq_{band}"] = subprocess.Popen(["dnsmasq", f"--conf-file={dns_conf}"])

    if hostapd_confs:
        _procs["hostapd"] = subprocess.Popen(["hostapd"] + hostapd_confs)
        return {"ok": True, "message": f"AP started ({len(hostapd_confs)} radio(s))"}

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

if __name__ == "__main__":
    print("==> Hostapd AP web manager starting...")
    if os.path.exists(CONFIG_FILE):
        print("==> Saved config found — applying on startup...")
        result = apply_config(load_config())
        print(f"==> {result['message']}")
    else:
        print("==> No saved config yet — open the web UI to configure.")
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
