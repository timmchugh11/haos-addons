'use strict';

const express = require('express');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = parseInt(process.env.PORT || '3050', 10);
const CORE_API_BASE = 'http://supervisor/core/api';

const INDEX_HTML = fs.readFileSync(path.join(__dirname, 'public', 'index.html'), 'utf8');

const ENTITY_MAP = {
  solar_voltage: process.env.SOLAR_VOLTAGE || 'sensor.epever_pv_voltage',
  solar_amp: process.env.SOLAR_AMP || 'sensor.epever_pv_current',
  solar_watt: process.env.SOLAR_WATT || 'sensor.epever_pv_power',
  battery_voltage: process.env.BATTERY_VOLTAGE || 'sensor.epever_battery_voltage',
  battery_amp: process.env.BATTERY_AMP || 'sensor.battery_current',
  battery_watt: process.env.BATTERY_WATT || 'sensor.battery_wattage',
  grid_voltage: process.env.GRID_VOLTAGE || 'sensor.charger_hookup_voltage',
  grid_amp: process.env.GRID_AMP || 'sensor.charger_hookup_current',
  grid_watt: process.env.GRID_WATT || 'sensor.charger_hookup_power',
  alternator_voltage: process.env.ALTERNATOR_VOLTAGE || 'sensor.charger_alternator_voltage',
  alternator_amp: process.env.ALTERNATOR_AMP || 'sensor.charger_alternator_current',
  alternator_watt: process.env.ALTERNATOR_WATT || 'sensor.charger_alternator_power',
  battery_percent: process.env.BATTERY_PERCENT || 'sensor.battery_percentage',
};

const APP_CONFIG = {
  title: process.env.TITLE || 'Van Power',
  refreshSeconds: Math.max(1, parseInt(process.env.REFRESH_SECONDS || '5', 10) || 5),
  modelUrl: './van.glb',
  entityMap: ENTITY_MAP,
};

app.use(express.json());
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  if (req.method === 'OPTIONS') {
    res.status(204).end();
    return;
  }
  next();
});

app.get('/vendor/three/build/three.core.js', (_req, res) => {
  res.sendFile(path.join(__dirname, 'node_modules', 'three', 'build', 'three.core.js'));
});
app.use(express.static(path.join(__dirname, 'public'), { index: false }));

function injectBase(html, req) {
  const base = req.headers['x-ingress-path'] || '';
  return html.replace(
    '</head>',
    `<script>window.__BASE__=${JSON.stringify(base)};window.__APP_CONFIG__=${JSON.stringify(APP_CONFIG)};</script></head>`
  );
}

function parseNumber(value) {
  if (value === null || value === undefined) return null;
  const normalized = String(value).trim().replace(/,/g, '');
  if (!normalized || normalized === 'unknown' || normalized === 'unavailable') return null;
  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

async function fetchEntityState(entityId) {
  const token = process.env.SUPERVISOR_TOKEN;
  if (!token) {
    throw new Error('SUPERVISOR_TOKEN is not available. Enable Home Assistant API access for this add-on.');
  }

  const response = await fetch(`${CORE_API_BASE}/states/${encodeURIComponent(entityId)}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Failed to load ${entityId}: ${response.status} ${detail}`.trim());
  }

  const payload = await response.json();
  return {
    entity_id: payload.entity_id,
    state: payload.state,
    unit: payload.attributes?.unit_of_measurement || '',
    friendly_name: payload.attributes?.friendly_name || payload.entity_id,
    value: parseNumber(payload.state),
    last_changed: payload.last_changed,
    last_updated: payload.last_updated,
  };
}

async function buildSnapshot() {
  const entries = await Promise.all(
    Object.entries(ENTITY_MAP).map(async ([key, entityId]) => {
      try {
        return [key, { ok: true, ...await fetchEntityState(entityId) }];
      } catch (error) {
        return [key, { ok: false, entity_id: entityId, error: error.message }];
      }
    })
  );

  const sensors = Object.fromEntries(entries);
  return {
    title: APP_CONFIG.title,
    refreshSeconds: APP_CONFIG.refreshSeconds,
    modelUrl: APP_CONFIG.modelUrl,
    entityMap: ENTITY_MAP,
    sensors,
    groups: {
      solar: {
        voltage: sensors.solar_voltage,
        amp: sensors.solar_amp,
        watt: sensors.solar_watt,
      },
      grid: {
        voltage: sensors.grid_voltage,
        amp: sensors.grid_amp,
        watt: sensors.grid_watt,
      },
      alternator: {
        voltage: sensors.alternator_voltage,
        amp: sensors.alternator_amp,
        watt: sensors.alternator_watt,
      },
      battery: {
        voltage: sensors.battery_voltage,
        amp: sensors.battery_amp,
        watt: sensors.battery_watt,
        percent: sensors.battery_percent,
      },
    },
    fetchedAt: new Date().toISOString(),
  };
}

app.get('/api/config', (_req, res) => {
  res.json(APP_CONFIG);
});

app.get('/api/van/snapshot', async (_req, res) => {
  try {
    res.json({ ok: true, data: await buildSnapshot() });
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message || String(error) });
  }
});

app.get('/api/van/card-example', (_req, res) => {
  res.type('text/plain; charset=utf-8').send([
    'type: custom:van-power-card',
    `solar_voltage: ${ENTITY_MAP.solar_voltage}`,
    `solar_amp: ${ENTITY_MAP.solar_amp}`,
    `solar_watt: ${ENTITY_MAP.solar_watt}`,
    `battery_voltage: ${ENTITY_MAP.battery_voltage}`,
    `battery_amp: ${ENTITY_MAP.battery_amp}`,
    `battery_watt: ${ENTITY_MAP.battery_watt}`,
    `grid_voltage: ${ENTITY_MAP.grid_voltage}`,
    `grid_amp: ${ENTITY_MAP.grid_amp}`,
    `grid_watt: ${ENTITY_MAP.grid_watt}`,
    `alternator_voltage: ${ENTITY_MAP.alternator_voltage}`,
    `alternator_amp: ${ENTITY_MAP.alternator_amp}`,
    `alternator_watt: ${ENTITY_MAP.alternator_watt}`,
    `battery_percent: ${ENTITY_MAP.battery_percent}`,
  ].join('\n'));
});

app.get('/favicon.ico', (_req, res) => {
  res.status(204).end();
});

function serveIndex(req, res) {
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.send(injectBase(INDEX_HTML, req));
}

app.get('/', serveIndex);

app.get('/{*path}', (req, res, next) => {
  if (path.extname(req.path)) {
    next();
    return;
  }
  const acceptsHtml = req.accepts(['html', 'json']) === 'html';
  if (!acceptsHtml) {
    next();
    return;
  }
  serveIndex(req, res);
});

app.listen(PORT, () => {
  console.log(`Van Power 3D running at http://localhost:${PORT}`);
});
