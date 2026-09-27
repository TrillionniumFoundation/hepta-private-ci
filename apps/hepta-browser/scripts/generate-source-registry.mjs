#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const OUTPUT = resolve(ROOT, "docs/modules/browser.servo/GENERATED_SOURCE_REGISTRY.json");
const EXPECTED_OPERATIONS = Object.freeze([
  "open_profile",
  "admit_effect_grant",
  "observe_page",
  "navigate_or_act",
  "reconcile_operation",
  "reconcile_persisted_operation",
  "close_profile",
]);

const SOURCE_PATHS = Object.freeze([
  "apps/hepta-browser/scripts/generate-source-registry.mjs",
  "apps/hepta-browser/scripts/verify-deployment-evidence.py",
  "apps/hepta-browser/src/action.js",
  "apps/hepta-browser/src/agentd-protocol.js",
  "apps/hepta-browser/src/agentd-service-main.js",
  "apps/hepta-browser/src/agentd-service.js",
  "apps/hepta-browser/src/egress-broker.js",
  "apps/hepta-browser/src/journal.js",
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
  "codex-rs/hepta-agentd/Cargo.toml",
  "codex-rs/hepta-agentd/src/browser_revocation_feed.rs",
  "codex-rs/hepta-agentd/src/browser_servo_persistent.rs",
  "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser-service.rs",
  "third_party/servo-patches/MANIFEST.json",
  ".github/workflows/blocking-ci.yml",
  ".github/workflows/hepta-browser-agentd-composition.yml",
  ".github/workflows/hepta-browser-servo-worker-dev.yml",
  ".github/workflows/hepta-browser-servo-independent-rebuild.yml",
  ".github/workflows/hepta-browser-servo-deployment-qualification.yml",
]);

function read(path) {
  return readFileSync(resolve(ROOT, path), "utf8");
}

function parseOperations() {
  const source = read("apps/hepta-browser/src/agentd-service.js");
  const match = source.match(/const SERVICE_METHODS = new Set\(\[(.*?)\]\);/s);
  if (!match) throw new Error("cannot locate closed Browser service method set");
  const operations = [...match[1].matchAll(/["']([a-z_]+)["']/g)].map((entry) => entry[1]);
  if (JSON.stringify(operations) !== JSON.stringify(EXPECTED_OPERATIONS)) {
    throw new Error(`Browser RPC set drifted: ${JSON.stringify(operations)}`);
  }
  return operations;
}

function assertContains(path, needles) {
  const source = read(path);
  for (const needle of needles) {
    if (!source.includes(needle)) {
      throw new Error(`${path} does not contain required capability marker ${needle}`);
    }
  }
}

function verifyCapabilities() {
  assertContains("apps/hepta-browser/servo-worker/src/main.rs", [
    '"navigate"',
    '"click"',
    '"type"',
    '"focus"',
    '"scroll"',
    '"wait"',
    "capability_not_connected",
    "pageRevision",
  ]);
  assertContains("apps/hepta-browser/src/egress-broker.js", [
    "CONNECT",
    "serverName",
    "allowedOrigins",
  ]);
  assertContains("apps/hepta-browser/src/journal.js", [
    "operation-journal.v2",
    "compact",
    "retireGeneration",
  ]);
  assertContains("codex-rs/hepta-agentd/src/bin/hepta-agentd-browser-service.rs", [
    "open_browser_servo_port_from_file",
    "while let Some(frame)",
    "navigate_or_act requires signed final-use grant",
  ]);
  assertContains(".github/workflows/blocking-ci.yml", [
    "browser-servo-source",
    "npm --prefix apps/hepta-browser run verify:registry",
  ]);
  assertContains(".github/workflows/hepta-browser-servo-worker-dev.yml", [
    "Require the exact reviewed committed dependency lock",
    "sameRunnerByteIdenticalBuilds",
    "reproducibleIndependentBuilds': False",
    "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6",
    "sbom-path: worker-evidence/hepta-servo-worker.spdx.json",
  ]);
  assertContains(".github/workflows/hepta-browser-servo-independent-rebuild.yml", [
    "independentEphemeralRunner",
    "git ls-files --error-unmatch",
    "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6",
  ]);
  assertContains(".github/workflows/hepta-browser-servo-deployment-qualification.yml", [
    "gh attestation verify",
    "--deny-self-hosted-runners",
    "https://spdx.dev/Document/v2.3",
    "verify-deployment-evidence.py attestations",
  ]);
  assertContains("apps/hepta-browser/scripts/verify-deployment-evidence.py", [
    "verifiedTimestamps",
    "signedBuildProvenanceVerified",
    "signedSbomVerified",
    "selfHostedBuilderAttestationsDenied",
  ]);
}

function gitBlob(path) {
  return execFileSync("git", ["hash-object", "--", path], {
    cwd: ROOT,
    encoding: "utf8",
  }).trim();
}

function buildRegistry() {
  verifyCapabilities();
  return {
    schema: "hepta.browser.servo-source-registry.v1",
    schemaVersion: 1,
    module: "browser.servo",
    rpcRegistry: parseOperations(),
    workerCapabilityMatrix: [
      { capability: "navigate", state: "implemented" },
      { capability: "click", state: "implemented" },
      { capability: "type", state: "implemented" },
      { capability: "focus", state: "implemented" },
      { capability: "scroll", state: "implemented" },
      { capability: "wait", state: "implemented" },
      { capability: "semantic_observation", state: "implemented_bounded" },
      { capability: "worker_effect_admission", state: "implemented" },
      { capability: "grant_scoped_egress", state: "implemented_linux_source" },
      { capability: "persisted_terminal_reconciliation", state: "implemented_signed_observer" },
      { capability: "credential", state: "fail_closed_not_connected" },
      { capability: "upload", state: "fail_closed_not_connected" },
      { capability: "download", state: "fail_closed_not_connected" },
      { capability: "persistent_agentd_owner", state: "implemented_inherited_stdio" },
      { capability: "committed_worker_lock", state: "implemented_required" },
      { capability: "multi_builder_reproducibility", state: "implemented_deployment_gate" },
      { capability: "signed_build_provenance", state: "implemented_main_sigstore_verified_target_gate" },
      { capability: "linux_isolation", state: "implemented_source_target_evidence_required" },
      { capability: "macos_isolation", state: "not_implemented_not_in_current_target" },
      { capability: "windows_isolation", state: "not_implemented_not_in_current_target" },
    ],
    sourceObjects: Object.fromEntries(SOURCE_PATHS.map((path) => [path, gitBlob(path)])),
    claimBoundary: {
      sourceRegistryGenerated: true,
      productionImplementation: false,
      deploymentQualification: false,
      operatorAcceptance: false,
      activation: false,
      promotion: false,
      release: false,
    },
  };
}

const rendered = `${JSON.stringify(buildRegistry(), null, 2)}\n`;
if (process.argv.includes("--check")) {
  const existing = readFileSync(OUTPUT, "utf8");
  if (existing !== rendered) {
    process.stderr.write("browser.servo generated source registry is stale\n");
    process.exit(1);
  }
} else {
  writeFileSync(OUTPUT, rendered, "utf8");
}
