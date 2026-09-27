import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { EffectScopedEgressBroker } from "../src/effect-egress-gate.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);

function listen(server, ...args) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(...args, () => {
      server.off("error", reject);
      resolve();
    });
  });
}

function close(server) {
  return new Promise((resolve) => server.close(() => resolve()));
}

function proxyRequest(socketPath, absoluteUrl) {
  return new Promise((resolve) => {
    const socket = net.createConnection(socketPath);
    const chunks = [];
    socket.on("connect", () => {
      socket.end(
        `GET ${absoluteUrl} HTTP/1.1\r\n` +
          `Host: ${new URL(absoluteUrl).host}\r\n` +
          "Connection: close\r\n\r\n",
      );
    });
    socket.on("data", (chunk) => chunks.push(chunk));
    socket.on("error", () => resolve(Buffer.concat(chunks)));
    socket.on("close", () => resolve(Buffer.concat(chunks)));
  });
}

async function fixture(t, { responseBytes = 32, maxResponseBytes = 4096 } = {}) {
  const root = await mkdtemp(join(tmpdir(), "hepta-effect-egress-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const server = http.createServer((_request, response) => {
    response.writeHead(200, {
      "content-type": "application/octet-stream",
      connection: "close",
    });
    response.end(Buffer.alloc(responseBytes, 0x61));
  });
  await listen(server, 0, "127.0.0.1");
  t.after(() => close(server));
  const port = server.address().port;
  const origin = `http://effect.test:${port}`;
  const socketPath = join(root, "egress.sock");
  const broker = new EffectScopedEgressBroker({
    socketPath,
    grantDigest: D1,
    allowedOrigins: [origin],
    allowPrivateNetworkForTests: true,
    resolver: async () => [{ address: "127.0.0.1", family: 4 }],
    maxRequestBytes: 4096,
    maxResponseBytes,
  });
  await broker.start();
  t.after(() => broker.close().catch(() => {}));
  return { broker, socketPath, origin };
}

test(
  "network is unavailable until one exact effect owns the gate",
  { skip: process.platform === "win32" },
  async (t) => {
    const { broker, socketPath, origin } = await fixture(t);
    const before = await proxyRequest(socketPath, `${origin}/before`);
    assert.equal(before.length, 0);

    broker.admitOperation({
      operationId: "operation.1",
      effectGrantDigest: D2,
      destinationOrigin: origin,
      deadlineMs: Date.now() + 10_000,
    });
    const response = await proxyRequest(socketPath, `${origin}/allowed`);
    assert.match(response.toString("latin1"), /HTTP\/1\.1 200/);

    const receipt = broker.completeOperation("operation.1", {
      status: "succeeded",
    });
    assert.equal(
      receipt.schema,
      "hepta.browser.egress-operation-receipt.v1",
    );
    assert.equal(receipt.effectGrantDigest, D2);
    assert.equal(receipt.destinationOrigin, origin);
    assert.equal(receipt.status, "succeeded");
    assert.equal(receipt.connectionCount, 1);
    assert.equal(receipt.boundedAbort, false);
    assert.ok(receipt.requestBytes > 0);
    assert.ok(receipt.responseBytes > 0);
    assert.match(receipt.receiptDigest, /^[0-9a-f]{64}$/);

    const after = await proxyRequest(socketPath, `${origin}/after`);
    assert.equal(after.length, 0);
  },
);

test(
  "effect origin cannot widen to another profile-admitted destination",
  { skip: process.platform === "win32" },
  async (t) => {
    const root = await mkdtemp(join(tmpdir(), "hepta-effect-origin-"));
    t.after(() => rm(root, { recursive: true, force: true }));
    const server = http.createServer((_request, response) => response.end("ok"));
    await listen(server, 0, "127.0.0.1");
    t.after(() => close(server));
    const port = server.address().port;
    const admitted = `http://one.test:${port}`;
    const other = `http://two.test:${port}`;
    const socketPath = join(root, "egress.sock");
    const broker = new EffectScopedEgressBroker({
      socketPath,
      grantDigest: D1,
      allowedOrigins: [admitted, other],
      allowPrivateNetworkForTests: true,
      resolver: async () => [{ address: "127.0.0.1", family: 4 }],
    });
    await broker.start();
    t.after(() => broker.close().catch(() => {}));
    broker.admitOperation({
      operationId: "operation.origin",
      effectGrantDigest: D2,
      destinationOrigin: admitted,
      deadlineMs: Date.now() + 10_000,
    });
    const denied = await proxyRequest(socketPath, `${other}/denied`);
    assert.equal(denied.length, 0);
    const receipt = broker.completeOperation("operation.origin", {
      status: "failed",
    });
    assert.equal(receipt.connectionCount, 0);
  },
);

test(
  "aggregate response bytes are bounded across all operation connections",
  { skip: process.platform === "win32" },
  async (t) => {
    const { broker, socketPath, origin } = await fixture(t, {
      responseBytes: 300,
      maxResponseBytes: 500,
    });
    broker.admitOperation({
      operationId: "operation.bounded",
      effectGrantDigest: D2,
      destinationOrigin: origin,
      deadlineMs: Date.now() + 10_000,
    });
    const first = await proxyRequest(socketPath, `${origin}/first`);
    assert.ok(first.length > 0);
    await proxyRequest(socketPath, `${origin}/second`);
    const receipt = broker.completeOperation("operation.bounded", {
      status: "indeterminate",
    });
    assert.equal(receipt.connectionCount, 2);
    assert.equal(receipt.boundedAbort, true);
    assert.ok(receipt.responseBytes > receipt.maxResponseBytes);
  },
);
