import { createVanScene } from './van-scene.js';

const DEFAULT_CONFIG = {
  solar_voltage: 'sensor.epever_pv_voltage',
  solar_amp: 'sensor.epever_pv_current',
  solar_watt: 'sensor.epever_pv_power',
  battery_voltage: 'sensor.epever_battery_voltage',
  battery_amp: 'sensor.battery_current',
  battery_watt: 'sensor.battery_wattage',
  grid_voltage: 'sensor.charger_hookup_voltage',
  grid_amp: 'sensor.charger_hookup_current',
  grid_watt: 'sensor.charger_hookup_power',
  alternator_voltage: 'sensor.charger_alternator_voltage',
  alternator_amp: 'sensor.charger_alternator_current',
  alternator_watt: 'sensor.charger_alternator_power',
  battery_percent: 'sensor.battery_percentage',
};

class VanPowerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = { ...DEFAULT_CONFIG };
    this._scene = null;
    this._elements = {};
  }

  setConfig(config) {
    this._config = { ...DEFAULT_CONFIG, ...(config || {}) };
    if (!this.shadowRoot.innerHTML) {
      this.render();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot.innerHTML) {
      this.render();
    }
    this.update();
  }

  getCardSize() {
    return 6;
  }

  disconnectedCallback() {
    this._scene?.destroy();
  }

  lookup(entityId) {
    return this._hass?.states?.[entityId];
  }

  format(entityId, fallbackUnit = '') {
    const state = this.lookup(entityId);
    if (!state) return '—';
    const unit = state.attributes?.unit_of_measurement || fallbackUnit;
    return `${state.state}${unit}`;
  }

  updateMetric(prefix, voltageId, ampId, wattId) {
    this._elements[`${prefix}-voltage`].textContent = this.format(voltageId, 'V');
    this._elements[`${prefix}-amp`].textContent = this.format(ampId, 'A');
    this._elements[`${prefix}-watt`].textContent = this.format(wattId, 'W');
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        *{box-sizing:border-box}
        :host{
          display:block;
          height:100%;
          min-height:100%;
        }
        ha-card{
          height:100%;
          min-height:calc(100vh - 32px);
          display:flex;
          flex-direction:column;
          overflow:hidden;
          border-radius:20px;
          background:transparent;
          box-shadow:none;
          color:#f5f7fa;
        }
        .wrap{
          padding:0;
          flex:1;
          display:flex;
          min-height:0;
        }
        .stage{
          position:relative;
          flex:1;
          min-height:620px;
          height:100%;
          width:100%;
          border:none;
          border-radius:18px;
          overflow:hidden;
          background:transparent;
        }
        .canvas{position:absolute;inset:0;touch-action:none}
        .canvas canvas{width:100%;height:100%;display:block}
        .overlay{
          position:relative;
          z-index:1;
          min-height:100%;
          height:100%;
          pointer-events:none;
          font-family:Inter,system-ui,sans-serif;
        }
        .label{
          position:absolute;
          display:flex;
          flex-direction:column;
          gap:4px;
          font-weight:800;
          letter-spacing:-0.02em;
          text-shadow:0 2px 20px rgba(0,0,0,0.55);
        }
        .label span{font-size:clamp(1rem, 2.2vw, 1.9rem)}
        .label small{
          font-size:0.72rem;
          font-weight:600;
          letter-spacing:0.12em;
          text-transform:uppercase;
          color:rgba(255,255,255,0.65);
        }
        .solar{left:4%;top:34%;align-items:flex-start}
        .grid{right:5%;top:5%;align-items:flex-end}
        .alternator{left:12%;bottom:28%;align-items:flex-start}
        .battery{right:8%;bottom:24%;align-items:flex-end}
        .battery .percent{
          margin-top:8px;
          font-size:clamp(2.5rem, 6vw, 5rem);
          line-height:0.95;
        }
        @media (max-width: 900px){
          ha-card{min-height:70vh}
          .stage{min-height:540px}
        }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="stage">
            <div class="canvas" id="scene"></div>
            <div class="overlay">
              <div class="label solar">
                <small>Solar</small>
                <span id="solar-voltage">—</span>
                <span id="solar-amp">—</span>
                <span id="solar-watt">—</span>
              </div>
              <div class="label grid">
                <small>Hookup</small>
                <span id="grid-voltage">—</span>
                <span id="grid-amp">—</span>
                <span id="grid-watt">—</span>
              </div>
              <div class="label alternator">
                <small>Alternator</small>
                <span id="alternator-voltage">—</span>
                <span id="alternator-amp">—</span>
                <span id="alternator-watt">—</span>
              </div>
              <div class="label battery">
                <small>Battery</small>
                <span id="battery-voltage">—</span>
                <span id="battery-amp">—</span>
                <span id="battery-watt">—</span>
                <span id="battery-percent" class="percent">—</span>
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;

    ['solar', 'grid', 'alternator', 'battery'].forEach((prefix) => {
      this._elements[`${prefix}-voltage`] = this.shadowRoot.getElementById(`${prefix}-voltage`);
      this._elements[`${prefix}-amp`] = this.shadowRoot.getElementById(`${prefix}-amp`);
      this._elements[`${prefix}-watt`] = this.shadowRoot.getElementById(`${prefix}-watt`);
    });
    this._elements['battery-percent'] = this.shadowRoot.getElementById('battery-percent');

    if (!this._scene) {
      const modelUrl = new URL('./van.glb', import.meta.url).toString();
      this._scene = createVanScene(this.shadowRoot.getElementById('scene'), {
        modelUrl,
        interactive: true,
        autoRotate: true,
        autoRotateSpeed: 0.18,
      });
    }
  }

  update() {
    if (!this._hass) return;
    this.updateMetric('solar', this._config.solar_voltage, this._config.solar_amp, this._config.solar_watt);
    this.updateMetric('grid', this._config.grid_voltage, this._config.grid_amp, this._config.grid_watt);
    this.updateMetric('alternator', this._config.alternator_voltage, this._config.alternator_amp, this._config.alternator_watt);
    this.updateMetric('battery', this._config.battery_voltage, this._config.battery_amp, this._config.battery_watt);
    const batteryPercent = this.lookup(this._config.battery_percent);
    this._elements['battery-percent'].textContent = batteryPercent ? `${batteryPercent.state}%` : '—';
  }
}

customElements.define('van-power-card', VanPowerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'van-power-card',
  name: 'Van Power Card',
  description: '3D van power dashboard card',
});
