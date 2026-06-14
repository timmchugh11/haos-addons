#!/usr/bin/env python3
"""
test_endpoints.py  —  Smoke-test for Starlink GUI server endpoints + direct
                       OpenWrt ubus connectivity.

Requirements:  pip install requests

Usage:
    python test_endpoints.py
    python test_endpoints.py --server http://192.168.1.50:3000
    python test_endpoints.py --openwrt-host 192.168.1.1 --openwrt-user root --openwrt-pass secret
    python test_endpoints.py --no-dish      # skip dish tests (dish not reachable)
    python test_endpoints.py --no-server    # skip server tests, only test ubus directly
"""

import argparse
import getpass
import json
import sys
import time

try:
    import requests
    requests.packages.urllib3.disable_warnings()
except ImportError:
    print("ERROR: 'requests' is required.  Run:  pip install requests")
    sys.exit(1)


# ── ANSI colours ──────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
DIM    = "\033[2m"

def ok(s):   return f"{GREEN}✓ {s}{RESET}"
def warn(s): return f"{YELLOW}⚠ {s}{RESET}"
def fail(s): return f"{RED}✗ {s}{RESET}"
def hdr(s):  return f"\n{BOLD}{CYAN}── {s} ──{RESET}"
def kv(k, v):
    v_str = str(v) if not isinstance(v, str) else v
    return f"   {DIM}{k}:{RESET} {v_str}"


# ── Shared state ──────────────────────────────────────────────────────────────

passed = 0
failed = 0
warned = 0


def record(status):
    global passed, failed, warned
    if status == "ok":   passed += 1
    elif status == "warn": warned += 1
    else:                failed += 1


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def get(url, timeout=10, **kwargs):
    try:
        t0 = time.monotonic()
        r  = requests.get(url, timeout=timeout, verify=False, **kwargs)
        ms = int((time.monotonic() - t0) * 1000)
        return r, ms, None
    except requests.exceptions.ConnectionError as e:
        return None, 0, f"Connection refused / unreachable: {e}"
    except requests.exceptions.Timeout:
        return None, 0, "Timed out"
    except Exception as e:
        return None, 0, str(e)


def post_json(url, body, timeout=12):
    try:
        t0 = time.monotonic()
        r  = requests.post(url, json=body, timeout=timeout, verify=False)
        ms = int((time.monotonic() - t0) * 1000)
        return r, ms, None
    except requests.exceptions.ConnectionError as e:
        return None, 0, f"Connection refused / unreachable: {e}"
    except requests.exceptions.Timeout:
        return None, 0, "Timed out"
    except Exception as e:
        return None, 0, str(e)


def parse_api(r):
    """Return (ok:bool, data, error_str)."""
    try:
        j = r.json()
        if j.get("ok"):
            return True, j.get("data"), None
        return False, None, j.get("error", "ok=false")
    except Exception as e:
        return False, None, f"JSON parse error: {e}"


# ── Server endpoint tests ─────────────────────────────────────────────────────

def test_server_endpoint(label, url, checks=None):
    """
    GET the URL, print pass/fail, run optional checks against the parsed data.
    checks: list of (description, callable(data) -> bool|str)
    Returns the parsed data dict or None.
    """
    r, ms, err = get(url)
    if err:
        print(fail(f"{label}  ({err})"))
        record("fail")
        return None

    ok_flag, data, api_err = parse_api(r)
    tag = f"[{ms} ms]"
    if not ok_flag:
        print(fail(f"{label}  {tag}  —  {api_err}"))
        record("fail")
        return None

    status = "ok"
    lines  = [f"  {tag}"]

    if checks:
        for desc, fn in checks:
            try:
                result = fn(data)
                if result is True or result == "ok":
                    lines.append(kv("  " + desc, "✓"))
                elif result is False or result == "fail":
                    lines.append(f"   {RED}✗ {desc}{RESET}")
                    status = "fail"
                elif isinstance(result, str) and result.startswith("warn:"):
                    lines.append(warn(f"  {desc}: {result[5:]}"))
                    if status == "ok":
                        status = "warn"
                else:
                    # result is a display string
                    lines.append(kv("  " + desc, result))
            except Exception as e:
                lines.append(fail(f"  {desc}: check raised {e}"))
                status = "fail"

    if status == "ok":
        print(ok(label))
    elif status == "warn":
        print(warn(label))
    else:
        print(fail(label))

    for l in lines:
        print(l)

    record(status)
    return data


# ── Direct ubus helpers ───────────────────────────────────────────────────────

ZERO_SESSION = "00000000000000000000000000000000"


def ubus_login(url, username, password):
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [ZERO_SESSION, "session", "login",
                   {"username": username, "password": password}],
    }
    r, ms, err = post_json(url, body)
    if err:
        return None, ms, err
    try:
        code, data = r.json()["result"]
        if code != 0 or "ubus_rpc_session" not in data:
            return None, ms, f"Login failed (code {code})"
        return data["ubus_rpc_session"], ms, None
    except Exception as e:
        return None, ms, f"Parse error: {e}"


def ubus_call(url, session, obj, method, params=None):
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": [session, obj, method, params or {}],
    }
    r, ms, err = post_json(url, body)
    if err:
        return None, ms, err
    try:
        result = r.json().get("result", [])
        code   = result[0] if isinstance(result, list) and len(result) > 0 else -1
        data   = result[1] if isinstance(result, list) and len(result) > 1 else {}
        if code != 0:
            return None, ms, f"ubus code {code}"
        return data, ms, None
    except Exception as e:
        return None, ms, f"Parse error: {e}"


def ubus_list(url, session, pattern="hostapd.*"):
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "list",
        "params": [pattern],
    }
    r, ms, err = post_json(url, body)
    if err:
        return None, ms, err
    try:
        result = r.json().get("result", {})
        return result, ms, None
    except Exception as e:
        return None, ms, f"Parse error: {e}"


def test_ubus(label, url, session, obj, method, params=None, checks=None):
    data, ms, err = ubus_call(url, session, obj, method, params)
    tag = f"[{ms} ms]"
    if err:
        print(fail(f"{label}  {tag}  —  {err}"))
        record("fail")
        return None

    status = "ok"
    lines  = []

    if checks:
        for desc, fn in checks:
            try:
                result = fn(data)
                if result is True or result == "ok":
                    lines.append(kv("  " + desc, "✓"))
                elif result is False or result == "fail":
                    lines.append(f"   {RED}✗ {desc}{RESET}")
                    status = "fail"
                elif isinstance(result, str) and result.startswith("warn:"):
                    lines.append(warn(f"  {desc}: {result[5:]}"))
                    if status == "ok":
                        status = "warn"
                else:
                    lines.append(kv("  " + desc, result))
            except Exception as e:
                lines.append(fail(f"  {desc}: check raised {e}"))
                status = "fail"

    if status == "ok":
        print(ok(f"{label}  {tag}"))
    elif status == "warn":
        print(warn(f"{label}  {tag}"))
    else:
        print(fail(f"{label}  {tag}"))

    for l in lines:
        print(l)

    record(status)
    return data


def fmt_uptime(seconds):
    if not isinstance(seconds, (int, float)):
        return "?"
    s = int(seconds)
    d = s // 86400
    h = (s % 86400) // 3600
    m = (s % 3600) // 60
    if d:   return f"{d}d {h}h {m}m"
    if h:   return f"{h}h {m}m"
    return f"{m}m"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Starlink GUI endpoint smoke-test")
    parser.add_argument("--server",        default="http://localhost:3000",
                        help="Base URL of the running Starlink GUI server (default: http://localhost:3000)")
    parser.add_argument("--openwrt-host",  default="192.168.1.1",
                        help="OpenWrt IP or hostname (default: 192.168.1.1)")
    parser.add_argument("--openwrt-proto", default="http", choices=["http", "https"],
                        help="OpenWrt protocol (default: http)")
    parser.add_argument("--openwrt-user",  default="root",
                        help="OpenWrt username (default: root)")
    parser.add_argument("--openwrt-pass",  default=None,
                        help="OpenWrt password (prompted if omitted)")
    parser.add_argument("--no-server",     action="store_true",
                        help="Skip all server endpoint tests")
    parser.add_argument("--no-dish",       action="store_true",
                        help="Skip dish-specific endpoint tests")
    parser.add_argument("--no-openwrt",    action="store_true",
                        help="Skip direct OpenWrt ubus tests")
    args = parser.parse_args()

    base    = args.server.rstrip("/")
    ow_url  = f"{args.openwrt_proto}://{args.openwrt_host}/ubus"

    if not args.no_openwrt and args.openwrt_pass is None:
        args.openwrt_pass = getpass.getpass(
            f"OpenWrt password for {args.openwrt_user}@{args.openwrt_host}: ")

    print(f"\n{BOLD}Starlink GUI  —  Endpoint Smoke-Test{RESET}")
    print(f"  Server  : {base}")
    if not args.no_openwrt:
        print(f"  OpenWrt : {ow_url}  (user: {args.openwrt_user})")

    # ── Server: config ────────────────────────────────────────────────────────
    if not args.no_server:
        print(hdr("Server — /api/config"))

        cfg_data = test_server_endpoint(
            "/api/config",
            f"{base}/api/config",
            checks=[
                ("dishHost",              lambda d: d.get("dishHost", "missing")),
                ("routerHost",            lambda d: d.get("routerHost", "missing")),
                ("openwrtFillRouterBlanks", lambda d:
                    str(d.get("openwrtFillRouterBlanks"))
                    if "openwrtFillRouterBlanks" in d
                    else "warn:field missing — server may be old build"),
            ],
        )

    # ── Server: dish ─────────────────────────────────────────────────────────
    if not args.no_server and not args.no_dish:
        print(hdr("Server — Dish endpoints"))

        test_server_endpoint(
            "/api/dishy/status",
            f"{base}/api/dishy/status",
            checks=[
                ("state",   lambda d: d.get("deviceState", {}).get("state", "—")),
                ("dl Mbps", lambda d: f"{d.get('downlinkThroughputBps', 0) / 1e6:.1f}"),
                ("ul Mbps", lambda d: f"{d.get('uplinkThroughputBps',   0) / 1e6:.1f}"),
                ("latency", lambda d: f"{d.get('popPingLatencyMs', '—')} ms"),
            ],
        )

        test_server_endpoint(
            "/api/dishy/diagnostics",
            f"{base}/api/dishy/diagnostics",
            checks=[
                ("hardwareSelfTest", lambda d: str(d.get("hardwareSelfTest", "—"))),
                ("stowed",           lambda d: str(d.get("stowed", "—"))),
            ],
        )

    # ── Server: router/summary ────────────────────────────────────────────────
    if not args.no_server:
        print(hdr("Server — /api/router/summary"))

        test_server_endpoint(
            "/api/router/summary  (no bypass)",
            f"{base}/api/router/summary",
            checks=[
                ("provider", lambda d: d.get("provider", "missing")),
                ("wanIp",    lambda d: d.get("wanIp", "—")),
                ("uptime",   lambda d: d.get("statCards", {}).get("uptime", "—")),
                ("clients",  lambda d: d.get("statCards", {}).get("clients", "—")),
                ("bands",    lambda d: d.get("statCards", {}).get("bands",   "—")),
            ],
        )

        test_server_endpoint(
            "/api/router/summary  (bypass=1)",
            f"{base}/api/router/summary?bypass=1",
            checks=[
                ("provider",  lambda d: d.get("provider", "missing")),
                ("wanIp",     lambda d: d.get("wanIp", "—")),
                ("uptime",    lambda d: d.get("statCards", {}).get("uptime", "—")),
                ("clients",   lambda d: d.get("statCards", {}).get("clients", "—")),
                ("error",     lambda d: ("warn:" + d["error"]) if d.get("error") else "none"),
            ],
        )

    # ── Server: OpenWrt debug routes ──────────────────────────────────────────
    if not args.no_server:
        print(hdr("Server — /api/openwrt/* (debug routes)"))

        test_server_endpoint(
            "/api/openwrt/status",
            f"{base}/api/openwrt/status",
            checks=[
                ("provider",         lambda d: d.get("provider", "—")),
                ("id (hostname)",    lambda d: d.get("id",              "—")),
                ("hardwareVersion",  lambda d: d.get("hardwareVersion", "—")),
                ("softwareVersion",  lambda d: d.get("softwareVersion", "—")),
                ("wanIp",            lambda d: d.get("wanIp",           "—")),
                ("uptime",           lambda d: d.get("uptime",          "—")),
                ("error",            lambda d: ("warn:" + d["error"]) if d.get("error") else "none"),
            ],
        )

        test_server_endpoint(
            "/api/openwrt/interfaces",
            f"{base}/api/openwrt/interfaces",
            checks=[
                ("WAN ipv4", lambda d: (
                    d.get("wan", {}).get("ipv4-address", [{}])[0].get("address", "—")
                    if d.get("wan") else "— (no WAN data)")),
                ("LAN ipv4", lambda d: (
                    d.get("lan", {}).get("ipv4-address", [{}])[0].get("address", "—")
                    if d.get("lan") else "— (no LAN data)")),
            ],
        )

        test_server_endpoint(
            "/api/openwrt/clients",
            f"{base}/api/openwrt/clients",
            checks=[
                ("totalClients",    lambda d: str(d.get("totalClients",    0))),
                ("clients2ghz",     lambda d: str(d.get("clients2ghz",     0))),
                ("clients5ghz",     lambda d: str(d.get("clients5ghz",     0))),
                ("clientsEthernet", lambda d: str(d.get("clientsEthernet", 0))),
            ],
        )

    # ── Direct OpenWrt ubus ───────────────────────────────────────────────────
    if not args.no_openwrt:
        print(hdr("Direct OpenWrt ubus"))

        # Login
        print(f"  Logging in to {ow_url} ...", end=" ", flush=True)
        session, ms, err = ubus_login(ow_url, args.openwrt_user, args.openwrt_pass)
        if err:
            print(fail(f"Login failed  [{ms} ms]  —  {err}"))
            record("fail")
        else:
            print(ok(f"Login  [{ms} ms]  session={session[:8]}…"))
            record("ok")

            test_ubus("system.board", ow_url, session, "system", "board",
                checks=[
                    ("hostname",    lambda d: d.get("hostname",             "—")),
                    ("model",       lambda d: d.get("model",                "—")),
                    ("description", lambda d: d.get("release", {}).get("description",
                                               d.get("release", {}).get("version", "—"))),
                ])

            test_ubus("system.info  (uptime)", ow_url, session, "system", "info",
                checks=[
                    ("uptime", lambda d: fmt_uptime(d.get("uptime", 0))),
                    ("memory free MB", lambda d: (
                        f"{d['memory']['free'] // 1024 // 1024}"
                        if d.get("memory") else "—")),
                ])

            # Dump all interfaces — this is what openwrt.js now uses
            dump_data, ms, err = ubus_call(ow_url, session, "network.interface", "dump")
            tag = f"[{ms} ms]"
            if err:
                print(fail(f"network.interface dump  {tag}  —  {err}"))
                record("fail")
            else:
                ifaces = dump_data.get("interface", [])
                # Pick WAN and LAN using same logic as openwrt.js
                def is_private(a):
                    return a and (a.startswith("10.") or a.startswith("192.168.")
                                  or bool(__import__("re").match(r"172\.(1[6-9]|2\d|3[01])\.", a)))
                wan_iface = next((i for i in ifaces if "wan" in i.get("interface","").lower()), None) \
                         or next((i for i in ifaces if i.get("ipv4-address") and
                                  not is_private(i["ipv4-address"][0]["address"]) and
                                  not i["ipv4-address"][0]["address"].startswith("127.")), None)
                lan_iface = next((i for i in ifaces if "lan" in i.get("interface","").lower()), None) \
                         or next((i for i in ifaces if i.get("ipv4-address") and
                                  is_private(i["ipv4-address"][0]["address"])), None)

                print(ok(f"network.interface dump  {tag}  —  {len(ifaces)} interface(s)"))
                record("ok")
                for i in ifaces:
                    ipv4 = i["ipv4-address"][0]["address"] if i.get("ipv4-address") else "—"
                    role = ""
                    if i is wan_iface: role = "  ← WAN"
                    if i is lan_iface: role = "  ← LAN"
                    print(kv(f"  {i.get('interface','?'):12s}  up={str(i.get('up','?')):<5}  ipv4={ipv4}{role}", ""))

            test_ubus("file.read  /tmp/dhcp.leases", ow_url, session,
                "file", "read", {"path": "/tmp/dhcp.leases"},
                checks=[
                    ("lease count", lambda d: str(
                        len([l for l in d.get("data", "").split("\n") if l.strip()]))),
                ])
            # code 6 = PERMISSION_DENIED — guide the user to fix it
            print(f"   {DIM}hint: code 6 = permission denied — both scopes needed in /usr/share/rpcd/acl.d/starlink-gui.json:{RESET}")
            print(f'   {DIM}  {{"starlink-gui":{{"description":"Starlink GUI","read":{{"ubus":{{"file":["read"]}},"file":{{"/tmp/dhcp.leases":["read"]}}}}}}}}{RESET}')
            print(f"   {DIM}  then run: /etc/init.d/rpcd restart && /etc/init.d/uhttpd restart{RESET}")

            # Discover hostapd objects
            print(f"  Listing hostapd.* objects ...", end=" ", flush=True)
            hostapd_objects, ms, err = ubus_list(ow_url, session, "hostapd.*")
            tag = f"[{ms} ms]"
            if err:
                print(warn(f"hostapd list  {tag}  —  {err}  (Wi-Fi counts unavailable)"))
                record("warn")
            elif not hostapd_objects:
                print(warn(f"hostapd list  {tag}  —  no hostapd.* objects found (hostapd not running?)"))
                record("warn")
            else:
                names = list(hostapd_objects.keys())
                print(ok(f"hostapd list  {tag}  —  {len(names)} object(s): {', '.join(names)}"))
                record("ok")

                for obj in names:
                    test_ubus(f"  {obj}.get_clients", ow_url, session, obj, "get_clients",
                        checks=[
                            ("clients", lambda d: str(len(d.get("clients", {})))),
                            ("freq MHz", lambda d: str(d.get("freq", "—"))),
                        ])

    # ── Summary ───────────────────────────────────────────────────────────────
    total = passed + warned + failed
    print(f"\n{BOLD}{'─' * 42}{RESET}")
    print(f"  {ok(f'Passed : {passed}/{total}')}")
    if warned:
        print(f"  {warn(f'Warned : {warned}/{total}')}")
    if failed:
        print(f"  {fail(f'Failed : {failed}/{total}')}")
    print(f"{BOLD}{'─' * 42}{RESET}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
