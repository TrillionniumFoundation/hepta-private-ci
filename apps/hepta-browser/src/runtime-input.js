// Capture only the existing host DTO fields before the first asynchronous
// boundary. This is immutable request data, never cached authority/currentness.
import { MAX_EFFECT_GRANTS, MAX_ORIGINS, requireRecord } from "./runtime-contract.js";

const MAX_INPUT_BYTES = 1_048_576;
const INPUT_SCALARS = ["profileId", "principalId", "manifestDigest", "grantDigest", "generation",
  "expiresAtMs", "observationBudget", "operationId", "pageGeneration", "destinationOrigin",
  "finalPayloadDigest", "effectGrantDigest", "authorityEpoch", "deadlineMs"];
const GRANT_SCALARS = ["grantDigest", "action", "destinationOrigin", "finalPayloadDigest", "authorityEpoch", "expiresAtMs"];

function record(value, name) {
  requireRecord(value, name);
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError(`${name} must be plain request data`);
  }
  return value;
}

function field(value, key) {
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  if (!descriptor) return undefined;
  if (!Object.hasOwn(descriptor, "value")) {
    throw new TypeError(`${String(key)} must be an own data property`);
  }
  return descriptor.value;
}

function scalar(value, budget) {
  if (value !== null && value !== undefined && !["string", "number", "boolean"].includes(typeof value)) {
    throw new TypeError("host fields must be scalar request data");
  }
  // Strings are immutable; check size before retaining or normalizing them.
  if (typeof value === "string" && value.length > MAX_INPUT_BYTES) {
    throw new TypeError("host input data byte capacity exceeded");
  }
  budget.bytes += typeof value === "string" ? Buffer.byteLength(value, "utf8") : 8;
  if (budget.bytes > MAX_INPUT_BYTES) throw new TypeError("host input data byte capacity exceeded");
  return value;
}

function scalars(value, keys, budget) {
  record(value, "host input record");
  const result = Object.create(null);
  for (const key of keys) {
    const item = field(value, key);
    if (Object.hasOwn(value, key)) result[key] = scalar(item, budget);
  }
  return result;
}

function array(value, maximum, name, copy) {
  if (!Array.isArray(value) || value.length > maximum) {
    throw new TypeError(`${name} must be a bounded array`);
  }
  const length = value.length;
  const result = [];
  for (let index = 0; index < length; index++) {
    const item = field(value, index);
    if (item === undefined) throw new TypeError(`${name} must contain own data elements`);
    result.push(copy(item));
  }
  return Object.freeze(result);
}

export function snapshotHostInput(input) {
  record(input, "input");
  const budget = { bytes: 0 };
  const result = scalars(input, INPUT_SCALARS, budget);
  const origins = field(input, "allowedOrigins");
  if (origins !== undefined) result.allowedOrigins = array(origins, MAX_ORIGINS, "allowedOrigins", (item) => scalar(item, budget));
  const copyGrant = (item) => Object.freeze(scalars(item, GRANT_SCALARS, budget));
  const grants = field(input, "effectGrants");
  if (grants !== undefined) result.effectGrants = array(grants, MAX_EFFECT_GRANTS, "effectGrants", copyGrant);
  const grant = field(input, "effectGrant");
  if (grant !== undefined) result.effectGrant = copyGrant(grant);
  const action = field(input, "typedAction");
  if (action !== undefined) {
    record(action, "typedAction");
    const keys = [];
    for (const key in action) {
      if (Object.hasOwn(action, key)) {
        if (keys.length === 8) throw new TypeError("typedAction contains too many fields");
        scalar(key, budget);
        keys.push(key);
      }
    }
    // Keep unknown own action keys so the existing exact-key validator rejects
    // them. Do not normalize away missing fields or unregistered action kinds.
    result.typedAction = Object.freeze(scalars(action, keys, budget));
  }
  return Object.freeze(result);
}
