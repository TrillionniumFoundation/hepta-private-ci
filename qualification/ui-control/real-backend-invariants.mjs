import { TERMINAL, assertEvidence } from "./external-evidence-primitives.mjs";

function positiveSafeInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

export function assertSnapshotNotRegressed(previous, next) {
  assertEvidence(previous && typeof previous === "object", "UI_CONTROL_SNAPSHOT_BASELINE", "previous snapshot is required");
  assertEvidence(next && typeof next === "object", "UI_CONTROL_SNAPSHOT_REFRESH", "refreshed snapshot is required");
  assertEvidence(
    positiveSafeInteger(previous.generation) && positiveSafeInteger(previous.revision),
    "UI_CONTROL_SNAPSHOT_BASELINE",
    "previous snapshot identity is invalid",
  );
  assertEvidence(
    positiveSafeInteger(next.generation) && positiveSafeInteger(next.revision),
    "UI_CONTROL_SNAPSHOT_REFRESH",
    "refreshed snapshot identity is invalid",
  );
  assertEvidence(
    next.generation >= previous.generation,
    "UI_CONTROL_SNAPSHOT_GENERATION_REGRESSION",
    "runtime generation regressed after a terminal operation",
  );
  if (next.generation === previous.generation) {
    assertEvidence(
      next.revision >= previous.revision,
      "UI_CONTROL_SNAPSHOT_REVISION_REGRESSION",
      "runtime revision regressed within one generation",
    );
  }
  return next;
}

export function assertOperationObservation(
  payload,
  request,
  { requireTerminal = false, expectedAuditTraceId = null } = {},
) {
  assertEvidence(payload?.found === true, "UI_CONTROL_OPERATION_NOT_FOUND", `operation ${request.operationId} was not found`);
  assertEvidence(
    payload.operationId === request.operationId,
    "UI_CONTROL_OPERATION_ID_MISMATCH",
    "operation lookup returned a different operation ID",
  );
  assertEvidence(
    payload.semanticDigest === request.semanticDigest,
    "UI_CONTROL_SEMANTIC_DIGEST_MISMATCH",
    "operation lookup returned a different semantic digest",
  );
  assertEvidence(
    typeof payload.auditTraceId === "string" && payload.auditTraceId.length > 0,
    "UI_CONTROL_AUDIT_TRACE_MISSING",
    "operation lookup did not retain an audit trace identity",
  );
  if (expectedAuditTraceId !== null) {
    assertEvidence(
      typeof expectedAuditTraceId === "string" && expectedAuditTraceId.length > 0,
      "UI_CONTROL_AUDIT_TRACE_EXPECTATION",
      "expected audit trace identity is invalid",
    );
    assertEvidence(
      payload.auditTraceId === expectedAuditTraceId,
      "UI_CONTROL_AUDIT_TRACE_MISMATCH",
      "operation lookup changed the durable audit trace identity",
    );
  }
  if (requireTerminal) {
    assertEvidence(
      TERMINAL.has(payload.status),
      "UI_CONTROL_OPERATION_NOT_TERMINAL",
      `operation ${request.operationId} is not terminal`,
    );
  }
  return payload;
}

export function assertSessionReconnection(previous, next) {
  assertEvidence(previous && typeof previous === "object", "UI_CONTROL_SESSION_BASELINE", "previous session is required");
  assertEvidence(next && typeof next === "object", "UI_CONTROL_SESSION_RECONNECT", "reconnected session is required");
  assertEvidence(
    next.identityId === previous.identityId,
    "UI_CONTROL_SESSION_PRINCIPAL_CHANGED",
    "same-principal reconnect changed authenticated identity",
  );
  assertEvidence(
    next.sessionId !== previous.sessionId || next.connectionGeneration !== previous.connectionGeneration,
    "UI_CONTROL_SESSION_SWITCH_GENERATION",
    "reconnect reused the revoked session identity and generation",
  );
  assertEvidence(
    positiveSafeInteger(previous.permissionRevision) && positiveSafeInteger(next.permissionRevision),
    "UI_CONTROL_PERMISSION_REVISION",
    "session permission revision is invalid",
  );
  assertEvidence(
    next.permissionRevision >= previous.permissionRevision,
    "UI_CONTROL_PERMISSION_REVISION_REGRESSION",
    "permission revision regressed after reconnect",
  );
  return next;
}
