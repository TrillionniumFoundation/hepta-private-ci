import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const validator = resolve(root, "qualification/ui-control/validate-repository-preflight.mjs");
const repository = "TrillionniumFoundation/hepta-private-ci";
const runId = "36417496222";

function git(directory, ...args) {
  return execFileSync("git", args, { cwd: directory, encoding: "utf8" }).trim();
}

function writeJson(directory, name, value) {
  const path = join(directory, name);
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
  return path;
}

function initializeCandidate(directory) {
  git(directory, "init", "-q");
  git(directory, "config", "user.name", "ui.control preflight test");
  git(directory, "config", "user.email", "ui-control-preflight@users.noreply.github.com");
  writeFileSync(join(directory, "candidate.txt"), "candidate\n");
  git(directory, "add", "candidate.txt");
  git(directory, "commit", "-q", "-m", "candidate");
  const commit = git(directory, "rev-parse", "HEAD");
  const tree = git(directory, "rev-parse", "HEAD^{tree}");
  git(directory, "update-ref", "refs/remotes/origin/main", commit);
  return { commit, tree };
}

function repositoryReceipt(kind, candidate) {
  const synthetic = kind === "synthetic-merge";
  return {
    schema: "hepta.ui-control.qualification-receipt.v2",
    candidate: {
      kind,
      sourceHead: { sha: candidate.commit, tree: candidate.tree },
      evaluated: synthetic
        ? { sha: "e".repeat(40), tree: "f".repeat(40) }
        : { sha: candidate.commit, tree: candidate.tree },
      base: synthetic ? { sha: "1".repeat(40), tree: "2".repeat(40) } : null,
    },
    verificationStages: {
      sourceTestsPassed: { state: "passed" },
      browserTestsPassed: { state: "passed" },
      mergeTreePassed: { state: synthetic ? "passed" : "not-evaluated" },
    },
    artifacts: {
      dependencyLockSha256: "3".repeat(64),
      browserBuildManifestSha256: "4".repeat(64),
      statusManifestSha256: "5".repeat(64),
    },
    claims: {
      repositorySourceQualified: true,
      repositoryBrowserCompositionQualified: true,
      deterministicMergeQualified: synthetic,
    },
  };
}

function qualificationRun(candidate, overrides = {}) {
  return {
    id: Number(runId),
    workflow_id: 367754060,
    run_attempt: 1,
    event: "pull_request",
    path: ".github/workflows/ui-control-qualification.yml",
    status: "completed",
    conclusion: "success",
    head_sha: candidate.commit,
    created_at: "2026-09-28T11:44:52Z",
    updated_at: "2026-09-28T12:20:58Z",
    repository: { full_name: repository },
    head_repository: { full_name: repository },
    pull_requests: [{
      head: { sha: candidate.commit },
      base: { ref: "main", repo: { name: "hepta-private-ci" } },
    }],
    ...overrides,
  };
}

function execute(directory, candidate, overrides = {}) {
  const source = writeJson(directory, "source.json", repositoryReceipt("source-head", candidate));
  const merge = writeJson(directory, "merge.json", repositoryReceipt("synthetic-merge", candidate));
  const metadata = writeJson(directory, "run.json", qualificationRun(candidate, overrides.runMetadata));
  const output = join(directory, "preflight.json");
  const result = spawnSync(process.execPath, [validator, output], {
    cwd: directory,
    env: {
      ...process.env,
      UI_CONTROL_WORKFLOW_REF: overrides.workflowRef ?? "refs/heads/main",
      UI_CONTROL_CANDIDATE_SHA: candidate.commit,
      UI_CONTROL_EXPECTED_REPOSITORY: repository,
      UI_CONTROL_QUALIFICATION_RUN_ID: runId,
      UI_CONTROL_QUALIFICATION_RUN_METADATA: metadata,
      UI_CONTROL_SOURCE_HEAD_RECEIPT: source,
      UI_CONTROL_MERGE_TREE_RECEIPT: merge,
      UI_CONTROL_MAIN_REF: "refs/remotes/origin/main",
    },
    encoding: "utf8",
  });
  return { result, receipt: JSON.parse(readFileSync(output, "utf8")) };
}

test("repository preflight accepts one official successful main-reachable qualification run", () => {
  const directory = mkdtempSync(join(tmpdir(), "ui-control-preflight-pass-"));
  try {
    const candidate = initializeCandidate(directory);
    const { result, receipt } = execute(directory, candidate);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(receipt.status, "passed");
    assert.equal(receipt.candidate.commit, candidate.commit);
    assert.equal(receipt.qualificationRun.id, Number(runId));
    assert.equal(receipt.claims.protectedSecretsEligible, true);
    assert.equal(receipt.claims.realBackendSemanticsQualified, false);
    assert.equal(receipt.claims.productionDeploymentApproved, false);
    assert.equal(receipt.claims.releaseAuthorized, false);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("repository preflight rejects off-main dispatch and mismatched workflow runs without secret eligibility", () => {
  const directory = mkdtempSync(join(tmpdir(), "ui-control-preflight-fail-"));
  try {
    const candidate = initializeCandidate(directory);
    const offMainDispatch = execute(directory, candidate, { workflowRef: "refs/heads/work/ui-control-candidate" });
    assert.notEqual(offMainDispatch.result.status, 0);
    assert.equal(offMainDispatch.receipt.failure.stage, "workflow-dispatch-ref");
    assert.equal(offMainDispatch.receipt.failure.code, "UI_CONTROL_PREFLIGHT_WORKFLOW_REF");
    assert.equal(offMainDispatch.receipt.claims.protectedSecretsEligible, false);

    const wrongRun = execute(directory, candidate, {
      runMetadata: { conclusion: "failure" },
    });
    assert.notEqual(wrongRun.result.status, 0);
    assert.equal(wrongRun.receipt.failure.stage, "qualification-run");
    assert.equal(wrongRun.receipt.failure.code, "UI_CONTROL_PREFLIGHT_RUN_CONCLUSION");
    assert.equal(wrongRun.receipt.claims.releaseAuthorized, false);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
