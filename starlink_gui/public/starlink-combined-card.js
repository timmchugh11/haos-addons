class StarlinkCombinedCard extends HTMLElement {
  static getStubConfig() {
    return {
      aspect_ratio: '16:9',
    };
  }

  setConfig(config) {
    if (config == null || typeof config !== 'object') {
      throw new Error('Invalid configuration');
    }

    this._config = {
      page: 'combined',
      aspect_ratio: '16:9',
      ...config,
    };

    this.render();
  }

  getCardSize() {
    return 4;
  }

  render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
    }

    const config = this._config || {};
    const page = String(config.page || 'combined').replace(/^\/*/, '');
    const src = new URL(page, resolveModuleBaseUrl());
    const params = new URLSearchParams();

    if (config.dish_host) params.set('dishHost', config.dish_host);
    if (config.dish_port != null) params.set('dishPort', String(config.dish_port));
    if (config.router_host) params.set('routerHost', config.router_host);
    if (config.router_port != null) params.set('routerPort', String(config.router_port));

    const query = params.toString();
    if (query) {
      src.search = query;
    }

    const wrapperStyle = getWrapperStyle(config);
    const titleMarkup = config.title ? `<div class="title">${escapeHtml(String(config.title))}</div>` : '';

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }

        ha-card {
          overflow: hidden;
        }

        .title {
          padding: 16px 16px 0;
          font-size: 1rem;
          font-weight: 500;
          line-height: 1.4;
        }

        .frame-wrap {
          position: relative;
          width: 100%;
          ${wrapperStyle}
        }

        iframe {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          border: 0;
          display: block;
          background: transparent;
        }
      </style>
      <ha-card>
        ${titleMarkup}
        <div class="frame-wrap">
          <iframe
            src="${escapeHtml(src.toString())}"
            loading="lazy"
            referrerpolicy="same-origin"
            allowfullscreen
          ></iframe>
        </div>
      </ha-card>
    `;
  }
}

function getWrapperStyle(config) {
  const height = normalizeCssDimension(config.height);
  if (height) {
    return `height: ${height};`;
  }

  const aspectRatio = normalizeAspectRatio(config.aspect_ratio);
  return `aspect-ratio: ${aspectRatio};`;
}

function normalizeCssDimension(value) {
  if (value == null || value === '') return '';
  const str = String(value).trim();
  if (!str) return '';
  if (/^\d+(\.\d+)?$/.test(str)) return `${str}px`;
  if (/^\d+(\.\d+)?(px|rem|em|vh|vw|%)$/.test(str)) return str;
  throw new Error(`Invalid height value: ${str}`);
}

function normalizeAspectRatio(value) {
  const fallback = '16 / 9';
  if (value == null || value === '') return fallback;
  const str = String(value).trim();
  if (!str) return fallback;

  if (/^\d+(\.\d+)?\s*:\s*\d+(\.\d+)?$/.test(str)) {
    return str.replace(':', ' / ');
  }

  if (/^\d+(\.\d+)?\s*\/\s*\d+(\.\d+)?$/.test(str)) {
    return str;
  }

  throw new Error(`Invalid aspect_ratio value: ${str}`);
}

function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

customElements.define('starlink-combined-card', StarlinkCombinedCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'starlink-combined-card',
  name: 'Starlink Combined Card',
  description: 'Embeds the bundled Starlink combined page from the Starlink GUI add-on.',
});

function resolveModuleBaseUrl() {
  const scripts = Array.from(document.querySelectorAll('script[src]'));
  const current = scripts.find((script) => /starlink-combined-card\.js(?:$|\?)/.test(script.src));
  if (current?.src) {
    return current.src;
  }
  return window.location.href;
}
