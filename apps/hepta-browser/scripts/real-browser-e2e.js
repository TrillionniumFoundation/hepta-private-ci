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
  for (let attempt = 0; attempt < 250 && current.terminalObserved !== true; attempt += 1) {
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
const hanging = new Set();

const forbidden = await listen((_request, response) => {
  forbiddenHits += 1;
  response.end("forbidden network escape");
});
const forbiddenOrigin = `http://127.0.0.1:${forbidden.address().port}`;

const app = await listen((request, response) => {
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

  const closed = await host.closeProfile({
    profileId: "profile.e2e",
    principalId: "principal.e2e",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);

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
      persistedCrashReconciliation: true,
      workerSha256: sha(workerBytes),
    }) + "\n",
  );
} finally {
  for (const response of hanging) response.destroy();
  await new Promise((resolve) => app.close(resolve));
  await new Promise((resolve) => forbidden.close(resolve));
  await rm(root, { recursive: true, force: true });
}
