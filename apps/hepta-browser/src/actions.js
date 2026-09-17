import { createHash } from "node:crypto";

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const UTF8 = new TextEncoder();
const MAX_SELECTOR_BYTES = 2_048;
const MAX_TEXT_BYTES = 16_384;
const MAX_URL_BYTES = 4_096;
const MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024;
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function requireExactKeys(value, keys, name) {
  const expected = [...keys].sort();
  const actual = Object.keys(value).sort();
  if (
    expected.length !== actual.length ||
    expected.some((key, index) => key !== actual[index])
  ) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function boundedString(value, name, maxBytes, { allowEmpty = false } = {}) {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    throw new TypeError(`${name} must be a bounded string`);
  }
  if (UTF8.encode(value).byteLength > maxBytes) {
    throw new TypeError(`${name} exceeds its UTF-8 byte limit`);
  }
  return value;
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function boundedInteger(value, name, min, max) {
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new TypeError(`${name} is outside its registered bounds`);
  }
  return value;
}

function webUrl(value, name) {
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
  if (url.username || url.password) {
    throw new TypeError(`${name} must not contain credentials`);
  }
  const normalized = url.toString();
  if (UTF8.encode(normalized).byteLength > MAX_URL_BYTES) {
    throw new TypeError(`${name} exceeds its normalized UTF-8 byte limit`);
  }
  return normalized;
}

function selector(value, name = "typedAction.selector") {
  return boundedString(value, name, MAX_SELECTOR_BYTES);
}

function deepFreeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) {
      deepFreeze(child);
    }
  }
  return value;
}

function canonicalize(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("typed action contains a non-finite number");
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  requireRecord(value, "canonical value");
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonicalize(value[key])]),
  );
}

export function normalizeTypedAction(value) {
  const action = requireRecord(value, "typedAction");
  const kind = stableId(action.kind, "typedAction.kind");
  let normalized;
  switch (kind) {
    case "navigate":
      requireExactKeys(action, ["kind", "url"], "typedAction");
      normalized = { kind, url: webUrl(action.url, "typedAction.url") };
      break;
    case "click":
      requireExactKeys(action, ["kind", "selector"], "typedAction");
      normalized = { kind, selector: selector(action.selector) };
      break;
    case "type":
      requireExactKeys(action, ["kind", "selector", "text"], "typedAction");
      normalized = {
        kind,
        selector: selector(action.selector),
        text: boundedString(action.text, "typedAction.text", MAX_TEXT_BYTES, {
          allowEmpty: true,
        }),
      };
      break;
    case "scroll":
      requireExactKeys(action, ["kind", "deltaX", "deltaY"], "typedAction");
      normalized = {
        kind,
        deltaX: boundedInteger(action.deltaX, "typedAction.deltaX", -100_000, 100_000),
        deltaY: boundedInteger(action.deltaY, "typedAction.deltaY", -100_000, 100_000),
      };
      break;
    case "focus":
      requireExactKeys(action, ["kind", "selector"], "typedAction");
      normalized = { kind, selector: selector(action.selector) };
      break;
    case "wait":
      requireExactKeys(action, ["kind", "milliseconds"], "typedAction");
      normalized = {
        kind,
        milliseconds: boundedInteger(
          action.milliseconds,
          "typedAction.milliseconds",
          1,
          30_000,
        ),
      };
      break;
    case "download":
      requireExactKeys(
        action,
        ["kind", "url", "downloadRef", "maxBytes"],
        "typedAction",
      );
      normalized = {
        kind,
        url: webUrl(action.url, "typedAction.url"),
        downloadRef: stableId(action.downloadRef, "typedAction.downloadRef"),
        maxBytes: boundedInteger(
          action.maxBytes,
          "typedAction.maxBytes",
          1,
          MAX_DOWNLOAD_BYTES,
        ),
      };
      break;
    case "upload":
      requireExactKeys(
        action,
        ["kind", "selector", "fileRef", "maxBytes"],
        "typedAction",
      );
      normalized = {
        kind,
        selector: selector(action.selector),
        fileRef: stableId(action.fileRef, "typedAction.fileRef"),
        maxBytes: boundedInteger(
          action.maxBytes,
          "typedAction.maxBytes",
          1,
          MAX_UPLOAD_BYTES,
        ),
      };
      break;
    case "credential_fill":
      requireExactKeys(
        action,
        ["kind", "selector", "credentialRef"],
        "typedAction",
      );
      normalized = {
        kind,
        selector: selector(action.selector),
        credentialRef: stableId(action.credentialRef, "typedAction.credentialRef"),
      };
      break;
    default:
      throw new TypeError("typedAction.kind is not registered");
  }
  return deepFreeze(normalized);
}

export function typedActionDigest(value) {
  const action = normalizeTypedAction(value);
  return createHash("sha256")
    .update(JSON.stringify(canonicalize(action)))
    .digest("hex");
}

export function typedActionDestinationOrigin(value, currentOrigin) {
  const action = normalizeTypedAction(value);
  if (action.kind === "navigate" || action.kind === "download") {
    return new URL(action.url).origin;
  }
  if (typeof currentOrigin !== "string") {
    throw new TypeError("currentOrigin is required for page-local typed actions");
  }
  return new URL(currentOrigin).origin;
}
