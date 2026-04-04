# @gibme/fetch

A TypeScript wrapper around [cross-fetch](https://npmjs.org/package/cross-fetch) that extends the standard Fetch API with timeout support, cookie jar persistence, authentication helpers, and convenience methods for JSON and form data — for both Node.js and browser environments.

## Features

- **Timeout support** — abort requests after a configurable duration
- **Cookie jar persistence** — maintain cookies across requests (Node.js only)
- **Authentication helpers** — Basic, Bearer, and JWT auth via simple options
- **JSON & form data shortcuts** — auto-serialization with correct `Content-Type` headers
- **HTTP method helpers** — `fetch.get()`, `fetch.post()`, `fetch.put()`, `fetch.del()`, etc.
- **Custom agents** — pass `http.Agent` or `https.Agent` for connection pooling (Node.js only)
- **SSL/TLS control** — disable certificate validation for development (Node.js only)
- **Dual entry points** — optimized builds for Node.js and browser

## Requirements

- Node.js >= 22

## Installation

```bash
npm install @gibme/fetch
# or
yarn add @gibme/fetch
```

## Usage

### Basic Request

```typescript
import fetch from '@gibme/fetch';

const response = await fetch('https://api.example.com/data', { timeout: 5000 });

console.log(await response.json());
```

### HTTP Method Helpers

```typescript
import fetch from '@gibme/fetch';

const response = await fetch.get('https://api.example.com/users');
const created = await fetch.post('https://api.example.com/users', {
    json: { name: 'Alice' }
});
const updated = await fetch.put('https://api.example.com/users/1', {
    json: { name: 'Bob' }
});
const deleted = await fetch.del('https://api.example.com/users/1');
```

All methods: `fetch.get()`, `fetch.post()`, `fetch.put()`, `fetch.del()`, `fetch.head()`, `fetch.patch()`, `fetch.options()`, `fetch.trace()`, `fetch.connect()`

### JSON Body

```typescript
const response = await fetch('https://api.example.com/data', {
    method: 'POST',
    json: { key: 'value', count: 42 }
});
```

Automatically stringifies the body and sets `Content-Type: application/json`.

### Form Data

```typescript
const response = await fetch('https://api.example.com/submit', {
    method: 'POST',
    formData: { username: 'alice', password: 'secret' }
});
```

Accepts a plain object or `URLSearchParams`. Sets `Content-Type: application/x-www-form-urlencoded`.

### Authentication

```typescript
// Basic Auth
const response = await fetch('https://api.example.com/protected', {
    username: 'alice',
    password: 'secret'
});

// Bearer Token
const response = await fetch('https://api.example.com/protected', {
    bearer: 'your-token-here'
});

// JWT
const response = await fetch('https://api.example.com/protected', {
    jwt: 'eyJhbGciOiJIUzI1NiIs...'
});
```

### Cookie Jar (Node.js only)

Persist cookies across multiple requests using a `CookieJar`:

```typescript
import fetch, { CookieJar } from '@gibme/fetch';

const cookieJar = new CookieJar();

// First request stores cookies in the jar
await fetch('https://example.com/login', {
    method: 'POST',
    json: { user: 'alice', pass: 'secret' },
    cookieJar
});

// Subsequent requests automatically include stored cookies
const response = await fetch('https://example.com/dashboard', { cookieJar });
```

### Timeout

```typescript
const response = await fetch('https://slow-api.example.com/data', {
    timeout: 10000 // abort after 10 seconds
});
```

### Custom Agents (Node.js only)

```typescript
import { Agent as HttpsAgent } from 'https';

const agent = new HttpsAgent({ keepAlive: true });

const response = await fetch('https://api.example.com/data', { agent });
```

### Disable SSL Verification (Node.js only)

```typescript
const response = await fetch('https://self-signed.local/api', {
    rejectUnauthorized: false
});
```

### Browser Usage

```typescript
import fetch from '@gibme/fetch/browser';

const response = await fetch('https://api.example.com/data');
```

The browser entry point excludes Node.js-specific features (cookie jar, agents, SSL control) for a smaller bundle. A pre-built minified bundle (`Fetch.min.js`) is also available in the `dist/` directory.

## Extended Options

All standard [Fetch API `RequestInit`](https://developer.mozilla.org/en-US/docs/Web/API/RequestInit) options are supported, plus:

| Option | Type | Platform | Description |
|--------|------|----------|-------------|
| `timeout` | `number` | Both | Request timeout in milliseconds |
| `json` | `any` | Both | Auto-stringified JSON body |
| `formData` | `Record<string, any> \| URLSearchParams` | Both | URL-encoded form body |
| `username` | `string` | Both | Basic auth username |
| `password` | `string` | Both | Basic auth password |
| `bearer` | `string` | Both | Bearer token |
| `jwt` | `string` | Both | JWT token (sent as Bearer) |
| `cookieJar` | `CookieJar` | Node.js | Cookie persistence across requests |
| `agent` | `http.Agent \| https.Agent` | Node.js | Custom HTTP/HTTPS agent |
| `rejectUnauthorized` | `boolean` | Node.js | SSL/TLS certificate validation (default: `true`) |

## Exports

| Import Path | Description |
|-------------|-------------|
| `@gibme/fetch` | Node.js entry point (default) |
| `@gibme/fetch/node` | Node.js entry point (explicit) |
| `@gibme/fetch/browser` | Browser entry point |

### Named Exports

Both entry points export: `fetch` (default), `Headers`, `Request`, `Response`, `toURLSearchParams`, `normalizeInit`

The Node.js entry point additionally exports: `Cookie`, `CookieJar`

## License

MIT
