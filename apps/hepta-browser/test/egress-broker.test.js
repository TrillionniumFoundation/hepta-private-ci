import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { GrantScopedEgressBroker } from "../src/egress-broker.js";

function listenHttp(handler) {
  const server = http.createServer(handler);
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

function rawProxy(socketPath, request) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    const chunks = [];
    socket.on("connect", () => socket.end(request));
    socket.on("data", (chunk) => chunks.push(chunk));
    socket.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    socket.on("error", reject);
  });
}

test("grant-scoped proxy admits only the exact allowed HTTP origin", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-egress-"));
  let forbiddenHits = 0;
  const allowed = await listenHttp((_request, response) => response.end("allowed"));
  const forbidden = await listenHttp((_request, response) => {
    forbiddenHits += 1;
    response.end("forbidden");
  });
  const allowedPort = allowed.address().port;
  const forbiddenPort = forbidden.address().port;
  const broker = new GrantScopedEgressBroker({
    socketPath: join(root, "proxy.sock"),
    allowedOrigins: [`http://127.0.0.1:${allowedPort}`],
    allowPrivateNetworkForTests: true,
  });
  await broker.start();
  try {
    const ok = await rawProxy(
      join(root, "proxy.sock"),
      `GET http://127.0.0.1:${allowedPort}/ok HTTP/1.1\r\nHost: 127.0.0.1:${allowedPort}\r\nConnection: close\r\n\r\n`,
    );
    assert.match(ok, /200 OK/);
    assert.match(ok, /allowed/);

    const denied = await rawProxy(
      join(root, "proxy.sock"),
      `GET http://127.0.0.1:${forbiddenPort}/no HTTP/1.1\r\nHost: 127.0.0.1:${forbiddenPort}\r\nConnection: close\r\n\r\n`,
    );
    assert.doesNotMatch(denied, /forbidden/);
    assert.equal(forbiddenHits, 0);
    assert.deepEqual(broker.observations.map((item) => item.origin), [
      `http://127.0.0.1:${allowedPort}`,
    ]);
  } finally {
    await broker.close();
    await new Promise((resolve) => allowed.close(resolve));
    await new Promise((resolve) => forbidden.close(resolve));
    await rm(root, { recursive: true, force: true });
  }
});

test("production broker rejects loopback/private DNS targets even when the origin string is granted", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-egress-private-"));
  const server = await listenHttp((_request, response) => response.end("should-not-reach"));
  const port = server.address().port;
  const broker = new GrantScopedEgressBroker({
    socketPath: join(root, "proxy.sock"),
    allowedOrigins: [`http://127.0.0.1:${port}`],
  });
  await broker.start();
  try {
    const response = await rawProxy(
      join(root, "proxy.sock"),
      `GET http://127.0.0.1:${port}/ HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nConnection: close\r\n\r\n`,
    );
    assert.match(response, /502 Bad Gateway|403 Forbidden/);
    assert.equal(broker.observations.length, 0);
  } finally {
    await broker.close();
    await new Promise((resolve) => server.close(resolve));
    await rm(root, { recursive: true, force: true });
  }
});
