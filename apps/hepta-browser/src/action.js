import { createHash } from "node:crypto";

const MAX_SELECTOR_BYTES = 2048;
const MAX_TEXT_BYTES = 65536;
const MAX_URL_BYTES = 4096;
const MAX_WAIT_MS = 120000;
const MAX_SCROLL_DELTA = 1_000_000;
const UTF8 = new TextEncoder();
const ASCII_CONTROL = /[\u0000-\u001f\u007f]/;
const ENCODED_ASCII_CONTROL = /%(?:0[0-9a-f]|1[0-9a-f]|7f)/i;
const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);
const WAIT_CONDITIONS = new Set(["load-complete"]);

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

function exactKeys(value, expected, name) {
  const keys = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (keys.length !== wanted.length || keys.some((key, index) => key !== wanted[index])) {
    throw new TypeError(`${name} contains missing or unknown fields`);
  }
}

function boundedString(value, name, maxBytes, { allowEmpty = false } = {}) {
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    throw new TypeError(`${name} must be a string`);
  }
  if (UTF8.encode(value).byteLength > maxBytes) {
    throw new TypeError(`${name} exceeds the byte limit`);
  }
  return value;
}

function stableId(value, name) {
  if (typeof value !== "string" || !STABLE_ID.test(value)) {
    throw new TypeError(`${name} must be a bounded stable identifier`);
  }
  return value;
}

function digest(value, name) {
  if (typeof value !== "string" || !DIGEST.test(value) || value === ZERO_DIGEST) {
    throw new TypeError(`${name} must be a non-zero lowercase SHA-256 digest`);
  }
  return value;
}

function positiveInteger(value, name, maximum = Number.MAX_SAFE_INTEGER) {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) {
    throw new TypeError(`${name} must be a bounded positive safe integer`);
  }
  return value;
}

function boundedInteger(value, name, maximumAbsolute) {
  if (!Number.isSafeInteger(value) || Math.abs(value) > maximumAbsolute) {
    throw new TypeError(`${name} must be a bounded safe integer`);
  }
  return value;
}

function containsLoneUtf16Surrogate(value) {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const nextCodeUnit = value.charCodeAt(index + 1);
      if (!(nextCodeUnit >= 0xdc00 && nextCodeUnit <= 0xdfff)) return true;
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return true;
    }
  }
  return false;
}

function webUrl(value, name = "url") {
  boundedString(value, name, MAX_URL_BYTES);
  if (ASCII_CONTROL.test(value) || ENCODED_ASCII_CONTROL.test(value)) {
    throw new TypeError(`${name} cannot contain control characters`);
  }
  if (containsLoneUtf16Surrogate(value)) {
    throw new TypeError(`${name} must contain well-formed Unicode`);
  }
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
    throw new TypeError(`${name} cannot contain credentials`);
  }
  const normalized = url.toString();
  if (UTF8.encode(normalized).byteLength > MAX_URL_BYTES) {
    throw new TypeError(`${name} exceeds the normalized byte limit`);
  }
  return normalized;
}

export function normalizeBrowserAction(value) {
  const action = requireRecord(value, "typedAction");
  if (typeof action.kind !== "string") {
    throw new TypeError("typedAction.kind must be a string");
  }
  switch (action.kind) {
    case "navigate": {
      exactKeys(action, ["kind", "url", "policyDigest", "expectedRevision"], "navigate action");
      return Object.freeze({
        kind: "navigate",
        url: webUrl(action.url),
        policyDigest: digest(action.policyDigest, "typedAction.policyDigest"),
        expectedRevision: positiveInteger(action.expectedRevision, "typedAction.expectedRevision"),
      });
    }
    case "click": {
      exactKeys(action, ["kind", "selector"], "click action");
      return Object.freeze({
        kind: "click",
        selector: boundedString(action.selector, "typedAction.selector", MAX_SELECTOR_BYTES),
      });
    }
    case "type": {
      exactKeys(action, ["kind", "selector", "text"], "type action");
      return Object.freeze({
        kind: "type",
        selector: boundedString(action.selector, "typedAction.selector", MAX_SELECTOR_BYTES),
        text: boundedString(action.text, "typedAction.text", MAX_TEXT_BYTES, { allowEmpty: true }),
      });
    }
    case "credential": {
      exactKeys(action, ["kind", "selector", "credentialRef"], "credential action");
      return Object.freeze({
        kind: "credential",
        selector: boundedString(action.selector, "typedAction.selector", MAX_SELECTOR_BYTES),
        credentialRef: stableId(action.credentialRef, "typedAction.credentialRef"),
      });
    }
    case "upload": {
      exactKeys(action, ["kind", "selector", "fileRef", "fileDigest", "maxBytes"], "upload action");
      return Object.freeze({
        kind: "upload",
        selector: boundedString(action.selector, "typedAction.selector", MAX_SELECTOR_BYTES),
        fileRef: stableId(action.fileRef, "typedAction.fileRef"),
        fileDigest: digest(action.fileDigest, "typedAction.fileDigest"),
        maxBytes: positiveInteger(action.maxBytes, "typedAction.maxBytes", 1_073_741_824),
      });
    }
    case "focus": {
      exactKeys(action, ["kind", "selector"], "focus action");
      return Object.freeze({
        kind: "focus",
        selector: boundedString(action.selector, "typedAction.selector", MAX_SELECTOR_BYTES),
      });
    }
    case "scroll": {
      exactKeys(action, ["kind", "deltaX", "deltaY"], "scroll action");
      return Object.freeze({
        kind: "scroll",
        deltaX: boundedInteger(action.deltaX, "typedAction.deltaX", MAX_SCROLL_DELTA),
        deltaY: boundedInteger(action.deltaY, "typedAction.deltaY", MAX_SCROLL_DELTA),
      });
    }
    case "wait": {
      exactKeys(action, ["kind", "condition", "timeoutMs"], "wait action");
      const condition = boundedString(action.condition, "typedAction.condition", 128);
      if (!WAIT_CONDITIONS.has(condition)) {
        throw new TypeError("typedAction.condition is not registered");
      }
      return Object.freeze({
        kind: "wait",
        condition,
        timeoutMs: positiveInteger(action.timeoutMs, "typedAction.timeoutMs", MAX_WAIT_MS),
      });
    }
    case "download": {
      exactKeys(action, ["kind", "url", "maxBytes"], "download action");
      return Object.freeze({
        kind: "download",
        url: webUrl(action.url, "typedAction.url"),
        maxBytes: positiveInteger(action.maxBytes, "typedAction.maxBytes", 1_073_741_824),
      });
    }
    default:
      throw new TypeError("typedAction.kind is not registered");
  }
}

export function browserActionDigest(value) {
  const normalized = normalizeBrowserAction(value);
  return createHash("sha256").update(JSON.stringify(normalized)).digest("hex");
}

export function browserActionDestinationOrigin(value) {
  const normalized = normalizeBrowserAction(value);
  if (normalized.kind !== "navigate" && normalized.kind !== "download") {
    return null;
  }
  return new URL(normalized.url).origin;
}
