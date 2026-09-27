#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { lstatSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const OUTPUT = resolve(ROOT, "docs/modules/browser.servo/GENERATED_SOURCE_REGISTRY.json");
const EXPECTED_OPERATIONS = Object.freeze([
  "open_profile", "admit_effect_grant", "observe_page", "navigate_or_act",
  "reconcile_operation", "reconcile_persisted_operation", "close_profile",
]);
const EXTRA_SOURCES = Object.freeze([
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
  "docs/modules/browser.servo/IMPLEMENTATION_MAP.json",
  "docs/modules/browser.servo/REMEDIATION_20260927.md",
]);
function git(args) {
  return execFileSync("git", args, { cwd: ROOT, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 }).trim();
}
function read(path) { return readFileSync(resolve(ROOT, path), "utf8"); }
function assertContains(path, needles) {
  const source = read(path);
  for (const needle of needles) {
    if (!source.includes(needle)) throw new Error(`${path} lacks source anchor ${needle}`);
  }
}
function sourcePaths() {
  // Inventory the entire tracked Browser package, including new implementation
  // files, tests, probes, lock and package metadata. Never bind only a facade.
  const packagePaths = git(["ls-files", "-z", "--", "apps/hepta-browser"]).split("\0").filter(Boolean);
  const paths = [...new Set([...packagePaths, ...EXTRA_SOURCES])].sort();
  if (paths.length > 2048) throw new Error("Browser source inventory exceeds its bound");
  for (const path of paths) {
    if (!lstatSync(resolve(ROOT, path)).isFile()) throw new Error(`source is not a regular file: ${path}`);
  }
  return paths;
}
function verifyAnchors(paths) {
  const source = read("apps/hepta-browser/src/agentd-service.js");
  const match = source.match(/const SERVICE_METHODS = new Set\(\[(.*?)\]\);/s);
  if (!match) throw new Error("closed Browser method set not found");
  const operations = [...match[1].matchAll(/["']([a-z_]+)["']/g)].map(entry => entry[1]);
  if (JSON.stringify(operations) !== JSON.stringify(EXPECTED_OPERATIONS)) throw new Error("Browser RPC set drifted");
  assertContains("apps/hepta-browser/src/journal.js", ['from "./journal-v2.js"']);
  assertContains("apps/hepta-browser/src/journal-v2.js", ["operation-journal.v2", "async compact(", "async retireProfile(", "acquireBrowserJournalLock"]);
  assertContains("apps/hepta-browser/src/journal-owner-lock.js", ["kernel-owner-lock.v2", "--exclusive"]);
  assertContains("apps/hepta-browser/src/egress-broker.js", ["GrantScopedEgressBroker", "CONNECT", "serverName", "allowedOrigins"]);
  assertContains("apps/hepta-browser/src/effect-network-driver.js", ["EffectScopedNetworkDriver", "admitOperation"]);
  assertContains("apps/hepta-browser/servo-worker/src/main.rs", ['matches!(kind, "credential" | "upload" | "download")', "typedAction capability is not connected", "dispatch_boundary", "pageGeneration"]);
  assertContains("codex-rs/hepta-agentd/src/bin/hepta-agentd-browser-service.rs", ["open_browser_servo_port_from_file", "while let Some(body)"]);
  const tracked = new Set(paths);
  // Static relative imports are the current Browser package's executable
  // closure. Dynamic/native/runtime closure requires independent qualification.
  for (const path of paths.filter(path => /\.(?:js|mjs)$/.test(path))) {
    for (const match of read(path).matchAll(/\bfrom\s+["'](\.[^"']+)["']/g)) {
      const imported = relative(ROOT, resolve(ROOT, dirname(path), match[1]));
      if (!tracked.has(imported)) throw new Error(`unmapped local import: ${path} -> ${imported}`);
    }
  }
  const map = JSON.parse(read("docs/modules/browser.servo/IMPLEMENTATION_MAP.json"));
  if (JSON.stringify(map.operations.map(item => item.designOperation)) !== JSON.stringify(operations)) throw new Error("implementation-map RPC set drifted");
  for (const operation of map.operations) {
    for (const anchor of [operation.ownerEntrypoint, ...operation.delegatedCallees]) {
      if (!tracked.has(anchor.path)) throw new Error(`unmapped callee: ${anchor.path}`);
      assertContains(anchor.path, [anchor.symbol]);
    }
    for (const test of operation.tests) {
      if (!tracked.has(test.path)) throw new Error(`unmapped test: ${test.path}`);
    }
  }
  // Source markers and hashes identify code; they never certify its semantics.
  return operations;
}
function buildRegistry() {
  const paths = sourcePaths();
  const operations = verifyAnchors(paths);
  const implemented = ["navigate", "click", "type", "focus", "scroll", "wait"];
  return {
    schema: "hepta.browser.servo-source-registry.v1", schemaVersion: 1, module: "browser.servo",
    rpcRegistry: operations,
    workerCapabilityMatrix: [
      ...implemented.map(capability => ({ capability, state: "implemented" })),
      { capability: "semantic_observation", state: "implemented_bounded" },
      { capability: "worker_effect_admission", state: "implemented" },
      { capability: "grant_scoped_egress", state: "implemented_linux_source" },
      { capability: "persisted_terminal_reconciliation", state: "implemented_signed_observer" },
      ...["credential", "upload", "download"].map(capability => ({ capability, state: "fail_closed_not_connected" })),
      { capability: "persistent_agentd_owner", state: "implemented_inherited_stdio" },
      { capability: "committed_worker_lock", state: "implemented_required" },
      { capability: "multi_builder_reproducibility", state: "implemented_deployment_gate" },
      { capability: "signed_build_provenance", state: "implemented_main_sigstore_verified_target_gate" },
      { capability: "linux_isolation", state: "implemented_source_target_evidence_required" },
      { capability: "macos_isolation", state: "not_implemented_not_in_current_target" },
      { capability: "windows_isolation", state: "not_implemented_not_in_current_target" },
    ],
    sourceObjects: Object.fromEntries(paths.map(path => [path, git(["hash-object", "--", path])])),
    claimBoundary: { sourceRegistryGenerated: true, productionImplementation: false,
      deploymentQualification: false, operatorAcceptance: false, activation: false, promotion: false, release: false },
  };
}
const rendered = `${JSON.stringify(buildRegistry(), null, 2)}\n`;
if (process.argv.includes("--check")) {
  if (readFileSync(OUTPUT, "utf8") !== rendered) {
    process.stderr.write("browser.servo generated source registry is stale\n"); process.exit(1);
  }
} else writeFileSync(OUTPUT, rendered, "utf8");
