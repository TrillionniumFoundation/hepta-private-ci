import {
  SHA256,
  assertEvidence,
  boundedText,
  exactSha,
  validateCommonReceipt,
} from "./external-evidence-primitives.mjs";

export const REQUIRED_OPERATIONAL_EXERCISE_CASES = Object.freeze([
  "rollback",
  "disaster-recovery",
  "alert-routing",
  "log-redaction",
  "credential-rotation",
  "mixed-version-mutation-fence",
]);

const STANDARD_OPERATIONAL_EXERCISE_CASES = new Set(
  REQUIRED_OPERATIONAL_EXERCISE_CASES.filter(id => id !== "mixed-version-mutation-fence"),
);

function assertExactKeys(value, required, optional, label) {
  assertEvidence(
    value && typeof value === "object" && !Array.isArray(value),
    "UI_CONTROL_OPERATIONS_CASE",
    `${label} must be an object`,
  );
  const allowed = new Set([...required, ...optional]);
  const keys = Object.keys(value);
  assertEvidence(
    required.every(key => keys.includes(key)) && keys.every(key => allowed.has(key)),
    "UI_CONTROL_OPERATIONS_CASE_FIELDS",
    `${label} has unknown or missing fields`,
  );
}

function validateStandardCase(item) {
  assertExactKeys(
    item,
    ["id", "status", "rawEvidenceDigest"],
    ["notes"],
    `operational exercise ${item?.id ?? "unknown"}`,
  );
  if (item.notes !== undefined) boundedText(item.notes, `${item.id}.notes`, 4096);
}

function validateMixedVersionFence(item, browserBuildManifestSha256) {
  assertExactKeys(
    item,
    [
      "id",
      "status",
      "oldMutationSessionsRevoked",
      "cachedHtmlInvalidated",
      "activeLegacyMutationSessions",
      "staleClientMutationStatus",
      "staleClientOperationCreated",
      "freshClientBuildManifestSha256",
      "rawEvidenceDigest",
    ],
    ["notes"],
    "mixed-version-mutation-fence",
  );
  assertEvidence(
    item.oldMutationSessionsRevoked === true,
    "UI_CONTROL_OPERATIONS_LEGACY_SESSION_REVOCATION",
    "old mutation-capable sessions were not revoked or drained",
  );
  assertEvidence(
    item.cachedHtmlInvalidated === true,
    "UI_CONTROL_OPERATIONS_CACHE_INVALIDATION",
    "cached HTML was not invalidated before mutation permission was restored",
  );
  assertEvidence(
    Number.isSafeInteger(item.activeLegacyMutationSessions) &&
      item.activeLegacyMutationSessions === 0,
    "UI_CONTROL_OPERATIONS_LEGACY_SESSIONS",
    "legacy mutation-capable sessions remain active",
  );
  assertEvidence(
    Number.isSafeInteger(item.staleClientMutationStatus) &&
      [401, 403].includes(item.staleClientMutationStatus),
    "UI_CONTROL_OPERATIONS_STALE_MUTATION_STATUS",
    "a stale client mutation was not rejected by authentication or authorization",
  );
  assertEvidence(
    item.staleClientOperationCreated === false,
    "UI_CONTROL_OPERATIONS_STALE_MUTATION_RECORD",
    "a stale client mutation created a durable operation record",
  );
  const observedManifest = exactSha(
    item.freshClientBuildManifestSha256,
    "mixed-version-mutation-fence.freshClientBuildManifestSha256",
    SHA256,
  );
  const expectedManifest = exactSha(
    browserBuildManifestSha256,
    "browserBuildManifestSha256",
    SHA256,
  );
  assertEvidence(
    observedManifest === expectedManifest,
    "UI_CONTROL_OPERATIONS_BUILD_IDENTITY",
    "mixed-version rollout exercise did not restore the exact qualified browser build",
  );
  if (item.notes !== undefined) boundedText(item.notes, `${item.id}.notes`, 4096);
  return Object.freeze({
    activeLegacyMutationSessions: item.activeLegacyMutationSessions,
    staleClientMutationStatus: item.staleClientMutationStatus,
    freshClientBuildManifestSha256: observedManifest,
    staleClientOperationCreated: false,
  });
}

export function validateOperationalExerciseWithRolloutFence(
  receipt,
  expected,
  { now = Date.now(), maxAgeMs = 90 * 24 * 60 * 60_000, browserBuildManifestSha256 } = {},
) {
  validateCommonReceipt(
    receipt,
    "hepta.ui-control.operational-exercise-receipt.v1",
    expected,
    now,
    maxAgeMs,
  );
  assertEvidence(
    Array.isArray(receipt.cases) &&
      receipt.cases.length === REQUIRED_OPERATIONAL_EXERCISE_CASES.length,
    "UI_CONTROL_OPERATIONS_CASES",
    "operational exercise receipt must contain exactly the required cases",
  );
  const required = new Set(REQUIRED_OPERATIONAL_EXERCISE_CASES);
  const observed = new Set();
  let rolloutFence = null;
  for (const item of receipt.cases) {
    assertEvidence(
      item && typeof item === "object" && !Array.isArray(item),
      "UI_CONTROL_OPERATIONS_CASE",
      "operational exercise case must be an object",
    );
    assertEvidence(
      required.has(item.id) && !observed.has(item.id),
      "UI_CONTROL_OPERATIONS_CASE_ID",
      `unexpected or duplicate operational exercise: ${item?.id ?? "unknown"}`,
    );
    assertEvidence(
      item.status === "passed",
      "UI_CONTROL_OPERATIONS_CASE_FAILED",
      `operational exercise failed: ${item.id}`,
    );
    exactSha(item.rawEvidenceDigest, `${item.id}.rawEvidenceDigest`, SHA256);
    if (STANDARD_OPERATIONAL_EXERCISE_CASES.has(item.id)) {
      validateStandardCase(item);
    } else {
      rolloutFence = validateMixedVersionFence(item, browserBuildManifestSha256);
    }
    observed.add(item.id);
    required.delete(item.id);
  }
  assertEvidence(
    required.size === 0 && rolloutFence !== null,
    "UI_CONTROL_OPERATIONS_SCOPE",
    `missing operational exercises: ${[...required].join(", ")}`,
  );
  return Object.freeze({
    schema: "hepta.ui-control.operational-exercise-summary.v1",
    caseCount: observed.size,
    mixedVersionMutationFence: rolloutFence,
  });
}
