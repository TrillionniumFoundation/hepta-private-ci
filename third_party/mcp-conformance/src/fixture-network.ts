import express from 'express';
import type { Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { performance } from 'node:perf_hooks';

/** Local harness admission, separate from OAuth success/failure observations. */
export function limitFixtureRequests(app: express.Application): void {
  // One bucket per fixture, not an unbounded map keyed by attacker input.
  const capacity = 120;
  let tokens = capacity;
  let updated = performance.now();
  let active = 0;
  app.use((_req, res, next) => {
    const now = performance.now();
    tokens = Math.min(capacity, tokens + ((now - updated) * capacity) / 60_000);
    updated = now;
    if (tokens < 1 || active >= 32) {
      res.setHeader('Retry-After', '1');
      res.status(429).json({ error: 'fixture_request_limit' });
      return;
    }
    tokens -= 1;
    active += 1;
    let released = false;
    const release = () => {
      if (!released) {
        released = true;
        active -= 1;
      }
    };
    res.once('finish', release);
    res.once('close', release);
    next();
  });
  app.use(express.json({ limit: '64kb', inflate: false }));
  app.use(
    express.urlencoded({
      extended: false,
      limit: '64kb',
      parameterLimit: 64,
      inflate: false
    })
  );
}

/** Bound incomplete HTTP requests without shortening intentional MCP streams. */
export async function listenOnLoopback(
  app: express.Application,
  port: number = 0
): Promise<{ server: Server; url: string }> {
  const server = app.listen(port, '127.0.0.1');
  server.headersTimeout = 10_000;
  server.requestTimeout = 15_000;
  server.keepAliveTimeout = 5_000;
  server.maxHeadersCount = 64;
  server.maxRequestsPerSocket = 100;
  try {
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.once('listening', resolve);
    });
    const address = server.address() as AddressInfo;
    return { server, url: `http://127.0.0.1:${address.port}` };
  } catch (error) {
    server.close();
    throw error;
  }
}

/** Browser Origins are explicit; non-browser clients send no Origin. */
export function fixtureBrowserOrigins(
  configured: string | undefined
): Set<string> {
  const origins =
    configured === undefined
      ? ['http://localhost:6274', 'http://127.0.0.1:6274']
      : configured.split(',').map((origin) => origin.trim());
  for (const origin of origins) {
    const parsed = new URL(origin);
    if (
      !['http:', 'https:'].includes(parsed.protocol) ||
      parsed.origin !== origin ||
      parsed.username ||
      parsed.password
    ) {
      throw new Error(
        'MCP_CONFORMANCE_ALLOWED_ORIGINS requires exact HTTP(S) origins'
      );
    }
  }
  return new Set(origins);
}

export function requireFixtureBrowserOrigin(
  origins: ReadonlySet<string>
): express.RequestHandler {
  return (req, res, next) => {
    const origin = req.headers.origin;
    if (origin !== undefined && !origins.has(origin)) {
      res.status(403).json({ error: 'fixture_origin_not_allowed' });
      return;
    }
    next();
  };
}
