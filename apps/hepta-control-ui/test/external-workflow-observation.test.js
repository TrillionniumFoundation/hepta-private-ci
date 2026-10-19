import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  buildExternalWorkflowInfrastructureFailure,
  buildExternalWorkflowObservation,
  EXTERNAL_WORKFLOW_OBSERVATION_SCHEMA,
} from "../../../qualification/ui-control/external-workflow-observation.mjs";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const observerWorkflow = readFileSync(`${root}.github/workflows/ui-control-external-observer.yml`, "utf8");
const qualificationWorkflow = readFileSync(`${root}.github/workflows/ui-control-qualification.yml`, "utf8");
const schema = JSON.parse(readFileSync(`${root}qualification/ui-control/EXTERNAL_WORKFLOW_OBSERVATION_SCHEMA.json`, "utf8"));
const candidate = "a".repeat(40);
const workflowSha = "b".repeat(40);
const digest = `sha256:${"c".repeat(64)}`;
const observerWorkflowSha = "d".repeat(40);
const observerOptions = Object.freeze({
  observerWorkflowSha,
  observerRunId: 98765,
  observerRunAttempt: 1,
  repository: "example/repo",
});

function run(overrides = {}) {
  return {
    id: 12345,
    run_attempt: 2,
    workflow_id: 67890,
    name: "ui.control external deployment qualification",
    display_title: `ui.control external qualification ${candidate}`,
    event: "workflow_dispatch",
    status: "completed",
    conclusion: "success",
    head_sha: workflowSha,
    html_url: "https://github.com/example/repo/actions/runs/12345",
    ...overrides,
  };
}

function artifact(name, id) {
  return {
    id,
    name,
    size_in_bytes: 1024,
    digest,
    expired: false,
  };
}

test("external workflow observer records success without manufacturing acceptance", () => {
  const observation = buildExternalWorkflowObservation(
    run(),
    {
      total_count: 3,
      artifacts: [
        artifact(`ui-control-external-evidence-${candidate}`, 3),
        artifact(`ui-control-repository-preflight-${candidate}`, 1),
        artifact(`ui-control-candidate-build-${candidate}`, 2),
      ],
    },
    { ...observerOptions, observedAt: "2026-09-29T00:00:00Z" },
  );
  assert.equal(observation.schema, EXTERNAL_WORKFLOW_OBSERVATION_SCHEMA);
  assert.equal(observation.status, "passed");
  assert.equal(observation.requestedCandidate.commit, candidate);
  assert.deepEqual(observation.evidenceAvailability, {
    repositoryPreflight: true,
    candidateBuild: true,
    protectedExternalEvidence: true,
  });
  assert.equal(observation.acceptedEvidence, false);
  assert.equal(observation.artifactInventoryComplete, true);
  assert.deepEqual(observation.observer, {
    workflowSha: observerWorkflowSha,
    runId: 98765,
    runAttempt: 1,
    repository: "example/repo",
  });
  assert.equal(observation.failure, null);
  assert.ok(Object.values(observation.claims).every(value => value === false));
  assert.deepEqual(
    observation.artifactInventory.map(item => item.name),
    [
      `ui-control-candidate-build-${candidate}`,
      `ui-control-external-evidence-${candidate}`,
      `ui-control-repository-preflight-${candidate}`,
    ],
  );
});

test("failed external workflow remains a structured non-accepting observation", () => {
  const observation = buildExternalWorkflowObservation(
    run({ conclusion: "timed_out" }),
    { total_count: 0, artifacts: [] },
    { ...observerOptions, observedAt: "2026-09-29T00:00:00Z" },
  );
  assert.equal(observation.status, "failed");
  assert.equal(observation.observedOutcome, "failed");
  assert.equal(observation.failure.code, "UI_CONTROL_EXTERNAL_WORKFLOW_TIMED_OUT");
  assert.equal(observation.acceptedEvidence, false);
  assert.ok(Object.values(observation.claims).every(value => value === false));
});

test("external workflow observer rejects ambiguous subjects and artifact metadata", () => {
  assert.throws(
    () => buildExternalWorkflowObservation(
      run({ display_title: "ui.control external qualification refs/heads/main" }),
      { total_count: 0, artifacts: [] },
      observerOptions,
    ),
    /candidate commit/u,
  );
  assert.throws(
    () => buildExternalWorkflowObservation(
      run(),
      { total_count: 1, artifacts: [{ ...artifact("bad", 1), digest: "sha256:wrong" }] },
      observerOptions,
    ),
    /artifact digest/u,
  );
  assert.throws(
    () => buildExternalWorkflowObservation(
      run({ name: "another workflow" }),
      { total_count: 0, artifacts: [] },
      observerOptions,
    ),
    /unexpected external workflow/u,
  );
  assert.throws(
    () => buildExternalWorkflowObservation(
      run(),
      { total_count: 2, artifacts: [artifact("one", 1)] },
      observerOptions,
    ),
    /inventory is incomplete/u,
  );
  assert.throws(
    () => buildExternalWorkflowObservation(
      run(),
      { total_count: 2, artifacts: [artifact("same", 1), artifact("same", 2)] },
      observerOptions,
    ),
    /duplicate identities/u,
  );
});

test("observer infrastructure fallback preserves no acceptance authority", () => {
  const observation = buildExternalWorkflowInfrastructureFailure({
    observedAt: "2026-09-29T00:00:00Z",
    runId: 12345,
    runAttempt: 2,
    headSha: workflowSha,
    observerWorkflowSha,
    observerRunId: 98765,
    observerRunAttempt: 1,
    repository: "example/repo",
    candidateCommit: candidate,
    conclusion: "failure",
    message: "metadata retrieval failed",
    checks: { metadata: "failure" },
  });
  assert.equal(observation.status, "failed");
  assert.equal(observation.requestedCandidate.commit, candidate);
  assert.equal(observation.failure.code, "UI_CONTROL_EXTERNAL_OBSERVER_INFRASTRUCTURE");
  assert.equal(observation.artifactInventoryComplete, false);
  assert.equal(observation.sourceRun.headSha, workflowSha);
  assert.equal(observation.observer.workflowSha, observerWorkflowSha);
  assert.deepEqual(observation.failure.checks, { metadata: "failure" });
  assert.equal(observation.acceptedEvidence, false);
  assert.ok(Object.values(observation.claims).every(value => value === false));
});

test("observer workflow is secretless, default-branch trusted, and always uploads a fallback", () => {
  assert.match(observerWorkflow, /workflow_run:/u);
  assert.match(observerWorkflow, /ui\.control external deployment qualification/u);
  assert.doesNotMatch(observerWorkflow, /workflow_dispatch:/u);
  assert.match(observerWorkflow, /permissions:\n  actions: read\n  contents: read/u);
  assert.doesNotMatch(observerWorkflow, /\$\{\{\s*secrets\./u);
  assert.doesNotMatch(observerWorkflow, /github\.event\.workflow_run\.head_sha/u);
  assert.match(observerWorkflow, /ref: \$\{\{ github\.workflow_sha \}\}/u);
  assert.match(observerWorkflow, /external-workflow-observation\.mjs/u);
  assert.match(observerWorkflow, /Emit a fail-closed observer-infrastructure record/u);
  assert.match(observerWorkflow, /if: always\(\)/u);
  assert.match(observerWorkflow, /acceptedEvidence": False/u);
  assert.match(observerWorkflow, /Upload the immutable secretless observer evidence/u);
  assert.equal(schema.$id, EXTERNAL_WORKFLOW_OBSERVATION_SCHEMA);
  assert.equal(schema.properties.acceptedEvidence.const, false);
  for (const property of Object.values(schema.properties.claims.properties)) {
    assert.equal(property.const, false);
  }
});

test("every ui.control workflow change triggers exact-tree requalification", () => {
  const trigger = /- "\.github\/workflows\/ui-control-\*\.yml"/gu;
  assert.equal(qualificationWorkflow.match(trigger)?.length, 2);
  assert.doesNotMatch(qualificationWorkflow, /ui-control-qualification\.yml/u);
});
