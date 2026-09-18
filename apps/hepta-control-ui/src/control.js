import {
  ERROR_CODES,
  fail,
  positiveInteger,
  readOwnDataFields,
  requireDigest,
  requireRecord,
  stableId,
  utf8Bytes,
} from "./protocol.js";

const RUNTIME_STATUSES = new Set([
  "ready",
  "degraded",
  "quarantined",
  "recovering",
  "unavailable",
]);

const OPERATION_ACTIONS = new Set([
  "request_quarantine",
  "request_reconcile",
  "request_retry",
  "request_rollback",
]);

const MAX_CANONICAL_INPUT_BYTES = 4096;
const LOCAL_RUNTIME_OBSERVATION_SCHEMA =
  "hepta.ui-control.local-runtime-observation.v1";
const LOCAL_RUNTIME_PROJECTION_SCHEMA =
  "hepta.ui-control.local-runtime-projection.v1";
const LOCAL_OPERATION_PROPOSAL_INPUT_SCHEMA =
  "hepta.ui-control.local-operation-proposal-input.v1";
const LOCAL_OPERATION_PROPOSAL_SCHEMA =
  "hepta.ui-control.local-operation-proposal.v1";

function parseCanonicalInput(encoded, expectedKeys, name) {
  if (
    typeof encoded !== "string" ||
    encoded.length === 0 ||
    encoded.length > MAX_CANONICAL_INPUT_BYTES
  ) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be bounded canonical JSON`);
  }
  if (utf8Bytes(encoded) > MAX_CANONICAL_INPUT_BYTES) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} exceeds the canonical JSON byte limit`);
  }
  let value;
  try {
    value = JSON.parse(encoded);
  } catch {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be valid canonical JSON`);
  }
  requireRecord(value, name);
  const canonicalKeys = [...expectedKeys].sort();
  const keys = Object.keys(value);
  if (
    keys.length !== canonicalKeys.length ||
    keys.some((key, index) => key !== canonicalKeys[index])
  ) {
    fail(
      ERROR_CODES.INVALID_INPUT,
      `${name} contains missing, unknown, or unordered fields`,
    );
  }
  const snapshot = Object.fromEntries(
    canonicalKeys.map((key) => [key, value[key]]),
  );
  if (JSON.stringify(snapshot) !== encoded) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} is not in canonical JSON form`);
  }
  return Object.freeze(snapshot);
}

export function projectRuntime(observation) {
  const fields = readOwnDataFields(
    observation,
    "observation",
    ["moduleId", "status", "revision", "digest"],
  );
  const moduleId = stableId(fields.moduleId, "moduleId");
  if (!RUNTIME_STATUSES.has(fields.status)) {
    fail(ERROR_CODES.INVALID_INPUT, "status is not a registered runtime state");
  }
  const revision = positiveInteger(fields.revision, "revision");
  const digest = requireDigest(fields.digest, "digest");

  return Object.freeze({
    moduleId,
    status: fields.status,
    revision,
    digest,
    ready: fields.status === "ready",
    authorityGranted: false,
    directStoreWrite: false,
  });
}

export function buildOperationProposal(input) {
  const fields = readOwnDataFields(
    input,
    "input",
    ["operationId", "subjectId", "action", "expectedRevision"],
  );
  const operationId = stableId(fields.operationId, "operationId");
  const subjectId = stableId(fields.subjectId, "subjectId");
  if (!OPERATION_ACTIONS.has(fields.action)) {
    fail(ERROR_CODES.INVALID_INPUT, "action is not a registered operator request");
  }
  const expectedRevision = positiveInteger(fields.expectedRevision, "expectedRevision");

  return Object.freeze({
    kind: "UiOperationProposalV1",
    operationId,
    subjectId,
    action: fields.action,
    expectedRevision,
    authorityGranted: false,
    directStoreWrite: false,
  });
}

/**
 * Compatibility alias. ui.control does not own or mint kernel.operations' OperationIntentV1.
 * @deprecated Use buildOperationProposal.
 */
export function buildOperationIntent(input) {
  return buildOperationProposal(input);
}

/**
 * Parse a bounded, package-local JSON fixture before shadow projection.
 * This is not a module ingress or a registered cross-module contract.
 *
 * @internal
 */
export function projectRuntimeFromLocalCanonicalJson(encoded) {
  const observation = parseCanonicalInput(
    encoded,
    ["schema", "moduleId", "status", "revision", "digest"],
    "local runtime observation",
  );
  if (observation.schema !== LOCAL_RUNTIME_OBSERVATION_SCHEMA) {
    fail(ERROR_CODES.INVALID_INPUT, "local runtime observation schema is unsupported");
  }
  return Object.freeze({
    localSchema: LOCAL_RUNTIME_PROJECTION_SCHEMA,
    ...projectRuntime(observation),
  });
}

/**
 * Build an authority-free, package-local shadow proposal from bounded JSON.
 * The result is not `OperationIntentV1` and must not cross a module boundary.
 *
 * @internal
 */
export function buildLocalOperationProposalFromCanonicalJson(encoded) {
  const input = parseCanonicalInput(
    encoded,
    ["schema", "operationId", "subjectId", "action", "expectedRevision"],
    "local operation proposal",
  );
  if (input.schema !== LOCAL_OPERATION_PROPOSAL_INPUT_SCHEMA) {
    fail(ERROR_CODES.INVALID_INPUT, "local operation proposal schema is unsupported");
  }
  const proposal = buildOperationProposal(input);
  return Object.freeze({
    localSchema: LOCAL_OPERATION_PROPOSAL_SCHEMA,
    operationId: proposal.operationId,
    subjectId: proposal.subjectId,
    action: proposal.action,
    expectedRevision: proposal.expectedRevision,
    authorityGranted: false,
    directStoreWrite: false,
  });
}
