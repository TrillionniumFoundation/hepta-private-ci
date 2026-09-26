import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { GrantScopedEgressBroker } from "../src/egress-broker.js";

const GRANT_DIGEST = "a".repeat(64);

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
    socket.on("connect", () => socket.write(request));
    socket.on("data", (chunk) => chunks.push(chunk));
    socket.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    socket.on("error", reject);
  });
}

function tlsClientHello(serverName) {
  const name = Buffer.from(serverName, "ascii");
  const serverNameEntry = Buffer.concat([
    Buffer.from([0]),
    Buffer.from([(name.length >>> 8) & 0xff, name.length & 0xff]),
    name,
  ]);
  const serverNameList = Buffer.concat([
    Buffer.from([
      (serverNameEntry.length >>> 8) & 0xff,
      serverNameEntry.length & 0xff,
    ]),
    serverNameEntry,
  ]);
  const extension = Buffer.concat([
    Buffer.from([0, 0, (serverNameList.length >>> 8) & 0xff, serverNameList.length & 0xff]),
    serverNameList,
  ]);
  const body = Buffer.concat([
    Buffer.from([0x03, 0x03]),
    Buffer.alloc(32, 7),
    Buffer.from([0]),
    Buffer.from([0, 2, 0x13, 0x01]),
    Buffer.from([1, 0]),
    Buffer.from([(extension.length >>> 8) & 0xff, extension.length & 0xff]),
    extension,
  ]);
  const handshake = Buffer.concat([
    Buffer.from([
      1,
      (body.length >>> 16) & 0xff,
      (body.length >>> 8) & 0xff,
      body.length & 0xff,
    ]),
    body,
  ]);
  return Buffer.concat([
    Buffer.from([
      22,
      0x03,
      0x01,
      (handshake.length >>> 8) & 0xff,
      handshake.length & 0xff,
    ]),
    handshake,
  ]);
}

function connectTunnel(socketPath, authority, hello) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    let header = "";
    let body = Buffer.alloc(0);
    let response = Buffer.alloc(0);
    let tunneled = false;
    let settled = false;
    let timer;

    const settle = (result, error = null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      if (error) reject(error);
      else resolve(result);
    };
    const finish = () => settle({ header, body });

    timer = setTimeout(() => {
      settle(null, new Error("CONNECT fixture timed out"));
    }, 5_000);
    socket.on("connect", () => {
      socket.write(
        `CONNECT ${authority} HTTP/1.1\r\nHost: ${authority}\r\nConnection: close\r\n\r\n`,
      );
    });
    socket.on("data", (chunk) => {
      if (tunneled) {
        body = Buffer.concat([body, chunk]);
        return;
      }
      response = Buffer.concat([response, chunk]);
      const split = response.indexOf("\r\n\r\n");
      if (split < 0) return;
      header = response.subarray(0, split + 4).toString("utf8");
      body = response.subarray(split + 4);
      if (!header.startsWith("HTTP/1.1 200")) {
        socket.end();
        return;
      }
      tunneled = true;
      socket.write(hello);
    });
    socket.on("end", finish);
    socket.on("close", finish);
    socket.on("error", (error) => {
      if (tunneled) finish();
      else settle(null, error);
    });
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
    grantDigest: GRANT_DIGEST,
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
    grantDigest: GRANT_DIGEST,
    socketPath: join(root, "proxy.sock"),
    allowedOrigins: [`http://127.0.0.1:${port}`],
  });
  try {
    await assert.rejects(broker.start(), /globally routable/);
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
    grantDigest: GRANT_DIGEST,
    socketPath: join(root, "proxy.sock"),
    allowedOrigins: ["http://[::ffff:7f00:1]"],
  });
  try {
    await assert.rejects(broker.start(), /globally routable/);
    assert.equal(broker.observations.length, 0);
  } finally {
    await broker.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("profile network grant freezes DNS answers for the broker generation", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-egress-dns-pin-"));
  let hits = 0;
  let resolutions = 0;
  const server = await listenHttp((_request, response) => {
    hits += 1;
    response.end("pinned");
  });
  const port = server.address().port;
  const resolver = async () => {
    resolutions += 1;
    return resolutions === 1
      ? [{ address: "127.0.0.1", family: 4 }]
      : [{ address: "203.0.113.7", family: 4 }];
  };
  const broker = new GrantScopedEgressBroker({
    grantDigest: GRANT_DIGEST,
    socketPath: join(root, "proxy.sock"),
    allowedOrigins: [`http://pinned.test:${port}`],
    allowPrivateNetworkForTests: true,
    resolver,
  });
  await broker.start();
  try {
    for (const path of ["/one", "/two"]) {
      const response = await rawProxy(
        join(root, "proxy.sock"),
        `GET http://pinned.test:${port}${path} HTTP/1.1\r\nHost: pinned.test:${port}\r\nConnection: close\r\n\r\n`,
      );
      assert.match(response, /200 OK/);
      assert.match(response, /pinned/);
    }
    assert.equal(resolutions, 1, "DNS must not be re-resolved after the profile grant is bound");
    assert.equal(hits, 2);
    assert.equal(new Set(broker.observations.map((item) => item.networkBindingDigest)).size, 1);
    assert.deepEqual(
      [...new Set(broker.observations.map((item) => item.grantDigest))],
      [GRANT_DIGEST],
    );
  } finally {
    await broker.close();
    await new Promise((resolve) => server.close(resolve));
    await rm(root, { recursive: true, force: true });
  }
});

test("HTTPS CONNECT binds exact authority, port, and TLS ClientHello SNI before upstream connect", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-egress-connect-"));
  let allowedHits = 0;
  let deniedHits = 0;
  const allowedServer = net.createServer((socket) => {
    allowedHits += 1;
    socket.end("accepted");
  });
  const deniedServer = net.createServer((socket) => {
    deniedHits += 1;
    socket.destroy();
  });
  await new Promise((resolve) => allowedServer.listen(0, "127.0.0.1", resolve));
  await new Promise((resolve) => deniedServer.listen(0, "127.0.0.1", resolve));
  const allowedAuthority = `localhost:${allowedServer.address().port}`;
  const deniedAuthority = `127.0.0.1:${deniedServer.address().port}`;
  const broker = new GrantScopedEgressBroker({
    grantDigest: GRANT_DIGEST,
    socketPath: join(root, "proxy.sock"),
    allowedOrigins: [`https://${allowedAuthority}`],
    allowPrivateNetworkForTests: true,
  });
  await broker.start();
  try {
    const allowed = await connectTunnel(
      join(root, "proxy.sock"),
      allowedAuthority,
      tlsClientHello("localhost"),
    );
    assert.match(allowed.header, /200/);
    assert.equal(allowedHits, 1);

    const mismatchedSni = await connectTunnel(
      join(root, "proxy.sock"),
      allowedAuthority,
      tlsClientHello("example.invalid"),
    );
    assert.match(mismatchedSni.header, /200/);
    assert.equal(
      allowedHits,
      1,
      "SNI drift must be rejected before any additional upstream connection",
    );

    const denied = await connectTunnel(
      join(root, "proxy.sock"),
      deniedAuthority,
      tlsClientHello("127.0.0.1"),
    );
    assert.doesNotMatch(denied.header, /200/);
    assert.equal(deniedHits, 0);
  } finally {
    await broker.close();
    await new Promise((resolve) => allowedServer.close(resolve));
    await new Promise((resolve) => deniedServer.close(resolve));
    await rm(root, { recursive: true, force: true });
  }
});
