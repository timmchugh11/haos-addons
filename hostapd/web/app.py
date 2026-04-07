#!/usr/bin/env python3
"""Hostapd AP web management backend."""

import json
import os
import ipaddress
import re
import subprocess
import time

from flask import Flask, Response, jsonify, request, make_response, stream_with_context

app = Flask(__name__, static_folder="/web", static_url_path="")

CONFIG_FILE = "/data/hostapd_config.json"
HOSTAPD_LOG_FILE = "/tmp/hostapd.log"
DNSMASQ_CONF_FILE = "/tmp/dnsmasq-br-ap.conf"
TCP_MSS_CLAMP_RULES = [
    ["iptables", "-t", "mangle", "-I", "FORWARD", "-i", "br-ap", "-p", "tcp", "--tcp-flags", "SYN,RST", "SYN", "-j", "TCPMSS", "--clamp-mss-to-pmtu"],
    ["iptables", "-t", "mangle", "-I", "FORWARD", "-o", "br-ap", "-p", "tcp", "--tcp-flags", "SYN,RST", "SYN", "-j", "TCPMSS", "--clamp-mss-to-pmtu"],
]
NAT_RULES = [
    ["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", "{subnet_cidr}", "-o", "{uplink}", "-j", "MASQUERADE"],
    ["iptables", "-A", "FORWARD", "-i", "br-ap", "-o", "{uplink}", "-j", "ACCEPT"],
    ["iptables", "-A", "FORWARD", "-i", "{uplink}", "-o", "br-ap", "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
]

DEFAULT_CONFIG = {
    "country_code": "US",
    "network_mode": "nat",
    "experimental_6ghz_enabled": False,
    "password": "changeme123",
    "dhcp": {
        "bridge_cidr": "192.168.50.1/24",
        "gateway": "192.168.50.1",
        "range_start": "192.168.50.50",
        "range_end": "192.168.50.199",
        "netmask": "255.255.255.0",
        "lease_time": "12h",
    },
    "radios": [
        {"band": "2g", "enabled": True,  "interface": "wlan0", "ssid": "HomeAssistant-AP",    "channel": 6,  "channel_width": "20", "ax_enabled": False, "wpa3": False},
        {"band": "5g", "enabled": False, "interface": "wlan1", "ssid": "HomeAssistant-AP-5G", "channel": 36, "channel_width": "80", "ax_enabled": True,  "wpa3": False},
        {"band": "6g", "enabled": False, "interface": "wlan2", "ssid": "HomeAssistant-AP-6G", "channel": 5,  "channel_width": "20", "ax_enabled": True,  "wpa3": True},
    ],
}

# Tracks running subprocesses keyed by name
_procs = {}
_last_generated_configs = {}
_last_hostapd_error = ""

HW_MODE = {"2g": "g", "5g": "a", "6g": "a"}
BAND_LABELS = {"2g": "2.4GHz", "5g": "5GHz", "6g": "6GHz"}
RADIO_WIDTHS = {"2g": {"20"}, "5g": {"20", "40", "80"}, "6g": {"20"}}
UI_EXPOSED_BANDS = {"2g", "5g"}


def _default_radio_map():
    return {radio["band"]: json.loads(json.dumps(radio)) for radio in DEFAULT_CONFIG["radios"]}


def normalize_config(cfg):
    """Fill in missing fields and migrate older configs forward."""
    cfg = cfg or {}
    normalized = {
        "country_code": str(cfg.get("country_code", DEFAULT_CONFIG["country_code"])).upper(),
        "network_mode": str(cfg.get("network_mode", DEFAULT_CONFIG["network_mode"])).strip().lower(),
        "experimental_6ghz_enabled": bool(cfg.get("experimental_6ghz_enabled", DEFAULT_CONFIG["experimental_6ghz_enabled"])),
        "password": cfg.get("password", DEFAULT_CONFIG["password"]),
        "dhcp": json.loads(json.dumps(DEFAULT_CONFIG["dhcp"])),
        "radios": [],
    }
    if normalized["network_mode"] not in ("nat", "bridge"):
        normalized["network_mode"] = DEFAULT_CONFIG["network_mode"]

    normalized["dhcp"].update(cfg.get("dhcp", {}))
    for key, default_value in DEFAULT_CONFIG["dhcp"].items():
        normalized["dhcp"][key] = str(normalized["dhcp"].get(key, default_value)).strip() or default_value

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
        merged["channel_width"] = str(merged.get("channel_width", default_radio.get("channel_width", "20")))
        if merged["channel_width"] not in RADIO_WIDTHS.get(band, {"20"}):
            merged["channel_width"] = default_radio.get("channel_width", "20")
        merged["ax_enabled"] = bool(merged.get("ax_enabled", default_radio.get("ax_enabled", False)))
        merged["wpa3"] = bool(merged.get("wpa3", default_radio.get("wpa3", False)))
        normalized["radios"].append(merged)

    return normalized


# 6 GHz remains in the backend config and hostapd generation paths on purpose so
# older saved configs still load and experimental support can be revisited later.
# The normal UI currently exposes only 2.4 GHz and 5 GHz radios.


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


def _extract_band4_channels(lines):
    enabled = []
    disabled = []
    in_band4 = False
    in_freqs = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Band 4:"):
            in_band4 = True
            in_freqs = False
            continue
        if in_band4 and re.match(r"Band \d+:", stripped):
            break
        if not in_band4:
            continue
        if stripped.startswith("Frequencies:"):
            in_freqs = True
            continue
        if in_freqs and stripped.startswith("*"):
            match = re.search(r"\[(\d+)\]", stripped)
            if not match:
                continue
            channel = int(match.group(1))
            if "(disabled)" in stripped or "(no IR)" in stripped:
                disabled.append(channel)
            else:
                enabled.append(channel)
            continue
        if in_freqs and stripped and not stripped.startswith("*"):
            in_freqs = False

    return enabled, disabled


def _band4_has_he_ap(lines):
    in_band4 = False
    in_he = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Band 4:"):
            in_band4 = True
            in_he = False
            continue
        if in_band4 and re.match(r"Band \d+:", stripped):
            break
        if not in_band4:
            continue
        if stripped.startswith("HE Iftypes:"):
            inline = stripped.split(":", 1)[1].strip().lower()
            if inline:
                tokens = {token.strip() for token in re.split(r"[,\s]+", inline) if token.strip()}
                if "ap" in tokens:
                    return True
            in_he = True
            continue
        if in_he:
            if stripped.startswith("*"):
                continue
            if stripped.endswith(":"):
                if stripped[:-1].strip().lower() == "ap":
                    return True
                continue
            if stripped:
                in_he = False
    return False


def _supported_commands(lines):
    commands = set()
    in_commands = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Supported commands:"):
            in_commands = True
            continue
        if in_commands:
            if stripped.startswith("*"):
                raw = stripped.lstrip("* ").strip().lower()
                normalized = re.sub(r"^[^a-z]+", "", raw)
                commands.add(normalized)
                continue
            if stripped:
                in_commands = False
    return commands


def _max_ap_go_interfaces(lines):
    for line in lines:
        if "AP" not in line and "P2P-GO" not in line:
            continue
        match = re.search(r"#\{\s*([^}]*)\}\s*<=\s*(\d+)", line)
        if not match:
            continue
        roles = {item.strip() for item in match.group(1).split(",")}
        if "AP" in roles or "P2P-GO" in roles:
            return int(match.group(2))
    return None


def _interface_combo_summary(lines):
    return {
        "max_ap_go": _max_ap_go_interfaces(lines),
    }


def _psc_channels(channels):
    return [channel for channel in channels if (channel - 5) % 16 == 0]


def _friendly_hostapd_error(log_tail):
    if not log_tail:
        return ""
    log_lower = log_tail.lower()
    if "primary frequency not allowed" in log_lower or "frequency not allowed" in log_lower:
        return "The selected 6 GHz primary channel is not currently allowed by the driver or regulatory domain."
    if "hardware does not support configured mode" in log_lower:
        return "The adapter or driver rejected the requested radio mode."
    if "failed to set beacon parameters" in log_lower:
        return "The driver accepted the config but failed while programming beacon parameters."
    return ""


def get_interface_info(iface):
    info = {
        "ap_supported": False,
        "bands": [],
        "supports_6ghz": False,
        "enabled_6ghz_channels": [],
        "disabled_6ghz_channels": [],
        "psc_6ghz_channels": [],
        "he_ap_6ghz": False,
        "start_ap_supported": False,
        "sae_supported": False,
        "capability_summary_6ghz": {},
        "interface_combination": {},
        "usb_info": None,
        "usb_speed": None,
    }
    phy = _phy_for(iface)
    if not phy:
        info["error"] = "Interface not found"
        return info
    info["phy"] = phy

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
        enabled_6g, disabled_6g = _extract_band4_channels(phy_lines)
        info["enabled_6ghz_channels"] = enabled_6g
        info["disabled_6ghz_channels"] = disabled_6g
        info["psc_6ghz_channels"] = _psc_channels(enabled_6g)
        info["he_ap_6ghz"] = _band4_has_he_ap(phy_lines)
        commands = _supported_commands(phy_lines)
        info["start_ap_supported"] = bool({"start_ap", "lstart_ap"} & commands)
        info["sae_supported"] = any("sae" in line.lower() and "authenticate" in line.lower() for line in phy_lines)
        info["interface_combination"] = _interface_combo_summary(phy_lines)
        failed_checks = []
        if not (enabled_6g or disabled_6g):
            failed_checks.append("band4_missing")
        if not info["he_ap_6ghz"]:
            failed_checks.append("he_ap_missing")
        if not info["sae_supported"]:
            failed_checks.append("sae_missing")
        if not info["start_ap_supported"]:
            failed_checks.append("start_ap_missing")
        if not enabled_6g:
            failed_checks.append("no_enabled_6ghz_channels")
        info["capability_summary_6ghz"] = {
            "band4_present": bool(enabled_6g or disabled_6g),
            "he_ap_present": info["he_ap_6ghz"],
            "sae_supported": info["sae_supported"],
            "start_ap_supported": info["start_ap_supported"],
            "enabled_channels": enabled_6g,
            "psc_channels": info["psc_6ghz_channels"],
            "max_ap_go": info["interface_combination"].get("max_ap_go"),
            "failed_checks": failed_checks,
            "experimental_ready": not failed_checks and info["supports_6ghz"],
        }
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
    channel_width = str(radio.get("channel_width", "20"))

    if not iface:
        return f"{band_label}: interface is required"
    if not ssid:
        return f"{band_label}: SSID is required"
    if len(ssid) > 32:
        return f"{band_label}: SSID must be 32 characters or fewer"
    if channel is None:
        return f"{band_label}: channel is required"
    if channel_width not in RADIO_WIDTHS.get(band, {"20"}):
        return f"{band_label}: invalid channel width"
    if band == "6g" and _op_class_for_6ghz(int(channel)) is None:
        return "6 GHz channel must be a valid 20 MHz channel (1, 5, 9 ... 233)"

    info = get_interface_info(iface)
    if not info.get("ap_supported"):
        return f"{iface}: AP mode is not supported"
    if BAND_LABELS.get(band) not in info.get("bands", []):
        return f"{iface}: {band_label} is not supported by this adapter"
    if band == "6g":
        if not radio.get("ax_enabled"):
            return "6 GHz requires Wi-Fi 6 / 802.11ax to remain enabled"
        if not radio.get("wpa3"):
            return "6 GHz requires WPA3-SAE and protected management frames"
        if not info.get("he_ap_6ghz"):
            return f"{iface}: 6 GHz HE AP capability was not detected"
        if not info.get("start_ap_supported"):
            return f"{iface}: start_ap support was not detected"
        if not info.get("sae_supported"):
            return f"{iface}: SAE support was not detected"
        enabled_6g = set(info.get("enabled_6ghz_channels", []))
        if enabled_6g and int(channel) not in enabled_6g:
            return "Selected 6 GHz channel is not currently enabled by the driver/regulatory domain"

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


def _run_command(cmd, timeout=10):
    def _as_text(val):
        if val is None:
            return ""
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="replace")
        return str(val)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "code": None,
            "stdout": _as_text(e.stdout),
            "stderr": _as_text(e.stderr) + "\nTimed out",
        }
    except Exception as e:
        return {"ok": False, "code": None, "stdout": "", "stderr": str(e)}


def _validate_exec_command(cmd):
    cmd = str(cmd or "").strip()
    if not cmd:
        return None, "Command is required"
    if len(cmd) > 1000:
        return None, "Command is too long"
    return cmd, None


def _validate_dhcp_config(dhcp):
    try:
        iface = ipaddress.ip_interface(dhcp["bridge_cidr"])
        gateway = ipaddress.ip_address(dhcp["gateway"])
        range_start = ipaddress.ip_address(dhcp["range_start"])
        range_end = ipaddress.ip_address(dhcp["range_end"])
        netmask = ipaddress.ip_address(dhcp["netmask"])
    except ValueError as e:
        return None, f"DHCP: {e}"

    if iface.version != 4:
        return None, "DHCP: bridge CIDR must be IPv4"
    network = iface.network
    if gateway != iface.ip:
        return None, "DHCP: gateway must match the bridge IP in bridge CIDR"
    if range_start.version != 4 or range_end.version != 4:
        return None, "DHCP: range must be IPv4"
    if range_start not in network or range_end not in network:
        return None, "DHCP: range start/end must be within the bridge subnet"
    if int(range_start) > int(range_end):
        return None, "DHCP: range start must be before range end"

    return {
        "bridge_cidr": str(iface),
        "gateway": str(gateway),
        "subnet_cidr": str(network),
        "range_start": str(range_start),
        "range_end": str(range_end),
        "netmask": str(netmask),
        "lease_time": dhcp["lease_time"],
    }, None


def _ht40_capab(channel):
    try:
        channel = int(channel)
    except (TypeError, ValueError):
        return None
    if channel in {36, 44, 52, 60, 100, 108, 116, 124, 132, 149, 157}:
        return "[HT40+]"
    if channel in {40, 48, 56, 64, 104, 112, 120, 128, 136, 153, 161}:
        return "[HT40-]"
    return None


def _vht_center_seg0(channel, width):
    try:
        channel = int(channel)
    except (TypeError, ValueError):
        return None
    width = str(width)
    if width == "40":
        return channel + 2 if _ht40_capab(channel) == "[HT40+]" else channel - 2 if _ht40_capab(channel) == "[HT40-]" else None
    if width != "80":
        return None
    groups = [
        ({36, 40, 44, 48}, 42),
        ({52, 56, 60, 64}, 58),
        ({100, 104, 108, 112}, 106),
        ({116, 120, 124, 128}, 122),
        ({132, 136, 140, 144}, 138),
        ({149, 153, 157, 161}, 155),
    ]
    for channels, center in groups:
        if channel in channels:
            return center
    return None


def _he_oper(channel, width):
    try:
        channel = int(channel)
    except (TypeError, ValueError):
        return None, None
    width = str(width)
    if width in {"20", "40"}:
        center = channel if width == "20" else _vht_center_seg0(channel, width)
        return 0, center
    if width == "80":
        return 1, _vht_center_seg0(channel, width)
    return None, None


def get_debug_snapshot():
    global _last_generated_configs, _last_hostapd_error
    cfg = load_config()
    radio_ifaces = [radio.get("interface") for radio in cfg.get("radios", []) if radio.get("interface")]
    commands = {
        "ip_addr_br_ap": ["ip", "addr", "show", _bridge_name()],
        "ip_route": ["ip", "route"],
        "bridge_link": ["bridge", "link"],
        "bridge_fdb": ["bridge", "fdb", "show"],
        "iptables_mangle": ["iptables", "-t", "mangle", "-S"],
        "hostapd_log": ["sh", "-lc", f"test -f {HOSTAPD_LOG_FILE} && tail -n 80 {HOSTAPD_LOG_FILE} || true"],
    }
    for iface in radio_ifaces:
        commands[f"ip_addr_{iface}"] = ["ip", "addr", "show", iface]
        commands[f"iw_{iface}"] = ["iw", "dev", iface, "info"]

    snapshot = {
        "ap_running": bool(_procs.get("hostapd") and _procs["hostapd"].poll() is None),
        "uplink": _uplink_interface(),
        "bridge": _bridge_name(),
        "radio_ifaces": radio_ifaces,
        "generated_configs": _last_generated_configs,
        "last_hostapd_error": _last_hostapd_error,
        "interface_capabilities": {iface: get_interface_info(iface) for iface in radio_ifaces},
        "commands": {},
    }
    for name, cmd in commands.items():
        snapshot["commands"][name] = {"command": " ".join(cmd), **_run_command(cmd)}
    return snapshot


def _set_tcp_mss_clamp(enabled):
    rules = TCP_MSS_CLAMP_RULES if enabled else [[rule[0], "-t", "mangle", "-D"] + rule[5:] for rule in TCP_MSS_CLAMP_RULES]
    for cmd in rules:
        subprocess.run(cmd, capture_output=True)


def _set_promisc(iface, enabled):
    if not iface:
        return
    mode = "on" if enabled else "off"
    subprocess.run(["ip", "link", "set", "dev", iface, "promisc", mode], capture_output=True)


def _set_bridge_compat(bridge, wifi_ifaces, enabled):
    if enabled:
        _set_promisc(bridge, True)
        for iface in wifi_ifaces:
            _set_promisc(iface, True)

        snooping_path = f"/sys/class/net/{bridge}/bridge/multicast_snooping"
        if os.path.exists(snooping_path):
            try:
                with open(snooping_path, "w") as f:
                    f.write("0")
            except Exception:
                pass
    else:
        _set_promisc(bridge, False)
        for iface in wifi_ifaces:
            _set_promisc(iface, False)


def _set_ip_forward(enabled):
    path = "/proc/sys/net/ipv4/ip_forward"
    previous = None
    try:
        with open(path, "r") as f:
            previous = f.read().strip()
    except Exception:
        pass
    _write_proc_value(path, "1" if enabled else "0")
    return previous


def _set_nat_rules(uplink, subnet_cidr, enabled):
    rules = []
    for template in NAT_RULES:
        cmd = [part.format(uplink=uplink, subnet_cidr=subnet_cidr) for part in template]
        if enabled:
            rules.append(cmd)
        else:
            delete_cmd = cmd.copy()
            action_idx = delete_cmd.index("-A")
            delete_cmd[action_idx] = "-D"
            rules.append(delete_cmd)
    for cmd in rules:
        subprocess.run(cmd, capture_output=True)


def _setup_ap_bridge(bridge, bridge_cidr):
    cmds = [
        ["ip", "link", "add", "name", bridge, "type", "bridge"],
        ["ip", "addr", "add", bridge_cidr, "dev", bridge],
        ["ip", "link", "set", bridge, "up"],
    ]
    for cmd in cmds:
        subprocess.run(cmd, capture_output=True)


def _setup_bridge_mode(bridge, uplink):
    """Create a bridge, move host uplink onto it, and preserve host connectivity."""
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
        cmds += [
            ["ip", "route", "del", "default"],
            ["ip", "route", "add", "default", "via", gateway, "dev", bridge],
        ]
    for cmd in cmds:
        subprocess.run(cmd, capture_output=True)
    return {"uplink": uplink, "gateway": gateway, "ip_prefix": ip_prefix, "mode": "bridge"}


def _teardown_ap_bridge(bridge):
    cmds = [
        ["ip", "link", "set", bridge, "down"],
        ["ip", "link", "del", bridge],
    ]
    for cmd in cmds:
        subprocess.run(cmd, capture_output=True)


def _teardown_bridge_mode(bridge, uplink, gateway=None, ip_prefix=None):
    if gateway:
        subprocess.run(["ip", "route", "del", "default"], capture_output=True)
        subprocess.run(["ip", "route", "add", "default", "via", gateway, "dev", uplink], capture_output=True)
    cmds = [
        ["ip", "link", "set", uplink, "nomaster"],
        ["ip", "link", "set", bridge, "down"],
        ["ip", "link", "del", bridge],
    ]
    if ip_prefix:
        cmds.append(["ip", "addr", "add", ip_prefix, "dev", uplink])
    for cmd in cmds:
        subprocess.run(cmd, capture_output=True)


def _write_dnsmasq_config(dhcp_cfg):
    with open(DNSMASQ_CONF_FILE, "w") as f:
        f.write("port=53\n")
        f.write("interface=br-ap\n")
        f.write("bind-interfaces\n")
        f.write("dhcp-authoritative\n")
        f.write(f"dhcp-range={dhcp_cfg['range_start']},{dhcp_cfg['range_end']},{dhcp_cfg['netmask']},{dhcp_cfg['lease_time']}\n")
        f.write(f"dhcp-option=option:router,{dhcp_cfg['gateway']}\n")
        f.write(f"dhcp-option=option:dns-server,{dhcp_cfg['gateway']}\n")
        f.write("domain-needed\n")
        f.write("bogus-priv\n")
        f.write("log-dhcp\n")
        f.write("log-queries\n")


def _start_dnsmasq(dhcp_cfg):
    _write_dnsmasq_config(dhcp_cfg)
    _procs["dnsmasq"] = subprocess.Popen(["dnsmasq", "--conf-file=" + DNSMASQ_CONF_FILE])


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
    global _last_hostapd_error
    _kill("dnsmasq")
    _kill("hostapd")
    _set_tcp_mss_clamp(False)
    cfg = load_config()
    radio_ifaces = [radio.get("interface") for radio in cfg.get("radios", []) if radio.get("interface")]
    bridge_state = _procs.pop("bridge", None) or {}
    mode = bridge_state.get("mode", "nat")
    uplink = bridge_state.get("uplink")
    subnet_cidr = bridge_state.get("subnet_cidr")
    if mode == "nat" and uplink:
        _set_nat_rules(uplink, subnet_cidr or "192.168.50.0/24", False)
        prev_ip_forward = bridge_state.get("ip_forward_prev")
        if prev_ip_forward in ("0", "1"):
            _write_proc_value("/proc/sys/net/ipv4/ip_forward", prev_ip_forward)
        _set_bridge_compat(_bridge_name(), radio_ifaces, False)
        _teardown_ap_bridge(_bridge_name())
    elif mode == "bridge" and uplink:
        _set_bridge_compat(_bridge_name(), radio_ifaces, False)
        _teardown_bridge_mode(_bridge_name(), uplink, bridge_state.get("gateway"), bridge_state.get("ip_prefix"))


def apply_config(cfg):
    global _last_generated_configs, _last_hostapd_error
    cfg = normalize_config(cfg)
    stop_ap()
    _last_hostapd_error = ""
    _last_generated_configs = {}
    country = cfg.get("country_code", "US")
    network_mode = cfg.get("network_mode", "nat")
    experimental_6ghz_enabled = bool(cfg.get("experimental_6ghz_enabled"))
    password = cfg.get("password", "changeme123")
    dhcp_cfg = None
    if network_mode == "nat":
        dhcp_cfg, dhcp_err = _validate_dhcp_config(cfg.get("dhcp", {}))
        if dhcp_err:
            return {"ok": False, "message": dhcp_err}
    hostapd_confs = []
    enabled_radios = [radio for radio in cfg.get("radios", []) if radio.get("enabled")]
    enabled_6g = [radio for radio in enabled_radios if radio.get("band") == "6g"]

    if len(password) < 8:
        return {"ok": False, "message": "WiFi password must be at least 8 characters"}
    if enabled_6g:
        if not experimental_6ghz_enabled:
            return {"ok": False, "message": "6 GHz radios require Experimental 6 GHz mode to be enabled in the UI"}
        if len(country.strip()) != 2:
            return {"ok": False, "message": "6 GHz requires a valid 2-letter country code"}

    seen_ifaces = set()
    phy_counts = {}
    phy_limits = {}
    for radio in enabled_radios:
        err = _validate_radio_selection(radio)
        if err:
            return {"ok": False, "message": err}
        iface = radio["interface"]
        if iface in seen_ifaces:
            return {"ok": False, "message": f"{iface}: cannot be assigned to multiple radios"}
        seen_ifaces.add(iface)
        info = get_interface_info(iface)
        phy = info.get("phy")
        if phy:
            phy_counts[phy] = phy_counts.get(phy, 0) + 1
            max_ap_go = (info.get("interface_combination") or {}).get("max_ap_go")
            if max_ap_go is not None:
                phy_limits[phy] = max_ap_go
    for phy, count in phy_counts.items():
        limit = phy_limits.get(phy)
        if limit is not None and count > limit:
            return {"ok": False, "message": f"{phy}: adapter interface combination allows only {limit} AP/GO interface(s) at a time"}

    uplink = _uplink_interface()
    if not uplink:
        return {"ok": False, "message": "Could not determine host uplink interface"}
    print(f"==> Uplink interface: {uplink}")

    bridge = _bridge_name()
    if network_mode == "nat":
        _setup_ap_bridge(bridge, dhcp_cfg["bridge_cidr"])
        prev_ip_forward = _set_ip_forward(True)
        _set_nat_rules(uplink, dhcp_cfg["subnet_cidr"], True)
        _procs["bridge"] = {
            "mode": "nat",
            "uplink": uplink,
            "ip_forward_prev": prev_ip_forward,
            "subnet_cidr": dhcp_cfg["subnet_cidr"],
        }
    else:
        _procs["bridge"] = _setup_bridge_mode(bridge, uplink)
    _set_bridge_compat(bridge, [radio["interface"] for radio in enabled_radios], True)
    _set_tcp_mss_clamp(True)

    for radio in enabled_radios:
        band = radio["band"]
        iface = radio["interface"]
        ssid = radio["ssid"]
        channel = int(radio["channel"])
        channel_width = str(radio.get("channel_width", "20"))
        ax_enabled = bool(radio.get("ax_enabled"))
        wpa3 = bool(radio.get("wpa3"))
        hw_mode = HW_MODE.get(band, "g")

        # Bring wifi iface up without IP — hostapd manages it via the bridge
        for cmd in [
            ["ip", "link", "set", iface, "down"],
            ["iw", "dev", iface, "set", "type", "__ap"],
            ["ip", "addr", "flush", "dev", iface],
            ["ip", "link", "set", iface, "master", bridge],
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
                if channel_width in {"40", "80"}:
                    ht_capab = _ht40_capab(channel)
                    if ht_capab:
                        f.write(f"ht_capab={ht_capab}\n")
                if channel_width in {"40", "80"}:
                    f.write("ieee80211ac=1\n")
                if channel_width == "40":
                    center = _vht_center_seg0(channel, channel_width)
                    if center is None:
                        return {"ok": False, "message": f"5GHz: channel {channel} does not support 40 MHz width"}
                    f.write("vht_oper_chwidth=0\n")
                    f.write(f"vht_oper_centr_freq_seg0_idx={center}\n")
                elif channel_width == "80":
                    center = _vht_center_seg0(channel, channel_width)
                    if center is None:
                        return {"ok": False, "message": f"5GHz: channel {channel} does not support 80 MHz width"}
                    f.write("vht_oper_chwidth=1\n")
                    f.write(f"vht_oper_centr_freq_seg0_idx={center}\n")
                if ax_enabled:
                    he_width, he_center = _he_oper(channel, channel_width)
                    if he_width is None or he_center is None:
                        return {"ok": False, "message": f"5GHz: channel {channel} does not support HE operation at {channel_width} MHz"}
                    f.write("ieee80211ax=1\n")
                    f.write(f"he_oper_chwidth={he_width}\n")
                    f.write(f"he_oper_centr_freq_seg0_idx={he_center}\n")
            elif band == "6g":
                op_class = _op_class_for_6ghz(channel)
                if op_class is None:
                    return {"ok": False, "message": "6 GHz channel must be a valid 20 MHz channel (1, 5, 9 ... 233)"}
                f.write(f"op_class={op_class}\n")
                f.write("ieee80211ax=1\n")
                f.write("ieee80211h=1\n")
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
                f.write("rsn_pairwise=CCMP\n")
                if wpa3:
                    f.write("wpa_key_mgmt=WPA-PSK SAE\n")
                    f.write("ieee80211w=1\n")
                    f.write("sae_pwe=1\n")
                else:
                    f.write("wpa_key_mgmt=WPA-PSK\n")
                f.write(f"wpa_passphrase={password}\n")
        try:
            with open(conf_path, "r") as f:
                _last_generated_configs[band] = f.read()
        except Exception:
            _last_generated_configs[band] = f"(failed to read {conf_path})"
        hostapd_confs.append(conf_path)

    if hostapd_confs:
        if network_mode == "nat":
            _start_dnsmasq(dhcp_cfg)
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
            _last_hostapd_error = log_tail
            stop_ap()
            hint = _friendly_hostapd_error(log_tail)
            detail = f" {hint}" if hint else ""
            if log_tail:
                detail += f" Hostapd log: {log_tail}"
            return {"ok": False, "message": f"hostapd failed to start.{detail}"}
        mode_label = "routed via" if network_mode == "nat" else "bridged to"
        return {"ok": True, "message": f"AP started ({len(hostapd_confs)} radio(s)) — {mode_label} {uplink}"}

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


@app.route("/api/debug", methods=["GET"])
def api_debug():
    return jsonify(get_debug_snapshot())


@app.route("/api/exec", methods=["POST"])
def api_exec():
    payload = request.get_json(force=True) or {}
    cmd, err = _validate_exec_command(payload.get("command", ""))
    if err:
        return jsonify({"ok": False, "code": None, "stdout": "", "stderr": err})
    result = _run_command(["sh", "-lc", cmd], timeout=20)
    result["command"] = cmd
    return jsonify(result)


@app.route("/api/exec_stream", methods=["GET"])
def api_exec_stream():
    cmd, err = _validate_exec_command(request.args.get("command", ""))
    if err:
        return jsonify({"ok": False, "stderr": err}), 400

    @stream_with_context
    def generate():
        proc = None
        try:
            yield f"event: meta\ndata: {json.dumps({'command': cmd})}\n\n"
            proc = subprocess.Popen(
                ["sh", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                yield f"data: {json.dumps({'line': line.rstrip(chr(10))})}\n\n"
            code = proc.wait()
            yield f"event: done\ndata: {json.dumps({'code': code})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

    return Response(generate(), mimetype="text/event-stream")


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
