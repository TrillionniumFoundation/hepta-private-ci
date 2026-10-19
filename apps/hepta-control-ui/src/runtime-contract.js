import {
  assertCanonicalText,
  assertSafeInteger,
  assertSha256,
  assertStableIdentifier,
  constantTimeEqual,
  canonicalJson,
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
const FORBIDDEN_KEYS = new Set(["__proto__", "constructor", "prototype"]);
const SAFE_BACKEND_CODE = /^[A-Za-z0-9._:-]{1,128}$/u;

export function invalid(message, details) {
  return uiControlError(UI_CONTROL_ERROR_CODES.INVALID_INPUT, message, { details });
}

export function assertPlainObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw invalid(`${label} must be an object`, { label });
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw invalid(`${label} must be a plain object`, { label });
  }
  const symbols = Object.getOwnPropertySymbols(value);
  if (symbols.length > 0) {
    throw invalid(`${label} cannot contain symbol keys`, { label });
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  for (const [key, descriptor] of Object.entries(descriptors)) {
    if (FORBIDDEN_KEYS.has(key)) {
      throw invalid(`${label} contains a forbidden object key`, { label, key });
    }
    if (!("value" in descriptor) || descriptor.get || descriptor.set) {
      throw invalid(`${label} cannot contain accessors`, { label, key });
    }
    if (!descriptor.enumerable) {
      throw invalid(`${label} cannot contain hidden properties`, { label, key });
    }
  }
  return value;
}

function normalizePermissions(value) {
  if (!Array.isArray(value) || value.length === 0 || value.length > KNOWN_PERMISSIONS.size) {
    throw invalid("session.permissions must be a non-empty bounded array");
  }
  value = JSON.parse(canonicalJson(value, {
    maxArrayLength: KNOWN_PERMISSIONS.size, maxEntries: KNOWN_PERMISSIONS.size,
    maxStringBytes: 256, maxEncodedBytes: 2048,
  }));
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
  const identityId = assertStableIdentifier(value.identityId, "session.identityId");
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
    identityId,
    connectionGeneration,
    permissionRevision,
    expiresAt,
    revoked: false,
    permissions: normalizePermissions(value.permissions),
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
    entry.protocolVersion === request.protocolVersion &&
    entry.method === request.method &&
    entry.operationId === request.operationId &&
    constantTimeEqual(entry.semanticDigest, request.semanticDigest) &&
    entry.action === request.action &&
    entry.targetId === request.targetId &&
    entry.reason === request.reason &&
    entry.sessionId === request.sessionId &&
    entry.connectionGeneration === request.connectionGeneration &&
    entry.generation === request.generation &&
    entry.displayedRevision === request.displayedRevision &&
    constantTimeEqual(entry.snapshotDigest, request.snapshotDigest)
  );
}

export function validateAuditTrace(entry, value) {
  if (typeof value !== "string" || (entry.auditTraceId !== null && value !== entry.auditTraceId)) {
    throw uiControlError(UI_CONTROL_ERROR_CODES.ACK_MISMATCH,
      "backend observation changed or omitted the operation audit identity",
      { retryable: true, details: { operationId: entry.operationId } });
  }
  return assertStableIdentifier(value, "auditTraceId");
}

export function validateAcknowledgement(entry, acknowledgement) {
  assertPlainObject(acknowledgement, "acknowledgement");
  if (acknowledgement.accepted !== true && acknowledgement.accepted !== false) {
    throw invalid("acknowledgement must explicitly declare acceptance");
  }
  if (acknowledgement.accepted === false) {
    const backendCode =
      typeof acknowledgement.errorCode === "string" &&
      SAFE_BACKEND_CODE.test(acknowledgement.errorCode)
        ? acknowledgement.errorCode
        : null;
    throw uiControlError(
      UI_CONTROL_ERROR_CODES.BACKEND_REJECTED,
      "backend rejected the control request",
      {
        details: {
          operationId: entry.operationId,
          backendCode,
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
