'use strict';

const express = require('express');
const cors = require('cors');
const fs    = require('fs');
const path = require('path');
const { Dishy } = require('@gibme/starlink');
const { WiFiRouter } = require('@gibme/starlink');
const { getRouterSummary: getOpenwrtRouterSummary, getRouterClients: getOpenwrtClients, getRouterInterfaces: getOpenwrtInterfaces, fmtUptime } = require('./openwrt');

const app = express();
const PORT = process.env.PORT || 3000;

// Defaults — overridden by HA add-on options (exported by run.sh via bashio)
const DEFAULT_DISH_HOST   = process.env.DISH_HOST   || '192.168.100.1';
const DEFAULT_DISH_PORT   = parseInt(process.env.DISH_PORT   || '9200', 10);
const DEFAULT_ROUTER_HOST = process.env.ROUTER_HOST || '192.168.1.1';
const DEFAULT_ROUTER_PORT = parseInt(process.env.ROUTER_PORT || '9000', 10);

// Bypass mode and OpenWrt config (from HA add-on options)
const BYPASS_MODE            = process.env.BYPASS_MODE === 'true';
const OPENWRT_FILL_ROUTER_BLANKS = process.env.OPENWRT_FILL_ROUTER_BLANKS === 'true';
const OPENWRT_HOST     = process.env.OPENWRT_HOST     || '192.168.1.1';
const OPENWRT_PROTOCOL = process.env.OPENWRT_PROTOCOL || 'http';
const OPENWRT_USERNAME = process.env.OPENWRT_USERNAME || 'root';
const OPENWRT_PASSWORD = process.env.OPENWRT_PASSWORD || '';

function owrtConfig() {
    return { protocol: OPENWRT_PROTOCOL, host: OPENWRT_HOST, username: OPENWRT_USERNAME, password: OPENWRT_PASSWORD };
}

// Read HTML files once at startup for ingress-path injection
const INDEX_HTML        = fs.readFileSync(path.join(__dirname, 'public', 'index.html'),        'utf8');
const OBSTRUCTION_HTML  = fs.readFileSync(path.join(__dirname, 'public', 'obstruction.html'),  'utf8');
const ALIGNMENT_HTML    = fs.readFileSync(path.join(__dirname, 'public', 'alignment.html'),    'utf8');

app.use(cors());
app.use(express.json());
// Serve static assets (css, js, images etc.) but NOT index.html — we inject the base path ourselves
app.use(express.static(path.join(__dirname, 'public'), { index: false }));
app.use('/vendor/three', express.static(path.join(__dirname, 'node_modules', 'three'), { index: false }));
app.get('/starlink-logo-01.png', (_req, res) => {
  res.sendFile(path.join(__dirname, 'starlink-logo-01.png'));
});

// ── helpers ──────────────────────────────────────────────────────────────────

function getDishy(req) {
    const host = req.query.dishHost || DEFAULT_DISH_HOST;
    const port = parseInt(req.query.dishPort || DEFAULT_DISH_PORT, 10);
    return new Dishy(host, port);
}

function getRouter(req) {
    const host = req.query.routerHost || DEFAULT_ROUTER_HOST;
    const port = parseInt(req.query.routerPort || DEFAULT_ROUTER_PORT, 10);
    return new WiFiRouter(host, port);
}

function unwrapResponse(response, preferredKey) {
    if (preferredKey && response && response[preferredKey] !== undefined) {
        return response[preferredKey];
    }
    return response;
}

async function collectResults(specs) {
    const out = {};
    for (const [name, spec] of Object.entries(specs)) {
        if (typeof spec !== 'function') {
            out[name] = {
                ok: false,
                skipped: true,
                request: spec.request,
                reason: spec.reason,
            };
            continue;
        }
        try {
            out[name] = {
                ok: true,
                data: await spec(),
            };
        } catch (err) {
            out[name] = {
                ok: false,
                error: err.message || String(err),
            };
        }
    }
    return out;
}

async function handle(res, fn) {
    try {
        const data = await fn();
        res.json({ ok: true, data });
    } catch (err) {
        res.status(500).json({ ok: false, error: err.message || String(err) });
    }
}

// ── Dishy routes ─────────────────────────────────────────────────────────────

app.get('/api/dishy/status', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.fetch_status().finally(() => dishy.close()));
});

app.get('/api/dishy/diagnostics', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.fetch_diagnostics().finally(() => dishy.close()));
});

app.get('/api/dishy/history', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.fetch_history().finally(() => dishy.close()));
});

app.get('/api/dishy/location', (_req, res) => {
    res.status(410).json({
        ok: false,
        error: 'Dish location is unavailable: Starlink policy disables local GetLocation requests on current firmware.',
    });
});

app.get('/api/dishy/obstruction-map', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.fetch_obstruction_map().finally(() => dishy.close()));
});

app.get('/api/dishy/alignment', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy['handle']({ getDiagnostics: {} })
        .then(r => {
            const stats = r?.dishGetDiagnostics?.alignmentStats;
            if (!stats) throw new Error('alignmentStats not available in diagnostics response');
            return stats;
        })
        .finally(() => dishy.close())
    );
});

app.get('/api/dishy/dump', async (req, res) => {
    const specs = {
        dishGetStatus: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getStatus: {} }).finally(() => dishy.close());
        },
        status: async () => {
            const dishy = getDishy(req);
            return dishy.fetch_status().finally(() => dishy.close());
        },
        dishGetDiagnostics: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getDiagnostics: {} }).finally(() => dishy.close());
        },
        diagnostics: async () => {
            const dishy = getDishy(req);
            return dishy.fetch_diagnostics().finally(() => dishy.close());
        },
        dishGetHistory: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getHistory: {} }).finally(() => dishy.close());
        },
        history: async () => {
            const dishy = getDishy(req);
            return dishy.fetch_history().finally(() => dishy.close());
        },
        getLocation: {
            request: { getLocation: {} },
            reason: 'Skipped: Starlink policy disables local GetLocation requests on current firmware.',
        },
        location: {
            request: { fetch_location: {} },
            reason: 'Skipped: Starlink policy disables local GetLocation requests on current firmware.',
        },
        dishGetObstructionMap: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ dishGetObstructionMap: {} }).finally(() => dishy.close());
        },
        obstructionMap: async () => {
            const dishy = getDishy(req);
            return dishy.fetch_obstruction_map().finally(() => dishy.close());
        },
        dishGetContext: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ dishGetContext: {} }).finally(() => dishy.close());
        },
        getDeviceInfo: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getDeviceInfo: {} }).finally(() => dishy.close());
        },
        getNetworkInterfaces: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getNetworkInterfaces: {} }).finally(() => dishy.close());
        },
        getPing: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getPing: {} }).finally(() => dishy.close());
        },
        getNextId: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getNextId: {} }).finally(() => dishy.close());
        },
        getLog: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getLog: {} }).finally(() => dishy.close());
        },
        getHeapDump: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ getHeapDump: {} }).finally(() => dishy.close());
        },
        transceiverGetStatus: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ transceiverGetStatus: {} }).finally(() => dishy.close());
        },
        transceiverGetTelemetry: async () => {
            const dishy = getDishy(req);
            return dishy['handle']({ transceiverGetTelemetry: {} }).finally(() => dishy.close());
        },
        transceiverIfLoopbackTest: {
            request: { transceiverIfLoopbackTest: {} },
            reason: 'Skipped: active test endpoint, not suitable for automatic dump execution.',
        },
        dishAuthenticate: {
            request: { dishAuthenticate: {} },
            reason: 'Skipped: authentication flow not implemented for automatic dump execution.',
        },
        dishEmc: {
            request: { dishEmc: {} },
            reason: 'Skipped: EMC control endpoint is undocumented for safe automatic probing.',
        },
        reboot: {
            request: { reboot: {} },
            reason: 'Skipped: destructive action.',
        },
        dishStow: {
            request: { dishStow: {} },
            reason: 'Skipped: destructive state-changing action.',
        },
        update: {
            request: { update: {} },
            reason: 'Skipped: state-changing action.',
        },
        restartControl: {
            request: { restartControl: {} },
            reason: 'Skipped: state-changing action.',
        },
        factoryReset: {
            request: { factoryReset: {} },
            reason: 'Skipped: destructive action.',
        },
        enableFlow: {
            request: { enableFlow: {} },
            reason: 'Skipped: state-changing action.',
        },
        fuse: {
            request: { fuse: {} },
            reason: 'Skipped: state-changing action.',
        },
        setSku: {
            request: { setSku: {} },
            reason: 'Skipped: state-changing action.',
        },
        setTrustedKeys: {
            request: { setTrustedKeys: {} },
            reason: 'Skipped: security-sensitive state-changing action.',
        },
        pingHost: {
            request: { pingHost: { address: '' } },
            reason: 'Skipped: requires a target host.',
        },
    };
    res.json({ ok: true, data: await collectResults(specs) });
});

app.post('/api/dishy/reboot', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.reboot().finally(() => dishy.close()));
});

app.post('/api/dishy/stow', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.stow().finally(() => dishy.close()));
});

app.post('/api/dishy/unstow', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.unstow().finally(() => dishy.close()));
});

// ── WiFi Router routes ────────────────────────────────────────────────────────

app.get('/api/router/diagnostics', async (req, res) => {
    if (BYPASS_MODE) {
        return res.json({ ok: true, data: { _source: 'bypass', _note: 'Router diagnostics not available in bypass mode' } });
    }
    const router = getRouter(req);
    handle(res, () => router.fetch_diagnostics().finally(() => router.close()));
});

app.get('/api/router/status', async (req, res) => {
    if (BYPASS_MODE && OPENWRT_FILL_ROUTER_BLANKS) {
        return handle(res, async () => {
            const s = await getOpenwrtRouterSummary(owrtConfig());
            return {
                deviceState:   { uptimeS: s.uptimeSeconds },
                ipv4WanAddress: s.wanIp,
                deviceInfo:    { id: s.id, hardwareVersion: s.hardwareVersion, softwareVersion: s.softwareVersion },
                serialNumber:  s.id,
                _source:       'openwrt',
            };
        });
    }
    if (BYPASS_MODE) return res.json({ ok: true, data: { _source: 'bypass' } });
    const router = getRouter(req);
    handle(res, () => router['handle']({ getStatus: {} })
        .then(r => {
            if (!r.wifiGetStatus) throw new Error('No status returned');
            return r.wifiGetStatus;
        })
        .finally(() => router.close())
    );
});

app.get('/api/router/clients', async (req, res) => {
    if (BYPASS_MODE && OPENWRT_FILL_ROUTER_BLANKS) {
        return handle(res, () => getOpenwrtClients(owrtConfig()));
    }
    if (BYPASS_MODE) return res.json({ ok: true, data: { clients: [], _source: 'bypass' } });
    const router = getRouter(req);
    handle(res, () => router['handle']({ wifiGetClients: {} })
        .then(r => {
            if (!r.wifiGetClients) throw new Error('No client data returned');
            return r.wifiGetClients;
        })
        .finally(() => router.close())
    );
});

app.get('/api/router/networks', async (req, res) => {
    if (BYPASS_MODE && OPENWRT_FILL_ROUTER_BLANKS) {
        return handle(res, async () => {
            const s = await getOpenwrtRouterSummary(owrtConfig());
            return {
                id: s.id,
                hardwareVersion: s.hardwareVersion,
                softwareVersion: s.softwareVersion,
                networks: [{
                    ipv4: s.lanIpv4,
                    ipv6: [],
                    clientsEthernet: s.clientsEthernet,
                    clients2ghz:     s.clients2ghz,
                    clients5ghz:     s.clients5ghz,
                }],
                _source: 'openwrt',
            };
        });
    }
    if (BYPASS_MODE) return res.json({ ok: true, data: { networks: [], _source: 'bypass' } });
    // wifiGetDiagnostics v1 is not implemented on current firmware;
    // use the v2 diagnostics which includes LAN network info.
    const router = getRouter(req);
    handle(res, () => router.fetch_diagnostics().finally(() => router.close()));
});

app.get('/api/router/config', (req, res) => {
    const router = getRouter(req);
    handle(res, () => router['handle']({ wifiGetConfig: {} })
        .then(r => unwrapResponse(r, 'wifiGetConfig'))
        .finally(() => router.close())
    );
});

app.get('/api/router/history', (req, res) => {
    const router = getRouter(req);
    handle(res, () => router['handle']({ getHistory: {} })
        .then(r => unwrapResponse(r, 'dishGetHistory'))
        .finally(() => router.close())
    );
});

app.get('/api/router/ping-metrics', async (req, res) => {
    if (BYPASS_MODE) return res.json({ ok: true, data: { results: [], _source: 'bypass' } });
    const router = getRouter(req);
    handle(res, () => router['handle']({ getPing: {} })
        .then(r => unwrapResponse(r, 'getPing'))
        .finally(() => router.close())
    );
});

app.get('/api/router/device-info', (req, res) => {
    const router = getRouter(req);
    handle(res, () => router['handle']({ getDeviceInfo: {} })
        .then(r => unwrapResponse(r, 'deviceInfo'))
        .finally(() => router.close())
    );
});

app.get('/api/router/interfaces', async (req, res) => {
    if (BYPASS_MODE && OPENWRT_FILL_ROUTER_BLANKS) {
        return handle(res, () => getOpenwrtInterfaces(owrtConfig()));
    }
    if (BYPASS_MODE) return res.json({ ok: true, data: { networkInterfaces: [], _source: 'bypass' } });
    const router = getRouter(req);
    handle(res, () => router['handle']({ getNetworkInterfaces: {} })
        .then(r => unwrapResponse(r, 'networkInterfaces'))
        .finally(() => router.close())
    );
});

app.get('/api/router/dump', async (req, res) => {
    const specs = {
        diagnostics: async () => {
            const router = getRouter(req);
            return router.fetch_diagnostics().finally(() => router.close());
        },
        status: async () => {
            const router = getRouter(req);
            return router['handle']({ getStatus: {} })
                .then(r => {
                    if (!r.wifiGetStatus) throw new Error('No status returned');
                    return r.wifiGetStatus;
                })
                .finally(() => router.close());
        },
        clients: async () => {
            const router = getRouter(req);
            return router['handle']({ wifiGetClients: {} })
                .then(r => {
                    if (!r.wifiGetClients) throw new Error('No client data returned');
                    return r.wifiGetClients;
                })
                .finally(() => router.close());
        },
        networks: async () => {
            const router = getRouter(req);
            return router.fetch_diagnostics().finally(() => router.close());
        },
        config: async () => {
            const router = getRouter(req);
            return router['handle']({ wifiGetConfig: {} })
                .then(r => unwrapResponse(r, 'wifiGetConfig'))
                .finally(() => router.close());
        },
        history: async () => {
            const router = getRouter(req);
            return router['handle']({ getHistory: {} })
                .then(r => unwrapResponse(r, 'dishGetHistory'))
                .finally(() => router.close());
        },
        pingMetrics: async () => {
            const router = getRouter(req);
            return router['handle']({ wifiGetPingMetrics: {} })
                .then(r => unwrapResponse(r, 'wifiGetPingMetrics'))
                .finally(() => router.close());
        },
        deviceInfo: async () => {
            const router = getRouter(req);
            return router['handle']({ getDeviceInfo: {} })
                .then(r => unwrapResponse(r, 'deviceInfo'))
                .finally(() => router.close());
        },
        interfaces: async () => {
            const router = getRouter(req);
            return router['handle']({ getNetworkInterfaces: {} })
                .then(r => unwrapResponse(r, 'networkInterfaces'))
                .finally(() => router.close());
        },
        wifiGetDiagnostics: async () => {
            const router = getRouter(req);
            return router['handle']({ wifiGetDiagnostics: {} }).finally(() => router.close());
        },
        wifiGetDiagnostics2: async () => {
            const router = getRouter(req);
            return router['handle']({ wifiGetDiagnostics2: {} }).finally(() => router.close());
        },
        wifiGetHistory: async () => {
            const router = getRouter(req);
            return router['handle']({ wifiGetHistory: {} }).finally(() => router.close());
        },
        getLocation: {
            request: { getLocation: {} },
            reason: 'Skipped: Starlink policy disables local GetLocation requests on current firmware.',
        },
        getLog: async () => {
            const router = getRouter(req);
            return router['handle']({ getLog: {} }).finally(() => router.close());
        },
        getHeapDump: async () => {
            const router = getRouter(req);
            return router['handle']({ getHeapDump: {} }).finally(() => router.close());
        },
        getNextId: async () => {
            const router = getRouter(req);
            return router['handle']({ getNextId: {} }).finally(() => router.close());
        },
        getPing: async () => {
            const router = getRouter(req);
            return router['handle']({ getPing: {} }).finally(() => router.close());
        },
        statusRaw: async () => {
            const router = getRouter(req);
            return router['handle']({ getStatus: {} }).finally(() => router.close());
        },
        getDeviceInfoRaw: async () => {
            const router = getRouter(req);
            return router['handle']({ getDeviceInfo: {} }).finally(() => router.close());
        },
        getNetworkInterfacesRaw: async () => {
            const router = getRouter(req);
            return router['handle']({ getNetworkInterfaces: {} }).finally(() => router.close());
        },
        wifiAuthenticate: {
            request: { wifiAuthenticate: {} },
            reason: 'Skipped: authentication flow not implemented for automatic dump execution.',
        },
        wifiSetConfig: {
            request: { wifiSetConfig: {} },
            reason: 'Skipped: state-changing action.',
        },
        wifiSetup: {
            request: { wifiSetup: {} },
            reason: 'Skipped: setup/state-changing action.',
        },
        reboot: {
            request: { reboot: {} },
            reason: 'Skipped: destructive action.',
        },
        update: {
            request: { update: {} },
            reason: 'Skipped: state-changing action.',
        },
        restartControl: {
            request: { restartControl: {} },
            reason: 'Skipped: state-changing action.',
        },
        factoryReset: {
            request: { factoryReset: {} },
            reason: 'Skipped: destructive action.',
        },
        enableFlow: {
            request: { enableFlow: {} },
            reason: 'Skipped: state-changing action.',
        },
        fuse: {
            request: { fuse: {} },
            reason: 'Skipped: state-changing action.',
        },
        setSku: {
            request: { setSku: {} },
            reason: 'Skipped: state-changing action.',
        },
        setTrustedKeys: {
            request: { setTrustedKeys: {} },
            reason: 'Skipped: security-sensitive state-changing action.',
        },
        pingHost: {
            request: { pingHost: { address: '' } },
            reason: 'Skipped: requires a target host.',
        },
    };
    res.json({ ok: true, data: await collectResults(specs) });
});

// ── Normalized router summary (Starlink | bypass placeholder | OpenWrt) ───────

const PH = '—';

function bypassPlaceholder() {
    return {
        provider: 'bypass',
        id: PH, hardwareVersion: PH, softwareVersion: PH, countryCode: PH,
        wanIp: PH, lanIpv4: PH, lanIpv6Count: 0,
        uptime: PH, uptimeSeconds: 0,
        totalClients: 0, clientsEthernet: 0, clients2ghz: 0, clients5ghz: 0,
        statCards: { wan: PH, uptime: PH, clients: '0', bands: '0 / 0 / 0' },
        error: null,
    };
}

app.get('/api/router/summary', async (req, res) => {
    const bypass = BYPASS_MODE || req.query.bypass === '1' || req.query.bypass === 'true';

    if (bypass && OPENWRT_FILL_ROUTER_BLANKS) {
        const summary = await getOpenwrtRouterSummary({
            protocol: OPENWRT_PROTOCOL,
            host: OPENWRT_HOST,
            username: OPENWRT_USERNAME,
            password: OPENWRT_PASSWORD,
        }).catch(e => ({ ...bypassPlaceholder(), provider: 'openwrt', error: e.message }));
        return res.json({ ok: true, data: summary });
    }

    if (bypass) {
        return res.json({ ok: true, data: bypassPlaceholder() });
    }

    // Normal mode: normalize Starlink router data into the shared shape
    const r1 = getRouter(req);
    const r2 = getRouter(req);
    const r3 = getRouter(req);
    try {
        const [sr, nr, cr] = await Promise.allSettled([
            r1['handle']({ getStatus: {} })
                .then(r => r.wifiGetStatus || {})
                .finally(() => r1.close()),
            r2.fetch_diagnostics()
                .finally(() => r2.close()),
            r3['handle']({ wifiGetClients: {} })
                .then(r => r.wifiGetClients || {})
                .finally(() => r3.close()),
        ]);

        const routerStatus   = sr.status === 'fulfilled' ? sr.value : {};
        const routerNetworks = nr.status === 'fulfilled' ? nr.value : {};
        const routerClients  = cr.status === 'fulfilled' ? cr.value : {};

        const routerDev = routerStatus.deviceState || {};
        const networks  = routerNetworks.networks  || [];
        const clients   = Array.isArray(routerClients.clients) ? routerClients.clients : [];
        const firstLan  = networks[0] || {};

        const uptimeSeconds   = routerDev.uptimeS ?? 0;
        const uptime          = uptimeSeconds > 0 ? fmtUptime(uptimeSeconds) : PH;
        const wanIp           = routerStatus.ipv4WanAddress ?? PH;
        const totalClients    = clients.length;
        const eth             = firstLan.clientsEthernet ?? clients.filter(c => c.iface === 1).length;
        const g2              = firstLan.clients2ghz     ?? clients.filter(c => c.iface === 2).length;
        const g5              = firstLan.clients5ghz     ?? clients.filter(c => c.iface === 3).length;
        const id              = routerStatus.deviceInfo?.id              ?? routerNetworks.id             ?? PH;
        const hardwareVersion = routerStatus.deviceInfo?.hardwareVersion ?? routerNetworks.hardwareVersion ?? PH;
        const softwareVersion = routerStatus.deviceInfo?.softwareVersion ?? routerNetworks.softwareVersion ?? PH;
        const countryCode     = routerStatus.deviceInfo?.countryCode     ?? PH;
        const lanIpv4         = firstLan.ipv4 ?? PH;
        const lanIpv6Count    = Array.isArray(firstLan.ipv6) ? firstLan.ipv6.length : 0;

        res.json({
            ok: true,
            data: {
                provider: 'starlink',
                id, hardwareVersion, softwareVersion, countryCode,
                wanIp, lanIpv4, lanIpv6Count,
                uptime, uptimeSeconds,
                totalClients, clientsEthernet: eth, clients2ghz: g2, clients5ghz: g5,
                statCards: {
                    wan:     wanIp,
                    uptime,
                    clients: String(totalClients),
                    bands:   `${g2} / ${g5} / ${eth}`,
                },
                error: null,
            },
        });
    } catch (e) {
        res.status(500).json({ ok: false, error: e.message || String(e) });
    }
});

// ── OpenWrt debug routes ──────────────────────────────────────────────────────

function owrtHandle(res, fn) {
    fn().then(data => res.json({ ok: true, data }))
        .catch(e => res.status(500).json({ ok: false, error: e.message || String(e) }));
}

app.get('/api/openwrt/status', (req, res) => {
    owrtHandle(res, () => getOpenwrtRouterSummary({
        protocol: OPENWRT_PROTOCOL,
        host: req.query.host || OPENWRT_HOST,
        username: OPENWRT_USERNAME,
        password: OPENWRT_PASSWORD,
    }));
});

app.get('/api/openwrt/interfaces', (req, res) => {
    owrtHandle(res, async () => {
        const summary = await getOpenwrtRouterSummary({
            protocol: OPENWRT_PROTOCOL,
            host: req.query.host || OPENWRT_HOST,
            username: OPENWRT_USERNAME,
            password: OPENWRT_PASSWORD,
        });
        return { wan: summary.raw?.wan ?? null, lan: summary.raw?.lan ?? null };
    });
});

app.get('/api/openwrt/clients', (req, res) => {
    owrtHandle(res, async () => {
        const summary = await getOpenwrtRouterSummary({
            protocol: OPENWRT_PROTOCOL,
            host: req.query.host || OPENWRT_HOST,
            username: OPENWRT_USERNAME,
            password: OPENWRT_PASSWORD,
        });
        return {
            totalClients:    summary.totalClients,
            clientsEthernet: summary.clientsEthernet,
            clients2ghz:     summary.clients2ghz,
            clients5ghz:     summary.clients5ghz,
            leases:          summary.raw?.leases ?? null,
        };
    });
});

// ── Config endpoint (returns active defaults for the frontend) ────────────────

app.get('/api/config', (_req, res) => {
    res.json({
        dishHost:   DEFAULT_DISH_HOST,
        dishPort:   DEFAULT_DISH_PORT,
        routerHost: DEFAULT_ROUTER_HOST,
        routerPort: DEFAULT_ROUTER_PORT,
        bypassMode:              BYPASS_MODE,
        openwrtFillRouterBlanks: OPENWRT_FILL_ROUTER_BLANKS,
    });
});

// ── Serve SPA — inject HA ingress base path so frontend fetch() calls work ────

function serveIndex(req, res) {
    // HA Supervisor sets X-Ingress-Path to the prefix it proxies under,
    // e.g. /api/hassio_ingress/abc123. The browser needs this to build correct URLs.
    const base = req.headers['x-ingress-path'] || '';
    const html = INDEX_HTML.replace(
        '</head>',
        `<script>window.__BASE__=${JSON.stringify(base)};</script></head>`
    );
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.send(html);
}

function serveSimplePage(html) {
    return (req, res) => {
        const base = req.headers['x-ingress-path'] || '';
        const out  = html.replace(
            '</head>',
            `<script>window.__BASE__=${JSON.stringify(base)};</script></head>`
        );
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        res.send(out);
    };
}

app.get('/obstruction', serveSimplePage(OBSTRUCTION_HTML));
app.get('/alignment',   serveSimplePage(ALIGNMENT_HTML));
app.get('/combined', (_req, res) => {
    res.status(410).type('text/plain; charset=utf-8').send(
        'The combined Lovelace iframe page has moved to the native Starlink custom integration.'
    );
});

const SIMPLE_PAGES = { obstruction: OBSTRUCTION_HTML, alignment: ALIGNMENT_HTML };

app.get('/', (req, res, next) => {
    if (req.query.p === 'combined') {
        return res.status(410).type('text/plain; charset=utf-8').send(
            'The combined Lovelace iframe page has moved to the native Starlink custom integration.'
        );
    }
    const page = SIMPLE_PAGES[req.query.p];
    if (page) return serveSimplePage(page)(req, res);
    next();
});

app.get('/', serveIndex);
app.get('/{*path}', serveIndex);

app.listen(PORT, () => {
    console.log(`Starlink GUI running at http://localhost:${PORT}`);
});
