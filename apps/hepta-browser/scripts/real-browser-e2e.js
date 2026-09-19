#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import http from "node:http";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { browserActionDigest } from "../src/action.js";
import { FileBrowserOperationJournal } from "../src/journal.js";
import { createFilePersistedEffectReconciler } from "../src/persisted-reconciler.js";
import { BrowserProfileHost } from "../src/runtime.js";
import {
  LinuxBubblewrapLauncher,
  PooledSubprocessBrowserDriver,
  SubprocessBrowserDriver,
} from "../src/worker-driver.js";

const workerPath = resolve(process.argv[2] ?? "");
if (!process.argv[2]) throw new Error("usage: real-browser-e2e.js WORKER_BINARY");

const sha = (value) => createHash("sha256").update(value).digest("hex");
const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const WITNESS = "a".repeat(64);

function listen(handler) {
  const server = http.createServer(handler);
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

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

function revocationRaceAuthority() {
  let enteredResolve;
  let releaseResolve;
  let exitedResolve;
  let inFence = false;
  let revoked = false;
  const entered = new Promise((resolve) => { enteredResolve = resolve; });
  const release = new Promise((resolve) => { releaseResolve = resolve; });
  const exited = new Promise((resolve) => { exitedResolve = resolve; });
  return {
    adapter: {
      async withVerifiedUse(request, consumer) {
        if (revoked) throw new TypeError("final-use authority was revoked");
        inFence = true;
        enteredResolve();
        await release;
        try {
          return await consumer({
            authorized: true,
            witnessDigest: WITNESS,
            authorityEpoch: request.authorityEpoch,
            requestDigest: request.requestDigest,
          });
        } finally {
          inFence = false;
          exitedResolve();
        }
      },
    },
    entered,
    release() {
      releaseResolve();
    },
    async revoke() {
      if (inFence) await exited;
      revoked = true;
    },
  };
}

function grant(action, digest, origin, suffix) {
  return {
    grantDigest: sha(`grant:${suffix}`),
    action,
    destinationOrigin: origin,
    finalPayloadDigest: digest,
    authorityEpoch: 7,
    expiresAtMs: Date.now() + 60_000,
  };
}

function operation({
  profileId,
  principalId,
  generation,
  operationId,
  pageGeneration,
  typedAction,
  origin,
  effectGrant,
}) {
  return {
    profileId,
    principalId,
    generation,
    operationId,
    pageGeneration,
    typedAction,
    destinationOrigin: origin,
    finalPayloadDigest: browserActionDigest(typedAction),
    effectGrantDigest: effectGrant.grantDigest,
    authorityEpoch: effectGrant.authorityEpoch,
    deadlineMs: Date.now() + 20_000,
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

const workerBytes = await readFile(workerPath);
const bwrapPath = "/usr/bin/bwrap";
const prlimitPath = "/usr/bin/prlimit";
const [bwrapBytes, prlimitBytes] = await Promise.all([
  readFile(bwrapPath),
  readFile(prlimitPath),
]);
const root = await mkdtemp(join(tmpdir(), "hepta-browser-real-e2e-"));
await chmod(root, 0o700);
let forbiddenHits = 0;
let profileACookieHeader = null;
let profileBCookieHeader = null;
const hanging = new Set();

const forbidden = await listen((_request, response) => {
  forbiddenHits += 1;
  response.end("forbidden network escape");
});
const forbiddenOrigin = `http://127.0.0.1:${forbidden.address().port}`;

const app = await listen((request, response) => {
  if (request.url === "/redirect-forbidden") {
    response.writeHead(302, { location: forbiddenOrigin + "/redirect-escape" });
    response.end();
    return;
  }
  if (request.url === "/cookie-set") {
    response.writeHead(200, {
      "content-type": "text/html; charset=utf-8",
      "set-cookie": "heptaProfile=alpha; Path=/; SameSite=Lax",
    });
    response.end("<html><body>cookie-set</body></html>");
    return;
  }
  if (request.url === "/cookie-echo-a") {
    profileACookieHeader = request.headers.cookie ?? "";
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end("<html><body>cookie-echo-a</body></html>");
    return;
  }
  if (request.url === "/cookie-echo-b") {
    profileBCookieHeader = request.headers.cookie ?? "";
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    response.end("<html><body>cookie-echo-b</body></html>");
    return;
  }
  if (request.url === "/never") {
    response.writeHead(200, { "content-type": "text/html" });
    response.write("<html><body>never terminal</body>");
    hanging.add(response);
    response.on("close", () => hanging.delete(response));
    return;
  }
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(`<!doctype html>
<html><head><title>Hepta Browser E2E</title></head>
<body>
<label>Name <input name="name" type="text" placeholder="name"></label>
<button aria-label="Commit value" onclick="document.getElementById('out').textContent=document.querySelector('input[name=name]').value">Commit</button>
<div id="out">empty</div>
<script>
fetch(${JSON.stringify(forbiddenOrigin + "/should-not-connect")}).catch(()=>{});
</script>
</body></html>`);
});
const origin = `http://127.0.0.1:${app.address().port}`;

function launcher() {
  return new LinuxBubblewrapLauncher({
    bwrapPath,
    bwrapDigest: sha(bwrapBytes),
    prlimitPath,
    prlimitDigest: sha(prlimitBytes),
  });
}

function realPool(profileRoot, maxProfiles = 2) {
  return new PooledSubprocessBrowserDriver({
    workerPath,
    workerDigest: sha(workerBytes),
    profileRoot,
    launcher: launcher(),
    maxProfiles,
    allowPrivateNetworkForTests: true,
  });
}

function realDriver(profileRoot, persistedReconciler = null) {
  return new SubprocessBrowserDriver({
    workerPath,
    workerDigest: sha(workerBytes),
    profileRoot,
    launcher: launcher(),
    persistedReconciler,
    allowPrivateNetworkForTests: true,
  });
}

try {
  // Full live profile lifecycle on one real Servo worker.
  const driver = realDriver(join(root, "profiles-live"));
  const journal = new FileBrowserOperationJournal(join(root, "live-journal.log"));
  const host = new BrowserProfileHost({
    driver,
    authority: authority(),
    journal,
    driverCallTimeoutMs: 10_000,
  });
  const navigateAction = {
    kind: "navigate",
    url: `${origin}/page`,
    policyDigest: D1,
    expectedRevision: 1,
  };
  const navigateGrant = grant("navigate", browserActionDigest(navigateAction), origin, "nav");
  await host.openProfile({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: Date.now() + 120_000,
    allowedOrigins: [origin],
    effectGrants: [navigateGrant],
  });
  const navInput = operation({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    operationId: "operation.navigate",
    pageGeneration: 0,
    typedAction: navigateAction,
    origin,
    effectGrant: navigateGrant,
  });
  const nav = await settle(host, navInput, await host.navigateOrAct(navInput));
  assert.equal(nav.status, "succeeded");

  let page = await host.observePage({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    observationBudget: 65_536,
  });
  const inputControl = page.semanticObservation.controls.find(
    (control) => control.tag === "input" && control.name === "name",
  );
  const buttonControl = page.semanticObservation.controls.find(
    (control) => control.tag === "button" && control.ariaLabel === "Commit value",
  );
  assert.ok(inputControl?.selector, "real Servo observation must expose the text input");
  assert.ok(buttonControl?.selector, "real Servo observation must expose the action button");

  const typeAction = {
    kind: "type",
    selector: inputControl.selector,
    text: "Hepta E2E",
  };
  const typeGrant = grant("type", browserActionDigest(typeAction), origin, "type");
  await host.admitEffectGrant({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    effectGrant: typeGrant,
  });
  const typeInput = operation({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    operationId: "operation.type",
    pageGeneration: page.pageGeneration,
    typedAction: typeAction,
    origin,
    effectGrant: typeGrant,
  });
  const typed = await settle(host, typeInput, await host.navigateOrAct(typeInput));
  assert.equal(typed.status, "succeeded");

  page = await host.observePage({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    observationBudget: 65_536,
  });
  const refreshedButton = page.semanticObservation.controls.find(
    (control) => control.tag === "button" && control.ariaLabel === "Commit value",
  );
  assert.ok(refreshedButton?.selector);
  const clickAction = { kind: "click", selector: refreshedButton.selector };
  const clickGrant = grant("click", browserActionDigest(clickAction), origin, "click");
  await host.admitEffectGrant({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    effectGrant: clickGrant,
  });
  const clickInput = operation({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    operationId: "operation.click",
    pageGeneration: page.pageGeneration,
    typedAction: clickAction,
    origin,
    effectGrant: clickGrant,
  });
  const clicked = await settle(host, clickInput, await host.navigateOrAct(clickInput));
  assert.equal(clicked.status, "succeeded");

  page = await host.observePage({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    observationBudget: 65_536,
  });
  assert.match(page.semanticObservation.visibleText, /Hepta E2E/);
  await new Promise((resolve) => setTimeout(resolve, 250));
  assert.equal(forbiddenHits, 0, "cross-origin subresource must not escape the grant broker");

  page = await host.observePage({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    observationBudget: 65_536,
  });
  const redirectAction = {
    kind: "navigate",
    url: `${origin}/redirect-forbidden`,
    policyDigest: D1,
    expectedRevision: 3,
  };
  const redirectGrant = grant("navigate", browserActionDigest(redirectAction), origin, "redirect");
  await host.admitEffectGrant({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    effectGrant: redirectGrant,
  });
  const redirectInput = operation({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
    operationId: "operation.redirect",
    pageGeneration: page.pageGeneration,
    typedAction: redirectAction,
    origin,
    effectGrant: redirectGrant,
  });
  const redirectReceipt = await settle(
    host,
    redirectInput,
    await host.navigateOrAct(redirectInput),
  );
  assert.equal(redirectReceipt.terminalObserved, true);
  assert.equal(
    ["succeeded", "failed"].includes(redirectReceipt.status),
    true,
    "redirect denial must reach a terminal local observation before profile close",
  );
  await new Promise((resolve) => setTimeout(resolve, 250));
  assert.equal(forbiddenHits, 0, "redirect target outside the origin grant must not be reached");

  const closed = await host.closeProfile({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);

  // Two simultaneous profile generations must not share cookies.
  const isolationDriver = realPool(join(root, "profiles-isolation"), 2);
  const isolationHost = new BrowserProfileHost({
    driver: isolationDriver,
    authority: authority(),
    journal: new FileBrowserOperationJournal(join(root, "isolation-journal.log")),
    driverCallTimeoutMs: 10_000,
    maxActiveProfiles: 2,
  });
  const isoAAction = {
    kind: "navigate",
    url: `${origin}/cookie-set`,
    policyDigest: D1,
    expectedRevision: 11,
  };
  const isoBAction = {
    kind: "navigate",
    url: `${origin}/cookie-echo-b`,
    policyDigest: D1,
    expectedRevision: 13,
  };
  const isoAGrant = grant("navigate", browserActionDigest(isoAAction), origin, "iso-a");
  const isoBGrant = grant("navigate", browserActionDigest(isoBAction), origin, "iso-b");
  await isolationHost.openProfile({
    profileId: "profile.iso.a",
    principalId: "principal.iso.a",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: Date.now() + 120_000,
    allowedOrigins: [origin],
    effectGrants: [isoAGrant],
  });
  await isolationHost.openProfile({
    profileId: "profile.iso.b",
    principalId: "principal.iso.b",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: Date.now() + 120_000,
    allowedOrigins: [origin],
    effectGrants: [isoBGrant],
  });
  const isoAInput = operation({
    profileId: "profile.iso.a",
    principalId: "principal.iso.a",
    generation: 1,
    operationId: "operation.iso.a",
    pageGeneration: 0,
    typedAction: isoAAction,
    origin,
    effectGrant: isoAGrant,
  });
  const isoBInput = operation({
    profileId: "profile.iso.b",
    principalId: "principal.iso.b",
    generation: 1,
    operationId: "operation.iso.b",
    pageGeneration: 0,
    typedAction: isoBAction,
    origin,
    effectGrant: isoBGrant,
  });
  assert.equal((await settle(isolationHost, isoAInput, await isolationHost.navigateOrAct(isoAInput))).status, "succeeded");

  const isoAPage = await isolationHost.observePage({
    profileId: "profile.iso.a",
    principalId: "principal.iso.a",
    generation: 1,
    observationBudget: 16_384,
  });
  const isoAEchoAction = {
    kind: "navigate",
    url: `${origin}/cookie-echo-a`,
    policyDigest: D1,
    expectedRevision: 12,
  };
  const isoAEchoGrant = grant("navigate", browserActionDigest(isoAEchoAction), origin, "iso-a-echo");
  await isolationHost.admitEffectGrant({
    profileId: "profile.iso.a",
    principalId: "principal.iso.a",
    generation: 1,
    effectGrant: isoAEchoGrant,
  });
  const isoAEchoInput = operation({
    profileId: "profile.iso.a",
    principalId: "principal.iso.a",
    generation: 1,
    operationId: "operation.iso.a.echo",
    pageGeneration: isoAPage.pageGeneration,
    typedAction: isoAEchoAction,
    origin,
    effectGrant: isoAEchoGrant,
  });
  assert.equal(
    (await settle(
      isolationHost,
      isoAEchoInput,
      await isolationHost.navigateOrAct(isoAEchoInput),
    )).status,
    "succeeded",
  );
  assert.equal(
    profileACookieHeader?.includes("heptaProfile=alpha"),
    true,
    "profile A must retain its own cookie before cross-profile isolation is claimed",
  );

  assert.equal((await settle(isolationHost, isoBInput, await isolationHost.navigateOrAct(isoBInput))).status, "succeeded");
  assert.equal(
    profileBCookieHeader?.includes("heptaProfile=alpha"),
    false,
    "profile B must not receive profile A cookie",
  );
  await isolationHost.closeProfile({
    profileId: "profile.iso.a",
    principalId: "principal.iso.a",
    generation: 1,
  });
  await isolationHost.closeProfile({
    profileId: "profile.iso.b",
    principalId: "principal.iso.b",
    generation: 1,
  });

  // A revocation update that begins after final-use entry must not become
  // current until the real Servo worker reaches the admission boundary.
  const race = revocationRaceAuthority();
  const raceDriver = realDriver(join(root, "profiles-revocation-race"));
  const raceJournal = new FileBrowserOperationJournal(join(root, "revocation-race-journal.log"));
  const raceHost = new BrowserProfileHost({
    driver: raceDriver,
    authority: race.adapter,
    journal: raceJournal,
    driverCallTimeoutMs: 10_000,
  });
  const raceAction = {
    kind: "navigate",
    url: `${origin}/page`,
    policyDigest: D1,
    expectedRevision: 3,
  };
  const raceGrant = grant("navigate", browserActionDigest(raceAction), origin, "race");
  await raceHost.openProfile({
    profileId: "profile.race",
    principalId: "principal.race",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: Date.now() + 60_000,
    allowedOrigins: [origin],
    effectGrants: [raceGrant],
  });
  const raceInput = operation({
    profileId: "profile.race",
    principalId: "principal.race",
    generation: 1,
    operationId: "operation.race",
    pageGeneration: 0,
    typedAction: raceAction,
    origin,
    effectGrant: raceGrant,
  });
  const racedEffect = raceHost.navigateOrAct(raceInput);
  await race.entered;
  let revocationSettled = false;
  const revocation = race.revoke().then(() => {
    revocationSettled = true;
  });
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.equal(
    revocationSettled,
    false,
    "revocation must remain blocked while final-use covers real worker admission",
  );
  race.release();
  const raceReceipt = await settle(raceHost, raceInput, await racedEffect);
  await revocation;
  assert.equal(revocationSettled, true);
  assert.equal(raceReceipt.terminalObserved, true);
  await raceHost.closeProfile({
    profileId: "profile.race",
    principalId: "principal.race",
    generation: 1,
  });

  // Crash/worker-loss path: preserve indeterminate identity, then converge only
  // through a separately supplied trusted persisted observation.
  const crashDriver = realDriver(join(root, "profiles-crash"));
  const crashJournal = new FileBrowserOperationJournal(join(root, "crash-journal.log"));
  const crashHost = new BrowserProfileHost({
    driver: crashDriver,
    authority: authority(),
    journal: crashJournal,
    driverCallTimeoutMs: 2_000,
  });
  const neverAction = {
    kind: "navigate",
    url: `${origin}/never`,
    policyDigest: D1,
    expectedRevision: 2,
  };
  const neverGrant = grant("navigate", browserActionDigest(neverAction), origin, "never");
  const crashSession = await crashHost.openProfile({
    profileId: "profile.crash",
    principalId: "principal.crash",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: Date.now() + 120_000,
    allowedOrigins: [origin],
    effectGrants: [neverGrant],
  });
  const neverInput = operation({
    profileId: "profile.crash",
    principalId: "principal.crash",
    generation: 1,
    operationId: "operation.never",
    pageGeneration: 0,
    typedAction: neverAction,
    origin,
    effectGrant: neverGrant,
  });
  const unknown = await crashHost.navigateOrAct(neverInput);
  assert.equal(unknown.terminalObserved, false);
  await crashDriver.contain({
    profileId: "profile.crash",
    processId: crashSession.processId,
    generation: 1,
  });
  const durable = await crashJournal.getOperation("profile.crash", 1, "operation.never");
  assert.equal(durable.terminalObserved, false);

  const receiptRoot = join(root, "trusted-reconciliation");
  await import("node:fs/promises").then(({ mkdir }) => mkdir(receiptRoot, { mode: 0o700 }));
  const trustedOutcome = sha("trusted external terminal observation");
  await writeFile(
    join(receiptRoot, "profile.crash.1.operation.never.json"),
    JSON.stringify({
      schema: "hepta.browser.persisted-effect-observation.v1",
      version: 1,
      profileId: "profile.crash",
      profileGeneration: 1,
      operationId: "operation.never",
      requestDigest: durable.requestDigest,
      semanticDigest: durable.semanticDigest,
      terminalObserved: true,
      status: "failed",
      outcomeDigest: trustedOutcome,
    }),
    { mode: 0o600 },
  );
  const replacement = new BrowserProfileHost({
    driver: realDriver(
      join(root, "profiles-replacement"),
      createFilePersistedEffectReconciler(receiptRoot),
    ),
    authority: authority(),
    journal: crashJournal,
    driverCallTimeoutMs: 2_000,
  });
  const recovered = await replacement.reconcilePersistedOperation({
    profileId: "profile.crash",
    principalId: "principal.crash",
    generation: 1,
    operationId: "operation.never",
  });
  assert.equal(recovered.terminalObserved, true);
  assert.equal(recovered.status, "failed");
  assert.equal(recovered.outcomeDigest, trustedOutcome);

  process.stdout.write(
    JSON.stringify({
      schema: "hepta.browser.real-servo-e2e.v1",
      openNavigateObserveTypeClickClose: true,
      exactOriginEgressObserved: true,
      crossOriginSubresourceDenied: true,
      redirectEscapeDenied: true,
      revocationRaceBlockedUntilDispatchBoundary: true,
      persistedCrashReconciliation: true,
      crossProfileCookieIsolation: true,
      workerSha256: sha(workerBytes),
    }) + "\n",
  );
} finally {
  for (const response of hanging) response.destroy();
  await new Promise((resolve) => app.close(resolve));
  await new Promise((resolve) => forbidden.close(resolve));
  await rm(root, { recursive: true, force: true });
}
