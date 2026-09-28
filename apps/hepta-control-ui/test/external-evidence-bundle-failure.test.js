import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  deploymentSubject,
  sha256,
} from "../../../qualification/ui-control/external-evidence-lib.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));

function initializeCandidate(directory) {
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

function writeReceipt(directory, name, value) {
  const text = `${JSON.stringify(value, null, 2)}\n`;
  const path = join(directory, name);
  writeFileSync(path, text);
  return { path, digest: sha256(text) };
}

function repositoryReceipt(candidate, kind, manifestDigest) {
  const merge = kind === "synthetic-merge";
  return {
    schema: "hepta.ui-control.qualification-receipt.v2",
    candidate: {
      kind,
      evaluated: merge
        ? { sha: "a".repeat(40), tree: "b".repeat(40) }
        : { sha: candidate.commit, tree: candidate.tree },
      sourceHead: { sha: candidate.commit, tree: candidate.tree },
      base: merge ? { sha: "c".repeat(40), tree: "d".repeat(40) } : null,
    },
    verificationStages: {
      sourceTestsPassed: { state: "passed" },
      browserTestsPassed: { state: "passed" },
      mergeTreePassed: { state: merge ? "passed" : "not-evaluated" },
    },
    artifacts: {
      dependencyLockSha256: "1".repeat(64),
      browserBuildManifestSha256: manifestDigest,
      statusManifestSha256: "2".repeat(64),
    },
    claims: {
      repositorySourceQualified: true,
      repositoryBrowserCompositionQualified: true,
      deterministicMergeQualified: merge,
    },
  };
}

test("bundle validation emits a structured fail-closed receipt", () => {
  const directory = mkdtempSync(join(tmpdir(), "ui-control-external-bundle-"));
  try {
    initializeCandidate(directory);
    const output = join(directory, "bundle.json");
    const result = spawnSync(
      process.execPath,
      [resolve(root, "qualification/ui-control/validate-external-evidence.mjs"), output],
      { cwd: directory, env: { ...process.env, HEPTA_UI_CONTROL_BASE_URL: "", HEPTA_UI_CONTROL_DEPLOYMENT_ID: "" }, encoding: "utf8" },
    );
    assert.notEqual(result.status, 0);
    const receipt = JSON.parse(readFileSync(output, "utf8"));
    assert.equal(receipt.schema, "hepta.ui-control.external-evidence-bundle.v1");
    assert.equal(receipt.status, "failed");
    assert.equal(receipt.claims.productionDeploymentApproved, false);
    assert.equal(receipt.claims.releaseAuthorized, false);
    assert.equal(receipt.stageResults["deployment-identity"].observedOutcome, "failed");
    assert.equal(receipt.stageResults["deployment-identity"].acceptedEvidence, false);
    assert.equal(receipt.failure.code, "UI_CONTROL_EXTERNAL_INPUT_MISSING");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("later bundle failure retains exact earlier accepted stage evidence", () => {
  const directory = mkdtempSync(join(tmpdir(), "ui-control-external-partial-"));
  try {
    const candidate = initializeCandidate(directory);
    const manifestDigest = "8".repeat(64);
    const source = writeReceipt(
      directory,
      "source.json",
      repositoryReceipt(candidate, "source-head", manifestDigest),
    );
    const merge = writeReceipt(
      directory,
      "merge.json",
      repositoryReceipt(candidate, "synthetic-merge", manifestDigest),
    );
    const selected = deploymentSubject("https://control.example.test/console", "release-partial");
    const output = join(directory, "bundle.json");
    const result = spawnSync(
      process.execPath,
      [resolve(root, "qualification/ui-control/validate-external-evidence.mjs"), output],
      {
        cwd: directory,
        env: {
          ...process.env,
          HEPTA_UI_CONTROL_BASE_URL: "https://control.example.test/console",
          HEPTA_UI_CONTROL_DEPLOYMENT_ID: "release-partial",
          UI_CONTROL_SOURCE_HEAD_RECEIPT: source.path,
          UI_CONTROL_MERGE_TREE_RECEIPT: merge.path,
          UI_CONTROL_REQUIRE_MAIN_ANCESTRY: "false",
        },
        encoding: "utf8",
      },
    );
    assert.notEqual(result.status, 0);
    const receipt = JSON.parse(readFileSync(output, "utf8"));
    assert.equal(receipt.status, "failed");
    assert.equal(receipt.backendDeploymentDigest, selected.digest);
    assert.equal(receipt.failure.stage, "deployment-security");
    assert.equal(receipt.failure.code, "UI_CONTROL_EXTERNAL_INPUT_MISSING");
    assert.deepEqual(receipt.evidenceDigests, {
      sourceHead: source.digest,
      mergeTree: merge.digest,
    });
    assert.deepEqual(receipt.stageResults["repository-source-head"], {
      observedOutcome: "passed",
      acceptedEvidence: true,
      evidenceDigest: source.digest,
    });
    assert.deepEqual(receipt.stageResults["repository-synthetic-merge"], {
      observedOutcome: "passed",
      acceptedEvidence: true,
      evidenceDigest: merge.digest,
    });
    assert.deepEqual(receipt.stageResults["deployment-security"], {
      observedOutcome: "failed",
      acceptedEvidence: false,
      evidenceDigest: null,
      failureCode: "UI_CONTROL_EXTERNAL_INPUT_MISSING",
    });
    assert.equal(receipt.claims.repositorySourceQualified, true);
    assert.equal(receipt.claims.repositoryBrowserCompositionQualified, true);
    assert.equal(receipt.claims.deterministicMergeQualified, true);
    assert.equal(receipt.claims.deployedSecurityObserved, false);
    assert.equal(receipt.claims.productionDeploymentApproved, false);
    assert.equal(receipt.claims.releaseAuthorized, false);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
