#!/usr/bin/env python3
"""Hostapd AP web management backend."""

import json
import os
import subprocess
import time

from flask import Flask, jsonify, request, make_response

app = Flask(__name__, static_folder="/web", static_url_path="")

CONFIG_FILE = "/data/hostapd_config.json"
HOSTAPD_LOG_FILE = "/tmp/hostapd.log"
IPV6_BRIDGE_RULES = [
    ["ip6tables", "-I", "INPUT", "-i", "br-ap", "-j", "DROP"],
    ["ip6tables", "-I", "FORWARD", "-i", "br-ap", "-j", "DROP"],
    ["ip6tables", "-I", "FORWARD", "-o", "br-ap", "-j", "DROP"],
]

DEFAULT_CONFIG = {
    "country_code": "US",
    "disable_client_ipv6": True,
    "password": "changeme123",
    "radios": [
        {"band": "2g", "enabled": True,  "interface": "wlan0", "ssid": "HomeAssistant-AP",    "channel": 6},
        {"band": "5g", "enabled": False, "interface": "wlan1", "ssid": "HomeAssistant-AP-5G", "channel": 36},
        {"band": "6g", "enabled": False, "interface": "wlan2", "ssid": "HomeAssistant-AP-6G", "channel": 5},
    ],
}

# Tracks running subprocesses keyed by name
_procs = {}

HW_MODE = {"2g": "g", "5g": "a", "6g": "a"}
BAND_LABELS = {"2g": "2.4GHz", "5g": "5GHz", "6g": "6GHz"}


def _default_radio_map():
    return {radio["band"]: json.loads(json.dumps(radio)) for radio in DEFAULT_CONFIG["radios"]}


def normalize_config(cfg):
    """Fill in missing fields and migrate older configs forward."""
    cfg = cfg or {}
    normalized = {
        "country_code": str(cfg.get("country_code", DEFAULT_CONFIG["country_code"])).upper(),
        "disable_client_ipv6": bool(cfg.get("disable_client_ipv6", DEFAULT_CONFIG["disable_client_ipv6"])),
        "password": cfg.get("password", DEFAULT_CONFIG["password"]),
        "radios": [],
    }

    defaults = _default_radio_map()
    saved = {}
    for radio in cfg.get("radios", []):
        band = radio.get("band")
        if band:
            saved[band] = radio

    for band, default_radio in defaults.items():
        merged = json.loads(json.dumps(default_radio))
        merged.update(saved.get(band, {}))
        if merged.get("channel") in (None, ""):
            merged["channel"] = default_radio["channel"]
        try:
            merged["channel"] = int(merged["channel"])
        except (TypeError, ValueError):
            merged["channel"] = default_radio["channel"]
        merged["enabled"] = bool(merged.get("enabled"))
        merged["interface"] = str(merged.get("interface", ""))
        merged["ssid"] = str(merged.get("ssid", ""))
        normalized["radios"].append(merged)

    return normalized


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return normalize_config(json.load(f))
    return normalize_config(DEFAULT_CONFIG)


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(normalize_config(cfg), f, indent=2)


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


def _bands_from_phy_block(lines):
    """Infer supported bands from frequency lines within one Wiphy block."""
    bands = []

    def add_band(name):
        if name not in bands:
            bands.append(name)

    in_freqs = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Frequencies:"):
            in_freqs = True
            continue
        if in_freqs and stripped.startswith("*"):
            mhz_token = stripped.lstrip("* ").split()[0]
            try:
                mhz = int(float(mhz_token))
            except ValueError:
                continue
            if 2400 <= mhz <= 2500:
                add_band("2.4GHz")
            elif 4900 <= mhz < 5925:
                add_band("5GHz")
            elif 5925 <= mhz <= 7125:
                add_band("6GHz")
            continue
        if in_freqs and stripped and not stripped.startswith("*"):
            in_freqs = False

    return bands


def get_interface_info(iface):
    info = {
        "ap_supported": False,
        "bands": [],
        "supports_6ghz": False,
        "usb_info": None,
        "usb_speed": None,
    }
    phy = _phy_for(iface)
    if not phy:
        info["error"] = "Interface not found"
        return info

    # AP mode + band support
    try:
        raw = subprocess.check_output(["iw", "list"], text=True, stderr=subprocess.DEVNULL)
        in_phy = False
        in_modes = False
        phy_lines = []
        for line in raw.splitlines():
            if line.startswith(f"Wiphy {phy}"):
                in_phy = True
                phy_lines = []
            elif line.startswith("Wiphy ") and in_phy:
                break
            if in_phy:
                phy_lines.append(line)
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
        info["bands"] = _bands_from_phy_block(phy_lines)
        info["supports_6ghz"] = "6GHz" in info["bands"]
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


def _validate_radio_selection(radio):
    band = radio.get("band")
    iface = radio.get("interface", "")
    ssid = radio.get("ssid", "").strip()
    channel = radio.get("channel")
    band_label = BAND_LABELS.get(band, band or "unknown")

    if not iface:
        return f"{band_label}: interface is required"
    if not ssid:
        return f"{band_label}: SSID is required"
    if len(ssid) > 32:
        return f"{band_label}: SSID must be 32 characters or fewer"
    if channel is None:
        return f"{band_label}: channel is required"
    if band == "6g" and _op_class_for_6ghz(int(channel)) is None:
        return "6 GHz channel must be a valid 20 MHz channel (1, 5, 9 ... 233)"

    info = get_interface_info(iface)
    if not info.get("ap_supported"):
        return f"{iface}: AP mode is not supported"
    if BAND_LABELS.get(band) not in info.get("bands", []):
        return f"{iface}: {band_label} is not supported by this adapter"

    return None


def _op_class_for_6ghz(channel):
    # 20 MHz 6 GHz operation class
    if channel < 1 or channel > 233 or (channel - 1) % 4 != 0:
        return None
    return 131


def _tail_file(path, max_lines=20):
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:]).strip()
    except Exception:
        return ""


def _write_proc_value(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except Exception:
        return False


def _set_bridge_ipv6_filtering(enabled):
    sysctl_path = "/proc/sys/net/bridge/bridge-nf-call-ip6tables"
    if os.path.exists(sysctl_path):
        _write_proc_value(sysctl_path, "1" if enabled else "0")

    rules = IPV6_BRIDGE_RULES if enabled else [[rule[0], "-D"] + rule[2:] for rule in IPV6_BRIDGE_RULES]
    for cmd in rules:
        subprocess.run(cmd, capture_output=True)


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


def _bridge_name():
    return "br-ap"


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


def _setup_bridge(bridge, uplink):
    """Create a shared bridge and move the host uplink IP/gateway onto it."""
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
    if name == "hostapd":
        logf = _procs.pop("hostapd_log", None)
        if logf:
            try:
                logf.close()
            except Exception:
                pass


def stop_ap():
    _kill("hostapd")
    _set_bridge_ipv6_filtering(False)
    bridge_state = _procs.pop("bridge", None)
    if bridge_state:
        uplink, gateway = bridge_state if isinstance(bridge_state, tuple) else (bridge_state, None)
        _teardown_bridge(_bridge_name(), uplink, gateway)

    # Backward-compatible cleanup for older in-memory state that tracked one bridge per band.
    for key in [k for k in list(_procs.keys()) if k.startswith("bridge_")]:
        val = _procs.pop(key, None)
        if val:
            uplink, gateway = val if isinstance(val, tuple) else (val, None)
            _teardown_bridge(_bridge_name(), uplink, gateway)


def apply_config(cfg):
    cfg = normalize_config(cfg)
    stop_ap()
    country = cfg.get("country_code", "US")
    disable_client_ipv6 = cfg.get("disable_client_ipv6", True)
    password = cfg.get("password", "changeme123")
    hostapd_confs = []
    enabled_radios = [radio for radio in cfg.get("radios", []) if radio.get("enabled")]

    if len(password) < 8:
        return {"ok": False, "message": "WiFi password must be at least 8 characters"}

    seen_ifaces = set()
    for radio in enabled_radios:
        err = _validate_radio_selection(radio)
        if err:
            return {"ok": False, "message": err}
        iface = radio["interface"]
        if iface in seen_ifaces:
            return {"ok": False, "message": f"{iface}: cannot be assigned to multiple radios"}
        seen_ifaces.add(iface)

    uplink = _uplink_interface()
    if not uplink:
        return {"ok": False, "message": "Could not determine host uplink interface"}
    print(f"==> Uplink interface: {uplink}")

    bridge = _bridge_name()
    gateway = _setup_bridge(bridge, uplink)
    _procs["bridge"] = (uplink, gateway)
    _set_bridge_ipv6_filtering(disable_client_ipv6)

    for radio in enabled_radios:
        band = radio["band"]
        iface = radio["interface"]
        ssid = radio["ssid"]
        channel = int(radio["channel"])
        hw_mode = HW_MODE.get(band, "g")

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
            f.write("ieee80211d=1\n")
            f.write("auth_algs=1\n")
            f.write("wmm_enabled=1\n")
            if band == "2g":
                f.write("ieee80211n=1\n")
            elif band == "5g":
                f.write("ieee80211n=1\n")
                f.write("ieee80211ac=1\n")
            elif band == "6g":
                op_class = _op_class_for_6ghz(channel)
                if op_class is None:
                    return {"ok": False, "message": "6 GHz channel must be a valid 20 MHz channel (1, 5, 9 ... 233)"}
                f.write(f"op_class={op_class}\n")
                f.write("ieee80211ax=1\n")
                f.write("he_oper_chwidth=0\n")
                f.write(f"he_oper_centr_freq_seg0_idx={channel}\n")
                f.write("ieee80211w=2\n")
                f.write("beacon_prot=1\n")
                f.write("wpa=2\n")
                f.write("wpa_key_mgmt=SAE\n")
                f.write("rsn_pairwise=CCMP\n")
                f.write("sae_pwe=1\n")
                f.write(f"wpa_passphrase={password}\n")
            if band != "6g":
                f.write("wpa=2\n")
                f.write("wpa_key_mgmt=WPA-PSK\n")
                f.write("rsn_pairwise=CCMP\n")
                f.write(f"wpa_passphrase={password}\n")
        hostapd_confs.append(conf_path)

    if hostapd_confs:
        with open(HOSTAPD_LOG_FILE, "w") as logf:
            logf.write("")
        logf = open(HOSTAPD_LOG_FILE, "a", buffering=1)
        _procs["hostapd_log"] = logf
        _procs["hostapd"] = subprocess.Popen(
            ["hostapd", "-dd"] + hostapd_confs,
            stdout=logf,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(2)
        if _procs["hostapd"].poll() is not None:
            log_tail = _tail_file(HOSTAPD_LOG_FILE)
            stop_ap()
            detail = f" Hostapd log: {log_tail}" if log_tail else ""
            return {"ok": False, "message": f"hostapd failed to start.{detail}"}
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
            s6   = "6GHz:yes" if info.get("supports_6ghz") else "6GHz:no"
            bands = "/".join(info.get("bands", [])) or "?"
            usb  = f"  USB: {info['usb_info']}" if info.get("usb_info") else ""
            spd  = f"  Speed: {info['usb_speed']}" if info.get("usb_speed") else ""
            err  = f"  ERR: {info['error']}" if info.get("error") else ""
            print(f"    {iface}  {ap}  {s6}  bands={bands}{usb}{spd}{err}")
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
