'use strict';

const express = require('express');
const cors = require('cors');
const fs    = require('fs');
const path = require('path');
const { Dishy } = require('@gibme/starlink');
const { WiFiRouter } = require('@gibme/starlink');

const app = express();
const PORT = process.env.PORT || 3000;

// Defaults — overridden by HA add-on options (exported by run.sh via bashio)
const DEFAULT_DISH_HOST   = process.env.DISH_HOST   || '192.168.100.1';
const DEFAULT_DISH_PORT   = parseInt(process.env.DISH_PORT   || '9200', 10);
const DEFAULT_ROUTER_HOST = process.env.ROUTER_HOST || '192.168.1.1';
const DEFAULT_ROUTER_PORT = parseInt(process.env.ROUTER_PORT || '9000', 10);

// Read index.html once at startup for ingress-path injection
const INDEX_HTML = fs.readFileSync(path.join(__dirname, 'public', 'index.html'), 'utf8');

app.use(cors());
app.use(express.json());
// Serve static assets (css, js, images etc.) but NOT index.html — we inject the base path ourselves
app.use(express.static(path.join(__dirname, 'public'), { index: false }));

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

app.get('/api/dishy/location', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.fetch_location().finally(() => dishy.close()));
});

app.get('/api/dishy/obstruction-map', (req, res) => {
    const dishy = getDishy(req);
    handle(res, () => dishy.fetch_obstruction_map().finally(() => dishy.close()));
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

app.get('/api/router/diagnostics', (req, res) => {
    const router = getRouter(req);
    handle(res, () => router.fetch_diagnostics().finally(() => router.close()));
});

// ── Config endpoint (returns active defaults for the frontend) ────────────────

app.get('/api/config', (_req, res) => {
    res.json({
        dishHost:   DEFAULT_DISH_HOST,
        dishPort:   DEFAULT_DISH_PORT,
        routerHost: DEFAULT_ROUTER_HOST,
        routerPort: DEFAULT_ROUTER_PORT,
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

app.get('/', serveIndex);
app.get('/{*path}', serveIndex);

app.listen(PORT, () => {
    console.log(`Starlink GUI running at http://localhost:${PORT}`);
});
