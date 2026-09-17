import { createHash } from "node:crypto";

export const MAX_ORIGINS = 128;
export const MAX_EFFECT_GRANTS = 1024;
export const MAX_ACTIVE_OPERATIONS = 1024;
export const MAX_OPERATION_RECORDS = 4096;
export const MAX_RETIRED_OPERATIONS = 32768;
export const DEFAULT_DRIVER_TIMEOUT_MS = 30_000;

const STABLE_ID = /^[A-Za-z0-9._:/-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const MAX_TYPED_ACTION_BYTES = 64 * 1024;
const MAX_SELECTOR_BYTES = 4096;
const MAX_TEXT_BYTES = 64 * 1024;
const MAX_URL_BYTES = 4096;
const MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024;
const UTF8 = new TextEncoder();

export function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function requireExactKeys(value, required, name) {
  const keys = Object.keys(requireRecord(value, name));
  const allowed = new Set(required);
  for (const key of keys) {
    if (!allowed.has(key)) throw new TypeError(`${name} contains unknown field ${key}`);
  }
  for (const key of required) {
    if (!Object.hasOwn(value, key)) throw new TypeError(`${name} is missing ${key}`);
  }
}

export function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

export function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

export function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

function signedInteger(value, name) {
  if (!Number.isSafeInteger(value)) throw new TypeError(`${name} must be a safe integer`);
  return value;
}

export function deadline(value, now, name = "deadlineMs") {
  const deadlineMs = positiveInteger(value, name);
  if (deadlineMs <= now) throw new TypeError(`${name} has expired`);
  return deadlineMs;
}

function boundedString(value, name, maximumBytes, { allowEmpty = false } = {}) {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    throw new TypeError(`${name} must be a bounded string`);
  }
  if (UTF8.encode(value).byteLength > maximumBytes) {
    throw new TypeError(`${name} exceeds its byte limit`);
  }
  return value;
}

export function canonicalOrigin(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new TypeError("origin must use HTTP or HTTPS");
  }
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new TypeError("origin must not contain credentials, path, query, or fragment");
  }
  return url.origin;
}

function canonicalWebUrl(value, name) {
  boundedString(value, name, MAX_URL_BYTES);
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new TypeError(`${name} must be an absolute URL`);
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new TypeError(`${name} must use HTTP or HTTPS`);
  }
  if (url.username || url.password) throw new TypeError(`${name} cannot contain credentials`);
  const normalized = url.toString();
  if (UTF8.encode(normalized).byteLength > MAX_URL_BYTES) {
    throw new TypeError(`${name} exceeds its normalized byte limit`);
  }
  return normalized;
}

function canonicalize(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new TypeError("canonical value contains a non-safe number");
    return value;
  }
  if (Array.isArray(value)) return value.map(canonicalize);
  if (typeof value === "object") {
    const output = {};
    for (const key of Object.keys(value).sort()) {
      if (value[key] === undefined) throw new TypeError("canonical value contains undefined");
      output[key] = canonicalize(value[key]);
    }
    return output;
  }
  throw new TypeError("canonical value has unsupported type");
}

export function canonicalDigest(value) {
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

export function normalizeTypedAction(value) {
  const action = requireRecord(value, "typedAction");
  const kind = stableId(action.kind, "typedAction.kind");
  let normalized;
  switch (kind) {
    case "navigate":
      requireExactKeys(action, ["kind", "url"], "typedAction");
      normalized = { kind, url: canonicalWebUrl(action.url, "typedAction.url") };
      break;
    case "click": {
      requireExactKeys(action, ["kind", "selector", "button"], "typedAction");
      if (!["primary", "middle", "secondary"].includes(action.button)) {
        throw new TypeError("typedAction.button is not registered");
      }
      normalized = {
        kind,
        selector: boundedString(action.selector, "typedAction.selector", MAX_SELECTOR_BYTES),
        button: action.button,
      };
      break;
    }
    case "type":
      requireExactKeys(action, ["kind", "selector", "text", "replace"], "typedAction");
      if (typeof action.replace !== "boolean") throw new TypeError("typedAction.replace must be a boolean");
      normalized = {
        kind,
        selector: boundedString(action.selector, "typedAction.selector", MAX_SELECTOR_BYTES),
        text: boundedString(action.text, "typedAction.text", MAX_TEXT_BYTES, { allowEmpty: true }),
        replace: action.replace,
      };
      break;
    case "scroll":
      requireExactKeys(action, ["kind", "deltaX", "deltaY"], "typedAction");
      normalized = {
        kind,
        deltaX: signedInteger(action.deltaX, "typedAction.deltaX"),
        deltaY: signedInteger(action.deltaY, "typedAction.deltaY"),
      };
      break;
    case "focus":
      requireExactKeys(action, ["kind", "selector"], "typedAction");
      normalized = {
        kind,
        selector: boundedString(action.selector, "typedAction.selector", MAX_SELECTOR_BYTES),
      };
      break;
    case "wait":
      requireExactKeys(action, ["kind", "condition", "timeoutMs"], "typedAction");
      normalized = {
        kind,
        condition: boundedString(action.condition, "typedAction.condition", MAX_SELECTOR_BYTES),
        timeoutMs: positiveInteger(action.timeoutMs, "typedAction.timeoutMs"),
      };
      break;
    case "download": {
      requireExactKeys(action, ["kind", "url", "maxBytes"], "typedAction");
      const maxBytes = positiveInteger(action.maxBytes, "typedAction.maxBytes");
      if (maxBytes > MAX_DOWNLOAD_BYTES) throw new TypeError("typedAction.maxBytes exceeds the download limit");
      normalized = { kind, url: canonicalWebUrl(action.url, "typedAction.url"), maxBytes };
      break;
    }
    default:
      throw new TypeError("typedAction.kind is not registered");
  }
  if (UTF8.encode(JSON.stringify(canonicalize(normalized))).byteLength > MAX_TYPED_ACTION_BYTES) {
    throw new TypeError("typedAction exceeds the canonical byte limit");
  }
  return Object.freeze({ action: Object.freeze(normalized), digest: canonicalDigest(normalized) });
}

export function browserTypedActionDigest(value) {
  return normalizeTypedAction(value).digest;
}

export function parseEffectGrant(value, now, allowedOrigins) {
  const grant = requireRecord(value, "effectGrant");
  const grantDigest = digest(grant.grantDigest, "effectGrant.grantDigest");
  const action = stableId(grant.action, "effectGrant.action");
  const destinationOrigin = canonicalOrigin(grant.destinationOrigin);
  if (!allowedOrigins.has(destinationOrigin)) {
    throw new TypeError("effect grant destination is outside the profile grant");
  }
  return Object.freeze({
    grantDigest,
    action,
    destinationOrigin,
    finalPayloadDigest: digest(grant.finalPayloadDigest, "effectGrant.finalPayloadDigest"),
    authorityEpoch: positiveInteger(grant.authorityEpoch, "effectGrant.authorityEpoch"),
    expiresAtMs: deadline(grant.expiresAtMs, now, "effectGrant.expiresAtMs"),
  });
}

export function freezeResult(value) {
  return Object.freeze({
    ...value,
    networkAuthority: false,
    filesystemAuthority: false,
    credentialExportAuthority: false,
  });
}

export function assertDriver(driver) {
  requireRecord(driver, "driver");
  for (const method of ["start", "observe", "act", "reconcile", "stop"]) {
    if (typeof driver[method] !== "function") throw new TypeError(`driver.${method} must be a function`);
  }
  const capabilities = requireRecord(driver.capabilities, "driver.capabilities");
  for (const capability of [
    "abortSignal",
    "isolatedProcess",
    "privateControlChannel",
    "networkPolicyEnforced",
    "profileIsolationEnforced",
    "credentialBoundaryEnforced",
  ]) {
    if (capabilities[capability] !== true) throw new TypeError(`driver capability ${capability} is required`);
  }
  return driver;
}

export function assertAuthority(authority) {
  requireRecord(authority, "authority");
  for (const method of ["claim", "withVerifiedUse"]) {
    if (typeof authority[method] !== "function") throw new TypeError(`authority.${method} must be a function`);
  }
  return authority;
}

export function assertStore(store, allowVolatileStore) {
  requireRecord(store, "store");
  for (const method of ["loadProfile", "saveProfile", "deleteProfile", "listProfiles"]) {
    if (typeof store[method] !== "function") throw new TypeError(`store.${method} must be a function`);
  }
  if (store.durable !== true && allowVolatileStore !== true) {
    throw new TypeError("a durable browser state store is required");
  }
  return store;
}
