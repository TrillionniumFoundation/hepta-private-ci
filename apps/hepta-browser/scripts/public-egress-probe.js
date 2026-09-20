#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import http from "node:http";
import net from "node:net";
import tls from "node:tls";
import { chmod, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { GrantScopedEgressBroker } from "../src/egress-broker.js";

const GRANT_DIGEST = createHash("sha256")
  .update("hepta.browser.public-egress-target.v1")
  .digest("hex");
const AUTHORITY = "example.com:443";
const ORIGIN = "https://example.com";

function connect(socketPath, authority) {
  return new Promise((resolve, reject) => {
    const request = http.request({
      socketPath,
      method: "CONNECT",
      path: authority,
      headers: { Host: authority, Connection: "close" },
    });
    request.once("connect", (response, socket, head) => {
      resolve({ response, socket, head });
    });
    request.once("error", reject);
    request.end();
  });
}

async function publicTls(socketPath) {
  const { response, socket, head } = await connect(socketPath, AUTHORITY);
  assert.equal(response.statusCode, 200, "granted public CONNECT must succeed");
  if (head.length) socket.unshift(head);
  return new Promise((resolve, reject) => {
    const secure = tls.connect({
      socket,
      servername: "example.com",
      rejectUnauthorized: true,
    });
    const chunks = [];
    let bytes = 0;
    const fail = (error) => {
      secure.destroy();
      reject(error);
    };
    secure.setTimeout(10_000, () => fail(new Error("public TLS probe timed out")));
    secure.once("error", fail);
    secure.once("secureConnect", () => {
      assert.equal(secure.authorized, true, "public TLS certificate must validate");
      secure.write(
        "GET / HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\nUser-Agent: hepta-browser-target-probe\r\n\r\n",
      );
    });
    secure.on("data", (chunk) => {
      bytes += chunk.length;
      if (bytes > 131_072) {
        fail(new Error("public TLS response exceeded probe bound"));
        return;
      }
      chunks.push(chunk);
    });
    secure.once("end", () => {
      const text = Buffer.concat(chunks).toString("utf8");
      const status = /^HTTP\/1\.[01] (\d{3})/.exec(text)?.[1];
      assert.ok(status, "public HTTPS endpoint must return an HTTP status");
      resolve(Number(status));
    });
  });
}

const root = await mkdtemp(join(tmpdir(), "hepta-public-egress-"));
await chmod(root, 0o700);
const socketPath = join(root, "egress.sock");
const broker = new GrantScopedEgressBroker({
  socketPath,
  grantDigest: GRANT_DIGEST,
  allowedOrigins: [ORIGIN],
});

try {
  await broker.start();
  const status = await publicTls(socketPath);
  const observation = broker.observations.find(
    (item) => item.origin === ORIGIN && item.kind === "connect",
  );
  assert.ok(observation, "public egress observation must be retained");
  assert.notEqual(net.isIP(observation.address), 0, "public destination must resolve to an IP");

  const denied = await connect(socketPath, "example.org:443");
  assert.notEqual(
    denied.response.statusCode,
    200,
    "ungranted public CONNECT must fail closed",
  );
  denied.socket.destroy();

  process.stdout.write(
    JSON.stringify({
      schema: "hepta.browser.public-egress-target-probe.v1",
      publicDnsResolved: true,
      publicTlsValidated: true,
      grantedOrigin: ORIGIN,
      selectedAddress: observation.address,
      networkBindingDigest: observation.networkBindingDigest,
      httpStatus: status,
      ungrantedPublicOriginDenied: true,
    }) + "\n",
  );
} finally {
  await broker.close().catch(() => {});
  await rm(root, { recursive: true, force: true });
}
