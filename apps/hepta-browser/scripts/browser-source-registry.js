#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(process.cwd());
const OUTPUT = resolve(ROOT, "docs/modules/browser.servo/SOURCE_REGISTRY.json");

const RPCS = Object.freeze([
  ["open_profile", "openProfile"],
  ["admit_effect_grant", "admitEffectGrant"],
  ["observe_page", "observePage"],
  ["navigate_or_act", "navigateOrAct"],
  ["reconcile_operation", "reconcileOperation"],
  ["reconcile_persisted_operation", "reconcilePersistedOperation"],
  ["close_profile", "closeProfile"],
]);

const ACTIVE_ACTIONS = Object.freeze([
  "navigate",
  "click",
  "type",
  "focus",
  "scroll",
  "wait",
]);

const FUTURE_FAIL_CLOSED_ACTIONS = Object.freeze([
  "credential",
  "upload",
  "download",
]);

const SOURCE_PATHS = Object.freeze([
  "apps/hepta-browser/src/action.js",
  "apps/hepta-browser/src/agentd-protocol.js",
  "apps/hepta-browser/src/agentd-service-main.js",
  "apps/hepta-browser/src/agentd-service.js",
  "apps/hepta-browser/src/bridge.js",
  "apps/hepta-browser/src/browser.js",
  "apps/hepta-browser/src/effect-egress-gate.js",
  "apps/hepta-browser/src/effect-network-driver.js",
  "apps/hepta-browser/src/egress-broker.js",
  "apps/hepta-browser/src/journal.js",
  "apps/hepta-browser/src/observation-redactor.js",
  "apps/hepta-browser/src/persisted-reconciler.js",
  "apps/hepta-browser/src/runtime-boundary.js",
  "apps/hepta-browser/src/runtime-contract.js",
  "apps/hepta-browser/src/runtime-host.js",
  "apps/hepta-browser/src/runtime.js",
  "apps/hepta-browser/src/worker-driver.js",
  "apps/hepta-browser/src/worker-protocol.js",
  "apps/hepta-browser/scripts/browser-source-registry.js",
  "apps/hepta-browser/scripts/service-closure-manifest.js",
  "apps/hepta-browser/test/agentd-service.test.js",
  "apps/hepta-browser/test/effect-egress-gate.test.js",
  "apps/hepta-browser/test/effect-network-driver.test.js",
  "apps/hepta-browser/test/journal-durability.test.js",
  "apps/hepta-browser/test/journal-monotonicity.test.js",
  "apps/hepta-browser/test/observation-redactor.test.js",
  "apps/hepta-browser/servo-worker/Cargo.toml",
  "apps/hepta-browser/servo-worker/Cargo.lock",
  "apps/hepta-browser/servo-worker/src/main.rs",
  "codex-rs/hepta-agentd/Cargo.toml",
  "codex-rs/hepta-agentd/src/lib.rs",
  "codex-rs/hepta-agentd/src/lib_base.rs",
  "codex-rs/hepta-agentd/src/browser_revocation_feed.rs",
  "codex-rs/hepta-agentd/src/browser_servo.rs",
  "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs",
  "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser-service.rs",
  "docs/modules/browser.servo/OPERATIONS.md",
]);

function read(path) {
  return readFileSync(resolve(ROOT, path), "utf8");
}

function exactQuotedStrings(source) {
  return [...source.matchAll(/"([a-z][a-z0-9_]*)"/g)].map(
    (match) => match[1],
  );
}

function unique(values) {
  return [...new Set(values)];
}

function assertExact(actual, expected, label) {
  const left = [...actual].sort();
  const right = [...expected].sort();
  if (JSON.stringify(left) !== JSON.stringify(right)) {
    throw new Error(
      `${label} drift: actual=${JSON.stringify(left)} expected=${JSON.stringify(right)}`,
    );
  }
}

function gitBlob(path) {
  const oid = execFileSync("git", ["hash-object", "--", path], {
    cwd: ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
  }).trim();
  if (!/^[0-9a-f]{40}$/.test(oid)) {
    throw new Error(`invalid Git blob id for ${path}: ${oid}`);
  }
  return oid;
}

function derive() {
  const service = read("apps/hepta-browser/src/agentd-service.js");
  const serviceMain = read("apps/hepta-browser/src/agentd-service-main.js");
  const serviceTests = read("apps/hepta-browser/test/agentd-service.test.js");
  const runtime = read("apps/hepta-browser/src/runtime.js");
  const actions = read("apps/hepta-browser/src/action.js");
  const worker = read("apps/hepta-browser/servo-worker/src/main.rs");
  const journal = read("apps/hepta-browser/src/journal.js");
  const journalDurability = read(
    "apps/hepta-browser/test/journal-durability.test.js",
  );
  const journalMonotonicity = read(
    "apps/hepta-browser/test/journal-monotonicity.test.js",
  );
  const driver = read("apps/hepta-browser/src/worker-driver.js");
  const egress = read("apps/hepta-browser/src/egress-broker.js");
  const effectEgress = read("apps/hepta-browser/src/effect-egress-gate.js");
  const effectNetworkDriver = read(
    "apps/hepta-browser/src/effect-network-driver.js",
  );
  const effectEgressTests = read(
    "apps/hepta-browser/test/effect-egress-gate.test.js",
  );
  const effectNetworkTests = read(
    "apps/hepta-browser/test/effect-network-driver.test.js",
  );
  const observationRedactor = read(
    "apps/hepta-browser/src/observation-redactor.js",
  );
  const observationRedactorTests = read(
    "apps/hepta-browser/test/observation-redactor.test.js",
  );
  const agentdService = read(
    "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser-service.rs",
  );
  const closureGenerator = read(
    "apps/hepta-browser/scripts/service-closure-manifest.js",
  );
  const operations = read("docs/modules/browser.servo/OPERATIONS.md");

  const serviceBlock = service.match(
    /const SERVICE_METHODS = new Set\(\[([\s\S]*?)\]\);/,
  );
  if (!serviceBlock) throw new Error("SERVICE_METHODS registry was not found");
  const serviceMethods = unique(exactQuotedStrings(serviceBlock[1]));
  assertExact(
    serviceMethods,
    RPCS.map(([wire]) => wire),
    "Browser RPC registry",
  );

  const runtimeMethods = unique(
    [...runtime.matchAll(/async\s+([A-Za-z][A-Za-z0-9]*)\s*\(/g)].map(
      (match) => match[1],
    ),
  );
  assertExact(
    runtimeMethods,
    RPCS.map(([, owner]) => owner),
    "Browser owner facade",
  );

  for (const action of ACTIVE_ACTIONS) {
    if (!actions.includes(`case "${action}"`)) {
      throw new Error(`active action ${action} is absent from action.js`);
    }
    if (!worker.includes(`"${action}"`)) {
      throw new Error(`active action ${action} is absent from the Servo worker`);
    }
  }
  for (const action of FUTURE_FAIL_CLOSED_ACTIONS) {
    if (!actions.includes(`case "${action}"`)) {
      throw new Error(
        `future fail-closed action ${action} is absent from action.js`,
      );
    }
  }

  const invariants = {
    journalV2: journal.includes("hepta.browser.operation-journal.v2"),
    journalSemanticIdentityImmutable:
      journal.includes("assertSameSemantics") &&
      journal.includes("reused with changed semantics"),
    journalTerminalMonotonic:
      journal.includes("cannot change or return to indeterminate") &&
      journalMonotonicity.includes("terminal result cannot return"),
    journalExactDuplicateNoOp:
      journal.includes("A dispatch retry is always a no-op") &&
      journalMonotonicity.includes("write no extra journal bytes"),
    journalIoFailureFencing:
      journal.includes("#fencedCause") &&
      journalDurability.includes("fences queued writes"),
    journalInterprocessOwnerLock:
      journal.includes("hepta.browser.journal-owner-lock.v1") &&
      journalDurability.includes("interprocess lock"),
    journalSchemaMigration:
      journal.includes("operation-journal.v1") &&
      journalMonotonicity.includes("migrate to canonical v2"),
    workerAdmissionBoundary:
      worker.includes("dispatch_boundary") &&
      driver.includes("dispatch_boundary"),
    structuredEffectAdmission:
      service.includes("BrowserEffectAdmissionV1") &&
      service.includes("validateBrowserEffectAdmission") &&
      serviceTests.includes("malformed admission prevents"),
    containmentProofBeforeFenceRelease:
      service.includes("captureLinuxProcessTree") &&
      service.includes("waitForLinuxProcessTreeExit") &&
      service.includes("error.workerContained = true") &&
      serviceTests.includes("proven containment releases the fence"),
    containmentStateMonotonic:
      service.includes("effect admission profile is contained") &&
      serviceTests.includes("makes containment monotonic"),
    admissionDriverComposed:
      serviceMain.includes("EffectAdmissionBrowserDriver") &&
      serviceMain.includes("containmentTimeoutMs"),
    semanticObservation: worker.includes(
      "hepta.browser.semantic-observation.v1",
    ),
    semanticObservationRedaction:
      observationRedactor.includes("redactSemanticObservation") &&
      observationRedactorTests.includes(
        "semantic redaction preserves stable action handles",
      ) &&
      serviceMain.includes("RedactingObservationBrowserDriver"),
    redactedSemanticDigestRebound:
      observationRedactor.includes(
        "semanticDigest: canonicalDigest(semanticObservation)",
      ) &&
      observationRedactorTests.includes(
        "rebinds its digest",
      ),
    grantScopedEgress:
      egress.includes("GrantScopedEgressBroker") &&
      egress.includes("grantDigest") &&
      egress.includes("allowedOrigins"),
    effectScopedEgress:
      effectEgress.includes("EffectScopedEgressBroker") &&
      effectNetworkDriver.includes("EffectScopedEgressBroker") &&
      serviceMain.includes("EffectScopedNetworkDriver") &&
      effectNetworkTests.includes(
        "operation gate at the worker-visible socket",
      ),
    boundedAggregateEgress:
      effectEgress.includes("aggregate > this.#maximum") &&
      effectEgressTests.includes(
        "aggregate response bytes are bounded",
      ),
    perOperationEgressReceipt:
      effectEgress.includes(
        "hepta.browser.egress-operation-receipt.v1",
      ) &&
      effectEgressTests.includes("receiptDigest") &&
      effectNetworkTests.includes("egressReceipt"),
    committedServoLock:
      read("apps/hepta-browser/servo-worker/Cargo.lock").length > 0,
    profileAffineWorkerPool: driver.includes("PooledSubprocessBrowserDriver"),
    boundedStderrDrain: driver.includes("child.stderr?.resume?.()"),
    resourceLimits:
      driver.includes("prlimitPath") && driver.includes("maxProcesses"),
    longRunningAgentdService:
      agentdService.includes("open_browser_servo_port_from_file") &&
      agentdService.includes("while let Some(bytes)"),
    serviceClosureManifest:
      closureGenerator.includes("hepta.browser.service-closure.v1") &&
      closureGenerator.includes("effect_egress_gate") &&
      closureGenerator.includes("effect_network_driver") &&
      closureGenerator.includes("observation_redactor") &&
      agentdService.includes("verify_service_closure") &&
      agentdService.includes("observation_redactor"),
    structuredOperationalMetrics: agentdService.includes(
      "hepta.browser.agentd-metric.v1",
    ),
    operatorRunbook:
      operations.includes("Mandatory fault drills") &&
      operations.includes("Servo pin and CVE refresh"),
  };
  for (const [name, value] of Object.entries(invariants)) {
    if (value !== true) throw new Error(`Browser invariant is absent: ${name}`);
  }

  return {
    schema: "hepta.browser.source-registry.v1",
    schemaVersion: 1,
    module: "browser.servo",
    rpcRegistry: RPCS.map(([wire, owner]) => ({
      wire,
      owner,
      service: "apps/hepta-browser/src/agentd-service.js",
      facade: "apps/hepta-browser/src/runtime.js",
    })),
    workerCapabilityMatrix: [
      ...ACTIVE_ACTIONS.map((action) => ({
        action,
        admission: "implemented",
        worker: "implemented",
        releaseState: "source_present_not_target_qualified",
      })),
      ...FUTURE_FAIL_CLOSED_ACTIONS.map((action) => ({
        action,
        admission: "future_capability_fail_closed",
        worker: "not_connected",
        releaseState: "out_of_scope",
      })),
    ],
    sourceBlobs: Object.fromEntries(
      SOURCE_PATHS.map((path) => [path, gitBlob(path)]),
    ),
    invariants,
    claimBoundary: {
      sourceRegistryGenerated: true,
      sourcePresenceIsDeploymentEvidence: false,
      deploymentQualified: false,
      operatorAccepted: false,
      releaseQualified: false,
    },
  };
}

const rendered = `${JSON.stringify(derive(), null, 2)}\n`;
const mode = process.argv[2] ?? "--check";
if (mode === "--write") {
  writeFileSync(OUTPUT, rendered, "utf8");
} else if (mode === "--check") {
  const current = readFileSync(OUTPUT, "utf8");
  if (current !== rendered) {
    process.stderr.write(
      "browser.servo source registry drifted; run " +
        "node apps/hepta-browser/scripts/browser-source-registry.js --write\n",
    );
    process.exitCode = 1;
  }
} else {
  throw new Error(`unsupported mode: ${mode}`);
}
