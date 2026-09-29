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
      ...REQUIRED_OPERATIONAL_EXERCISE_CASES
        .filter(id => id !== "mixed-version-mutation-fence")
        .map(id => ({ id, status: "passed", rawEvidenceDigest })),
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

test("operational evidence binds mixed-version fencing to the exact qualified browser build", () => {
  const result = validateOperationalExerciseWithRolloutFence(receipt(), expected, options);
  assert.equal(result.caseCount, REQUIRED_OPERATIONAL_EXERCISE_CASES.length);
  assert.deepEqual(result.mixedVersionMutationFence, {
    activeLegacyMutationSessions: 0,
    staleClientMutationStatus: 403,
    freshClientBuildManifestSha256: manifestDigest,
    staleClientOperationCreated: false,
  });
});

test("operational evidence rejects a stale mutation that created an operation record", () => {
  const value = receipt();
  value.cases.at(-1).staleClientOperationCreated = true;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(value, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_STALE_MUTATION_RECORD",
  );
});

test("operational evidence rejects a rollout restored with another browser build", () => {
  const value = receipt();
  value.cases.at(-1).freshClientBuildManifestSha256 = "6".repeat(64);
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(value, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_BUILD_IDENTITY",
  );
});

test("operational evidence rejects any remaining legacy mutation-capable session", () => {
  const value = receipt();
  value.cases.at(-1).activeLegacyMutationSessions = 1;
  assert.throws(
    () => validateOperationalExerciseWithRolloutFence(value, expected, options),
    error => error?.code === "UI_CONTROL_OPERATIONS_LEGACY_SESSIONS",
  );
});
