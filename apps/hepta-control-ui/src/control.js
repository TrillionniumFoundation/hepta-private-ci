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

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_CANONICAL_INPUT_BYTES = 4096;
const UTF8 = new TextEncoder();
const LOCAL_RUNTIME_OBSERVATION_SCHEMA =
  "hepta.ui-control.local-runtime-observation.v1";
const LOCAL_RUNTIME_PROJECTION_SCHEMA =
  "hepta.ui-control.local-runtime-projection.v1";
const LOCAL_OPERATION_PROPOSAL_INPUT_SCHEMA =
  "hepta.ui-control.local-operation-proposal-input.v1";
const LOCAL_OPERATION_PROPOSAL_SCHEMA =
  "hepta.ui-control.local-operation-proposal.v1";

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function ownData(value, key, name) {
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  if (
    !descriptor ||
    !Object.hasOwn(descriptor, "value") ||
    descriptor.enumerable !== true
  ) {
    throw new TypeError(
      `${name}.${key} must be an enumerable own data property`,
    );
  }
  return descriptor.value;
}

function exactDataRecord(value, expectedKeys, name) {
  requireRecord(value, name);
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError(`${name} must be a plain object`);
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(descriptors);
  if (
    keys.length !== expectedKeys.length ||
    keys.some((key) => typeof key !== "string") ||
    expectedKeys.some((key) => !Object.hasOwn(descriptors, key))
  ) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
  const result = Object.create(null);
  for (const key of expectedKeys) {
    const descriptor = descriptors[key];
    if (!Object.hasOwn(descriptor, "value") || descriptor.enumerable !== true) {
      throw new TypeError(
        `${name}.${key} must be an enumerable own data property`,
      );
    }
    result[key] = descriptor.value;
  }
  return Object.freeze(result);
}

function requireStableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function requireRevision(value, name = "revision") {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function requireDigest(value, name = "digest") {
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new TypeError(
      `${name} must contain 64 lowercase hexadecimal characters`,
    );
  }
  return value;
}

function requireNonzeroDigest(value, name = "digest") {
  const checked = requireDigest(value, name);
  if (checked === ZERO_DIGEST) {
    throw new TypeError(`${name} must be non-zero`);
  }
  return checked;
}

function parseCanonicalInput(encoded, expectedKeys, name) {
  if (
    typeof encoded !== "string" ||
    encoded.length === 0 ||
    encoded.length > MAX_CANONICAL_INPUT_BYTES
  ) {
    throw new TypeError(`${name} must be bounded canonical JSON`);
  }
  const byteLength = UTF8.encode(encoded).byteLength;
  if (byteLength > MAX_CANONICAL_INPUT_BYTES) {
    throw new TypeError(`${name} exceeds the canonical JSON byte limit`);
  }
  let value;
  try {
    value = JSON.parse(encoded);
  } catch {
    throw new TypeError(`${name} must be valid canonical JSON`);
  }
  requireRecord(value, name);
  const canonicalKeys = [...expectedKeys].sort();
  const keys = Object.keys(value);
  if (
    keys.length !== canonicalKeys.length ||
    keys.some((key, index) => key !== canonicalKeys[index])
  ) {
    throw new TypeError(
      `${name} contains missing, unknown, or unordered fields`,
    );
  }
  const snapshot = Object.fromEntries(
    canonicalKeys.map((key) => [key, value[key]]),
  );
  if (JSON.stringify(snapshot) !== encoded) {
    throw new TypeError(`${name} is not in canonical JSON form`);
  }
  return Object.freeze(snapshot);
}

/**
 * Project an untrusted runtime observation into the only fields that are
 * allowed to cross the presentation boundary. Unknown source fields are
 * deliberately never read, so provider payloads and secrets are dropped.
 */
export function projectRuntime(observation) {
  requireRecord(observation, "observation");
  const moduleId = requireStableId(
    ownData(observation, "moduleId", "observation"),
    "moduleId",
  );
  const status = ownData(observation, "status", "observation");
  if (!RUNTIME_STATUSES.has(status)) {
    throw new TypeError("status is not a registered runtime state");
  }
  const revision = requireRevision(
    ownData(observation, "revision", "observation"),
  );
  const digest = requireNonzeroDigest(
    ownData(observation, "digest", "observation"),
  );

  return Object.freeze({
    moduleId,
    status,
    revision,
    digest,
    ready: status === "ready",
    authorityGranted: false,
    directStoreWrite: false,
  });
}

/**
 * Build an authority-free UI proposal. `OperationIntentV1` is owned by
 * `kernel.operations`; this package must never mint that canonical contract.
 */
export function buildOperationProposal(input) {
  const record = exactDataRecord(
    input,
    ["operationId", "subjectId", "action", "expectedRevision"],
    "input",
  );
  const operationId = requireStableId(record.operationId, "operationId");
  const subjectId = requireStableId(record.subjectId, "subjectId");
  if (!OPERATION_ACTIONS.has(record.action)) {
    throw new TypeError("action is not a registered operator request");
  }
  const expectedRevision = requireRevision(
    record.expectedRevision,
    "expectedRevision",
  );

  return Object.freeze({
    kind: "UiControlOperationProposalV1",
    operationId,
    subjectId,
    action: record.action,
    expectedRevision,
    authorityGranted: false,
    directStoreWrite: false,
  });
}

/**
 * @deprecated Use `buildOperationProposal`. Kept as a compatibility export;
 * it intentionally does not produce `OperationIntentV1`.
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
    throw new TypeError("local runtime observation schema is unsupported");
  }
  requireNonzeroDigest(observation.digest);
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
    throw new TypeError("local operation proposal schema is unsupported");
  }
  const proposal = buildOperationProposal({
    operationId: input.operationId,
    subjectId: input.subjectId,
    action: input.action,
    expectedRevision: input.expectedRevision,
  });
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
