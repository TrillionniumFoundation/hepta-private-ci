/*
 * Typed value bridge for the UI -> Agentd module-port boundary.
 *
 * This module deliberately does not import the Agentd client or expose its
 * owner-only Unix socket. A trusted Agentd adapter is injected as `modulePort`;
 * the UI receives only bounded runtime projections and proposal receipts. A
 * proposal is not an OperationIntentV1, a final-use grant, or an HOS2 D.
 */

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_PAYLOAD_KEYS = 16;
const MAX_PAYLOAD_VALUE_BYTES = 512;
const MAX_MESSAGE_BYTES = 512;

const LIFECYCLES = new Set([
  "registered",
  "ready",
  "quarantined",
  "recovering",
  "stopped",
  "unavailable",
]);
const ACTIONS = new Set([
  "request_quarantine",
  "request_reconcile",
  "request_retry",
  "request_rollback",
]);
const STATUSES = new Set([
  "accepted",
  "idempotent_replay",
  "conflict",
  "rejected",
  "unknown",
]);
const FORBIDDEN_FIELDS = new Set([
  "requestAddr",
  "responseAddr",
  "controlFd",
  "deviceFd",
  "capSpaceId",
  "bootId",
  "sequence",
  "finalUse",
  "signature",
  "signedGrant",
  "secret",
  "socketPath",
]);

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function requireStableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function requirePositive(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function requireDigest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
    throw new TypeError(`${name} must be a non-zero lowercase hexadecimal digest`);
  }
  return value;
}

function requireScalarPayload(payload) {
  requireRecord(payload, "proposal.payload");
  const keys = Object.keys(payload);
  if (keys.length > MAX_PAYLOAD_KEYS) {
    throw new TypeError("proposal.payload has too many fields");
  }
  const snapshot = {};
  for (const key of keys) {
    if (!STABLE_ID.test(key) || FORBIDDEN_FIELDS.has(key)) {
      throw new TypeError("proposal.payload contains a forbidden field");
    }
    const value = payload[key];
    if (
      value !== null &&
      typeof value !== "string" &&
      typeof value !== "boolean" &&
      (typeof value !== "number" || !Number.isFinite(value))
    ) {
      throw new TypeError("proposal.payload values must be scalar");
    }
    if (typeof value === "string" && new TextEncoder().encode(value).byteLength > MAX_PAYLOAD_VALUE_BYTES) {
      throw new TypeError("proposal.payload string value is too large");
    }
    snapshot[key] = value;
  }
  return Object.freeze(snapshot);
}

function rejectForbiddenFields(value, name) {
  for (const key of Object.keys(value)) {
    if (FORBIDDEN_FIELDS.has(key)) {
      throw new TypeError(`${name} contains a forbidden field`);
    }
  }
}

function normalizeQuery(query) {
  requireRecord(query, "runtime query");
  return Object.freeze({
    moduleId: requireStableId(query.moduleId, "moduleId"),
    expectedGeneration: requirePositive(query.expectedGeneration, "expectedGeneration"),
  });
}

function normalizeSnapshot(snapshot, query) {
  requireRecord(snapshot, "runtime snapshot");
  rejectForbiddenFields(snapshot, "runtime snapshot");
  const moduleId = requireStableId(snapshot.moduleId, "snapshot.moduleId");
  if (moduleId !== query.moduleId) {
    throw new TypeError("module port returned a different module identity");
  }
  const generation = requirePositive(snapshot.generation, "snapshot.generation");
  if (generation < query.expectedGeneration) {
    throw new TypeError("module port returned a stale generation");
  }
  if (!LIFECYCLES.has(snapshot.lifecycle)) {
    throw new TypeError("snapshot.lifecycle is not registered");
  }
  const revision = requirePositive(snapshot.revision, "snapshot.revision");
  const stateDigest = requireDigest(snapshot.stateDigest, "snapshot.stateDigest");
  if (typeof snapshot.ready !== "boolean") {
    throw new TypeError("snapshot.ready must be boolean");
  }
  if (
    ("authorityGranted" in snapshot && snapshot.authorityGranted !== false) ||
    ("directStoreWrite" in snapshot && snapshot.directStoreWrite !== false)
  ) {
    throw new TypeError("UI snapshot cannot advertise authority or direct store access");
  }
  return Object.freeze({
    moduleId,
    generation,
    lifecycle: snapshot.lifecycle,
    revision,
    stateDigest,
    ready: snapshot.ready,
    authorityGranted: false,
    directStoreWrite: false,
  });
}

function normalizeProposal(proposal) {
  requireRecord(proposal, "proposal");
  rejectForbiddenFields(proposal, "proposal");
  if (!ACTIONS.has(proposal.action)) {
    throw new TypeError("proposal.action is not registered");
  }
  return Object.freeze({
    scopeId: requireStableId(proposal.scopeId, "scopeId"),
    operationId: requireStableId(proposal.operationId, "operationId"),
    subjectId: requireStableId(proposal.subjectId, "subjectId"),
    payloadDigest: requireDigest(proposal.payloadDigest, "payloadDigest"),
    action: proposal.action,
    expectedResourceRevision: requirePositive(
      proposal.expectedResourceRevision,
      "expectedResourceRevision",
    ),
    expectedBodyGeneration: requirePositive(
      proposal.expectedBodyGeneration,
      "expectedBodyGeneration",
    ),
    expectedAuthorityEpoch: requirePositive(
      proposal.expectedAuthorityEpoch,
      "expectedAuthorityEpoch",
    ),
    clientRequestId: requireStableId(proposal.clientRequestId, "clientRequestId"),
    payload: requireScalarPayload(proposal.payload),
  });
}

function normalizeReceipt(receipt, proposal) {
  requireRecord(receipt, "proposal receipt");
  rejectForbiddenFields(receipt, "proposal receipt");
  if (
    receipt.scopeId !== proposal.scopeId ||
    receipt.operationId !== proposal.operationId
  ) {
    throw new TypeError("proposal receipt changed durable K");
  }
  if (receipt.payloadDigest !== proposal.payloadDigest) {
    throw new TypeError("proposal receipt changed semantic digest");
  }
  if (!STATUSES.has(receipt.status)) {
    throw new TypeError("proposal receipt status is not registered");
  }
  const observedResourceRevision = requirePositive(
    receipt.observedResourceRevision,
    "receipt.observedResourceRevision",
  );
  if (observedResourceRevision < proposal.expectedResourceRevision) {
    throw new TypeError("proposal receipt regressed resource revision");
  }
  const observedBodyGeneration = requirePositive(
    receipt.observedBodyGeneration,
    "receipt.observedBodyGeneration",
  );
  if (observedBodyGeneration < proposal.expectedBodyGeneration) {
    throw new TypeError("proposal receipt regressed body generation");
  }
  const observedAuthorityEpoch = requirePositive(
    receipt.observedAuthorityEpoch,
    "receipt.observedAuthorityEpoch",
  );
  if (observedAuthorityEpoch < proposal.expectedAuthorityEpoch) {
    throw new TypeError("proposal receipt regressed authority epoch");
  }
  const message = receipt.message ?? "";
  if (typeof message !== "string" || new TextEncoder().encode(message).byteLength > MAX_MESSAGE_BYTES) {
    throw new TypeError("receipt.message is too large");
  }
  return Object.freeze({
    scopeId: proposal.scopeId,
    operationId: proposal.operationId,
    payloadDigest: proposal.payloadDigest,
    status: receipt.status,
    observedResourceRevision,
    observedBodyGeneration,
    observedAuthorityEpoch,
    message,
    exposesDeliveryIdentity: false,
  });
}

/**
 * Create a UI-only adapter around an Agentd-owned module port.
 *
 * `modulePort` is intentionally structural: it has only readRuntime and
 * submitProposal methods. The returned closure does not expose the port,
 * socket path, credentials, capabilities, or HOS2 delivery identity.
 */
export function createAuthorityFreeAgentdBridge(modulePort) {
  requireRecord(modulePort, "modulePort");
  if (
    typeof modulePort.readRuntime !== "function" ||
    typeof modulePort.submitProposal !== "function"
  ) {
    throw new TypeError("modulePort must implement readRuntime and submitProposal");
  }
  return Object.freeze({
    readRuntime(query) {
      const normalizedQuery = normalizeQuery(query);
      return normalizeSnapshot(modulePort.readRuntime(normalizedQuery), normalizedQuery);
    },
    submitProposal(value) {
      const proposal = normalizeProposal(value);
      return normalizeReceipt(modulePort.submitProposal(proposal), proposal);
    },
  });
}

