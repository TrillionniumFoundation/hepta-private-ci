import { createHash } from "node:crypto";
import {
  browserActionDestinationOrigin,
  browserActionDigest,
  normalizeBrowserAction,
} from "./action.js";

export const DEFAULT_MAX_ACTIVE_PROFILES = 1;
export const MAX_CONFIGURED_ACTIVE_PROFILES = 64;
export const MAX_ORIGINS = 128;
export const MAX_EFFECT_GRANTS = 1024;
export const MAX_OUTSTANDING_OPERATIONS = 1024;
export const MAX_RETAINED_TERMINAL_OPERATIONS = 256;
export const DEFAULT_DRIVER_CALL_TIMEOUT_MS = 30_000;

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);

export function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
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

export function nonNegativeInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative safe integer`);
  }
  return value;
}

export function futureDeadline(value, now, name = "deadlineMs") {
  const deadlineMs = positiveInteger(value, name);
  if (deadlineMs <= now) {
    throw new TypeError(`${name} has expired`);
  }
  return deadlineMs;
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

export function canonicalDigest(value) {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

export function freezeResult(value) {
  return Object.freeze({
    ...value,
    networkAuthority: false,
    filesystemAuthority: false,
    credentialExportAuthority: false,
  });
}

export function parseEffectGrant(value, now, allowedOrigins) {
  const grant = requireRecord(value, "effectGrant");
  const grantDigest = digest(grant.grantDigest, "effectGrant.grantDigest");
  const action = stableId(grant.action, "effectGrant.action");
  const destinationOrigin = canonicalOrigin(grant.destinationOrigin);
  if (!allowedOrigins.has(destinationOrigin)) {
    throw new TypeError("effect grant destination is outside the profile grant");
  }
  const finalPayloadDigest = digest(grant.finalPayloadDigest, "effectGrant.finalPayloadDigest");
  const authorityEpoch = positiveInteger(grant.authorityEpoch, "effectGrant.authorityEpoch");
  const expiresAtMs = futureDeadline(grant.expiresAtMs, now, "effectGrant.expiresAtMs");
  return Object.freeze({
    grantDigest,
    action,
    destinationOrigin,
    finalPayloadDigest,
    authorityEpoch,
    expiresAtMs,
  });
}

export function indeterminateReceipt(profileId, operationId, semanticDigest, reason) {
  return freezeResult({
    kind: "BrowserEffectObservationV1",
    profileId,
    operationId,
    semanticDigest,
    status: "indeterminate",
    outcomeDigest: null,
    terminalObserved: false,
    observationReason: reason,
  });
}

export function admitNewOperation(state, input, now) {
  const operationId = stableId(input.operationId, "operationId");
  const typedAction = normalizeBrowserAction(input.typedAction);
  const action = stableId(typedAction.kind, "typedAction.kind");
  const pageGeneration = nonNegativeInteger(input.pageGeneration, "pageGeneration");
  const bootstrapNavigation =
    action === "navigate" &&
    pageGeneration === 0 &&
    state.pageGeneration === 0 &&
    state.documentDigest === null;
  if (
    !bootstrapNavigation &&
    (pageGeneration === 0 || pageGeneration !== state.pageGeneration || state.documentDigest === null)
  ) {
    throw new TypeError("stale page generation");
  }
  const destinationOrigin = canonicalOrigin(input.destinationOrigin);
  if (!state.allowedOrigins.has(destinationOrigin)) {
    throw new TypeError("destination origin is outside the profile grant");
  }
  const actionDestination = browserActionDestinationOrigin(typedAction);
  if (actionDestination !== null && actionDestination !== destinationOrigin) {
    throw new TypeError("typed action destination does not match destinationOrigin");
  }
  const finalPayloadDigest = digest(input.finalPayloadDigest, "finalPayloadDigest");
  if (browserActionDigest(typedAction) !== finalPayloadDigest) {
    throw new TypeError("finalPayloadDigest does not bind typedAction");
  }
  const effectGrantDigest = digest(input.effectGrantDigest, "effectGrantDigest");
  const authorityEpoch = positiveInteger(input.authorityEpoch, "authorityEpoch");
  const deadlineMs = futureDeadline(input.deadlineMs, now);
  const grant = state.effectGrants.get(effectGrantDigest);
  if (!grant) throw new TypeError("effect grant is not registered for this profile");
  if (now >= grant.expiresAtMs) throw new TypeError("effect grant has expired");
  if (
    grant.action !== action ||
    grant.destinationOrigin !== destinationOrigin ||
    grant.finalPayloadDigest !== finalPayloadDigest ||
    grant.authorityEpoch !== authorityEpoch
  ) {
    throw new TypeError("effect grant does not bind the final browser operation");
  }
  const requestSemantics = Object.freeze({
    profileId: state.profileId,
    principalId: state.principalId,
    processId: state.processId,
    profileGeneration: state.generation,
    pageGeneration,
    documentDigest: bootstrapNavigation ? null : state.documentDigest,
    operationId,
    action,
    typedAction,
    destinationOrigin,
    finalPayloadDigest,
    profileGrantDigest: state.grantDigest,
    effectGrantDigest,
    authorityEpoch,
    deadlineMs,
  });
  return {
    operationId,
    requestSemantics,
    requestDigest: canonicalDigest(requestSemantics),
  };
}

export function reconciliationRequestDigest(state, input, stored) {
  const typedAction = normalizeBrowserAction(input.typedAction);
  const candidate = Object.freeze({
    profileId: state.profileId,
    principalId: state.principalId,
    processId: state.processId,
    profileGeneration: state.generation,
    pageGeneration: nonNegativeInteger(input.pageGeneration, "pageGeneration"),
    documentDigest: stored.documentDigest,
    operationId: stableId(input.operationId, "operationId"),
    action: stableId(typedAction.kind, "typedAction.kind"),
    typedAction,
    destinationOrigin: canonicalOrigin(input.destinationOrigin),
    finalPayloadDigest: digest(input.finalPayloadDigest, "finalPayloadDigest"),
    profileGrantDigest: state.grantDigest,
    effectGrantDigest: digest(input.effectGrantDigest, "effectGrantDigest"),
    authorityEpoch: positiveInteger(input.authorityEpoch, "authorityEpoch"),
    // Recovery observes an already-dispatched identity; expiry is not new authority.
    deadlineMs: positiveInteger(input.deadlineMs, "deadlineMs"),
  });
  if (browserActionDigest(typedAction) !== candidate.finalPayloadDigest) {
    throw new TypeError("finalPayloadDigest does not bind typedAction");
  }
  return canonicalDigest(candidate);
}
