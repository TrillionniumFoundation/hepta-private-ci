const UTF8 = new TextEncoder();

export const DEFAULT_MAX_CANONICAL_BYTES = 16 * 1024;
const MAX_DEPTH = 16;
const MAX_ARRAY_ITEMS = 4096;
const MAX_OBJECT_KEYS = 256;

function fail(name, detail) {
  throw new TypeError(`${name} ${detail}`);
}

function plainDataRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(name, "must be an object");
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    fail(name, "must be a plain object");
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(descriptors);
  if (keys.some((key) => typeof key !== "string")) {
    fail(name, "must contain only string-keyed fields");
  }
  if (keys.length > MAX_OBJECT_KEYS) {
    fail(name, "contains too many fields");
  }
  for (const key of keys) {
    const descriptor = descriptors[key];
    if (!Object.hasOwn(descriptor, "value") || descriptor.enumerable !== true) {
      fail(`${name}.${key}`, "must be an enumerable own data property");
    }
  }
  return descriptors;
}

function snapshot(value, name, depth) {
  if (depth > MAX_DEPTH) {
    fail(name, "exceeds maximum nesting depth");
  }
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      fail(name, "must use safe integers only");
    }
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length > MAX_ARRAY_ITEMS) {
      fail(name, "contains too many array items");
    }
    const result = value.map((item, index) =>
      snapshot(item, `${name}[${index}]`, depth + 1),
    );
    return Object.freeze(result);
  }
  if (typeof value !== "object") {
    fail(name, "must contain only canonical JSON values");
  }

  const descriptors = plainDataRecord(value, name);
  const result = Object.create(null);
  for (const key of Object.keys(descriptors).sort()) {
    result[key] = snapshot(descriptors[key].value, `${name}.${key}`, depth + 1);
  }
  return Object.freeze(result);
}

export function snapshotCanonicalJson(value, name = "value") {
  return snapshot(value, name, 0);
}

export function canonicalJson(
  value,
  { name = "value", maxBytes = DEFAULT_MAX_CANONICAL_BYTES } = {},
) {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) {
    throw new TypeError("maxBytes must be a positive safe integer");
  }
  const frozen = snapshotCanonicalJson(value, name);
  const encoded = JSON.stringify(frozen);
  if (UTF8.encode(encoded).byteLength > maxBytes) {
    fail(name, "exceeds the canonical JSON byte limit");
  }
  return encoded;
}

export async function canonicalSha256(value, options = {}) {
  const encoded = canonicalJson(value, options);
  const subtle = globalThis.crypto?.subtle;
  if (!subtle || typeof subtle.digest !== "function") {
    throw new TypeError("Web Crypto SHA-256 is unavailable");
  }
  const bytes = await subtle.digest("SHA-256", UTF8.encode(encoded));
  return [...new Uint8Array(bytes)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
