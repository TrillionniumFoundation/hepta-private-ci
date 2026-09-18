const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const UTF8 = new TextEncoder();

export const MAX_VIEW_BYTES = 1024 * 1024;
export const MAX_REQUEST_BYTES = 64 * 1024;
export const MAX_CANONICAL_DEPTH = 32;
export const MAX_CANONICAL_NODES = 4096;

export const ERROR_CODES = Object.freeze({
  INVALID_INPUT: "INVALID_INPUT",
  NOT_CONNECTED: "NOT_CONNECTED",
  UNAUTHENTICATED: "UNAUTHENTICATED",
  INCOMPATIBLE_PROTOCOL: "INCOMPATIBLE_PROTOCOL",
  STALE_SNAPSHOT: "STALE_SNAPSHOT",
  REQUEST_REJECTED: "REQUEST_REJECTED",
  BACKEND_UNAVAILABLE: "BACKEND_UNAVAILABLE",
  PROTOCOL_VIOLATION: "PROTOCOL_VIOLATION",
  RECONCILIATION_MISMATCH: "RECONCILIATION_MISMATCH",
  CAPACITY_EXHAUSTED: "CAPACITY_EXHAUSTED",
  VIEW_TOO_LARGE: "VIEW_TOO_LARGE",
  PERSISTENCE_UNAVAILABLE: "PERSISTENCE_UNAVAILABLE",
  TRANSPORT_SECURITY_VIOLATION: "TRANSPORT_SECURITY_VIOLATION",
});

export class UiControlError extends TypeError {
  constructor(code, message, details = undefined) {
    super(message);
    this.name = "UiControlError";
    this.code = code;
    if (details !== undefined) {
      this.details = snapshotCanonical(details, "error details", {
        maxBytes: 8192,
        allowEmptyObject: true,
      });
    }
    Object.freeze(this);
  }
}

export function fail(code, message, details) {
  throw new UiControlError(code, message, details);
}

export function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be an object`);
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be a plain object`);
  }
  return value;
}

export function readOwnDataFields(value, name, fields) {
  requireRecord(value, name);
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const result = Object.create(null);
  for (const field of fields) {
    const descriptor = descriptors[field];
    if (
      !descriptor ||
      !Object.hasOwn(descriptor, "value") ||
      descriptor.enumerable !== true ||
      descriptor.get !== undefined ||
      descriptor.set !== undefined
    ) {
      fail(ERROR_CODES.INVALID_INPUT, `${name}.${field} must be an enumerable own data field`);
    }
    result[field] = descriptor.value;
  }
  return Object.freeze(result);
}

export function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be a bounded stable identifier`);
  }
  return value;
}

export function requireDigest(value, name, { allowZero = false } = {}) {
  if (
    typeof value !== "string" ||
    !DIGEST.test(value) ||
    (!allowZero && value === ZERO_DIGEST)
  ) {
    fail(
      ERROR_CODES.INVALID_INPUT,
      `${name} must be a ${allowZero ? "" : "non-zero "}lowercase SHA-256 digest`,
    );
  }
  return value;
}

export function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be a positive safe integer`);
  }
  return value;
}

export function nonNegativeInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must be a non-negative safe integer`);
  }
  return value;
}

export function utf8Bytes(value) {
  return UTF8.encode(value).byteLength;
}

function snapshotValue(value, name, state, depth) {
  state.nodes += 1;
  if (state.nodes > state.maxNodes) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} exceeds the canonical node limit`);
  }
  if (depth > state.maxDepth) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} exceeds the canonical depth limit`);
  }

  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      fail(ERROR_CODES.INVALID_INPUT, `${name} numbers must be safe integers`);
    }
    return value;
  }
  if (Array.isArray(value)) {
    if (state.seen.has(value)) {
      fail(ERROR_CODES.INVALID_INPUT, `${name} must not contain cycles`);
    }
    state.seen.add(value);
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const expectedKeys = new Set([...Array(value.length).keys()].map(String).concat("length"));
    for (const key of Reflect.ownKeys(descriptors)) {
      if (typeof key !== "string" || !expectedKeys.has(key)) {
        fail(ERROR_CODES.INVALID_INPUT, `${name} arrays must contain only indexed data`);
      }
    }
    const result = [];
    for (let index = 0; index < value.length; index += 1) {
      const descriptor = descriptors[String(index)];
      if (!descriptor || !Object.hasOwn(descriptor, "value") || descriptor.enumerable !== true) {
        fail(ERROR_CODES.INVALID_INPUT, `${name} arrays must be dense enumerable data`);
      }
      result.push(snapshotValue(descriptor.value, `${name}[${index}]`, state, depth + 1));
    }
    state.seen.delete(value);
    return Object.freeze(result);
  }
  if (typeof value !== "object") {
    fail(ERROR_CODES.INVALID_INPUT, `${name} contains a non-canonical value`);
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must contain only plain objects`);
  }
  if (state.seen.has(value)) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must not contain cycles`);
  }
  state.seen.add(value);
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(descriptors);
  if (keys.some((key) => typeof key !== "string")) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} contains unsupported symbol fields`);
  }
  const stringKeys = keys.sort();
  if (!state.allowEmptyObject && depth === 0 && stringKeys.length === 0) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} must not be empty`);
  }
  const entries = [];
  for (const key of stringKeys) {
    const descriptor = descriptors[key];
    if (
      !Object.hasOwn(descriptor, "value") ||
      descriptor.enumerable !== true ||
      descriptor.get !== undefined ||
      descriptor.set !== undefined
    ) {
      fail(ERROR_CODES.INVALID_INPUT, `${name}.${key} must be an enumerable data field`);
    }
    entries.push([
      key,
      snapshotValue(descriptor.value, `${name}.${key}`, state, depth + 1),
    ]);
  }
  state.seen.delete(value);
  return Object.freeze(Object.fromEntries(entries));
}

export function snapshotCanonical(
  value,
  name = "value",
  {
    maxBytes = MAX_REQUEST_BYTES,
    maxDepth = MAX_CANONICAL_DEPTH,
    maxNodes = MAX_CANONICAL_NODES,
    allowEmptyObject = false,
  } = {},
) {
  const snapshot = snapshotValue(
    value,
    name,
    {
      seen: new Set(),
      nodes: 0,
      maxDepth,
      maxNodes,
      allowEmptyObject,
    },
    0,
  );
  const encoded = JSON.stringify(snapshot);
  if (utf8Bytes(encoded) > maxBytes) {
    fail(ERROR_CODES.INVALID_INPUT, `${name} exceeds the canonical byte limit`);
  }
  return snapshot;
}

export function canonicalJson(value, name = "value", options = undefined) {
  return JSON.stringify(snapshotCanonical(value, name, options));
}

export async function canonicalSha256(value, name = "request semantics") {
  const encoded = canonicalJson(value, name, { maxBytes: MAX_REQUEST_BYTES });
  const crypto = globalThis.crypto;
  if (!crypto?.subtle || typeof crypto.subtle.digest !== "function") {
    fail(ERROR_CODES.PROTOCOL_VIOLATION, "Web Crypto SHA-256 is unavailable");
  }
  const bytes = UTF8.encode(encoded);
  const digestBuffer = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digestBuffer)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function freezeResult(value) {
  return Object.freeze({
    ...value,
    authorityGranted: false,
    directStoreWrite: false,
    terminalAuthority: false,
  });
}
