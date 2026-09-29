#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const EXTERNAL_WORKFLOW_NAME = "ui.control external deployment qualification";
export const EXTERNAL_WORKFLOW_RUN_PREFIX = "ui.control external qualification ";
export const EXTERNAL_WORKFLOW_OBSERVATION_SCHEMA = "hepta.ui-control.external-workflow-observation.v1";

const SHA1 = /^[0-9a-f]{40}$/u;
const SHA256_DIGEST = /^sha256:[0-9a-f]{64}$/u;
const FINAL_CONCLUSIONS = new Set([
  "success",
  "failure",
  "cancelled",
  "timed_out",
  "action_required",
  "neutral",
  "skipped",
  "stale",
  "startup_failure",
]);

function observationError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function requireObject(value, code, message) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw observationError(code, message);
  }
  return value;
}

function requireString(value, code, message, { maxLength = 4096 } = {}) {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
    throw observationError(code, message);
  }
  return value;
}

function requirePositiveInteger(value, code, message) {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw observationError(code, message);
  }
  return value;
}

function normalizeIso(value, code = "UI_CONTROL_EXTERNAL_OBSERVER_TIME") {
  const text = requireString(value, code, "external-workflow observation time is missing");
  const milliseconds = Date.parse(text);
  if (!Number.isFinite(milliseconds)) {
    throw observationError(code, "external-workflow observation time is invalid");
  }
  return new Date(milliseconds).toISOString();
}

function normalizeObserver(options) {
  const workflowSha = requireString(
    options.observerWorkflowSha,
    "UI_CONTROL_EXTERNAL_OBSERVER_WORKFLOW_SHA",
    "trusted observer workflow SHA is missing",
  );
  if (!SHA1.test(workflowSha)) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_WORKFLOW_SHA",
      "trusted observer workflow SHA must be one lowercase 40-character SHA",
    );
  }
  return Object.freeze({
    workflowSha,
    runId: requirePositiveInteger(
      options.observerRunId,
      "UI_CONTROL_EXTERNAL_OBSERVER_OBSERVER_RUN_ID",
      "trusted observer run id is invalid",
    ),
    runAttempt: requirePositiveInteger(
      options.observerRunAttempt,
      "UI_CONTROL_EXTERNAL_OBSERVER_OBSERVER_RUN_ATTEMPT",
      "trusted observer run attempt is invalid",
    ),
    repository: requireString(
      options.repository,
      "UI_CONTROL_EXTERNAL_OBSERVER_REPOSITORY",
      "trusted observer repository is missing",
      { maxLength: 256 },
    ),
  });
}

function parseCandidate(displayTitle) {
  const title = requireString(
    displayTitle,
    "UI_CONTROL_EXTERNAL_OBSERVER_RUN_NAME",
    "external workflow display title is missing",
    { maxLength: 512 },
  );
  if (!title.startsWith(EXTERNAL_WORKFLOW_RUN_PREFIX)) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_RUN_NAME",
      "external workflow display title does not identify the ui.control candidate",
    );
  }
  const candidate = title.slice(EXTERNAL_WORKFLOW_RUN_PREFIX.length).trim();
  if (!SHA1.test(candidate)) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_CANDIDATE",
      "external workflow candidate commit must be one lowercase 40-character SHA",
    );
  }
  return candidate;
}

function normalizeArtifact(raw) {
  const artifact = requireObject(
    raw,
    "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACT",
    "external workflow artifact entry must be an object",
  );
  const id = requirePositiveInteger(
    artifact.id,
    "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACT_ID",
    "external workflow artifact id is invalid",
  );
  const name = requireString(
    artifact.name,
    "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACT_NAME",
    "external workflow artifact name is invalid",
    { maxLength: 256 },
  );
  const sizeInBytes = artifact.size_in_bytes;
  if (!Number.isSafeInteger(sizeInBytes) || sizeInBytes < 0 || sizeInBytes > 1_073_741_824) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACT_SIZE",
      `external workflow artifact size is invalid: ${name}`,
    );
  }
  const digest = artifact.digest ?? null;
  if (digest !== null && (typeof digest !== "string" || !SHA256_DIGEST.test(digest))) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACT_DIGEST",
      `external workflow artifact digest is invalid: ${name}`,
    );
  }
  if (typeof artifact.expired !== "boolean") {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACT_EXPIRY",
      `external workflow artifact expiry state is invalid: ${name}`,
    );
  }
  return Object.freeze({
    id,
    name,
    sizeInBytes,
    digest,
    expired: artifact.expired,
  });
}

function falseClaims() {
  return {
    repositorySourceQualified: false,
    deterministicMergeQualified: false,
    deployedSecurityObserved: false,
    realBackendSemanticsQualified: false,
    durableCrashRestartQualified: false,
    independentAccessibilityAndOperatorAcceptanceSigned: false,
    independentSecurityReviewPassed: false,
    rollbackDisasterRecoveryMonitoringAndRedactionExercised: false,
    productionDeploymentApproved: false,
    releaseAuthorized: false,
  };
}

function conclusionCode(conclusion) {
  return `UI_CONTROL_EXTERNAL_WORKFLOW_${conclusion.toUpperCase().replaceAll(/[^A-Z0-9]+/gu, "_")}`;
}

export function buildExternalWorkflowObservation(runInput, artifactInput, options = {}) {
  const run = requireObject(
    runInput,
    "UI_CONTROL_EXTERNAL_OBSERVER_RUN",
    "external workflow run metadata must be an object",
  );
  const artifactsEnvelope = requireObject(
    artifactInput,
    "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACTS",
    "external workflow artifact metadata must be an object",
  );
  const workflowName = requireString(
    run.name,
    "UI_CONTROL_EXTERNAL_OBSERVER_WORKFLOW",
    "external workflow name is missing",
    { maxLength: 256 },
  );
  if (workflowName !== EXTERNAL_WORKFLOW_NAME) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_WORKFLOW",
      `unexpected external workflow: ${workflowName}`,
    );
  }
  if (run.event !== "workflow_dispatch") {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_EVENT",
      "external workflow observation requires a workflow_dispatch source run",
    );
  }
  if (run.status !== "completed") {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_STATUS",
      "external workflow observation requires a completed source run",
    );
  }
  const conclusion = requireString(
    run.conclusion,
    "UI_CONTROL_EXTERNAL_OBSERVER_CONCLUSION",
    "external workflow conclusion is missing",
    { maxLength: 64 },
  );
  if (!FINAL_CONCLUSIONS.has(conclusion)) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_CONCLUSION",
      `unsupported external workflow conclusion: ${conclusion}`,
    );
  }
  const candidateCommit = parseCandidate(run.display_title);
  const runId = requirePositiveInteger(
    run.id,
    "UI_CONTROL_EXTERNAL_OBSERVER_RUN_ID",
    "external workflow run id is invalid",
  );
  const runAttempt = requirePositiveInteger(
    run.run_attempt,
    "UI_CONTROL_EXTERNAL_OBSERVER_RUN_ATTEMPT",
    "external workflow run attempt is invalid",
  );
  const workflowId = requirePositiveInteger(
    run.workflow_id,
    "UI_CONTROL_EXTERNAL_OBSERVER_WORKFLOW_ID",
    "external workflow id is invalid",
  );
  const headSha = requireString(
    run.head_sha,
    "UI_CONTROL_EXTERNAL_OBSERVER_WORKFLOW_SHA",
    "external workflow SHA is missing",
  );
  if (!SHA1.test(headSha)) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_WORKFLOW_SHA",
      "external workflow SHA must be one lowercase 40-character SHA",
    );
  }
  if (!Number.isSafeInteger(artifactsEnvelope.total_count) || artifactsEnvelope.total_count < 0) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACTS",
      "external workflow artifact total_count is invalid",
    );
  }
  if (!Array.isArray(artifactsEnvelope.artifacts)) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACTS",
      "external workflow artifact list is missing",
    );
  }
  if (artifactsEnvelope.total_count !== artifactsEnvelope.artifacts.length) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACTS",
      "external workflow artifact inventory is incomplete",
    );
  }
  if (artifactsEnvelope.artifacts.length > 1000) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACTS",
      "external workflow artifact list exceeds the observer bound",
    );
  }
  const artifacts = artifactsEnvelope.artifacts
    .map(normalizeArtifact)
    .sort((left, right) => left.name.localeCompare(right.name) || left.id - right.id);
  const ids = new Set(artifacts.map(artifact => artifact.id));
  const names = new Set(artifacts.map(artifact => artifact.name));
  if (ids.size !== artifacts.length || names.size !== artifacts.length) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_ARTIFACTS",
      "external workflow artifact inventory contains duplicate identities",
    );
  }
  const observer = normalizeObserver(options);
  const repositoryPreflightName = `ui-control-repository-preflight-${candidateCommit}`;
  const candidateBuildName = `ui-control-candidate-build-${candidateCommit}`;
  const protectedEvidenceName = `ui-control-external-evidence-${candidateCommit}`;
  const success = conclusion === "success";
  const observedAt = normalizeIso(options.observedAt ?? new Date().toISOString());

  return {
    schema: EXTERNAL_WORKFLOW_OBSERVATION_SCHEMA,
    status: success ? "passed" : "failed",
    observedAt,
    observer,
    sourceRun: {
      id: runId,
      attempt: runAttempt,
      workflowId,
      workflowName,
      headSha,
      event: run.event,
      status: run.status,
      conclusion,
      displayTitle: run.display_title,
      htmlUrl: typeof run.html_url === "string" ? run.html_url : null,
    },
    requestedCandidate: {
      commit: candidateCommit,
    },
    artifactInventory: artifacts,
    artifactInventoryComplete: true,
    evidenceAvailability: {
      repositoryPreflight: names.has(repositoryPreflightName),
      candidateBuild: names.has(candidateBuildName),
      protectedExternalEvidence: names.has(protectedEvidenceName),
    },
    observedOutcome: success ? "passed" : "failed",
    acceptedEvidence: false,
    failure: success
      ? null
      : {
          stage: "external-workflow",
          code: conclusionCode(conclusion),
          message: `external qualification workflow concluded with ${conclusion}`,
        },
    claims: falseClaims(),
  };
}

export function buildExternalWorkflowInfrastructureFailure(input = {}) {
  const observedAt = normalizeIso(input.observedAt ?? new Date().toISOString());
  const candidateCommit = typeof input.candidateCommit === "string" && SHA1.test(input.candidateCommit)
    ? input.candidateCommit
    : null;
  const runId = Number.isSafeInteger(input.runId) && input.runId > 0 ? input.runId : null;
  const runAttempt = Number.isSafeInteger(input.runAttempt) && input.runAttempt > 0
    ? input.runAttempt
    : null;
  return {
    schema: EXTERNAL_WORKFLOW_OBSERVATION_SCHEMA,
    status: "failed",
    observedAt,
    observer: {
      workflowSha: typeof input.observerWorkflowSha === "string" && SHA1.test(input.observerWorkflowSha)
        ? input.observerWorkflowSha
        : null,
      runId: Number.isSafeInteger(input.observerRunId) && input.observerRunId > 0
        ? input.observerRunId
        : null,
      runAttempt: Number.isSafeInteger(input.observerRunAttempt) && input.observerRunAttempt > 0
        ? input.observerRunAttempt
        : null,
      repository: typeof input.repository === "string" && input.repository.length > 0
        ? input.repository.slice(0, 256)
        : null,
    },
    sourceRun: {
      id: runId,
      attempt: runAttempt,
      workflowId: null,
      workflowName: EXTERNAL_WORKFLOW_NAME,
      headSha: typeof input.headSha === "string" && SHA1.test(input.headSha)
        ? input.headSha
        : null,
      event: "workflow_dispatch",
      status: "completed",
      conclusion: typeof input.conclusion === "string" ? input.conclusion : null,
      displayTitle: typeof input.displayTitle === "string" ? input.displayTitle : null,
      htmlUrl: null,
    },
    requestedCandidate: { commit: candidateCommit },
    artifactInventory: [],
    artifactInventoryComplete: false,
    evidenceAvailability: {
      repositoryPreflight: false,
      candidateBuild: false,
      protectedExternalEvidence: false,
    },
    observedOutcome: "failed",
    acceptedEvidence: false,
    failure: {
      stage: "observer-infrastructure",
      code: "UI_CONTROL_EXTERNAL_OBSERVER_INFRASTRUCTURE",
      message: typeof input.message === "string" && input.message.length > 0
        ? input.message.slice(0, 512)
        : "external workflow observer could not produce a semantic observation",
      checks: input.checks && typeof input.checks === "object" && !Array.isArray(input.checks)
        ? { ...input.checks }
        : {},
    },
    claims: falseClaims(),
  };
}

async function main() {
  const [runPath, artifactPath, outputPath] = process.argv.slice(2).map(value => value && resolve(value));
  if (!runPath || !artifactPath || !outputPath) {
    throw observationError(
      "UI_CONTROL_EXTERNAL_OBSERVER_USAGE",
      "usage: external-workflow-observation.mjs <workflow-run.json> <artifacts.json> <output.json>",
    );
  }
  const run = JSON.parse(await readFile(runPath, "utf8"));
  const artifacts = JSON.parse(await readFile(artifactPath, "utf8"));
  const observation = buildExternalWorkflowObservation(run, artifacts, {
    observerWorkflowSha: process.env.GITHUB_WORKFLOW_SHA,
    observerRunId: Number(process.env.GITHUB_RUN_ID),
    observerRunAttempt: Number(process.env.GITHUB_RUN_ATTEMPT),
    repository: process.env.GITHUB_REPOSITORY,
  });
  await writeFile(outputPath, `${JSON.stringify(observation, null, 2)}\n`);
  process.stdout.write(`${outputPath}\n`);
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    process.stderr.write(`${error.code ?? "UI_CONTROL_EXTERNAL_OBSERVER"}: ${error.message}\n`);
    process.exitCode = 1;
  });
}
