import express from 'express';
import type { Server } from 'node:http';
import { afterEach, describe, expect, test } from 'vitest';
import {
  fixtureBrowserOrigins,
  limitFixtureRequests,
  listenOnLoopback,
  requireFixtureBrowserOrigin
} from './fixture-network';

const servers: Server[] = [];
afterEach(async () => {
  await Promise.all(
    servers.splice(0).map(
      (server) =>
        new Promise<void>((resolve) => {
          server.closeAllConnections();
          server.close(() => resolve());
        })
    )
  );
});
async function start(app: express.Application) {
  const listening = await listenOnLoopback(app);
  servers.push(listening.server);
  return listening;
}

describe('local fixture HTTP boundary', () => {
  test('accepts local requests and rejects a real sequential burst before dispatch', async () => {
    const app = express();
    limitFixtureRequests(app);
    let handled = 0;
    app.post('/token', (_req, res) => {
      handled += 1;
      res.json({ accepted: true });
    });
    const { server, url } = await start(app);
    expect(server.address()).toMatchObject({
      address: '127.0.0.1',
      family: 'IPv4'
    });
    const statuses: number[] = [];
    for (let i = 0; i < 200; i++) {
      const response = await fetch(`${url}/token`, { method: 'POST' });
      statuses.push(response.status);
      await response.arrayBuffer();
    }
    expect(statuses).toContain(200);
    expect(statuses).toContain(429);
    expect(handled).toBe(statuses.filter((status) => status === 200).length);
    const denied = await fetch(`${url}/token`, { method: 'POST' });
    expect(denied.status).toBe(429);
    expect(denied.headers.get('retry-after')).toBe('1');
    await denied.arrayBuffer();
  });

  test('rejects oversized and over-parameterized bodies without calling OAuth', async () => {
    const app = express();
    limitFixtureRequests(app);
    let handled = 0;
    app.post('/token', (_req, res) => {
      handled += 1;
      res.end();
    });
    const { url } = await start(app);
    for (const [type, body] of [
      ['application/json', JSON.stringify({ assertion: 'x'.repeat(65_536) })],
      [
        'application/x-www-form-urlencoded',
        new URLSearchParams(
          Array.from({ length: 65 }, (_, i) => [`p${i}`, 'value'])
        ).toString()
      ]
    ]) {
      const response = await fetch(`${url}/token`, {
        method: 'POST',
        headers: { 'Content-Type': type },
        body
      });
      expect(response.status).toBe(413);
      await response.arrayBuffer();
    }
    expect(handled).toBe(0);
    const valid = await fetch(`${url}/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'grant_type=authorization_code&code=fixture'
    });
    expect(valid.status).toBe(200);
    expect(handled).toBe(1);
    await valid.arrayBuffer();
  });

  test('caps active work and releases disconnected requests exactly once', async () => {
    const app = express();
    limitFixtureRequests(app);
    let admitted = 0;
    let batchReady: () => void = () => {};
    let released = 0;
    let batchClosed: () => void = () => {};
    app.get('/hold', (_req, res) => {
      admitted += 1;
      res.flushHeaders();
      res.once('close', () => {
        released += 1;
        if (released % 32 === 0) batchClosed();
      });
      if (admitted % 32 === 0) batchReady();
    });
    const { url } = await start(app);
    for (let batch = 0; batch < 2; batch++) {
      const ready = new Promise<void>((resolve) => {
        batchReady = resolve;
      });
      const controllers = Array.from(
        { length: 32 },
        () => new AbortController()
      );
      const pending = controllers.map((controller) =>
        fetch(`${url}/hold`, { signal: controller.signal }).catch(() => null)
      );
      await ready;
      const denied = await fetch(`${url}/hold`);
      expect(denied.status).toBe(429);
      await denied.arrayBuffer();
      // Wait for the server's close handlers before filling the second batch.
      const closed = new Promise<void>((resolve) => {
        batchClosed = resolve;
      });
      // The responses above publish headers, so client cancellation is a real socket close.
      controllers.forEach((controller) => controller.abort());
      await Promise.all(pending);
      await closed;
    }
    expect(admitted).toBe(64);
  });

  test('rejects unlisted browser Origins while preserving non-browser and allowed clients', async () => {
    const app = express();
    app.use(
      requireFixtureBrowserOrigin(
        fixtureBrowserOrigins('http://127.0.0.1:6274')
      )
    );
    let handled = 0;
    app.post('/mcp', (_req, res) => {
      handled += 1;
      res.end();
    });
    const { url } = await start(app);
    for (const origin of [
      'https://attacker.invalid',
      'null',
      'http://127.0.0.1:6275'
    ]) {
      const denied = await fetch(`${url}/mcp`, {
        method: 'POST',
        headers: { Origin: origin }
      });
      expect(denied.status).toBe(403);
      await denied.arrayBuffer();
    }
    expect(handled).toBe(0);
    for (const headers of [
      new Headers(), new Headers({ Origin: 'http://127.0.0.1:6274' })
    ]) {
      const accepted = await fetch(`${url}/mcp`, { method: 'POST', headers });
      expect(accepted.status).toBe(200);
      await accepted.arrayBuffer();
    }
    expect(handled).toBe(2);
    for (const malformed of [
      '*',
      'null',
      'https://allowed.invalid/path',
      'https://user:secret@allowed.invalid'
    ]) {
      expect(() => fixtureBrowserOrigins(malformed)).toThrow();
    }
  });
});
