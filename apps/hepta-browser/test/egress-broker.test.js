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

function connectTunnel(socketPath, authority, payload = "probe") {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    let buffered = Buffer.alloc(0);
    let tunneled = false;
    socket.on("connect", () => {
      socket.write(
        `CONNECT ${authority} HTTP/1.1\r\nHost: ${authority}\r\nConnection: close\r\n\r\n`,
      );
    });
    socket.on("data", (chunk) => {
      buffered = Buffer.concat([buffered, chunk]);
      if (!tunneled) {
        const split = buffered.indexOf("\r\n\r\n");
        if (split >= 0) {
          const header = buffered.subarray(0, split + 4).toString("utf8");
          if (!header.startsWith("HTTP/1.1 200")) {
            socket.end();
            resolve({ header, body: buffered.subarray(split + 4).toString("utf8") });
            return;
          }
          tunneled = true;
          buffered = buffered.subarray(split + 4);
          socket.write(payload);
        }
      } else if (buffered.toString("utf8").includes(`echo:${payload}`)) {
        socket.end();
      }
    });
    socket.on("end", () => {
      const text = buffered.toString("utf8");
      resolve({ header: tunneled ? "HTTP/1.1 200" : text, body: text });
    });
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


test("production broker fails closed on IPv4-mapped IPv6 destinations", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-egress-mapped-"));
  const broker = new GrantScopedEgressBroker({
    socketPath: join(root, "proxy.sock"),
    allowedOrigins: ["http://[::ffff:7f00:1]"],
  });
  await broker.start();
  try {
    const response = await rawProxy(
      join(root, "proxy.sock"),
      "GET http://[::ffff:7f00:1]/ HTTP/1.1\r\nHost: [::ffff:7f00:1]\r\nConnection: close\r\n\r\n",
    );
    assert.match(response, /502 Bad Gateway|403 Forbidden/);
    assert.equal(broker.observations.length, 0);
  } finally {
    await broker.close();
    await rm(root, { recursive: true, force: true });
  }
});


test("HTTPS CONNECT is bound to the exact granted authority and port", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-egress-connect-"));
  let allowedHits = 0;
  let deniedHits = 0;
  const allowedServer = net.createServer((socket) => {
    socket.once("data", (chunk) => {
      allowedHits += 1;
      socket.end(`echo:${chunk.toString("utf8")}`);
    });
  });
  const deniedServer = net.createServer((socket) => {
    deniedHits += 1;
    socket.destroy();
  });
  await new Promise((resolve) => allowedServer.listen(0, "127.0.0.1", resolve));
  await new Promise((resolve) => deniedServer.listen(0, "127.0.0.1", resolve));
  const allowedAuthority = `127.0.0.1:${allowedServer.address().port}`;
  const deniedAuthority = `127.0.0.1:${deniedServer.address().port}`;
  const broker = new GrantScopedEgressBroker({
    socketPath: join(root, "proxy.sock"),
    allowedOrigins: [`https://${allowedAuthority}`],
    allowPrivateNetworkForTests: true,
  });
  await broker.start();
  try {
    const allowed = await connectTunnel(join(root, "proxy.sock"), allowedAuthority, "tls-bytes");
    assert.match(allowed.header, /200/);
    assert.match(allowed.body, /echo:tls-bytes/);
    assert.equal(allowedHits, 1);

    const denied = await connectTunnel(join(root, "proxy.sock"), deniedAuthority, "blocked");
    assert.doesNotMatch(denied.header, /200/);
    assert.equal(deniedHits, 0);
  } finally {
    await broker.close();
    await new Promise((resolve) => allowedServer.close(resolve));
    await new Promise((resolve) => deniedServer.close(resolve));
    await rm(root, { recursive: true, force: true });
  }
});
