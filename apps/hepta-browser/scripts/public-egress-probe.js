#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import http from "node:http";
import net from "node:net";
import tls from "node:tls";
import { chmod, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { browserActionDigest } from "../src/action.js";
import { GrantScopedEgressBroker } from "../src/egress-broker.js";
import { FileBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";
import {
  LinuxBubblewrapLauncher,
  SubprocessBrowserDriver,
} from "../src/worker-driver.js";

const workerPath = resolve(process.argv[2] ?? "");
if (!process.argv[2]) {
  throw new Error("usage: public-egress-probe.js WORKER_BINARY");
}

const sha = (value) => createHash("sha256").update(value).digest("hex");
const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const WITNESS = "a".repeat(64);
const GRANT_DIGEST = sha("hepta.browser.public-egress-target.v2");
const AUTHORITY = "example.com:443";
const ORIGIN = "https://example.com";

function authority() {
  return {
    async withVerifiedUse(request, consumer) {
      return consumer({
        authorized: true,
        witnessDigest: WITNESS,
        authorityEpoch: request.authorityEpoch,
        requestDigest: request.requestDigest,
      });
    },
  };
}

function grant(action, digest) {
  return {
    grantDigest: sha("hepta.browser.public-egress-effect.v1"),
    action,
    destinationOrigin: ORIGIN,
    finalPayloadDigest: digest,
    authorityEpoch: 7,
    expiresAtMs: Date.now() + 60_000,
  };
}

function operation(action, effectGrant) {
  return {
    profileId: "profile.public-egress",
    principalId: "principal.public-egress",
    generation: 1,
    operationId: "operation.public-egress.navigate",
    pageGeneration: 0,
    typedAction: action,
    destinationOrigin: ORIGIN,
    finalPayloadDigest: browserActionDigest(action),
    effectGrantDigest: effectGrant.grantDigest,
    authorityEpoch: effectGrant.authorityEpoch,
    deadlineMs: Date.now() + 30_000,
  };
}

async function settle(host, input, receipt) {
  let current = receipt;
  for (let attempt = 0; attempt < 750 && current.terminalObserved !== true; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 20));
    current = await host.reconcileOperation(input);
  }
  return current;
}

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

const [workerBytes, bwrapBytes, prlimitBytes] = await Promise.all([
  readFile(workerPath),
  readFile("/usr/bin/bwrap"),
  readFile("/usr/bin/prlimit"),
]);
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

  // Prove the same public HTTPS path through the actual sandboxed Servo worker,
  // not only through a host-side broker client. This exercises the worker's
  // proxy configuration, private Unix relay, pinned broker destination and
  // Servo/rustls certificate validation as one target-host path.
  const driver = new SubprocessBrowserDriver({
    workerPath,
    workerDigest: sha(workerBytes),
    profileRoot: join(root, "profiles"),
    launcher: new LinuxBubblewrapLauncher({
      bwrapPath: "/usr/bin/bwrap",
      bwrapDigest: sha(bwrapBytes),
      prlimitPath: "/usr/bin/prlimit",
      prlimitDigest: sha(prlimitBytes),
    }),
  });
  const host = new BrowserProfileHost({
    driver,
    authority: authority(),
    journal: new FileBrowserOperationJournal(join(root, "browser-journal.log")),
    driverCallTimeoutMs: 20_000,
  });
  const navigateAction = {
    kind: "navigate",
    url: "https://example.com/",
    policyDigest: D1,
    expectedRevision: 1,
  };
  const navigateGrant = grant("navigate", browserActionDigest(navigateAction));
  await host.openProfile({
    profileId: "profile.public-egress",
    principalId: "principal.public-egress",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: Date.now() + 60_000,
    allowedOrigins: [ORIGIN],
    effectGrants: [navigateGrant],
  });
  const navigateInput = operation(navigateAction, navigateGrant);
  const navigation = await settle(
    host,
    navigateInput,
    await host.navigateOrAct(navigateInput),
  );
  assert.equal(
    navigation.status,
    "succeeded",
    "real Servo public HTTPS navigation must succeed",
  );
  const page = await host.observePage({
    profileId: "profile.public-egress",
    principalId: "principal.public-egress",
    generation: 1,
    observationBudget: 65_536,
  });
  assert.equal(page.origin, ORIGIN, "real Servo must remain on the granted public origin");
  assert.equal(page.originAllowed, true);
  assert.ok(
    page.semanticObservation && typeof page.semanticObservation === "object",
    "real Servo public page must produce a bounded semantic observation",
  );

  const escapeGrant = {
    ...navigateGrant,
    grantDigest: sha("hepta.browser.public-egress-escape.v1"),
    destinationOrigin: "https://example.org",
  };
  await assert.rejects(
    host.admitEffectGrant({
      profileId: "profile.public-egress",
      principalId: "principal.public-egress",
      generation: 1,
      effectGrant: escapeGrant,
    }),
    /outside the profile grant/,
  );
  await host.closeProfile({
    profileId: "profile.public-egress",
    principalId: "principal.public-egress",
    generation: 1,
  });

  process.stdout.write(
    JSON.stringify({
      schema: "hepta.browser.public-egress-target-probe.v2",
      publicDnsResolved: true,
      publicTlsValidated: true,
      realServoPublicHttps: true,
      realServoObservedOrigin: page.origin,
      realServoSemanticDigest: page.semanticDigest,
      profileScopeEscapeDenied: true,
      workerSha256: sha(workerBytes),
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
