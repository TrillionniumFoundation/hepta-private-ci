import test from "node:test";
import assert from "node:assert/strict";
import {
  assertOperationObservation,
  assertSessionReconnection,
  assertSnapshotNotRegressed,
} from "../../../qualification/ui-control/real-backend-invariants.mjs";

const request = {
  operationId: "operation-1",
  semanticDigest: "a".repeat(64),
};

function observation(overrides = {}) {
  return {
    found: true,
    operationId: request.operationId,
    semanticDigest: request.semanticDigest,
    status: "succeeded",
    auditTraceId: "audit-operation-1",
    ...overrides,
  };
}

test("real-backend snapshot refresh rejects generation and revision regression", () => {
  const baseline = { generation: 7, revision: 11 };
  assert.equal(assertSnapshotNotRegressed(baseline, { generation: 7, revision: 11 }).revision, 11);
  assert.equal(assertSnapshotNotRegressed(baseline, { generation: 7, revision: 12 }).revision, 12);
  assert.equal(assertSnapshotNotRegressed(baseline, { generation: 8, revision: 1 }).generation, 8);
  assert.throws(
    () => assertSnapshotNotRegressed(baseline, { generation: 6, revision: 99 }),
    error => error.code === "UI_CONTROL_SNAPSHOT_GENERATION_REGRESSION",
  );
  assert.throws(
    () => assertSnapshotNotRegressed(baseline, { generation: 7, revision: 10 }),
    error => error.code === "UI_CONTROL_SNAPSHOT_REVISION_REGRESSION",
  );
});

test("real-backend lookup remains bound to operation identity, audit trace, and terminal state", () => {
  assert.equal(
    assertOperationObservation(observation(), request, {
      requireTerminal: true,
      expectedAuditTraceId: "audit-operation-1",
    }).status,
    "succeeded",
  );
  assert.equal(assertOperationObservation(observation({ status: "pending" }), request).status, "pending");
  assert.throws(
    () => assertOperationObservation(observation({ operationId: "operation-2" }), request),
    error => error.code === "UI_CONTROL_OPERATION_ID_MISMATCH",
  );
  assert.throws(
    () => assertOperationObservation(observation({ semanticDigest: "b".repeat(64) }), request),
    error => error.code === "UI_CONTROL_SEMANTIC_DIGEST_MISMATCH",
  );
  assert.throws(
    () => assertOperationObservation(
      observation({ auditTraceId: "audit-operation-2" }),
      request,
      { expectedAuditTraceId: "audit-operation-1" },
    ),
    error => error.code === "UI_CONTROL_AUDIT_TRACE_MISMATCH",
  );
  assert.throws(
    () => assertOperationObservation(observation({ status: "pending" }), request, { requireTerminal: true }),
    error => error.code === "UI_CONTROL_OPERATION_NOT_TERMINAL",
  );
});

test("same-principal reconnect requires a new session generation without permission regression", () => {
  const previous = {
    identityId: "operator-1",
    sessionId: "session-1",
    connectionGeneration: 4,
    permissionRevision: 7,
  };
  const next = {
    identityId: "operator-1",
    sessionId: "session-2",
    connectionGeneration: 5,
    permissionRevision: 8,
  };
  assert.equal(assertSessionReconnection(previous, next), next);
  assert.throws(
    () => assertSessionReconnection(previous, { ...next, identityId: "operator-2" }),
    error => error.code === "UI_CONTROL_SESSION_PRINCIPAL_CHANGED",
  );
  assert.throws(
    () => assertSessionReconnection(previous, { ...previous }),
    error => error.code === "UI_CONTROL_SESSION_SWITCH_GENERATION",
  );
  assert.throws(
    () => assertSessionReconnection(previous, { ...next, permissionRevision: 6 }),
    error => error.code === "UI_CONTROL_PERMISSION_REVISION_REGRESSION",
  );
});
