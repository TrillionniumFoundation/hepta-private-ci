#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import http from "node:http";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { browserActionDigest } from "../src/action.js";
import { FileBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";
import {
  LinuxBubblewrapLauncher,
  SubprocessBrowserDriver,
} from "../src/worker-driver.js";

const workerPath = resolve(process.argv[2] ?? "");
if (!process.argv[2]) throw new Error("usage: real-worker-smoke.js WORKER_BINARY");

const sha = (value) => createHash("sha256").update(value).digest("hex");
const workerBytes = await readFile(workerPath);
const workerDigest = sha(workerBytes);
const bwrapBytes = await readFile("/usr/bin/bwrap");
const bwrapDigest = sha(bwrapBytes);
const prlimitBytes = await readFile("/usr/bin/prlimit");
const prlimitDigest = sha(prlimitBytes);
const root = await mkdtemp(join(tmpdir(), "hepta-servo-worker-smoke-"));
const digest = "1".repeat(64);
const witnessDigest = "a".repeat(64);

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
        witnessDigest,
        authorityEpoch: request.authorityEpoch,
        requestDigest: request.requestDigest,
      });
    },
  };
}

function grant(action, finalPayloadDigest, origin, suffix) {
  return {
    grantDigest: sha(`smoke-grant:${suffix}`),
    action,
    destinationOrigin: origin,
    finalPayloadDigest,
    authorityEpoch: 7,
    expiresAtMs: Date.now() + 90_000,
  };
}

function operation({ operationId, pageGeneration, typedAction, origin, effectGrant }) {
  return {
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    generation: 1,
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
  for (let attempt = 0; attempt < 500 && current.terminalObserved !== true; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 20));
    current = await host.reconcileOperation(input);
  }
  return current;
}

async function requirePreDispatchRejection({ host, page, typedAction, origin, suffix }) {
  const effectGrant = grant(
    typedAction.kind,
    browserActionDigest(typedAction),
    origin,
    suffix,
  );
  await host.admitEffectGrant({
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    generation: 1,
    effectGrant,
  });
  const input = operation({
    operationId: `operation.smoke.${suffix}`,
    pageGeneration: page.pageGeneration,
    typedAction,
    origin,
    effectGrant,
  });
  const receipt = await host.navigateOrAct(input);
  assert.equal(receipt.terminalObserved, true);
  assert.equal(receipt.status, "failed");
  assert.equal(receipt.observationReason, "worker_rejected_before_dispatch");
  return receipt;
}

const app = await listen((request, response) => {
  if (request.url !== "/atomic-target") {
    response.writeHead(404);
    response.end("not found");
    return;
  }
  response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  response.end(`<!doctype html>
<html><head><title>Atomic target identity</title></head>
<body>
<button aria-label="Native click target" onclick="document.getElementById('native-result').textContent='original-fired'">Native</button>
<button id="replacement-target" aria-label="Replacement target" onclick="document.getElementById('replacement-result').textContent='old-node-fired'">Replace me</button>
<input aria-label="Readonly text target" type="text" value="locked" readonly oninput="document.getElementById('policy-result').textContent='readonly-mutated'">
<input aria-label="Checkbox type target" type="checkbox" onchange="document.getElementById('policy-result').textContent='checkbox-mutated'">
<input id="file-target" aria-label="File chooser target" type="file" onchange="document.getElementById('policy-result').textContent='file-mutated'">
<a id="download-target" aria-label="Download target" href="/download.bin" download onclick="document.getElementById('policy-result').textContent='download-fired'">Download</a>
<div id="native-result">native-pending</div>
<div id="replacement-result">replacement-pending</div>
<div id="policy-result">policy-pending</div>
<div id="bridge-hook-state">bridge-hooks-clean</div>
<div id="phase">initial</div>
<script>
setTimeout(() => {
  const hookState = document.getElementById('bridge-hook-state');
  const nativeLowerCase = String.prototype.toLowerCase;
  const nativePush = Array.prototype.push;
  HTMLElement.prototype.click = function () {
    document.getElementById('native-result').textContent = 'malicious-prototype-fired';
  };
  String.prototype.toLowerCase = function () {
    const value = String(this);
    if (value === 'file') return 'text';
    return Reflect.apply(nativeLowerCase, value, []);
  };
  Array.prototype.push = function (...items) {
    for (const item of items) {
      if (item && typeof item === 'object' && typeof item.handle === 'string') {
        hookState.textContent = 'bridge-handle-leaked';
      }
    }
    return Reflect.apply(nativePush, this, items);
  };
  Object.prototype.toJSON = function () {
    if (this && this.ok === false) {
      hookState.textContent = 'bridge-failure-forged';
      return { ok: true, acted: true };
    }
    return this;
  };
  document.getElementById('phase').textContent = 'prototype-patched';
}, 500);
setTimeout(() => {
  const prior = document.getElementById('replacement-target');
  const replacement = prior.cloneNode(true);
  replacement.setAttribute('onclick', "document.getElementById('replacement-result').textContent='replacement-fired'");
  prior.replaceWith(replacement);
  document.getElementById('phase').textContent = 'node-replaced';
}, 12000);
</script>
</body></html>`);
});
const origin = `http://127.0.0.1:${app.address().port}`;

const driver = new SubprocessBrowserDriver({
  workerPath,
  workerDigest,
  profileRoot: join(root, "profiles"),
  launcher: new LinuxBubblewrapLauncher({
    bwrapPath: "/usr/bin/bwrap",
    bwrapDigest,
    prlimitPath: "/usr/bin/prlimit",
    prlimitDigest,
  }),
  allowPrivateNetworkForTests: true,
});
const host = new BrowserProfileHost({
  driver,
  authority: authority(),
  journal: new FileBrowserOperationJournal(join(root, "journal.log")),
  driverCallTimeoutMs: 10_000,
});

try {
  const navigateAction = {
    kind: "navigate",
    url: `${origin}/atomic-target`,
    policyDigest: digest,
    expectedRevision: 1,
  };
  const navigateGrant = grant(
    "navigate",
    browserActionDigest(navigateAction),
    origin,
    "navigate",
  );
  const started = await host.openProfile({
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    manifestDigest: digest,
    grantDigest: "2".repeat(64),
    generation: 1,
    expiresAtMs: Date.now() + 120_000,
    allowedOrigins: [origin],
    effectGrants: [navigateGrant],
  });
  assert.match(started.processId, /^servo\.pid\./);

  const navigateInput = operation({
    operationId: "operation.smoke.navigate",
    pageGeneration: 0,
    typedAction: navigateAction,
    origin,
    effectGrant: navigateGrant,
  });
  const navigated = await settle(
    host,
    navigateInput,
    await host.navigateOrAct(navigateInput),
  );
  assert.equal(navigated.status, "succeeded");

  let page = await host.observePage({
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    generation: 1,
    observationBudget: 32_768,
  });
  const nativeTarget = page.semanticObservation.controls.find(
    (control) => control.ariaLabel === "Native click target",
  );
  assert.ok(nativeTarget?.selector, "native click target must be observed");

  await new Promise((resolve) => setTimeout(resolve, 1_000));
  const clickAction = { kind: "click", selector: nativeTarget.selector };
  const clickGrant = grant(
    "click",
    browserActionDigest(clickAction),
    origin,
    "native-click",
  );
  await host.admitEffectGrant({
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    generation: 1,
    effectGrant: clickGrant,
  });
  const clickInput = operation({
    operationId: "operation.smoke.native-click",
    pageGeneration: page.pageGeneration,
    typedAction: clickAction,
    origin,
    effectGrant: clickGrant,
  });
  const clicked = await settle(host, clickInput, await host.navigateOrAct(clickInput));
  assert.equal(clicked.status, "succeeded");

  page = await host.observePage({
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    generation: 1,
    observationBudget: 32_768,
  });
  assert.match(page.semanticObservation.visibleText, /original-fired/);
  assert.doesNotMatch(page.semanticObservation.visibleText, /malicious-prototype-fired/);
  assert.match(page.semanticObservation.visibleText, /bridge-hooks-clean/);
  const replacementTarget = page.semanticObservation.controls.find(
    (control) => control.ariaLabel === "Replacement target",
  );
  assert.ok(replacementTarget?.selector, "replacement target must be observed");

  const readonlyTarget = page.semanticObservation.controls.find(
    (control) => control.ariaLabel === "Readonly text target",
  );
  const checkboxTarget = page.semanticObservation.controls.find(
    (control) => control.ariaLabel === "Checkbox type target",
  );
  assert.ok(readonlyTarget?.selector, "readonly text target must be observed");
  assert.equal(readonlyTarget.readOnly, true);
  assert.ok(checkboxTarget?.selector, "checkbox target must be observed");
  assert.equal(
    page.semanticObservation.controls.some(
      (control) => control.ariaLabel === "File chooser target",
    ),
    false,
  );
  assert.equal(
    page.semanticObservation.links.some((link) => link.text === "Download"),
    false,
  );

  await requirePreDispatchRejection({
    host,
    page,
    typedAction: {
      kind: "type",
      selector: readonlyTarget.selector,
      text: "must-not-write",
    },
    origin,
    suffix: "readonly-type",
  });
  await requirePreDispatchRejection({
    host,
    page,
    typedAction: {
      kind: "type",
      selector: checkboxTarget.selector,
      text: "must-not-coerce",
    },
    origin,
    suffix: "checkbox-type",
  });
  await requirePreDispatchRejection({
    host,
    page,
    typedAction: {
      kind: "click",
      selector: "html:nth-of-type(1)>body:nth-of-type(1)>input:nth-of-type(3)",
    },
    origin,
    suffix: "file-click",
  });
  await requirePreDispatchRejection({
    host,
    page,
    typedAction: {
      kind: "click",
      selector: "html:nth-of-type(1)>body:nth-of-type(1)>a:nth-of-type(1)",
    },
    origin,
    suffix: "download-click",
  });

  await new Promise((resolve) => setTimeout(resolve, 12_500));
  const replacementAction = {
    kind: "click",
    selector: replacementTarget.selector,
  };
  const replacementGrant = grant(
    "click",
    browserActionDigest(replacementAction),
    origin,
    "replacement-click",
  );
  await host.admitEffectGrant({
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    generation: 1,
    effectGrant: replacementGrant,
  });
  const replacementInput = operation({
    operationId: "operation.smoke.replacement-click",
    pageGeneration: page.pageGeneration,
    typedAction: replacementAction,
    origin,
    effectGrant: replacementGrant,
  });
  const replacementReceipt = await host.navigateOrAct(replacementInput);
  assert.equal(replacementReceipt.terminalObserved, true);
  assert.equal(replacementReceipt.status, "failed");
  assert.equal(
    replacementReceipt.observationReason,
    "worker_rejected_before_dispatch",
  );

  const finalPage = await host.observePage({
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    generation: 1,
    observationBudget: 32_768,
  });
  assert.match(finalPage.semanticObservation.visibleText, /node-replaced/);
  assert.match(finalPage.semanticObservation.visibleText, /policy-pending/);
  assert.match(finalPage.semanticObservation.visibleText, /bridge-hooks-clean/);
  assert.doesNotMatch(finalPage.semanticObservation.visibleText, /replacement-fired/);
  assert.doesNotMatch(finalPage.semanticObservation.visibleText, /old-node-fired/);
  assert.doesNotMatch(finalPage.semanticObservation.visibleText, /readonly-mutated/);
  assert.doesNotMatch(finalPage.semanticObservation.visibleText, /checkbox-mutated/);
  assert.doesNotMatch(finalPage.semanticObservation.visibleText, /file-mutated/);
  assert.doesNotMatch(finalPage.semanticObservation.visibleText, /download-fired/);
  assert.doesNotMatch(finalPage.semanticObservation.visibleText, /bridge-handle-leaked/);
  assert.doesNotMatch(finalPage.semanticObservation.visibleText, /bridge-failure-forged/);

  const stopped = await host.closeProfile({
    profileId: "profile.smoke",
    principalId: "principal.smoke",
    generation: 1,
  });
  assert.equal(stopped.terminalObserved, true);

  process.stdout.write(
    JSON.stringify({
      schema: "hepta.browser.real-worker-smoke.v1",
      workerSha256: workerDigest,
      currentPinWorkerBooted: true,
      privateProtocolRoundTrip: true,
      sandboxedStartStop: true,
      privateAtomicActionBridge: true,
      pageRealmMonkeypatchBypassed: true,
      pagePrototypeHooksIsolated: true,
      failureSerializationCannotForgeSuccess: true,
      privateHandlesNotLeakedThroughArrayHooks: true,
      identicalShapeNodeReplacementRejected: true,
      nonTextTypeRejectedBeforeDispatch: true,
      readOnlyTypeRejectedBeforeDispatch: true,
      fileChooserAndDownloadExcluded: true,
    }) + "\n",
  );
} finally {
  await new Promise((resolve) => app.close(resolve));
  await rm(root, { recursive: true, force: true });
}
