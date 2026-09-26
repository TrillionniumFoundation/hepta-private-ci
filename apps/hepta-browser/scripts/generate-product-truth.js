#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const OUTPUT = resolve(ROOT, "apps/hepta-browser/generated/PRODUCT_TRUTH.json");
const SERVO_PIN = "b5a1f5e6ec6f8685d40cd389802ced7abe4980f6";
const OPERATIONS = Object.freeze([
  "open_profile",
  "admit_effect_grant",
  "observe_page",
  "navigate_or_act",
  "reconcile_operation",
  "reconcile_persisted_operation",
  "close_profile",
]);
const CAPABILITIES = Object.freeze([
  Object.freeze({ action: "navigate", ingress: "implemented", worker: "implemented", qualification: "source_present_target_evidence_required" }),
  Object.freeze({ action: "click", ingress: "implemented", worker: "implemented", qualification: "source_present_target_evidence_required" }),
  Object.freeze({ action: "type", ingress: "implemented", worker: "implemented", qualification: "source_present_target_evidence_required" }),
  Object.freeze({ action: "focus", ingress: "implemented", worker: "implemented", qualification: "source_present_target_evidence_required" }),
  Object.freeze({ action: "scroll", ingress: "implemented", worker: "implemented", qualification: "source_present_target_evidence_required" }),
  Object.freeze({ action: "wait", ingress: "implemented", worker: "implemented", qualification: "source_present_target_evidence_required" }),
  Object.freeze({ action: "credential", ingress: "fail_closed_future_capability", worker: "not_reachable", qualification: "not_enabled" }),
  Object.freeze({ action: "upload", ingress: "fail_closed_future_capability", worker: "not_reachable", qualification: "not_enabled" }),
  Object.freeze({ action: "download", ingress: "fail_closed_future_capability", worker: "not_reachable", qualification: "not_enabled" }),
]);
const SOURCE_PATHS = Object.freeze([
  "apps/hepta-browser/scripts/generate-product-truth.js",
  "apps/hepta-browser/src/action.js",
  "apps/hepta-browser/src/agentd-protocol.js",
  "apps/hepta-browser/src/agentd-service-main.js",
  "apps/hepta-browser/src/agentd-service.js",
  "apps/hepta-browser/src/effect-admission.js",
  "apps/hepta-browser/src/egress-broker.js",
  "apps/hepta-browser/src/journal-owner.js",
  "apps/hepta-browser/src/journal.js",
  "apps/hepta-browser/src/persisted-reconciler.js",
  "apps/hepta-browser/src/runtime-contract.js",
  "apps/hepta-browser/src/runtime-host.js",
  "apps/hepta-browser/src/runtime.js",
  "apps/hepta-browser/src/worker-driver.js",
  "apps/hepta-browser/src/worker-protocol.js",
  "apps/hepta-browser/servo-worker/Cargo.lock",
  "apps/hepta-browser/servo-worker/Cargo.toml",
  "apps/hepta-browser/servo-worker/src/main.rs",
  "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs",
  "codex-rs/hepta-agentd/src/browser_revocation_feed.rs",
  "codex-rs/hepta-agentd/src/browser_servo_admission_frame.rs",
  "codex-rs/hepta-agentd/src/browser_servo_admission_transport.rs",
  "codex-rs/hepta-agentd/src/browser_servo_product.rs",
  "codex-rs/hepta-agentd/src/browser_servo_product_host.rs",
  "third_party/servo-patches/MANIFEST.json",
]);

function fail(message) {
  throw new Error(`browser.servo truth verification failed: ${message}`);
}

function git(...args) {
  return execFileSync("git", ["--literal-pathspecs", "-c", "core.fsmonitor=false", ...args], {
    cwd: ROOT,
    encoding: "utf8",
    env: {
      ...process.env,
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_CONFIG_GLOBAL: process.platform === "win32" ? "NUL" : "/dev/null",
      GIT_NO_REPLACE_OBJECTS: "1",
      GIT_NO_LAZY_FETCH: "1",
      GIT_TERMINAL_PROMPT: "0",
      GIT_OPTIONAL_LOCKS: "0",
    },
  }).trim();
}

async function text(path) {
  return readFile(resolve(ROOT, path), "utf8");
}

function quotedValues(source) {
  return [...source.matchAll(/["']([a-z][a-z0-9_]*)["']/g)].map((match) => match[1]);
}

function extractSet(source, name) {
  const match = source.match(new RegExp(`const\\s+${name}\\s*=\\s*new\\s+Set\\s*\\(\\s*\\[([\\s\\S]*?)\\]\\s*\\)`));
  if (!match) fail(`cannot parse ${name}`);
  return quotedValues(match[1]);
}

function assertExact(actual, expected, name) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    fail(`${name} drifted: expected ${JSON.stringify(expected)}, observed ${JSON.stringify(actual)}`);
  }
}

function hashObject(path) {
  return git("hash-object", "--", path);
}

async function buildTruth() {
  const service = await text("apps/hepta-browser/src/agentd-service.js");
  const actions = await text("apps/hepta-browser/src/action.js");
  const worker = await text("apps/hepta-browser/servo-worker/src/main.rs");
  const cargoToml = await text("apps/hepta-browser/servo-worker/Cargo.toml");
  const cargoLock = await text("apps/hepta-browser/servo-worker/Cargo.lock");
  const manifest = JSON.parse(await text("third_party/servo-patches/MANIFEST.json"));
  const productPort = await text("codex-rs/hepta-agentd/src/browser_servo_product.rs");

  assertExact(extractSet(service, "SERVICE_METHODS"), OPERATIONS, "Browser service RPC registry");
  for (const operation of OPERATIONS) {
    if (!productPort.includes(`\"${operation}\"`)) {
      fail(`Rust Browser product port omits ${operation}`);
    }
  }
  for (const action of CAPABILITIES.filter((row) => row.ingress === "implemented").map((row) => row.action)) {
    if (!actions.includes(`case \"${action}\"`)) fail(`Browser action ingress omits ${action}`);
    if (!worker.includes(`\"${action}\"`)) fail(`Servo worker omits ${action}`);
  }
  for (const action of CAPABILITIES.filter((row) => row.ingress !== "implemented").map((row) => row.action)) {
    if (!actions.includes(`case \"${action}\"`)) fail(`future capability is not named at ingress: ${action}`);
    if (!actions.includes("future capability and is not connected")) fail("future capabilities are not fail closed");
  }

  const cargoPin = cargoToml.match(/servo\s*=\s*\{[^\n]*\brev\s*=\s*\"([0-9a-f]{40})\"/u)?.[1];
  if (cargoPin !== SERVO_PIN) fail(`Cargo.toml Servo pin is ${cargoPin ?? "missing"}`);
  if (manifest.upstream_commit !== SERVO_PIN) fail(`MANIFEST Servo pin is ${manifest.upstream_commit ?? "missing"}`);
  if (!cargoLock.includes(SERVO_PIN)) fail("Cargo.lock does not bind the selected Servo pin");

  return {
    schema: "hepta.browser.product-truth.v1",
    schemaVersion: 1,
    module: "browser.servo",
    operations: OPERATIONS,
    capabilityMatrix: CAPABILITIES,
    servo: {
      repository: "servo/servo",
      pin: SERVO_PIN,
      cargoLockCommitted: true,
    },
    durableEffect: {
      journalSchema: "hepta.browser.operation-journal.v2",
      crossProcessSingleOwner: true,
      immutableSemanticIdentity: true,
      terminalStateMonotonic: true,
      exactDuplicateNoOp: true,
      tornTailRecovery: true,
      compactionAndGenerationRetirement: true,
      effectAdmissionSchema: "BrowserEffectAdmissionV1",
      admissionRequiredBeforeFinalUseRelease: true,
      postProcessLossTerminalityRequiresSignedObserver: true,
    },
    productComposition: {
      owner: "runtime.agentd",
      caller: "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs",
      persistentPrivateChild: true,
      publicBrowserListener: false,
      liveMonotonicRevocationFeed: true,
      serviceClosureDigestBound: true,
    },
    sourceBlobMap: SOURCE_PATHS.map((path) => ({ path, object: hashObject(path) })),
    claimBoundary: {
      sourceImplemented: true,
      exactHeadQualified: false,
      targetHostQualified: false,
      operatorAcceptance: false,
      activation: false,
      promotion: false,
      releaseQualified: false,
    },
  };
}

function canonical(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

const command = process.argv[2] ?? "verify";
const truth = await buildTruth();
if (command === "write") {
  await writeFile(OUTPUT, canonical(truth), "utf8");
} else if (command === "verify") {
  const current = await readFile(OUTPUT, "utf8");
  if (current !== canonical(truth)) fail("generated PRODUCT_TRUTH.json is stale");
  if (git("status", "--porcelain=v1", "--untracked-files=no")) fail("tracked checkout is dirty");
} else {
  fail(`unknown command ${command}`);
}
