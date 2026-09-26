#!/usr/bin/env node
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");

function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function sha256Parts(paths) {
  const hash = createHash("sha256");
  for (const path of paths.sort()) {
    hash.update(path);
    hash.update("\0");
    hash.update(readFileSync(join(ROOT, path)));
    hash.update("\0");
  }
  return hash.digest("hex");
}

function git(...args) {
  return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
}

const outIndex = process.argv.indexOf("--out");
const out = outIndex >= 0 ? process.argv[outIndex + 1] : null;
if (!out) throw new Error("usage: receipt.mjs --out <path>");

const generated = [
  "docs/modules/ui.native/generated/api-registry.json",
  "docs/modules/ui.native/generated/capability-registry.json",
  "docs/modules/ui.native/generated/platform-matrix.json",
  "docs/modules/ui.native/generated/test-registry.json",
];

for (const path of generated) {
  if (!existsSync(join(ROOT, path))) throw new Error(`missing generated artifact: ${path}`);
}

const workflowPath = ".github/workflows/hepta-ui-native-current-source.yml";
const projectionWorkflowPath = ".github/workflows/hepta-ui-native-projections.yml";
const lockPaths = [
  "apps/hepta-native/Cargo.lock",
  "codex-rs/Cargo.lock",
  "tools/ui-native-projections/package-lock.json",
];

const receipt = {
  schema: "hepta.ui.native.qualification-receipt.v1",
  sourceSha: git("rev-parse", "HEAD"),
  sourceTree: git("rev-parse", "HEAD^{tree}"),
  workflowSha256: {
    native: sha256File(join(ROOT, workflowPath)),
    projections: sha256File(join(ROOT, projectionWorkflowPath)),
  },
  dependencyLockDigest: sha256Parts(lockPaths),
  toolchain: {
    node: process.version,
    rust: readFileSync(join(ROOT, "apps/hepta-native/rust-toolchain.toml"), "utf8").trim(),
  },
  platformImage: {
    runnerOs: process.env.RUNNER_OS ?? os.platform(),
    runnerArch: process.env.RUNNER_ARCH ?? os.arch(),
    imageOs: process.env.ImageOS ?? null,
    imageVersion: process.env.ImageVersion ?? null,
  },
  testManifestDigest: sha256File(
    join(ROOT, "docs/modules/ui.native/generated/test-registry.json"),
  ),
  artifactDigest: sha256Parts(generated),
  timestamp: new Date().toISOString(),
  claims: {
    exactHeadOrSyntheticMerge: process.env.HEPTA_SOURCE_KIND ?? "local",
    productionSigningObserved: false,
    physicalAccessibilityAccepted: false,
    releaseAuthorized: false,
  },
};

const output = resolve(ROOT, out);
mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
console.log(output);
