import {
  assertCanonicalText,
  assertSafeInteger,
  assertSha256,
  assertStableIdentifier,
  constantTimeEqual,
} from "./canonical.js";
import {
  UI_CONTROL_ERROR_CODES,
  uiControlError,
} from "./errors.js";

export const UI_CONTROL_PROTOCOL_VERSION = "hepta.ui-control.v1";

export const UI_CONTROL_PERMISSIONS = Object.freeze({
  READ: "hepta://ui.control/runtime.read",
  REQUEST: "hepta://ui.control/runtime.request",
  START: "hepta://ui.control/runtime.start",
  STOP: "hepta://ui.control/runtime.stop",
});

export const TERMINAL_STATUSES = new Set([
  "succeeded",
  "failed",
  "rejected",
  "cancelled",
]);
export const ACTIVE_STATUSES = new Set([
  "accepted",
  "pending",
  "indeterminate",
]);

const KNOWN_PERMISSIONS = new Set(Object.values(UI_CONTROL_PERMISSIONS));

export function invalid(message, details) {
  return uiControlError(UI_CONTROL_ERROR_CODES.INVALID_INPUT, message, { details });
}

export function assertPlainObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw invalid(`${label} must be an object`, { label });
  }
  return value;
}

function normalizePermissions(value) {
  if (!Array.isArray(value) || value.length === 0 || value.length > KNOWN_PERMISSIONS.size) {
    throw invalid("session.permissions must be a non-empty bounded array");
  }
  const permissions = [];
  const seen = new Set();
  for (const [index, permission] of value.entries()) {
    assertCanonicalText(permission, `session.permissions[${index}]`, { maxBytes: 256 });
    if (!KNOWN_PERMISSIONS.has(permission)) {
      throw invalid("session contains an unknown permission", { permission });
    }
    if (seen.has(permission)) {
      throw invalid("session contains a duplicate permission", { permission });
    }
    seen.add(permission);
    permissions.push(permission);
  }
  return Object.freeze(permissions.sort());
}

export function normalizeSession(value, expectedProtocol, now) {
  assertPlainObject(value, "session");
  if (value.authenticated !== true) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.PERMISSION_DENIED,
      "backend did not establish an authenticated ui.control session",
    );
  }
  const protocolVersion = assertCanonicalText(value.protocolVersion, "session.protocolVersion", {
    maxBytes: 128,
  });
  if (protocolVersion !== expectedProtocol) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.PROTOCOL_MISMATCH,
      "backend protocol version is incompatible",
      { details: { expectedProtocol, actualProtocol: protocolVersion } },
    );
  }
  const sessionId = assertStableIdentifier(value.sessionId, "session.sessionId");
  const connectionGeneration = assertSafeInteger(
    value.connectionGeneration,
    "session.connectionGeneration",
    { min: 1 },
  );
  const permissionRevision = assertSafeInteger(
    value.permissionRevision,
    "session.permissionRevision",
    { min: 1 },
  );
  const expiresAt = assertSafeInteger(value.expiresAt, "session.expiresAt", { min: 1 });
  if (expiresAt <= now) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
      "ui.control session is already expired",
      { retryable: true, details: { expiresAt } },
    );
  }
  if (value.revoked === true) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.SESSION_REVOKED,
      "ui.control session is revoked",
    );
  }
  return Object.freeze({
    authenticated: true,
    protocolVersion,
    sessionId,
    connectionGeneration,
    permissionRevision,
    expiresAt,
    revoked: false,
    permissions: normalizePermissions(value.permissions),
    identityId: value.identityId === undefined
      ? null
      : assertStableIdentifier(value.identityId, "session.identityId"),
  });
}

export function publicOperation(entry) {
  return Object.freeze({
    operationId: entry.operationId,
    semanticDigest: entry.semanticDigest,
    method: entry.method,
    action: entry.action,
    targetId: entry.targetId,
    state: entry.state,
    auditTraceId: entry.auditTraceId ?? null,
    generation: entry.generation,
    displayedRevision: entry.displayedRevision,
    createdAt: entry.createdAt,
    updatedAt: entry.updatedAt,
    terminalStatus: entry.terminalStatus ?? null,
    outcomeDigest: entry.outcomeDigest ?? null,
    authorityGranted: false,
  });
}

export function operationMatches(entry, request) {
  return (
    entry.method === request.method &&
    entry.semanticDigest === request.semanticDigest &&
    entry.action === request.action &&
    entry.targetId === request.targetId
  );
}

export function validateAcknowledgement(entry, acknowledgement) {
  assertPlainObject(acknowledgement, "acknowledgement");
  if (acknowledgement.accepted !== true) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.BACKEND_REJECTED,
      acknowledgement.message || "backend rejected the control request",
      {
        details: {
          operationId: entry.operationId,
          backendCode: acknowledgement.errorCode ?? null,
        },
      },
    );
  }
  const operationId = assertStableIdentifier(
    acknowledgement.operationId,
    "acknowledgement.operationId",
  );
  const semanticDigest = assertSha256(
    acknowledgement.semanticDigest,
    "acknowledgement.semanticDigest",
  );
  const status = assertCanonicalText(acknowledgement.status, "acknowledgement.status", {
    maxBytes: 32,
  });
  const auditTraceId = assertStableIdentifier(
    acknowledgement.auditTraceId,
    "acknowledgement.auditTraceId",
  );
  if (
    operationId !== entry.operationId ||
    !constantTimeEqual(semanticDigest, entry.semanticDigest) ||
    !ACTIVE_STATUSES.has(status)
  ) {
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.ACK_MISMATCH,
      "backend acknowledgement does not bind the submitted operation",
      {
        retryable: true,
        details: { operationId: entry.operationId, auditTraceId },
      },
    );
  }
  return Object.freeze({ status, auditTraceId });
}
