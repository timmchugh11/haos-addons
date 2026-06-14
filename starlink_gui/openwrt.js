'use strict';

const http  = require('http');
const https = require('https');

const ZERO_SESSION = '00000000000000000000000000000000';

function fmtUptime(seconds) {
    const s = Math.floor(seconds);
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function httpPost(url, body) {
    return new Promise((resolve, reject) => {
        const parsed = new URL(url);
        const isHttps = parsed.protocol === 'https:';
        const lib = isHttps ? https : http;
        const payload = JSON.stringify(body);
        const options = {
            hostname: parsed.hostname,
            port: parsed.port || (isHttps ? 443 : 80),
            path: parsed.pathname,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(payload),
            },
            timeout: 8000,
            rejectUnauthorized: false, // allow self-signed certs on local LAN
        };
        const req = lib.request(options, (res) => {
            const chunks = [];
            res.on('data', chunk => chunks.push(chunk));
            res.on('end', () => {
                try {
                    resolve(JSON.parse(Buffer.concat(chunks).toString()));
                } catch (e) {
                    reject(new Error(`JSON parse error: ${e.message}`));
                }
            });
        });
        req.on('error', reject);
        req.on('timeout', () => { req.destroy(new Error('OpenWrt request timed out')); });
        req.write(payload);
        req.end();
    });
}

async function ubusLogin(url, username, password) {
    const res = await httpPost(url, {
        jsonrpc: '2.0',
        id: 1,
        method: 'call',
        params: [ZERO_SESSION, 'session', 'login', { username, password }],
    });
    const [code, data] = Array.isArray(res.result) ? res.result : [];
    if (code !== 0 || !data?.ubus_rpc_session) {
        throw new Error(`OpenWrt login failed (code ${code ?? 'unknown'})`);
    }
    return data.ubus_rpc_session;
}

async function ubusCall(url, session, object, method, params = {}) {
    const res = await httpPost(url, {
        jsonrpc: '2.0',
        id: 1,
        method: 'call',
        params: [session, object, method, params],
    });
    const [code, data] = Array.isArray(res.result) ? res.result : [];
    if (code !== 0) throw new Error(`ubus ${object}.${method} failed (code ${code ?? 'unknown'})`);
    return data || {};
}

function parseDhcpLeases(raw) {
    if (typeof raw !== 'string' || !raw.trim()) return 0;
    return raw.split('\n').filter(l => l.trim().length > 0).length;
}

async function getDhcpLeaseCount(url, session) {
    // Try luci-rpc first — works without any ACL setup on routers with LuCI installed
    try {
        const d = await ubusCall(url, session, 'luci-rpc', 'getDHCPLeases');
        return Array.isArray(d.dhcp_leases) ? d.dhcp_leases.length : 0;
    } catch (_) {}
    // Fallback: read the leases file directly (requires file read ACL in rpcd)
    try {
        const d = await ubusCall(url, session, 'file', 'read', { path: '/tmp/dhcp.leases' });
        return parseDhcpLeases(d.data);
    } catch (e) {
        console.warn('[openwrt] DHCP leases unavailable:', e.message,
            '— install luci-rpc or add file read ACL in /usr/share/rpcd/acl.d/');
        return 0;
    }
}

function isPrivateIp(addr) {
    if (!addr) return false;
    return addr.startsWith('10.')
        || addr.startsWith('192.168.')
        || /^172\.(1[6-9]|2\d|3[01])\./.test(addr);
}

function pickWan(ifaces) {
    // Prefer an interface whose UCI name contains 'wan'
    return ifaces.find(i => /wan/i.test(i.interface))
        // Fall back: first interface with a public (non-private, non-loopback) IPv4
        || ifaces.find(i => {
            const a = i['ipv4-address']?.[0]?.address;
            return a && !isPrivateIp(a) && !a.startsWith('127.');
        })
        || {};
}

function pickLan(ifaces) {
    // Prefer an interface whose UCI name contains 'lan'
    return ifaces.find(i => /lan/i.test(i.interface))
        // Fall back: first interface with a private IPv4
        || ifaces.find(i => {
            const a = i['ipv4-address']?.[0]?.address;
            return a && isPrivateIp(a);
        })
        || {};
}

async function discoverWifiClients(url, session) {
    // Try zyxel.ap ubus bridge first — one call, band-accurate counts
    try {
        const d = await ubusCall(url, session, 'zyxel.ap', 'get_clients');
        if (d && typeof d === 'object') {
            const entries = Object.values(d);
            if (entries.length > 0) {
                let clients2ghz = 0, clients5ghz = 0;
                for (const c of entries) {
                    if (c.band === '5GHz') clients5ghz++;
                    else clients2ghz++;
                }
                return { clients2ghz, clients5ghz };
            }
        }
    } catch (_) {}
    // Fall back to hostapd ubus objects
    return discoverHostapdClients(url, session);
}

async function discoverHostapdClients(url, session) {
    let clients2ghz = 0;
    let clients5ghz = 0;
    try {
        const listRes = await httpPost(url, {
            jsonrpc: '2.0',
            id: 1,
            method: 'list',
            params: ['hostapd.*'],
        });
        const objects = (listRes.result && typeof listRes.result === 'object')
            ? Object.keys(listRes.result)
            : [];
        for (const obj of objects) {
            try {
                const cd = await ubusCall(url, session, obj, 'get_clients');
                const count = (cd.clients && typeof cd.clients === 'object')
                    ? Object.keys(cd.clients).length
                    : 0;
                // Prefer freq field (MHz); fall back to interface name heuristic.
                // Common OpenWrt convention: wlan0/phy0 = 2.4 GHz, wlan1/phy1 = 5 GHz.
                const freq = typeof cd.freq === 'number' ? cd.freq : null;
                let is5ghz;
                if (freq !== null) {
                    is5ghz = freq >= 5000;
                } else {
                    const iface = obj.replace(/^hostapd\./, '');
                    is5ghz = /1$/.test(iface) || iface.includes('5g') || iface.includes('5G');
                }
                if (is5ghz) clients5ghz += count;
                else        clients2ghz += count;
            } catch (e) {
                console.warn(`[openwrt] ${obj}.get_clients failed:`, e.message);
            }
        }
    } catch (e) {
        console.warn('[openwrt] hostapd discovery failed:', e.message);
    }
    return { clients2ghz, clients5ghz };
}

async function getRouterSummary({ protocol, host, username, password }) {
    const url = `${protocol}://${host}/ubus`;
    const PH = '—';
    const empty = {
        provider: 'openwrt',
        id: PH, hardwareVersion: PH, softwareVersion: PH, countryCode: PH,
        wanIp: PH, lanIpv4: PH, lanIpv6Count: 0,
        uptime: PH, uptimeSeconds: 0,
        totalClients: 0, clientsEthernet: 0, clients2ghz: 0, clients5ghz: 0,
        statCards: { wan: PH, uptime: PH, clients: '0', bands: '0 / 0 / 0' },
        error: null, raw: {},
    };

    let session;
    try {
        session = await ubusLogin(url, username, password);
    } catch (e) {
        console.warn('[openwrt] Login error:', e.message);
        return { ...empty, error: `OpenWrt login failed: ${e.message}` };
    }

    const raw = {};
    let board = {}, info = {}, wan = {}, lan = {};
    let dhcpLeases = 0, clients2ghz = 0, clients5ghz = 0;

    const settled = await Promise.allSettled([
        ubusCall(url, session, 'system', 'board')
            .then(d => { board = d; raw.board = d; }),
        ubusCall(url, session, 'system', 'info')
            .then(d => { info  = d; raw.info  = d; }),
        // Dump all interfaces at once — works regardless of UCI interface names
        ubusCall(url, session, 'network.interface', 'dump', {})
            .then(d => {
                const ifaces = d.interface || [];
                raw.ifaceDump = ifaces;
                wan = pickWan(ifaces);
                lan = pickLan(ifaces);
                raw.wan = wan;
                raw.lan = lan;
            }),
        getDhcpLeaseCount(url, session)
            .then(n => { dhcpLeases = n; }),
        discoverWifiClients(url, session)
            .then(c => { clients2ghz = c.clients2ghz; clients5ghz = c.clients5ghz; }),
    ]);

    const callNames = [
        'system.board', 'system.info',
        'network.interface dump',
        'dhcp leases', 'hostapd',
    ];
    settled.forEach((r, i) => {
        if (r.status === 'rejected') {
            console.warn(`[openwrt] ${callNames[i]} failed:`, r.reason?.message ?? r.reason);
        }
    });

    const uptimeSeconds   = typeof info.uptime === 'number' ? info.uptime : 0;
    const uptime          = uptimeSeconds > 0 ? fmtUptime(uptimeSeconds) : PH;
    const wanIp           = wan['ipv4-address']?.[0]?.address ?? PH;
    const lanIpv4         = lan['ipv4-address']?.[0]?.address ?? PH;
    const lanIpv6Count    = Array.isArray(lan['ipv6-address']) ? lan['ipv6-address'].length : 0;
    const id              = board.hostname              ?? PH;
    const hardwareVersion = board.model                 ?? PH;
    const softwareVersion = board.release?.description ?? board.release?.version ?? PH;
    const wifiClients     = clients2ghz + clients5ghz;
    const clientsEthernet = Math.max(0, dhcpLeases - wifiClients);
    const totalClients    = dhcpLeases;

    return {
        provider: 'openwrt',
        id, hardwareVersion, softwareVersion, countryCode: PH,
        wanIp, lanIpv4, lanIpv6Count,
        uptime, uptimeSeconds,
        totalClients, clientsEthernet, clients2ghz, clients5ghz,
        statCards: {
            wan:     wanIp,
            uptime,
            clients: String(totalClients),
            bands:   `${clients2ghz} / ${clients5ghz} / ${clientsEthernet}`,
        },
        error: null,
        raw,
    };
}

async function getRouterClients({ protocol, host, username, password }) {
    const url = `${protocol}://${host}/ubus`;
    let session;
    try {
        session = await ubusLogin(url, username, password);
    } catch (e) {
        return { clients: [], _source: 'openwrt', error: `Login failed: ${e.message}` };
    }

    // Try zyxel.ap ubus bridge — gives band info (iface 2=2.4GHz, 3=5GHz)
    try {
        const d = await ubusCall(url, session, 'zyxel.ap', 'get_clients');
        if (d && typeof d === 'object' && Object.keys(d).length > 0) {
            const clients = Object.values(d).map(c => ({
                mac:           c.macaddr || '—',
                ipAddress:     c.ipaddr  || '—',
                hostname:      c.ssid    || '',
                iface:         c.band === '5GHz' ? 3 : 2,
                signalStrength: typeof c.signal === 'number' ? c.signal : null,
                _txRate:       c.tx_rate,
                _rxRate:       c.rx_rate,
                _band:         c.band,
            }));
            return { clients, _source: 'zyxel-ap-ubus' };
        }
    } catch (e) {
        console.warn('[openwrt] zyxel.ap get_clients failed:', e.message);
    }

    // Fall back to DHCP leases (no band info)
    let clients = [];
    try {
        const d = await ubusCall(url, session, 'luci-rpc', 'getDHCPLeases');
        if (Array.isArray(d.dhcp_leases)) {
            clients = d.dhcp_leases.map(l => ({
                mac:      l.macaddr || '—',
                ipAddress: l.ipaddr || '—',
                hostname: l.hostname || '',
                iface:    1,
            }));
        }
    } catch (e) {
        console.warn('[openwrt] getDHCPLeases failed:', e.message);
    }
    return { clients, _source: 'openwrt' };
}

async function getRouterInterfaces({ protocol, host, username, password }) {
    const url = `${protocol}://${host}/ubus`;
    let session;
    try {
        session = await ubusLogin(url, username, password);
    } catch (e) {
        return { networkInterfaces: [], _source: 'openwrt', error: `Login failed: ${e.message}` };
    }
    let networkInterfaces = [];
    try {
        const devStatus = await ubusCall(url, session, 'network.device', 'status', {});
        networkInterfaces = Object.entries(devStatus).map(([name, dev]) => ({
            name,
            ethernet: { linkDetected: dev.up === true },
            rxStats: {
                bytes: dev.statistics?.rx_bytes ?? 0,
                packets: dev.statistics?.rx_packets ?? 0,
            },
            txStats: {
                bytes: dev.statistics?.tx_bytes ?? 0,
                packets: dev.statistics?.tx_packets ?? 0,
            },
        }));
    } catch (e) {
        console.warn('[openwrt] network.device status failed:', e.message);
    }
    return { networkInterfaces, _source: 'openwrt' };
}

module.exports = { getRouterSummary, getRouterClients, getRouterInterfaces, fmtUptime };
