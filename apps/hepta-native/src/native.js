const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const ACTIONS = new Set([
  "request_open_path",
  "request_reveal_path",
  "request_copy_text",
  "request_notify",
]);

function snapshotDataRecord(value, name) {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    throw new TypeError(`${name} must be an object`);
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError(`${name} must be a plain object`);
  }

  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(descriptors);
  if (keys.some((key) => typeof key !== "string")) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }

  const snapshot = Object.create(null);
  for (const key of keys) {
    const descriptor = descriptors[key];
    if (!Object.hasOwn(descriptor, "value") || descriptor.enumerable !== true) {
      throw new TypeError(`${name} fields must be enumerable own data properties`);
    }
    snapshot[key] = descriptor.value;
  }
  return Object.freeze(snapshot);
}

function requireExactKeys(value, expected, name) {
  const keys = Reflect.ownKeys(value);
  if (
    keys.length !== expected.length ||
    expected.some((key) => !Object.hasOwn(value, key))
  ) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function requireStableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function requireDigest(value, name) {
  if (
    typeof value !== "string" ||
    !DIGEST.test(value) ||
    value === ZERO_DIGEST
  ) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

export function buildNativeIntent(input) {
  const record = snapshotDataRecord(input, "input");
  requireExactKeys(
    record,
    [
      "operationId",
      "subjectId",
      "action",
      "payloadDigest",
      "leasePayloadDigest",
    ],
    "input",
  );
  const operationId = requireStableId(record.operationId, "operationId");
  const subjectId = requireStableId(record.subjectId, "subjectId");
  if (!ACTIONS.has(record.action)) {
    throw new TypeError("action is not registered");
  }
  const payloadDigest = requireDigest(record.payloadDigest, "payloadDigest");
  const leasePayloadDigest = requireDigest(
    record.leasePayloadDigest,
    "leasePayloadDigest",
  );
  if (payloadDigest !== leasePayloadDigest) {
    throw new TypeError("lease payload does not match the final payload");
  }
  return Object.freeze({
    kind: "NativeOperationIntentV1",
    operationId,
    subjectId,
    action: record.action,
    payloadDigest,
    effectAuthority: false,
    filesystemAuthority: false,
    notificationAuthority: false,
  });
}

export function observeNativeOutcome(input) {
  const record = snapshotDataRecord(input, "input");
  const operationId = requireStableId(record.operationId, "operationId");
  if (record.terminalObserved !== true && record.terminalObserved !== false) {
    throw new TypeError("terminalObserved must be exactly true or false");
  }
  if (record.terminalObserved === false) {
    requireExactKeys(record, ["operationId", "terminalObserved"], "input");
    return Object.freeze({
      operationId,
      status: "indeterminate",
      outcomeDigest: null,
      effectAuthority: false,
    });
  }
  requireExactKeys(
    record,
    ["operationId", "terminalObserved", "terminalStatus", "outcomeDigest"],
    "input",
  );
  if (record.terminalStatus !== "succeeded" && record.terminalStatus !== "failed") {
    throw new TypeError("terminalStatus is not registered");
  }
  requireDigest(record.outcomeDigest, "outcomeDigest");

  // A terminal conclusion must come from a backend-owned receipt bound to the
  // session incarnation, operation, status and outcome, with expiry and
  // revocation enforced. This package has no such verifier.
  throw new TypeError("terminal outcome requires a trusted backend receipt");
}
