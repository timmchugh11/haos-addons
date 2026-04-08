import { createVanScene } from './van-scene.js';

const LOCAL_MODEL_HOSTNAME = '192.168.1.10';

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

  buildSceneLabels() {
    const batteryPercent = this.lookup(this._config.battery_percent);
    return {
      solar: {
        title: 'SOLAR',
        lines: [
          this.format(this._config.solar_watt, 'W'),
          this.format(this._config.solar_amp, 'A'),
          this.format(this._config.solar_voltage, 'V'),
        ],
      },
      grid: {
        title: 'HOOKUP',
        lines: [
          this.format(this._config.grid_watt, 'W'),
          this.format(this._config.grid_amp, 'A'),
          this.format(this._config.grid_voltage, 'V'),
        ],
      },
      alternator: {
        title: 'ALTERNATOR',
        lines: [
          this.format(this._config.alternator_watt, 'W'),
          this.format(this._config.alternator_amp, 'A'),
          this.format(this._config.alternator_voltage, 'V'),
        ],
      },
      battery: {
        title: 'BATTERY',
        lines: [
          batteryPercent ? `${batteryPercent.state}%` : '—',
          this.format(this._config.battery_amp, 'A'),
          this.format(this._config.battery_voltage, 'V'),
        ],
      },
    };
  }

  resolveModelUrl() {
    return window.location.hostname === LOCAL_MODEL_HOSTNAME
      ? new URL('./van.glb', import.meta.url).toString()
      : `${window.location.origin}/api/van/model`;
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
        .overlay{display:none}
        @media (max-width: 900px){
          ha-card{min-height:70vh}
          .stage{min-height:540px}
        }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="stage">
            <div class="canvas" id="scene"></div>
            <div class="overlay"></div>
          </div>
        </div>
      </ha-card>
    `;

    if (!this._scene) {
      const modelUrl = this.resolveModelUrl();
      this._scene = createVanScene(this.shadowRoot.getElementById('scene'), {
        modelUrl,
        interactive: true,
        autoRotate: true,
        autoRotateSpeed: 0.18,
        labelsSpinWithModel: false,
      });
    }
  }

  update() {
    if (!this._hass) return;
    this._scene?.setLabels?.(this.buildSceneLabels());
  }
}

customElements.define('van-power-card', VanPowerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'van-power-card',
  name: 'Van Power Card',
  description: '3D van power dashboard card',
});
