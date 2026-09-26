#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const root = resolve(fileURLToPath(new URL("../../..", import.meta.url)));
const outputPath = resolve(
  root,
  "docs/modules/browser.servo/GENERATED_SOURCE_REGISTRY.json",
);

const RPCS = [
  "open_profile",
  "admit_effect_grant",
  "observe_page",
  "navigate_or_act",
  "reconcile_operation",
  "reconcile_persisted_operation",
  "close_profile",
];
const ACTIONS = [
  "navigate",
  "click",
  "type",
  "credential",
  "upload",
  "focus",
  "scroll",
  "wait",
  "download",
];
const EXECUTABLE_ACTIONS = ["navigate", "click", "type", "focus", "scroll", "wait"];
const FAIL_CLOSED_ACTIONS = ["credential", "upload", "download"];
const SOURCE_PATHS = [
  "apps/hepta-browser/src/action.js",
  "apps/hepta-browser/src/agentd-protocol.js",
  "apps/hepta-browser/src/agentd-service-main.js",
  "apps/hepta-browser/src/agentd-service.js",
  "apps/hepta-browser/src/bridge.js",
  "apps/hepta-browser/src/egress-broker.js",
  "apps/hepta-browser/src/journal.js",
  "apps/hepta-browser/src/journal-core.js",
  "apps/hepta-browser/src/persisted-reconciler.js",
  "apps/hepta-browser/src/runtime-boundary.js",
  "apps/hepta-browser/src/runtime-contract.js",
  "apps/hepta-browser/src/runtime-host.js",
  "apps/hepta-browser/src/runtime.js",
  "apps/hepta-browser/src/worker-driver.js",
  "apps/hepta-browser/src/worker-protocol.js",
  "apps/hepta-browser/servo-worker/Cargo.toml",
  "apps/hepta-browser/servo-worker/Cargo.lock",
  "apps/hepta-browser/servo-worker/src/main.rs",
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function quotedItems(source, pattern, name) {
  const match = source.match(pattern);
  assert(match, `${name} registry was not found`);
  return [...match[1].matchAll(/"([a-z_]+)"/g)].map((entry) => entry[1]);
}

function sameArray(actual, expected, name) {
  assert(
    JSON.stringify(actual) === JSON.stringify(expected),
    `${name} drifted: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`,
  );
}

async function text(path) {
  return readFile(resolve(root, path), "utf8");
}

function gitBlob(path) {
  return execFileSync("git", ["hash-object", path], {
    cwd: root,
    encoding: "utf8",
  }).trim();
}

const service = await text("apps/hepta-browser/src/agentd-service.js");
const action = await text("apps/hepta-browser/src/action.js");
const worker = await text("apps/hepta-browser/servo-worker/src/main.rs");
const runtime = await text("apps/hepta-browser/src/runtime-host.js");
const driver = await text("apps/hepta-browser/src/worker-driver.js");
const egress = await text("apps/hepta-browser/src/egress-broker.js");
const journal = await text("apps/hepta-browser/src/journal.js");

const rpcMethods = quotedItems(
  service,
  /const SERVICE_METHODS = new Set\(\[([\s\S]*?)\]\);/,
  "Browser RPC",
);
sameArray(rpcMethods, RPCS, "Browser RPC closed world");

const actionKinds = [...action.matchAll(/case "([a-z_]+)":/g)].map((entry) => entry[1]);
sameArray(actionKinds, ACTIONS, "typed Browser action closed world");

for (const name of EXECUTABLE_ACTIONS) {
  assert(worker.includes(`"${name}"`), `Servo worker lacks ${name} action`);
}
for (const name of FAIL_CLOSED_ACTIONS) {
  assert(worker.includes(`"${name}"`), `Servo worker lacks fail-closed ${name} action`);
}

const markers = {
  workerAdmissionReceipt:
    worker.includes("dispatch_boundary") &&
    driver.includes("dispatch_boundary"),
  pageRevisionRevalidation:
    worker.includes("navigationEpoch") &&
    worker.includes("actionableSurfaceDigest"),
  semanticObservation:
    worker.includes("visibleText") &&
    worker.includes("forms") &&
    worker.includes("links"),
  grantScopedEgress:
    egress.includes("MAX_DNS_ANSWERS") &&
    egress.includes("blocked.addSubnet") &&
    egress.includes("ClientHello"),
  persistedReconciliation: runtime.includes("reconcilePersistedOperation"),
  monotonicJournalOwner:
    journal.includes("BrowserJournalOwnerLockedError") &&
    journal.includes("foldObservation"),
};
for (const [name, present] of Object.entries(markers)) {
  assert(present, `Browser capability marker ${name} is absent`);
}

const sourceBlobs = Object.fromEntries(
  SOURCE_PATHS.map((path) => [path, gitBlob(path)]),
);
const registry = {
  schema: "hepta.browser.generated-source-registry.v1",
  schemaVersion: 1,
  module: "browser.servo",
  rpcRegistry: rpcMethods,
  workerCapabilityMatrix: {
    registeredActions: actionKinds,
    executableActions: EXECUTABLE_ACTIONS,
    failClosedActions: FAIL_CLOSED_ACTIONS,
    credentialBrokerConnected: false,
    uploadBrokerConnected: false,
    downloadObserverConnected: false,
    networkControlListener: false,
    callerProvidedJavaScript: false,
    workerAdmissionReceipt: markers.workerAdmissionReceipt,
    pageRevisionRevalidation: markers.pageRevisionRevalidation,
    semanticObservation: markers.semanticObservation,
    grantScopedEgress: markers.grantScopedEgress,
    persistedReconciliation: markers.persistedReconciliation,
    monotonicJournalOwner: markers.monotonicJournalOwner,
  },
  sourceBlobs,
};
const rendered = `${JSON.stringify(registry, null, 2)}\n`;

if (process.argv.includes("--check")) {
  const current = await readFile(outputPath, "utf8");
  assert(current === rendered, "generated Browser source registry is stale");
  process.stdout.write(rendered);
} else {
  await writeFile(outputPath, rendered, "utf8");
  process.stdout.write(rendered);
}
