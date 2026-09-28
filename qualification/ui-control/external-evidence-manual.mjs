import {
  CHAOS_CASES,
  SHA1,
  SHA256,
  TERMINAL,
  assertEvidence,
  boundedText,
  exactSha,
  parseTimestamp,
  validateCommonReceipt,
} from "./external-evidence-primitives.mjs";

export function validateChaosEvidence(evidence, expected, options = {}) {
  const now = options.now ?? Date.now();
  const maxAgeMs = options.maxAgeMs ?? 30 * 24 * 60 * 60_000;
  assertEvidence(evidence && typeof evidence === "object" && !Array.isArray(evidence), "UI_CONTROL_CHAOS_OBJECT", "chaos evidence must be an object");
  assertEvidence(evidence.schema === "hepta.ui-control.agentd-chaos-evidence.v2", "UI_CONTROL_CHAOS_SCHEMA", "unsupported chaos evidence schema");
  exactSha(evidence.candidateCommit, "candidateCommit", SHA1);
  exactSha(evidence.candidateTree, "candidateTree", SHA1);
  exactSha(evidence.backendDeploymentDigest, "backendDeploymentDigest", SHA256);
  exactSha(evidence.rawEvidenceDigest, "rawEvidenceDigest", SHA256);
  assertEvidence(evidence.candidateCommit === expected.candidateCommit, "UI_CONTROL_CHAOS_COMMIT", "chaos evidence is bound to another candidate commit");
  assertEvidence(evidence.candidateTree === expected.candidateTree, "UI_CONTROL_CHAOS_TREE", "chaos evidence is bound to another candidate tree");
  assertEvidence(evidence.backendDeploymentDigest === expected.backendDeploymentDigest, "UI_CONTROL_CHAOS_DEPLOYMENT", "chaos evidence is bound to another backend deployment");
  parseTimestamp(evidence.executedAt, "executedAt", now, maxAgeMs);
  boundedText(evidence.executor, "executor");
  assertEvidence(Array.isArray(evidence.cases) && evidence.cases.length === CHAOS_CASES.size, "UI_CONTROL_CHAOS_CASE_COUNT", "chaos evidence must contain exactly the required cases");

  const ids = new Set();
  const operationIds = new Set();
  for (const item of evidence.cases) {
    assertEvidence(item && typeof item === "object" && !Array.isArray(item), "UI_CONTROL_CHAOS_CASE", "chaos case must be an object");
    const policy = CHAOS_CASES.get(item.id);
    assertEvidence(policy, "UI_CONTROL_CHAOS_CASE_ID", `unexpected chaos case: ${item.id}`);
    assertEvidence(!ids.has(item.id), "UI_CONTROL_CHAOS_DUPLICATE_CASE", `duplicate chaos case: ${item.id}`);
    ids.add(item.id);
    assertEvidence(item.status === "passed", "UI_CONTROL_CHAOS_CASE_FAILED", `chaos case did not pass: ${item.id}`);
    boundedText(item.operationId, `${item.id}.operationId`, 192);
    assertEvidence(!operationIds.has(item.operationId), "UI_CONTROL_CHAOS_OPERATION_REUSE", "chaos cases must use distinct operation IDs");
    operationIds.add(item.operationId);
    exactSha(item.rawEvidenceDigest, `${item.id}.rawEvidenceDigest`, SHA256);
    assertEvidence(Number.isInteger(item.observedRecordCount), "UI_CONTROL_CHAOS_RECORD_COUNT", `${item.id} record count must be an integer`);
    assertEvidence(Number.isInteger(item.observedSideEffectCount), "UI_CONTROL_CHAOS_EFFECT_COUNT", `${item.id} side-effect count must be an integer`);
    assertEvidence(item.observedRecordCount === policy.records, "UI_CONTROL_CHAOS_RECORD_SEMANTICS", `${item.id} observed the wrong durable record count`);
    const allowedEffects = Array.isArray(policy.effects) ? policy.effects : [policy.effects];
    assertEvidence(allowedEffects.includes(item.observedSideEffectCount), "UI_CONTROL_CHAOS_EFFECT_SEMANTICS", `${item.id} observed an invalid side-effect count`);
    if (policy.terminal) {
      assertEvidence(TERMINAL.has(item.terminalStatus), "UI_CONTROL_CHAOS_TERMINAL", `${item.id} did not retain a terminal observation`);
    }
  }
  assertEvidence(ids.size === CHAOS_CASES.size, "UI_CONTROL_CHAOS_REQUIRED_CASE", "one or more required chaos cases are missing");
  return Object.freeze({ caseCount: ids.size, executedAt: evidence.executedAt, rawEvidenceDigest: evidence.rawEvidenceDigest });
}

export function validateAuthorityEvidence(receipt, expected, options = {}) {
  const now = options.now ?? Date.now();
  validateCommonReceipt(receipt, "hepta.ui-control.authority-evidence-receipt.v1", expected, now, options.maxAgeMs ?? 30 * 24 * 60 * 60_000);
  boundedText(receipt.executor, "executor");
  const required = new Set([
    "permission-revision-change-observed",
    "permission-revocation-fences-mutation",
    "session-switch-requires-new-generation",
  ]);
  const observed = new Set();
  assertEvidence(Array.isArray(receipt.cases), "UI_CONTROL_AUTHORITY_CASES", "authority evidence cases are required");
  for (const item of receipt.cases) {
    assertEvidence(item?.status === "passed", "UI_CONTROL_AUTHORITY_CASE_FAILED", `authority case failed: ${item?.id ?? "unknown"}`);
    assertEvidence(required.has(item.id), "UI_CONTROL_AUTHORITY_CASE_ID", `unexpected or duplicate authority case: ${item?.id ?? "unknown"}`);
    assertEvidence(!observed.has(item.id), "UI_CONTROL_AUTHORITY_DUPLICATE_CASE", `duplicate authority case: ${item.id}`);
    observed.add(item.id);
    required.delete(item.id);
    exactSha(item.rawEvidenceDigest, `${item.id}.rawEvidenceDigest`, SHA256);
    if (item.id === "permission-revision-change-observed") {
      assertEvidence(Number.isSafeInteger(item.beforePermissionRevision) && item.beforePermissionRevision >= 0, "UI_CONTROL_AUTHORITY_PERMISSION_REVISION", "before permission revision is invalid");
      assertEvidence(Number.isSafeInteger(item.afterPermissionRevision) && item.afterPermissionRevision > item.beforePermissionRevision, "UI_CONTROL_AUTHORITY_PERMISSION_REVISION", "permission revision did not advance");
    } else if (item.id === "permission-revocation-fences-mutation") {
      assertEvidence([401, 403].includes(item.postRevocationStatus), "UI_CONTROL_AUTHORITY_REVOCATION_STATUS", "revoked mutation did not fail with 401 or 403");
      assertEvidence(item.operationCreated === false, "UI_CONTROL_AUTHORITY_REVOCATION_RECORD", "revoked mutation created a durable operation");
    } else if (item.id === "session-switch-requires-new-generation") {
      exactSha(item.beforeSessionIdDigest, "beforeSessionIdDigest", SHA256);
      exactSha(item.afterSessionIdDigest, "afterSessionIdDigest", SHA256);
      assertEvidence(Number.isSafeInteger(item.beforeConnectionGeneration) && item.beforeConnectionGeneration > 0, "UI_CONTROL_AUTHORITY_SESSION_GENERATION", "before connection generation is invalid");
      assertEvidence(Number.isSafeInteger(item.afterConnectionGeneration) && item.afterConnectionGeneration > 0, "UI_CONTROL_AUTHORITY_SESSION_GENERATION", "after connection generation is invalid");
      assertEvidence(
        item.beforeSessionIdDigest !== item.afterSessionIdDigest || item.afterConnectionGeneration > item.beforeConnectionGeneration,
        "UI_CONTROL_AUTHORITY_SESSION_SWITCH",
        "session switch reused both the session identity and connection generation",
      );
    }
  }
  assertEvidence(required.size === 0, "UI_CONTROL_AUTHORITY_SCOPE", `missing authority cases: ${[...required].join(", ")}`);
}

export function validateIndependentAcceptance(receipt, expected, options = {}) {
  const now = options.now ?? Date.now();
  validateCommonReceipt(receipt, "hepta.ui-control.independent-acceptance-receipt.v2", expected, now, options.maxAgeMs ?? 90 * 24 * 60 * 60_000);
  assertEvidence(receipt.verifier?.independentOfImplementationAuthor === true, "UI_CONTROL_ACCEPTANCE_INDEPENDENCE", "acceptance verifier is not independent");
  boundedText(receipt.verifier?.identity, "verifier.identity");
  boundedText(receipt.verifier?.organization, "verifier.organization");
  assertEvidence(Array.isArray(receipt.observations) && receipt.observations.length >= 5, "UI_CONTROL_ACCEPTANCE_OBSERVATIONS", "independent acceptance requires a browser and assistive-technology matrix");
  const browsers = new Set();
  const modalities = new Set();
  const assistiveTechnologies = new Set();
  const observationIds = new Set();
  for (const item of receipt.observations) {
    assertEvidence(item?.result === "pass", "UI_CONTROL_ACCEPTANCE_CASE_FAILED", `acceptance observation failed: ${item?.id ?? "unknown"}`);
    boundedText(item.id, "observation.id", 128);
    assertEvidence(!observationIds.has(item.id), "UI_CONTROL_ACCEPTANCE_DUPLICATE", `duplicate acceptance observation: ${item.id}`);
    observationIds.add(item.id);
    assertEvidence(["browser-operator", "keyboard-only", "screen-reader"].includes(item.modality), "UI_CONTROL_ACCEPTANCE_MODALITY", `unsupported acceptance modality: ${item.modality}`);
    assertEvidence(["Chrome", "Firefox", "Safari"].includes(item.browser?.name), "UI_CONTROL_ACCEPTANCE_BROWSER", "Chrome, Firefox, or Safari is required");
    boundedText(item.browser.version, "browser.version", 64);
    boundedText(item.os, "observation.os", 128);
    exactSha(item.rawEvidenceDigest, "observation.rawEvidenceDigest", SHA256);
    browsers.add(item.browser.name);
    modalities.add(item.modality);
    if (item.modality === "screen-reader") {
      boundedText(item.assistiveTechnology?.name, "assistiveTechnology.name", 128);
      boundedText(item.assistiveTechnology?.version, "assistiveTechnology.version", 64);
      assistiveTechnologies.add(`${item.assistiveTechnology.name}:${item.assistiveTechnology.version}`);
    }
  }
  assertEvidence(["Chrome", "Firefox", "Safari"].every(name => browsers.has(name)), "UI_CONTROL_ACCEPTANCE_BROWSER_MATRIX", "Chrome, Firefox, and Safari observations are all required");
  assertEvidence(modalities.has("keyboard-only") && modalities.has("screen-reader"), "UI_CONTROL_ACCEPTANCE_MODALITY_MATRIX", "keyboard-only and screen-reader observations are required");
  assertEvidence(assistiveTechnologies.size >= 2, "UI_CONTROL_ACCEPTANCE_AT_MATRIX", "at least two distinct assistive-technology observations are required");
}

export function validateIndependentSecurityReview(receipt, expected, options = {}) {
  const now = options.now ?? Date.now();
  validateCommonReceipt(receipt, "hepta.ui-control.independent-security-review-receipt.v1", expected, now, options.maxAgeMs ?? 90 * 24 * 60 * 60_000);
  assertEvidence(receipt.reviewer?.independentOfImplementationAuthor === true, "UI_CONTROL_SECURITY_INDEPENDENCE", "security reviewer is not independent");
  boundedText(receipt.reviewer?.identity, "reviewer.identity");
  boundedText(receipt.reviewer?.organization, "reviewer.organization");
  const requiredScope = ["tls", "csp", "csrf", "cors", "cookie", "identity", "session", "operation-ledger", "logging-redaction", "penetration-test"];
  assertEvidence(Array.isArray(receipt.scope) && requiredScope.every(item => receipt.scope.includes(item)), "UI_CONTROL_SECURITY_SCOPE", "security review scope is incomplete");
  assertEvidence(receipt.findings?.openCritical === 0 && receipt.findings?.openHigh === 0, "UI_CONTROL_SECURITY_FINDINGS", "critical or high security findings remain open");
}

export function validateOperationalExercise(receipt, expected, options = {}) {
  const now = options.now ?? Date.now();
  validateCommonReceipt(receipt, "hepta.ui-control.operational-exercise-receipt.v1", expected, now, options.maxAgeMs ?? 90 * 24 * 60 * 60_000);
  const required = new Set(["rollback", "disaster-recovery", "alert-routing", "log-redaction", "credential-rotation"]);
  assertEvidence(Array.isArray(receipt.cases), "UI_CONTROL_OPERATIONS_CASES", "operational exercise cases are required");
  const observed = new Set();
  for (const item of receipt.cases) {
    assertEvidence(item?.status === "passed", "UI_CONTROL_OPERATIONS_CASE_FAILED", `operational exercise failed: ${item?.id ?? "unknown"}`);
    assertEvidence(required.has(item.id) && !observed.has(item.id), "UI_CONTROL_OPERATIONS_CASE_ID", `unexpected or duplicate operational exercise: ${item?.id ?? "unknown"}`);
    observed.add(item.id);
    required.delete(item.id);
    exactSha(item.rawEvidenceDigest, `${item.id}.rawEvidenceDigest`, SHA256);
  }
  assertEvidence(required.size === 0, "UI_CONTROL_OPERATIONS_SCOPE", `missing operational exercises: ${[...required].join(", ")}`);
}

export function validateProductionApproval(receipt, expected, evidenceDigests, options = {}) {
  const now = options.now ?? Date.now();
  validateCommonReceipt(receipt, "hepta.ui-control.production-approval-receipt.v1", expected, now, options.maxAgeMs ?? 30 * 24 * 60 * 60_000);
  const approvedAt = Date.parse(receipt.approvedAt);
  const expiresAt = Date.parse(receipt.expiresAt);
  assertEvidence(Number.isFinite(approvedAt) && Number.isFinite(expiresAt), "UI_CONTROL_EVIDENCE_TIME", "approval timestamps are invalid");
  assertEvidence(expiresAt > now && expiresAt > approvedAt, "UI_CONTROL_APPROVAL_EXPIRED", "production approval is expired or has an invalid lifetime");
  assertEvidence(expiresAt <= approvedAt + 90 * 24 * 60 * 60_000, "UI_CONTROL_APPROVAL_LIFETIME", "production approval lifetime exceeds 90 days");
  assertEvidence(receipt.signature?.kind === "sigstore-bundle" && SHA256.test(receipt.signature?.digest ?? ""), "UI_CONTROL_APPROVAL_SIGNATURE", "retained Sigstore bundle metadata is required");
  assertEvidence(Array.isArray(receipt.approvals), "UI_CONTROL_APPROVALS", "production approvals are required");
  const roles = new Set();
  const identities = new Set();
  for (const item of receipt.approvals) {
    const identity = boundedText(item?.identity, "approval.identity");
    assertEvidence(["deployment-authority", "release-authority", "security-authority"].includes(item?.role), "UI_CONTROL_APPROVAL_ROLE", `unsupported approval role: ${item?.role ?? "unknown"}`);
    assertEvidence(!roles.has(item.role), "UI_CONTROL_APPROVAL_DUPLICATE_ROLE", `duplicate approval role: ${item.role}`);
    assertEvidence(!identities.has(identity), "UI_CONTROL_APPROVAL_DUPLICATE_IDENTITY", "deployment, release, and security approvals require distinct identities");
    roles.add(item.role);
    identities.add(identity);
  }
  assertEvidence(["deployment-authority", "release-authority", "security-authority"].every(role => roles.has(role)), "UI_CONTROL_APPROVAL_ROLES", "deployment, release, and security authorities must approve");
  assertEvidence(identities.size >= 3, "UI_CONTROL_APPROVAL_IDENTITIES", "three distinct approval identities are required");
  const expectedKeys = Object.keys(evidenceDigests).sort();
  const actualKeys = Object.keys(receipt.evidenceDigests ?? {}).sort();
  assertEvidence(JSON.stringify(actualKeys) === JSON.stringify(expectedKeys), "UI_CONTROL_APPROVAL_EVIDENCE_KEYS", "production approval evidence digest set is incomplete or contains extras");
  for (const [key, digest] of Object.entries(evidenceDigests)) {
    assertEvidence(receipt.evidenceDigests?.[key] === digest, "UI_CONTROL_APPROVAL_EVIDENCE_DIGEST", `production approval does not bind ${key}`);
  }
}
