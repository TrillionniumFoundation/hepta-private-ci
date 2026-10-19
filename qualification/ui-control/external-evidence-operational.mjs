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

const MAX_OBJECTIVE_SECONDS = 24 * 60 * 60;

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

function exactZero(value, code, message) {
  assertEvidence(Number.isSafeInteger(value) && value === 0, code, message);
}

function positiveCount(value, code, message) {
  assertEvidence(Number.isSafeInteger(value) && value > 0, code, message);
}

function objectiveWindow(objective, observed, label) {
  assertEvidence(
    Number.isSafeInteger(objective) && objective > 0 && objective <= MAX_OBJECTIVE_SECONDS,
    "UI_CONTROL_OPERATIONS_OBJECTIVE",
    `${label} objective must be a positive bounded number of seconds`,
  );
  assertEvidence(
    Number.isSafeInteger(observed) && observed >= 0 && observed <= objective,
    "UI_CONTROL_OPERATIONS_OBJECTIVE_MISSED",
    `${label} exceeded its accepted objective`,
  );
}

function validateNotes(item) {
  if (item.notes !== undefined) boundedText(item.notes, `${item.id}.notes`, 4096);
}

function validateRollback(item, browserBuildManifestSha256) {
  assertExactKeys(
    item,
    [
      "id",
      "status",
      "rollbackBuildManifestSha256",
      "restoredBrowserBuildManifestSha256",
      "mutationFenceObserved",
      "operationLedgerContinuity",
      "unresolvedOperations",
      "duplicateSideEffects",
      "rawEvidenceDigest",
    ],
    ["notes"],
    "rollback",
  );
  const rollbackManifest = exactSha(
    item.rollbackBuildManifestSha256,
    "rollback.rollbackBuildManifestSha256",
    SHA256,
  );
  const restoredManifest = exactSha(
    item.restoredBrowserBuildManifestSha256,
    "rollback.restoredBrowserBuildManifestSha256",
    SHA256,
  );
  const candidateManifest = exactSha(
    browserBuildManifestSha256,
    "browserBuildManifestSha256",
    SHA256,
  );
  assertEvidence(
    rollbackManifest !== candidateManifest,
    "UI_CONTROL_OPERATIONS_ROLLBACK_DISTINCT",
    "rollback did not exercise a distinct retained browser build",
  );
  assertEvidence(
    restoredManifest === candidateManifest,
    "UI_CONTROL_OPERATIONS_ROLLBACK_RESTORE",
    "rollback exercise did not restore the exact qualified browser build",
  );
  assertEvidence(
    item.mutationFenceObserved === true,
    "UI_CONTROL_OPERATIONS_ROLLBACK_FENCE",
    "rollback did not retain a mutation fence while assets changed",
  );
  assertEvidence(
    item.operationLedgerContinuity === true,
    "UI_CONTROL_OPERATIONS_ROLLBACK_LEDGER",
    "rollback did not preserve durable operation-ledger continuity",
  );
  exactZero(
    item.unresolvedOperations,
    "UI_CONTROL_OPERATIONS_ROLLBACK_UNRESOLVED",
    "rollback left unresolved qualification operations",
  );
  exactZero(
    item.duplicateSideEffects,
    "UI_CONTROL_OPERATIONS_ROLLBACK_DUPLICATE_EFFECT",
    "rollback observed duplicate side effects",
  );
  validateNotes(item);
  return Object.freeze({
    rollbackBuildManifestSha256: rollbackManifest,
    restoredBrowserBuildManifestSha256: restoredManifest,
    unresolvedOperations: 0,
    duplicateSideEffects: 0,
  });
}

function validateDisasterRecovery(item) {
  assertExactKeys(
    item,
    [
      "id",
      "status",
      "objectiveRpoSeconds",
      "observedRpoSeconds",
      "objectiveRtoSeconds",
      "observedRtoSeconds",
      "operationLedgerRestored",
      "auditLinkageRestored",
      "terminalLookupContinuity",
      "unresolvedOperations",
      "duplicateSideEffects",
      "rawEvidenceDigest",
    ],
    ["notes"],
    "disaster-recovery",
  );
  objectiveWindow(
    item.objectiveRpoSeconds,
    item.observedRpoSeconds,
    "disaster-recovery RPO",
  );
  objectiveWindow(
    item.objectiveRtoSeconds,
    item.observedRtoSeconds,
    "disaster-recovery RTO",
  );
  assertEvidence(
    item.operationLedgerRestored === true,
    "UI_CONTROL_OPERATIONS_DR_LEDGER",
    "disaster recovery did not restore the durable operation ledger",
  );
  assertEvidence(
    item.auditLinkageRestored === true,
    "UI_CONTROL_OPERATIONS_DR_AUDIT",
    "disaster recovery did not restore audit linkage",
  );
  assertEvidence(
    item.terminalLookupContinuity === true,
    "UI_CONTROL_OPERATIONS_DR_LOOKUP",
    "disaster recovery did not preserve authoritative terminal lookup",
  );
  exactZero(
    item.unresolvedOperations,
    "UI_CONTROL_OPERATIONS_DR_UNRESOLVED",
    "disaster recovery left unresolved qualification operations",
  );
  exactZero(
    item.duplicateSideEffects,
    "UI_CONTROL_OPERATIONS_DR_DUPLICATE_EFFECT",
    "disaster recovery observed duplicate side effects",
  );
  validateNotes(item);
  return Object.freeze({
    objectiveRpoSeconds: item.objectiveRpoSeconds,
    observedRpoSeconds: item.observedRpoSeconds,
    objectiveRtoSeconds: item.objectiveRtoSeconds,
    observedRtoSeconds: item.observedRtoSeconds,
    unresolvedOperations: 0,
    duplicateSideEffects: 0,
  });
}

function validateAlertRouting(item) {
  assertExactKeys(
    item,
    [
      "id",
      "status",
      "alertRuleSha256",
      "routeConfigurationSha256",
      "objectiveAcknowledgementSeconds",
      "observedAcknowledgementSeconds",
      "alertTriggered",
      "routeMatched",
      "acknowledged",
      "escalationPolicyVerified",
      "rawEvidenceDigest",
    ],
    ["notes"],
    "alert-routing",
  );
  const alertRuleSha256 = exactSha(
    item.alertRuleSha256,
    "alert-routing.alertRuleSha256",
    SHA256,
  );
  const routeConfigurationSha256 = exactSha(
    item.routeConfigurationSha256,
    "alert-routing.routeConfigurationSha256",
    SHA256,
  );
  objectiveWindow(
    item.objectiveAcknowledgementSeconds,
    item.observedAcknowledgementSeconds,
    "alert acknowledgement",
  );
  for (const [field, code] of [
    ["alertTriggered", "UI_CONTROL_OPERATIONS_ALERT_TRIGGER"],
    ["routeMatched", "UI_CONTROL_OPERATIONS_ALERT_ROUTE"],
    ["acknowledged", "UI_CONTROL_OPERATIONS_ALERT_ACK"],
    ["escalationPolicyVerified", "UI_CONTROL_OPERATIONS_ALERT_ESCALATION"],
  ]) {
    assertEvidence(item[field] === true, code, `alert-routing ${field} was not observed`);
  }
  validateNotes(item);
  return Object.freeze({
    alertRuleSha256,
    routeConfigurationSha256,
    objectiveAcknowledgementSeconds: item.objectiveAcknowledgementSeconds,
    observedAcknowledgementSeconds: item.observedAcknowledgementSeconds,
  });
}

function validateLogRedaction(item) {
  assertExactKeys(
    item,
    [
      "id",
      "status",
      "logCorpusSha256",
      "secretCanaryCount",
      "secretCanaryMatches",
      "correlationCanaryCount",
      "fullIdentifierMatches",
      "redactedCorrelationMatches",
      "credentialMatches",
      "rawEvidenceDigest",
    ],
    ["notes"],
    "log-redaction",
  );
  const logCorpusSha256 = exactSha(
    item.logCorpusSha256,
    "log-redaction.logCorpusSha256",
    SHA256,
  );
  positiveCount(
    item.secretCanaryCount,
    "UI_CONTROL_OPERATIONS_REDACTION_SECRET_SAMPLE",
    "log-redaction requires at least one secret canary",
  );
  positiveCount(
    item.correlationCanaryCount,
    "UI_CONTROL_OPERATIONS_REDACTION_ID_SAMPLE",
    "log-redaction requires at least one correlation-identity canary",
  );
  exactZero(
    item.secretCanaryMatches,
    "UI_CONTROL_OPERATIONS_REDACTION_SECRET",
    "log corpus retained a secret canary",
  );
  exactZero(
    item.fullIdentifierMatches,
    "UI_CONTROL_OPERATIONS_REDACTION_IDENTIFIER",
    "log corpus retained a full correlation identifier",
  );
  exactZero(
    item.credentialMatches,
    "UI_CONTROL_OPERATIONS_REDACTION_CREDENTIAL",
    "log corpus retained credential material",
  );
  assertEvidence(
    Number.isSafeInteger(item.redactedCorrelationMatches) &&
      item.redactedCorrelationMatches === item.correlationCanaryCount,
    "UI_CONTROL_OPERATIONS_REDACTION_CORRELATION",
    "log corpus did not retain the expected redacted correlation form",
  );
  validateNotes(item);
  return Object.freeze({
    logCorpusSha256,
    secretCanaryCount: item.secretCanaryCount,
    correlationCanaryCount: item.correlationCanaryCount,
    secretCanaryMatches: 0,
    fullIdentifierMatches: 0,
    credentialMatches: 0,
  });
}

function validateCredentialRotation(item) {
  assertExactKeys(
    item,
    [
      "id",
      "status",
      "oldCredentialFingerprintSha256",
      "newCredentialFingerprintSha256",
      "activeOldCredentials",
      "oldCredentialRejectedStatus",
      "oldCredentialOperationCreated",
      "newCredentialAuthenticated",
      "permissionRevisionAdvanced",
      "postRotationLookupSucceeded",
      "rawEvidenceDigest",
    ],
    ["notes"],
    "credential-rotation",
  );
  const oldCredentialFingerprintSha256 = exactSha(
    item.oldCredentialFingerprintSha256,
    "credential-rotation.oldCredentialFingerprintSha256",
    SHA256,
  );
  const newCredentialFingerprintSha256 = exactSha(
    item.newCredentialFingerprintSha256,
    "credential-rotation.newCredentialFingerprintSha256",
    SHA256,
  );
  assertEvidence(
    oldCredentialFingerprintSha256 !== newCredentialFingerprintSha256,
    "UI_CONTROL_OPERATIONS_ROTATION_IDENTITY",
    "credential rotation reused the old credential fingerprint",
  );
  exactZero(
    item.activeOldCredentials,
    "UI_CONTROL_OPERATIONS_ROTATION_ACTIVE_OLD",
    "old credentials remain active after rotation",
  );
  assertEvidence(
    Number.isSafeInteger(item.oldCredentialRejectedStatus) &&
      [401, 403].includes(item.oldCredentialRejectedStatus),
    "UI_CONTROL_OPERATIONS_ROTATION_REJECTION",
    "old credential was not rejected by authentication or authorization",
  );
  assertEvidence(
    item.oldCredentialOperationCreated === false,
    "UI_CONTROL_OPERATIONS_ROTATION_RECORD",
    "old credential created a durable operation after rotation",
  );
  for (const [field, code] of [
    ["newCredentialAuthenticated", "UI_CONTROL_OPERATIONS_ROTATION_NEW_AUTH"],
    ["permissionRevisionAdvanced", "UI_CONTROL_OPERATIONS_ROTATION_PERMISSION"],
    ["postRotationLookupSucceeded", "UI_CONTROL_OPERATIONS_ROTATION_LOOKUP"],
  ]) {
    assertEvidence(item[field] === true, code, `credential-rotation ${field} was not observed`);
  }
  validateNotes(item);
  return Object.freeze({
    oldCredentialFingerprintSha256,
    newCredentialFingerprintSha256,
    activeOldCredentials: 0,
    oldCredentialRejectedStatus: item.oldCredentialRejectedStatus,
    oldCredentialOperationCreated: false,
  });
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
  exactZero(
    item.activeLegacyMutationSessions,
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
  validateNotes(item);
  return Object.freeze({
    activeLegacyMutationSessions: 0,
    staleClientMutationStatus: item.staleClientMutationStatus,
    freshClientBuildManifestSha256: observedManifest,
    staleClientOperationCreated: false,
  });
}

const validators = Object.freeze({
  rollback: validateRollback,
  "disaster-recovery": validateDisasterRecovery,
  "alert-routing": validateAlertRouting,
  "log-redaction": validateLogRedaction,
  "credential-rotation": validateCredentialRotation,
  "mixed-version-mutation-fence": validateMixedVersionFence,
});

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
  const summaries = {};
  for (const item of receipt.cases) {
    assertEvidence(
      item && typeof item === "object" && !Array.isArray(item),
      "UI_CONTROL_OPERATIONS_CASE",
      "operational exercise case must be an object",
    );
    assertEvidence(
      required.has(item.id),
      "UI_CONTROL_OPERATIONS_CASE_ID",
      `unexpected or duplicate operational exercise: ${item?.id ?? "unknown"}`,
    );
    assertEvidence(
      item.status === "passed",
      "UI_CONTROL_OPERATIONS_CASE_FAILED",
      `operational exercise failed: ${item.id}`,
    );
    exactSha(item.rawEvidenceDigest, `${item.id}.rawEvidenceDigest`, SHA256);
    summaries[item.id] = validators[item.id](item, browserBuildManifestSha256);
    required.delete(item.id);
  }
  assertEvidence(
    required.size === 0,
    "UI_CONTROL_OPERATIONS_SCOPE",
    `missing operational exercises: ${[...required].join(", ")}`,
  );
  return Object.freeze({
    schema: "hepta.ui-control.operational-exercise-summary.v1",
    caseCount: receipt.cases.length,
    cases: Object.freeze(summaries),
    mixedVersionMutationFence: summaries["mixed-version-mutation-fence"],
  });
}
