import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  UI_CONTROL_BROWSER_BUILD_SCHEMA,
  UI_CONTROL_RUNTIME_SUBSTITUTIONS,
} from "../../../qualification/ui-control/deployment-asset-invariants.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const script = resolve(root, "qualification/ui-control/candidate-build-artifact.mjs");
const sha256 = value => createHash("sha256").update(value).digest("hex");

function initialize(directory) {
  execFileSync("git", ["init", "-q"], { cwd: directory });
  execFileSync("git", ["config", "user.name", "ui.control test"], { cwd: directory });
  execFileSync("git", ["config", "user.email", "ui-control-test@example.invalid"], { cwd: directory });
  writeFileSync(join(directory, "marker.txt"), "candidate\n");
  execFileSync("git", ["add", "marker.txt"], { cwd: directory });
  execFileSync("git", ["commit", "-q", "-m", "candidate"], { cwd: directory });
  return {
    commit: execFileSync("git", ["rev-parse", "HEAD"], { cwd: directory, encoding: "utf8" }).trim(),
    tree: execFileSync("git", ["rev-parse", "HEAD^{tree}"], { cwd: directory, encoding: "utf8" }).trim(),
  };
}

function createArtifact(directory, candidate) {
  const build = join(directory, "build");
  mkdirSync(build);
  const files = {
    "app.js": Buffer.from("export const ready = true;\n"),
    "index.html": Buffer.from('<!doctype html><meta name="csrf-token" content=""><script type="module" src="app.js"></script>\n'),
  };
  for (const [name, bytes] of Object.entries(files)) writeFileSync(join(build, name), bytes);
  const manifest = {
    schema: UI_CONTROL_BROWSER_BUILD_SCHEMA,
    runtimeSubstitutions: UI_CONTROL_RUNTIME_SUBSTITUTIONS,
    files: Object.fromEntries(Object.entries(files).map(([name, bytes]) => [name, {
      bytes: bytes.byteLength,
      sha256: sha256(bytes),
    }])),
  };
  const manifestText = `${JSON.stringify(manifest, null, 2)}\n`;
  const manifestPath = join(build, "build-manifest.json");
  writeFileSync(manifestPath, manifestText);
  const receiptPath = join(directory, "source-receipt.json");
  writeFileSync(receiptPath, `${JSON.stringify({
    schema: "hepta.ui-control.qualification-receipt.v2",
    candidate: {
      kind: "source-head",
      evaluated: { sha: candidate.commit, tree: candidate.tree },
      sourceHead: { sha: candidate.commit, tree: candidate.tree },
      base: null,
    },
    verificationStages: {
      sourceTestsPassed: { state: "passed" },
      browserTestsPassed: { state: "passed" },
      mergeTreePassed: { state: "not-evaluated" },
    },
    artifacts: {
      dependencyLockSha256: "1".repeat(64),
      browserBuildManifestSha256: sha256(manifestText),
      statusManifestSha256: "2".repeat(64),
    },
    claims: {
      repositorySourceQualified: true,
      repositoryBrowserCompositionQualified: true,
      deterministicMergeQualified: false,
    },
  }, null, 2)}\n`);
  return { build, manifestPath, receiptPath };
}

function run(directory, artifact) {
  const output = join(directory, "observation.json");
  const result = spawnSync(
    process.execPath,
    [script, artifact.manifestPath, artifact.receiptPath, output],
    { cwd: directory, encoding: "utf8" },
  );
  return {
    ...result,
    observation: JSON.parse(readFileSync(output, "utf8")),
  };
}

test("trusted candidate-build validation accepts one exact receipt-bound regular-file set", () => {
  const directory = mkdtempSync(join(tmpdir(), "ui-control-candidate-build-"));
  try {
    const candidate = initialize(directory);
    const artifact = createArtifact(directory, candidate);
    const result = run(directory, artifact);
    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(result.observation.status, "passed");
    assert.equal(result.observation.candidate.commit, candidate.commit);
    assert.equal(result.observation.verifiedFileCount, 2);
    assert.equal(result.observation.claims.protectedSecretsEligible, true);
    assert.equal(result.observation.claims.productionDeploymentApproved, false);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("trusted candidate-build validation rejects unmanifested files", () => {
  const directory = mkdtempSync(join(tmpdir(), "ui-control-candidate-build-extra-"));
  try {
    const candidate = initialize(directory);
    const artifact = createArtifact(directory, candidate);
    writeFileSync(join(artifact.build, "unlisted.js"), "doNotDeploy();\n");
    const result = run(directory, artifact);
    assert.notEqual(result.status, 0);
    assert.equal(result.observation.status, "failed");
    assert.equal(result.observation.failure.code, "UI_CONTROL_BUILD_FILE_SET");
    assert.equal(result.observation.claims.protectedSecretsEligible, false);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("trusted candidate-build validation rejects manifest drift from the accepted source receipt", () => {
  const directory = mkdtempSync(join(tmpdir(), "ui-control-candidate-build-drift-"));
  try {
    const candidate = initialize(directory);
    const artifact = createArtifact(directory, candidate);
    const manifest = JSON.parse(readFileSync(artifact.manifestPath, "utf8"));
    manifest.files["app.js"].bytes += 1;
    writeFileSync(artifact.manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
    const result = run(directory, artifact);
    assert.notEqual(result.status, 0);
    assert.equal(result.observation.status, "failed");
    assert.equal(result.observation.failure.code, "UI_CONTROL_BUILD_MANIFEST_RECEIPT_MISMATCH");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
