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
    this._ingressPath = normalizeIngressPath(this._config.ingress_path || '') || getStoredIngressPath();
    this._frameSrc = '';
    this._status = 'loading';
    this._error = '';
    this._resolveToken = 0;
    this.render();
    this.ensureFrameSource();
  }

  set hass(hass) {
    this._hass = hass;
    this.ensureFrameSource();
  }

  getCardSize() {
    return 4;
  }

  async ensureFrameSource() {
    if (!this._config) return;

    const token = ++this._resolveToken;
    const ingressPath = this._ingressPath || await this.resolveIngressPath();
    if (token !== this._resolveToken) return;

    if (!ingressPath) {
      this._status = 'fallback';
      this._error = 'No ingress path is available for the Starlink add-on.';
      this.render();
      return;
    }

    this._ingressPath = ingressPath;
    this._frameSrc = buildFrameUrl(ingressPath, this._config);
    this._status = 'ready';
    this._error = '';
    this.render();
  }

  async resolveIngressPath() {
    if (this._ingressPath) {
      return this._ingressPath;
    }

    const storedIngressPath = getStoredIngressPath();
    if (storedIngressPath) {
      return storedIngressPath;
    }

    const hass = this._hass;
    if (!hass?.callApi) {
      return '';
    }

    const probes = [
      ['hassio/addons/starlink_gui/info', extractIngressPath],
      ['hassio/addons/self/info', extractIngressPath],
      ['hassio/addons', (payload) => extractIngressPathFromList(payload, 'starlink_gui')],
    ];

    for (const [path, picker] of probes) {
      try {
        const payload = await hass.callApi('get', path);
        const ingressPath = normalizeIngressPath(picker(payload));
        if (ingressPath) {
          return ingressPath;
        }
      } catch (_) {
        // Try the next endpoint.
      }
    }

    return '';
  }

  render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
    }

    const config = this._config || {};
    const wrapperStyle = getWrapperStyle(config);
    const titleMarkup = config.title ? `<div class="title">${escapeHtml(String(config.title))}</div>` : '';
    const iframeMarkup = this._status === 'ready'
      ? `<iframe src="${escapeHtml(this._frameSrc)}" loading="lazy" referrerpolicy="same-origin" allowfullscreen></iframe>`
      : '';
    const loadingMarkup = this._status === 'loading'
      ? '<div class="state-msg">Resolving add-on session...</div>'
      : '';
    const fallbackMarkup = this._status === 'fallback'
      ? buildFallbackMarkup(this._error, this._ingressPath, config)
      : '';

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
          min-height: 220px;
          ${wrapperStyle}
        }

        iframe,
        .state-msg,
        .fallback {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
        }

        iframe {
          border: 0;
          display: block;
          background: transparent;
        }

        .state-msg,
        .fallback {
          display: flex;
          align-items: center;
          justify-content: center;
          text-align: center;
          padding: 20px;
          background: #111111;
          color: #e6e6e6;
        }

        .fallback-box {
          max-width: 420px;
        }

        .fallback-title {
          font-size: 1rem;
          font-weight: 600;
          line-height: 1.4;
        }

        .fallback-copy {
          margin-top: 10px;
          font-size: 0.92rem;
          line-height: 1.5;
          color: #aaaaaa;
        }

        .fallback-actions {
          display: flex;
          gap: 10px;
          justify-content: center;
          flex-wrap: wrap;
          margin-top: 16px;
        }

        .fallback-link,
        .retry-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 10px 14px;
          border-radius: 10px;
          border: 1px solid #2a2a2a;
          background: transparent;
          color: #e6e6e6;
          text-decoration: none;
          font: inherit;
          cursor: pointer;
        }

        .fallback-link:hover,
        .retry-btn:hover {
          background: #1a1a1a;
        }

        code {
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
      </style>
      <ha-card>
        ${titleMarkup}
        <div class="frame-wrap">
          ${iframeMarkup}
          ${loadingMarkup}
          ${fallbackMarkup}
        </div>
      </ha-card>
    `;

    if (this._status === 'ready') {
      const frame = this.shadowRoot.querySelector('iframe');
      frame?.addEventListener('load', () => this.checkUnauthorizedFrame(frame));
      window.setTimeout(() => this.checkUnauthorizedFrame(frame), 1200);
    }

    this.shadowRoot.querySelector('.retry-btn')?.addEventListener('click', () => {
      this._status = 'loading';
      this._error = '';
      this.render();
      this.ensureFrameSource();
    });
  }

  checkUnauthorizedFrame(frame) {
    if (!frame || this._status !== 'ready') return;
    try {
      const doc = frame.contentDocument;
      const text = `${doc?.title || ''} ${doc?.body?.textContent || ''}`.toLowerCase();
      if (text.includes('401') || text.includes('unauthorized') || text.includes('unauthorised')) {
        this._status = 'fallback';
        this._error = 'The add-on ingress session is not active on this device.';
        this.render();
      }
    } catch (_) {
      // If the browser blocks access here, keep the iframe visible.
    }
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

function buildFrameUrl(ingressPath, config) {
  const page = String(config.page || 'combined').replace(/^\/*/, '');
  const base = new URL(ensureTrailingSlash(toAbsoluteIngressUrl(ingressPath)), window.location.origin);
  const src = new URL(page, base);
  const params = new URLSearchParams();

  if (config.dish_host) params.set('dishHost', config.dish_host);
  if (config.dish_port != null) params.set('dishPort', String(config.dish_port));
  if (config.router_host) params.set('routerHost', config.router_host);
  if (config.router_port != null) params.set('routerPort', String(config.router_port));

  const query = params.toString();
  if (query) {
    src.search = query;
  }

  return src.toString();
}

function buildFallbackMarkup(error, ingressPath, config) {
  const openHref = ingressPath ? buildFrameUrl(ingressPath, { ...config, page: 'combined' }) : '';
  return `
    <div class="fallback">
      <div class="fallback-box">
        <div class="fallback-title">Starlink GUI needs an active add-on session</div>
        <div class="fallback-copy">${escapeHtml(error || 'Open the add-on once on this device, then reload the card.')}</div>
        <div class="fallback-copy">The card module loads from <code>/local/starlink-gui/starlink-combined-card.js</code>, but the embedded page still uses Home Assistant ingress.</div>
        <div class="fallback-actions">
          ${openHref ? `<a class="fallback-link" href="${escapeHtml(openHref)}" target="_blank" rel="noreferrer">Open Add-on</a>` : ''}
          <button class="retry-btn" type="button">Retry</button>
        </div>
      </div>
    </div>
  `;
}

function extractIngressPath(payload) {
  return payload?.data?.ingress_url
    || payload?.data?.ingress_entry
    || payload?.ingress_url
    || payload?.ingress_entry
    || '';
}

function extractIngressPathFromList(payload, slug) {
  const addons = payload?.data?.addons || payload?.addons || [];
  const match = addons.find((item) => item.slug === slug || item.addon === slug || item.name === slug);
  return extractIngressPath(match);
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

function normalizeIngressPath(value) {
  if (!value) return '';
  const str = String(value).trim();
  if (!str) return '';
  if (/^https?:\/\//i.test(str)) return str;
  return str.startsWith('/') ? str : `/${str}`;
}

function getStoredIngressPath() {
  try {
    const value = window.localStorage.getItem('starlink_gui.ingress_path');
    const normalized = normalizeIngressPath(value || '');
    return normalized.startsWith('/api/hassio_ingress/') ? normalized : '';
  } catch (_) {
    return '';
  }
}

function ensureTrailingSlash(value) {
  return value.endsWith('/') ? value : `${value}/`;
}

function toAbsoluteIngressUrl(value) {
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) return value;
  return `${window.location.origin}${value}`;
}

function escapeHtml(value) {
  return String(value)
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
