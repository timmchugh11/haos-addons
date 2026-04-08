import { createVanScene } from './van-scene.js';

const APP_CONFIG = window.__APP_CONFIG__ || {};
const BASE = window.__BASE__ || '';
const LOCAL_MODEL_HOSTNAME = '192.168.1.10';
const REMOTE_MODEL_URL = 'https://www.tmch.me/static/van.glb';

const demoConfig = {
  type: 'custom:van-power-card',
  ...APP_CONFIG.entityMap,
};

let currentPage = 'dashboard';
let scene;
let refreshTimer = 0;

function apiUrl(path) {
  return `${BASE}${path}`;
}

function resolveModelUrl() {
  return window.location.hostname === LOCAL_MODEL_HOSTNAME
    ? `${BASE}/van.glb`
    : REMOTE_MODEL_URL;
}

function fmtMetric(sensor, fallbackUnit = '') {
  if (!sensor || !sensor.ok) return '—';
  const unit = sensor.unit || fallbackUnit;
  return `${sensor.state}${unit}`;
}

function buildSceneLabels(data) {
  return {
    solar: {
      title: 'SOLAR',
      lines: [
        fmtMetric(data.groups.solar?.watt, 'W'),
        fmtMetric(data.groups.solar?.amp, 'A'),
        fmtMetric(data.groups.solar?.voltage, 'V'),
      ],
    },
    grid: {
      title: 'HOOKUP',
      lines: [
        fmtMetric(data.groups.grid?.watt, 'W'),
        fmtMetric(data.groups.grid?.amp, 'A'),
        fmtMetric(data.groups.grid?.voltage, 'V'),
      ],
    },
    alternator: {
      title: 'ALTERNATOR',
      lines: [
        fmtMetric(data.groups.alternator?.watt, 'W'),
        fmtMetric(data.groups.alternator?.amp, 'A'),
        fmtMetric(data.groups.alternator?.voltage, 'V'),
      ],
    },
    battery: {
      title: 'BATTERY',
      lines: [
        data.groups.battery?.percent?.ok ? `${data.groups.battery.percent.state}%` : '—',
        fmtMetric(data.groups.battery?.amp, 'A'),
        fmtMetric(data.groups.battery?.voltage, 'V'),
      ],
    },
  };
}

function updateMetricBlock(idPrefix, group) {
  const voltageEl = document.getElementById(`${idPrefix}-voltage`);
  const ampEl = document.getElementById(`${idPrefix}-amp`);
  const wattEl = document.getElementById(`${idPrefix}-watt`);

  if (voltageEl) voltageEl.textContent = fmtMetric(group?.voltage, 'V');
  if (ampEl) ampEl.textContent = fmtMetric(group?.amp, 'A');
  if (wattEl) wattEl.textContent = fmtMetric(group?.watt, 'W');
}

function updateConnection(ok) {
  const badge = document.getElementById('conn-status');
  badge.className = `conn-badge ${ok ? 'ok' : 'err'}`;
  badge.textContent = ok ? 'Live' : 'Sensor Error';
}

function showPage(page) {
  currentPage = page;
  document.querySelectorAll('.page').forEach((node) => node.classList.toggle('active', node.dataset.page === page));
  document.querySelectorAll('.nav-link').forEach((node) => node.classList.toggle('active', node.dataset.page === page));
}

async function fetchSnapshot() {
  const response = await fetch(apiUrl('/api/van/snapshot'));
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || 'Failed to load snapshot');
  }
  return payload.data;
}

function updateRawTable(sensors) {
  const rows = Object.values(sensors).map((sensor) => {
    const state = sensor.ok ? sensor.state : 'error';
    const unit = sensor.ok ? (sensor.unit || '—') : '—';
    const updated = sensor.ok ? new Date(sensor.last_updated).toLocaleTimeString() : '—';
    const detail = sensor.ok ? (sensor.friendly_name || sensor.entity_id) : sensor.error;
    return `<tr>
      <td>${sensor.entity_id}</td>
      <td>${detail}</td>
      <td>${state}</td>
      <td>${unit}</td>
      <td>${updated}</td>
    </tr>`;
  }).join('');
  document.getElementById('raw-table').innerHTML = `<table class="tbl">
    <thead><tr><th>Entity</th><th>Label</th><th>State</th><th>Unit</th><th>Updated</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function updateDemoYaml() {
  document.getElementById('yaml-snippet').textContent = [
    'type: custom:van-power-card',
    ...Object.entries(demoConfig)
      .filter(([key]) => key !== 'type')
      .map(([key, value]) => `${key}: ${value}`),
  ].join('\n');
}

async function refresh() {
  try {
    const data = await fetchSnapshot();
    updateMetricBlock('solar', data.groups.solar);
    updateMetricBlock('grid', data.groups.grid);
    updateMetricBlock('alternator', data.groups.alternator);
    updateMetricBlock('battery', data.groups.battery);

    const percent = data.groups.battery?.percent;
    document.getElementById('battery-percent-chip').textContent = percent?.ok ? `${percent.state}%` : 'Offline';
    document.getElementById('hero-title').textContent = data.title;
    document.getElementById('last-updated').textContent = `Updated ${new Date(data.fetchedAt).toLocaleTimeString()}`;
    document.getElementById('stat-solar').textContent = fmtMetric(data.groups.solar?.watt, 'W');
    document.getElementById('stat-grid').textContent = fmtMetric(data.groups.grid?.watt, 'W');
    document.getElementById('stat-alternator').textContent = fmtMetric(data.groups.alternator?.watt, 'W');
    document.getElementById('stat-battery').textContent = fmtMetric(data.groups.battery?.watt, 'W');
    scene?.setLabels?.(buildSceneLabels(data));
    updateRawTable(data.sensors);
    updateConnection(Object.values(data.sensors).some((sensor) => sensor.ok));
  } catch (error) {
    updateConnection(false);
    document.getElementById('last-updated').textContent = error.message;
  }
}

function startAutoRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = window.setInterval(refresh, (APP_CONFIG.refreshSeconds || 5) * 1000);
}

function initNav() {
  document.querySelectorAll('.nav-link[data-page]').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      const page = link.dataset.page;
      if (page) showPage(page);
    });
  });
}

function initScene() {
  scene = createVanScene(document.getElementById('stage-canvas'), {
    modelUrl: resolveModelUrl(),
    interactive: true,
    autoRotate: true,
    autoRotateSpeed: 0.18,
    labelsSpinWithModel: false,
  });
}

function init() {
  document.getElementById('app-title').textContent = APP_CONFIG.title || 'Van Power';
  document.getElementById('hero-title').textContent = APP_CONFIG.title || 'Van Power';
  document.getElementById('refresh-pill').textContent = `${APP_CONFIG.refreshSeconds || 5}s refresh`;
  document.getElementById('resource-url').textContent = `${window.location.origin}${BASE}/van-power-card.js`;
  updateDemoYaml();
  initNav();
  initScene();
  showPage('dashboard');
  refresh();
  startAutoRefresh();
}

window.addEventListener('beforeunload', () => {
  clearInterval(refreshTimer);
  scene?.destroy();
});

init();
