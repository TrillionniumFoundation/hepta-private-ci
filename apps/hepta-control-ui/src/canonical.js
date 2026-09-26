import {
  UI_CONTROL_ERROR_CODES,
  uiControlError,
} from "./errors.js";

const encoder = new TextEncoder();
const FORBIDDEN_KEYS = new Set(["__proto__", "constructor", "prototype"]);
const BIDI_OR_INVISIBLE = /[\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]/u;
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f-\u009f]/u;
const STABLE_IDENTIFIER = /^[A-Za-z0-9._:-]+$/u;
const SHA256 = /^[0-9a-f]{64}$/u;

export const DEFAULT_CANONICAL_LIMITS = Object.freeze({
  maxDepth: 16,
  maxEntries: 4096,
  maxArrayLength: 1000,
  maxStringBytes: 64 * 1024,
  maxEncodedBytes: 1024 * 1024,
});

function invalid(message, details) {
  return uiControlError(UI_CONTROL_ERROR_CODES.INVALID_INPUT, message, {
    details,
  });
}

export function assertSafeInteger(value, label, { min = 0, max = Number.MAX_SAFE_INTEGER } = {}) {
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw invalid(`${label} must be a safe integer in [${min}, ${max}]`, {
      label,
      value,
    });
  }
  return value;
}

export function assertStableIdentifier(value, label, { maxBytes = 128 } = {}) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    !STABLE_IDENTIFIER.test(value) ||
    encoder.encode(value).byteLength > maxBytes ||
    CONTROL_CHARACTER.test(value) ||
    BIDI_OR_INVISIBLE.test(value) ||
    value.normalize("NFC") !== value
  ) {
    throw invalid(`${label} must be a canonical stable identifier`, { label });
  }
  return value;
}

export function assertSha256(value, label, { allowZero = false } = {}) {
  if (
    typeof value !== "string" ||
    !SHA256.test(value) ||
    (!allowZero && value === "0".repeat(64))
  ) {
    throw invalid(`${label} must be a non-zero lowercase SHA-256 digest`, {
      label,
    });
  }
  return value;
}

export function assertCanonicalText(value, label, { maxBytes = 4096, allowEmpty = false } = {}) {
  if (
    typeof value !== "string" ||
    (!allowEmpty && value.length === 0) ||
    encoder.encode(value).byteLength > maxBytes ||
    CONTROL_CHARACTER.test(value) ||
    BIDI_OR_INVISIBLE.test(value) ||
    value.normalize("NFC") !== value
  ) {
    throw invalid(`${label} must be bounded NFC text without control or bidi characters`, {
      label,
    });
  }
  return value;
}

function readPlainObject(value, label) {
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw invalid(`${label} must be a plain object`, { label });
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
  return descriptors;
}

function normalize(value, state, depth, label) {
  if (depth > state.limits.maxDepth) {
    throw invalid(`${label} exceeds maximum nesting depth`, { label });
  }

  if (value === null || typeof value === "boolean") return value;

  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      throw invalid(`${label} contains a non-safe integer`, { label, value });
    }
    return value;
  }

  if (typeof value === "string") {
    assertCanonicalText(value, label, {
      maxBytes: state.limits.maxStringBytes,
      allowEmpty: true,
    });
    return value;
  }

  if (Array.isArray(value)) {
    if (value.length > state.limits.maxArrayLength) {
      throw invalid(`${label} exceeds maximum array length`, { label });
    }
    state.entries += value.length;
    if (state.entries > state.limits.maxEntries) {
      throw invalid(`${label} exceeds maximum entry count`, { label });
    }
    return value.map((entry, index) =>
      normalize(entry, state, depth + 1, `${label}[${index}]`),
    );
  }

  if (typeof value === "object") {
    const descriptors = readPlainObject(value, label);
    const keys = Object.keys(descriptors).sort();
    state.entries += keys.length;
    if (state.entries > state.limits.maxEntries) {
      throw invalid(`${label} exceeds maximum entry count`, { label });
    }
    const output = Object.create(null);
    for (const key of keys) {
      assertCanonicalText(key, `${label} key`, { maxBytes: 256 });
      output[key] = normalize(
        descriptors[key].value,
        state,
        depth + 1,
        `${label}.${key}`,
      );
    }
    return output;
  }

  throw invalid(`${label} contains an unsupported value`, {
    label,
    type: typeof value,
  });
}

export function canonicalJson(value, limits = {}) {
  const resolvedLimits = Object.freeze({
    ...DEFAULT_CANONICAL_LIMITS,
    ...limits,
  });
  const normalized = normalize(
    value,
    { limits: resolvedLimits, entries: 0 },
    0,
    "value",
  );
  const encoded = JSON.stringify(normalized);
  if (encoder.encode(encoded).byteLength > resolvedLimits.maxEncodedBytes) {
    throw invalid("canonical JSON exceeds maximum encoded size", {
      maxEncodedBytes: resolvedLimits.maxEncodedBytes,
    });
  }
  return encoded;
}

export function parseCanonicalJson(text, { label = "document", ...limits } = {}) {
  if (typeof text !== "string") {
    throw invalid(`${label} must be JSON text`, { label });
  }
  const bytes = encoder.encode(text).byteLength;
  const maxEncodedBytes = limits.maxEncodedBytes ?? DEFAULT_CANONICAL_LIMITS.maxEncodedBytes;
  if (bytes > maxEncodedBytes) {
    throw invalid(`${label} exceeds maximum encoded size`, {
      label,
      maxEncodedBytes,
    });
  }
  let value;
  try {
    value = JSON.parse(text);
  } catch (cause) {
    throw uiControlError(UI_CONTROL_ERROR_CODES.INVALID_INPUT, `${label} is not valid JSON`, {
      details: { label },
      cause,
    });
  }
  const canonical = canonicalJson(value, { ...limits, maxEncodedBytes });
  if (canonical !== text) {
    throw invalid(`${label} must use exact canonical JSON encoding`, { label });
  }
  return value;
}

function bytesToHex(bytes) {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
}

export async function digestCanonical(domain, value, limits) {
  assertStableIdentifier(domain, "digest domain", { maxBytes: 128 });
  const payload = `${domain}\u0000${canonicalJson(value, limits)}`;
  const digest = await globalThis.crypto.subtle.digest("SHA-256", encoder.encode(payload));
  return bytesToHex(new Uint8Array(digest));
}

export function constantTimeEqual(left, right) {
  if (typeof left !== "string" || typeof right !== "string" || left.length !== right.length) {
    return false;
  }
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}
