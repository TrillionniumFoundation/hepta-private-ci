import test from "node:test";
import assert from "node:assert/strict";
import {
  REQUIRED_OPERATIONAL_EXERCISE_CASES,
  validateOperationalExerciseWithRolloutFence,
} from "../../../qualification/ui-control/external-evidence-operational.mjs";

const expected = Object.freeze({
  candidateCommit: "1".repeat(40),
  candidateTree: "2".repeat(40),
  backendDeploymentDigest: "3".repeat(64),
});
const manifestDigest = "4".repeat(64);
const rawEvidenceDigest = "5".repeat(64);

function receipt() {
  return {
    schema: "hepta.ui-control.operational-exercise-receipt.v1",
    status: "passed",
    candidateCommit: expected.candidateCommit,
    candidateTree: expected.candidateTree,
    backendDeploymentDigest: expected.backendDeploymentDigest,
    executedAt: "2026-09-29T09:40:00.000Z",
    rawEvidenceDigest,
    cases: [
      {
        id: "rollback",
        status: "passed",
        rollbackBuildManifestSha256: "6".repeat(64),
        restoredBrowserBuildManifestSha256: manifestDigest,
        mutationFenceObserved: true,
        operationLedgerContinuity: true,
        unresolvedOperations: 0,
        duplicateSideEffects: 0,
        rawEvidenceDigest,
      },
      {
        id: "disaster-recovery",
        status: "passed",
        objectiveRpoSeconds: 300,
        observedRpoSeconds: 12,
        objectiveRtoSeconds: 1800,
        observedRtoSeconds: 420,
        operationLedgerRestored: true,
        auditLinkageRestored: true,
        terminalLookupContinuity: true,
        unresolvedOperations: 0,
        duplicateSideEffects: 0,
        rawEvidenceDigest,
      },
      {
        id: "alert-routing",
        status: "passed",
        alertRuleSha256: "7".repeat(64),
        routeConfigurationSha256: "8".repeat(64),
        objectiveAcknowledgementSeconds: 900,
        observedAcknowledgementSeconds: 42,
        alertTriggered: true,
        routeMatched: true,
        acknowledged: true,
        escalationPolicyVerified: true,
        rawEvidenceDigest,
      },
      {
        id: "log-redaction",
        status: "passed",
        logCorpusSha256: "9".repeat(64),
        secretCanaryCount: 4,
        secretCanaryMatches: 0,
        correlationCanaryCount: 6,
        fullIdentifierMatches: 0,
        redactedCorrelationMatches: 6,
        credentialMatches: 0,
        rawEvidenceDigest,
      },
      {
        id: "credential-rotation",
        status: "passed",
        oldCredentialFingerprintSha256: "a".repeat(64),
        newCredentialFingerprintSha256: "b".repeat(64),
        activeOldCredentials: 0,
        oldCredentialRejectedStatus: 403,
        oldCredentialOperationCreated: false,
        newCredentialAuthenticated: true,
        permissionRevisionAdvanced: true,
        postRotationLookupSucceeded: true,
        rawEvidenceDigest,
      },
      {
        id: "mixed-version-mutation-fence",
        status: "passed",
        oldMutationSessionsRevoked: true,
        cachedHtmlInvalidated: true,
        activeLegacyMutationSessions: 0,
        staleClientMutationStatus: 403,
        staleClientOperationCreated: false,
        freshClientBuildManifestSha256: manifestDigest,
        rawEvidenceDigest,
      },
    ],
  };
}

const options = Object.freeze({
  now: Date.parse("2026-09-29T10:00:00.000Z"),
  browserBuildManifestSha256: manifestDigest,
});

function caseById(value, id) {
  return value.cases.find(item => item.id === id);
}

test("operational evidence requires semantic proof for every release exercise", () => {
  const result = validateOperationalExerciseWithRolloutFence(receipt(), expected, options);
  assert.equal(result.caseCount, REQUIRED_OPERATIONAL_EXERCISE_CASES.length);
  assert.equal(result.cases.rollback.unresolvedOperations, 0);
  assert.equal(result.cases["disaster-recovery"].duplicateSideEffects, 0);
  assert.equal(result.cases["log-redaction"].fullIdentifierMatches, 0);
  assert.equal(result.cases["credential-rotation"].activeOldCredentials, 0);
  assert.deepEqual(result.mixedVersionMutationFence, {
    activeLegacyMutationSessions: 0,
    staleClientMutationStatus: 403,
    freshClientBuildManifestSha256: manifestDigest,
    staleClientOperationCreated: false,
  });
});

test("operational evidence rejects status-only placeholder cases", () => {
  const value = receipt();
  value.cases[0] = {
    id: "rollback",
    status: "passed",
    rawEvidenceDigest,
  };
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(value, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_CASE_FIELDS",
  );
});

test("rollback must exercise another build and restore the exact candidate", () => {
  const sameBuild = receipt();
  caseById(sameBuild, "rollback").rollbackBuildManifestSha256 = manifestDigest;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(sameBuild, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_ROLLBACK_DISTINCT",
  );

  const wrongRestore = receipt();
  caseById(wrongRestore, "rollback").restoredBrowserBuildManifestSha256 = "c".repeat(64);
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(wrongRestore, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_ROLLBACK_RESTORE",
  );
});

test("disaster recovery rejects missed objectives and duplicate effects", () => {
  const missedRto = receipt();
  caseById(missedRto, "disaster-recovery").observedRtoSeconds = 1801;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(missedRto, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_OBJECTIVE_MISSED",
  );

  const duplicate = receipt();
  caseById(duplicate, "disaster-recovery").duplicateSideEffects = 1;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(duplicate, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_DR_DUPLICATE_EFFECT",
  );
});

test("alert routing requires acknowledgement within the retained objective", () => {
  const value = receipt();
  caseById(value, "alert-routing").observedAcknowledgementSeconds = 901;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(value, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_OBJECTIVE_MISSED",
  );
});

test("log redaction rejects full identifiers, credentials, and missing redacted correlation", () => {
  const fullIdentifier = receipt();
  caseById(fullIdentifier, "log-redaction").fullIdentifierMatches = 1;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(fullIdentifier, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_REDACTION_IDENTIFIER",
  );

  const missingRedacted = receipt();
  caseById(missingRedacted, "log-redaction").redactedCorrelationMatches = 5;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(missingRedacted, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_REDACTION_CORRELATION",
  );
});

test("credential rotation rejects an old credential that still has mutation authority", () => {
  const value = receipt();
  caseById(value, "credential-rotation").oldCredentialOperationCreated = true;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(value, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_ROTATION_RECORD",
  );
});

test("mixed-version fencing rejects stale mutation admission and another restored build", () => {
  const admitted = receipt();
  caseById(admitted, "mixed-version-mutation-fence").staleClientOperationCreated = true;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(admitted, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_STALE_MUTATION_RECORD",
  );

  const wrongBuild = receipt();
  caseById(wrongBuild, "mixed-version-mutation-fence").freshClientBuildManifestSha256 = "d".repeat(64);
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(wrongBuild, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_BUILD_IDENTITY",
  );
});
