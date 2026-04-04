# Event-based Timer/Metronome

A simple, event-driven timer library for Node.js built on `EventEmitter`. Provides a base `Timer` for interval-based ticks, plus `SyncTimer` and `AsyncTimer` helpers that execute functions on each tick and emit typed results.

## Documentation

[https://gibme-npm.github.io/timer/](https://gibme-npm.github.io/timer/)

## Installation

```bash
npm install @gibme/timer
```

or

```bash
yarn add @gibme/timer
```

## Usage

### Basic Timer

```typescript
import Timer from '@gibme/timer';

const timer = new Timer(60_000);

timer.on('tick', () => {
    // runs every 60 seconds
});

timer.start();
```

### Auto-Start with Arguments

```typescript
const timer = new Timer(5_000, true, 'hello', 42);

timer.on('tick', (greeting: string, value: number) => {
    console.log(greeting, value); // "hello" 42
});
```

### SyncTimer

Wraps a synchronous function, executing it on each interval and emitting the result via the `data` event.

```typescript
import { SyncTimer } from '@gibme/timer';

const timer = new SyncTimer(() => Math.random(), 1_000, true);

timer.on('data', (value, timestamp, interval) => {
    console.log(`Got ${value} at ${timestamp}s (every ${interval}ms)`);
});
```

### AsyncTimer

Wraps an asynchronous function, awaiting it on each interval and emitting the resolved value.

```typescript
import { AsyncTimer } from '@gibme/timer';

const timer = new AsyncTimer(async () => {
    const res = await fetch('https://api.example.com/data');
    return res.json();
}, 30_000, true);

timer.on('data', (payload, timestamp, interval) => {
    console.log(payload);
});

timer.on('error', (error) => {
    console.error('Request failed:', error);
});
```

### sleep

A simple async sleep utility.

```typescript
import { sleep } from '@gibme/timer';

await sleep(2_000); // wait 2 seconds
```

## API

### Timer

```typescript
new Timer(interval: number, autoStart?: boolean, ...args: any[])
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interval` | `number` | | Milliseconds between ticks |
| `autoStart` | `boolean` | `false` | Start immediately on construction |
| `...args` | `any[]` | | Arguments forwarded to every `tick` event |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `interval` | `number` | The tick interval in milliseconds |
| `paused` | `boolean` | Whether the timer is paused |
| `destroyed` | `boolean` | Whether the timer has been destroyed |

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `start()` | `void` | Start the timer |
| `stop()` | `void` | Stop the timer |
| `toggle()` | `boolean` | Toggle on/off; returns `true` if now running |
| `tick(...args)` | `void` | Force an immediate tick with optional arguments |
| `destroy()` | `void` | Permanently stop and clean up the timer |

#### Events

| Event | Listener Signature | Description |
|-------|--------------------|-------------|
| `tick` | `(...args: any[]) => void` | Emitted on each interval tick |
| `start` | `() => void` | Emitted when the timer starts |
| `stop` | `() => void` | Emitted when the timer stops |
| `error` | `(error: Error) => void` | Emitted on errors |

### SyncTimer\<Type\>

Extends `Timer`. Executes a synchronous function on each tick.

```typescript
new SyncTimer(func: () => Type, interval: number, autoStart?: boolean)
```

Emits a `data` event after each execution:

```typescript
timer.on('data', (result: Type, timestamp: number, interval: number) => void)
```

### AsyncTimer\<Type\>

Extends `Timer`. Executes an asynchronous function on each tick.

```typescript
new AsyncTimer(func: () => Promise<Type>, interval: number, autoStart?: boolean)
```

Emits a `data` event after each execution resolves:

```typescript
timer.on('data', (result: Type, timestamp: number, interval: number) => void)
```

Errors thrown or rejected by the function are emitted as `error` events.

## License

MIT
