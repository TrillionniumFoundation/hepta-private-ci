#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import {
  assertEvidence,
  boundedText,
  safeFailure,
  sha256,
  validateRepositoryQualificationReceipt,
} from "./external-evidence-lib.mjs";

const MAX_EVIDENCE_BYTES = 2 * 1024 * 1024;
const QUALIFICATION_WORKFLOW_PATH = ".github/workflows/ui-control-qualification.yml";
const PREFLIGHT_SCHEMA = "hepta.ui-control.repository-preflight-observation.v1";

const required = name => {
  const value = process.env[name];
  if (!value) {
    const error = new Error(`${name} is required`);
    error.code = "UI_CONTROL_EXTERNAL_INPUT_MISSING";
    throw error;
  }
  return value;
};

const git = (...args) => execFileSync("git", args, { encoding: "utf8" }).trim();
const output = resolve(process.argv[2] ?? "ui-control-preflight-evidence/repository-preflight-observation.json");
const candidate = Object.freeze({
  commit: git("rev-parse", "HEAD"),
  tree: git("rev-parse", "HEAD^{tree}"),
});
const checks = [];
let stage = "initialization";
let runSummary = null;
let receiptDigests = null;

async function readJsonEvidence(environmentName, label) {
  const path = resolve(required(environmentName));
  const metadata = await stat(path);
  assertEvidence(metadata.isFile(), "UI_CONTROL_PREFLIGHT_FILE", `${label} is not a file`);
  assertEvidence(
    metadata.size > 0 && metadata.size <= MAX_EVIDENCE_BYTES,
    "UI_CONTROL_PREFLIGHT_FILE_SIZE",
    `${label} is empty or exceeds the evidence limit`,
  );
  const bytes = await readFile(path);
  let value;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    const error = new Error(`${label} contains malformed JSON`);
    error.code = "UI_CONTROL_PREFLIGHT_JSON";
    throw error;
  }
  return Object.freeze({ path, bytes, value });
}

async function emit(receipt) {
  await mkdir(dirname(output), { recursive: true });
  const serialized = `${JSON.stringify(receipt, null, 2)}\n`;
  await writeFile(output, serialized);
  process.stdout.write(serialized);
}

function assertQualificationRun(run, { runId, repository }) {
  assertEvidence(run && typeof run === "object" && !Array.isArray(run), "UI_CONTROL_PREFLIGHT_RUN", "qualification run metadata must be an object");
  assertEvidence(run.id === runId, "UI_CONTROL_PREFLIGHT_RUN_ID", "qualification run metadata has another run ID");
  assertEvidence(run.repository?.full_name === repository, "UI_CONTROL_PREFLIGHT_REPOSITORY", "qualification run belongs to another repository");
  assertEvidence(run.head_repository?.full_name === repository, "UI_CONTROL_PREFLIGHT_HEAD_REPOSITORY", "qualification run head repository is not the trusted repository");
  assertEvidence(run.path === QUALIFICATION_WORKFLOW_PATH, "UI_CONTROL_PREFLIGHT_WORKFLOW", "qualification run used another workflow");
  assertEvidence(run.event === "pull_request", "UI_CONTROL_PREFLIGHT_EVENT", "qualification run must be a pull_request run with both exact-head and synthetic-merge jobs");
  assertEvidence(run.status === "completed", "UI_CONTROL_PREFLIGHT_RUN_STATUS", "qualification run is not completed");
  assertEvidence(run.conclusion === "success", "UI_CONTROL_PREFLIGHT_RUN_CONCLUSION", "qualification run did not succeed");
  assertEvidence(run.head_sha === candidate.commit, "UI_CONTROL_PREFLIGHT_RUN_HEAD", "qualification run is bound to another candidate commit");
  assertEvidence(Number.isSafeInteger(run.workflow_id) && run.workflow_id > 0, "UI_CONTROL_PREFLIGHT_WORKFLOW_ID", "qualification workflow ID is invalid");
  assertEvidence(Number.isSafeInteger(run.run_attempt) && run.run_attempt > 0, "UI_CONTROL_PREFLIGHT_RUN_ATTEMPT", "qualification run attempt is invalid");
  const matchingPullRequest = Array.isArray(run.pull_requests) && run.pull_requests.some(pullRequest =>
    pullRequest?.head?.sha === candidate.commit &&
    pullRequest?.base?.ref === "main" &&
    pullRequest?.base?.repo?.name === repository.split("/").at(-1),
  );
  assertEvidence(matchingPullRequest, "UI_CONTROL_PREFLIGHT_PULL_REQUEST", "qualification run does not identify a matching pull request into main");
  return Object.freeze({
    id: run.id,
    workflowId: run.workflow_id,
    runAttempt: run.run_attempt,
    event: run.event,
    path: run.path,
    headSha: run.head_sha,
    status: run.status,
    conclusion: run.conclusion,
    createdAt: boundedText(run.created_at, "run.created_at", 64),
    updatedAt: boundedText(run.updated_at, "run.updated_at", 64),
  });
}

try {
  stage = "workflow-dispatch-ref";
  const workflowRef = required("UI_CONTROL_WORKFLOW_REF");
  assertEvidence(workflowRef === "refs/heads/main", "UI_CONTROL_PREFLIGHT_WORKFLOW_REF", "external qualification must be dispatched from refs/heads/main");
  checks.push("workflow-dispatched-from-main");

  stage = "candidate-input";
  const expectedCandidate = required("UI_CONTROL_CANDIDATE_SHA");
  assertEvidence(/^[0-9a-f]{40}$/u.test(expectedCandidate), "UI_CONTROL_PREFLIGHT_CANDIDATE", "candidate SHA must be a lowercase 40-character Git SHA");
  assertEvidence(candidate.commit === expectedCandidate, "UI_CONTROL_PREFLIGHT_CHECKOUT", "checked-out commit does not equal the requested candidate");
  const runIdText = required("UI_CONTROL_QUALIFICATION_RUN_ID");
  assertEvidence(/^[1-9][0-9]{0,18}$/u.test(runIdText), "UI_CONTROL_PREFLIGHT_RUN_ID", "qualification run ID is invalid");
  const runId = Number(runIdText);
  assertEvidence(Number.isSafeInteger(runId), "UI_CONTROL_PREFLIGHT_RUN_ID", "qualification run ID exceeds the safe integer range");
  const repository = required("UI_CONTROL_EXPECTED_REPOSITORY");
  assertEvidence(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/u.test(repository), "UI_CONTROL_PREFLIGHT_REPOSITORY", "expected repository has an invalid name");
  checks.push("candidate-and-run-input-bound");

  stage = "main-ancestry";
  const mainRef = process.env.UI_CONTROL_MAIN_REF || "refs/remotes/origin/main";
  assertEvidence(mainRef === "refs/remotes/origin/main", "UI_CONTROL_PREFLIGHT_MAIN_REF", "repository preflight requires refs/remotes/origin/main");
  try {
    execFileSync("git", ["merge-base", "--is-ancestor", candidate.commit, mainRef], { stdio: "pipe" });
  } catch {
    const error = new Error(`candidate ${candidate.commit} is not reachable from ${mainRef}`);
    error.code = "UI_CONTROL_CANDIDATE_NOT_ON_MAIN";
    throw error;
  }
  checks.push("candidate-reachable-from-main");

  stage = "qualification-run";
  const runMetadata = await readJsonEvidence("UI_CONTROL_QUALIFICATION_RUN_METADATA", "qualification run metadata");
  runSummary = assertQualificationRun(runMetadata.value, { runId, repository });
  checks.push("official-successful-qualification-run");

  const expected = {
    candidateCommit: candidate.commit,
    candidateTree: candidate.tree,
  };

  stage = "source-head-receipt";
  const sourceHeadEvidence = await readJsonEvidence("UI_CONTROL_SOURCE_HEAD_RECEIPT", "source-head qualification receipt");
  const sourceSummary = validateRepositoryQualificationReceipt(sourceHeadEvidence.value, "source-head", expected);
  checks.push("source-head-receipt-accepted");

  stage = "synthetic-merge-receipt";
  const mergeTreeEvidence = await readJsonEvidence("UI_CONTROL_MERGE_TREE_RECEIPT", "synthetic-merge qualification receipt");
  const mergeSummary = validateRepositoryQualificationReceipt(mergeTreeEvidence.value, "synthetic-merge", expected);
  assertEvidence(
    sourceSummary.browserBuildManifestSha256 === mergeSummary.browserBuildManifestSha256,
    "UI_CONTROL_PREFLIGHT_BUILD_IDENTITY",
    "source-head and synthetic-merge receipts observed different browser build manifests",
  );
  assertEvidence(
    sourceHeadEvidence.value.artifacts?.dependencyLockSha256 === mergeTreeEvidence.value.artifacts?.dependencyLockSha256,
    "UI_CONTROL_PREFLIGHT_DEPENDENCY_IDENTITY",
    "source-head and synthetic-merge receipts observed different dependency locks",
  );
  checks.push("synthetic-merge-receipt-accepted", "repository-receipts-mutually-bound");

  receiptDigests = Object.freeze({
    qualificationRunMetadataSha256: sha256(runMetadata.bytes),
    sourceHeadReceiptSha256: sha256(sourceHeadEvidence.bytes),
    syntheticMergeReceiptSha256: sha256(mergeTreeEvidence.bytes),
  });

  await emit({
    schema: PREFLIGHT_SCHEMA,
    status: "passed",
    observedAt: new Date().toISOString(),
    repository,
    workflowRef,
    mainRef,
    candidate,
    qualificationRun: runSummary,
    sourceHead: {
      evaluated: sourceSummary.evaluated,
      browserBuildManifestSha256: sourceSummary.browserBuildManifestSha256,
    },
    syntheticMerge: {
      evaluated: mergeSummary.evaluated,
      base: mergeSummary.base,
      browserBuildManifestSha256: mergeSummary.browserBuildManifestSha256,
    },
    evidenceDigests: receiptDigests,
    checks,
    claims: {
      workflowDispatchedFromMain: true,
      candidateReachableFromMain: true,
      officialQualificationRunValidated: true,
      sourceReceiptAccepted: true,
      mergeReceiptAccepted: true,
      protectedSecretsEligible: true,
      realBackendSemanticsQualified: false,
      productionDeploymentApproved: false,
      releaseAuthorized: false,
    },
  });
} catch (error) {
  await emit({
    schema: PREFLIGHT_SCHEMA,
    status: "failed",
    observedAt: new Date().toISOString(),
    candidate,
    qualificationRun: runSummary,
    evidenceDigests: receiptDigests,
    checks,
    failure: safeFailure(error, stage),
    claims: {
      workflowDispatchedFromMain: false,
      candidateReachableFromMain: false,
      officialQualificationRunValidated: false,
      sourceReceiptAccepted: false,
      mergeReceiptAccepted: false,
      protectedSecretsEligible: false,
      realBackendSemanticsQualified: false,
      productionDeploymentApproved: false,
      releaseAuthorized: false,
    },
  });
  process.exitCode = 1;
}
