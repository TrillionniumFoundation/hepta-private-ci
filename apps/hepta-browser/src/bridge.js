import { browserActionDigest, normalizeBrowserAction } from "./action.js";

const STABLE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const ZERO_DIGEST = "0".repeat(64);

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
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

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${name} must be a positive safe integer`);
  }
  return value;
}

export function navigationActionFromIntent(intent) {
  requireRecord(intent, "intent");
  if (intent.kind !== "BrowserNavigationIntentV1") {
    throw new TypeError("intent is not BrowserNavigationIntentV1");
  }
  if (
    intent.networkAuthority !== false ||
    intent.effectAuthority !== false ||
    intent.directStoreWrite !== false
  ) {
    throw new TypeError("navigation intent must remain authority-free");
  }
  stableId(intent.navigationId, "intent.navigationId");
  stableId(intent.tabId, "intent.tabId");
  return normalizeBrowserAction({
    kind: "navigate",
    url: intent.url,
    policyDigest: digest(intent.policyDigest, "intent.policyDigest"),
    expectedRevision: positiveInteger(intent.expectedRevision, "intent.expectedRevision"),
  });
}

export function navigationGrantBinding(intent) {
  const typedAction = navigationActionFromIntent(intent);
  return Object.freeze({
    action: typedAction.kind,
    destinationOrigin: new URL(typedAction.url).origin,
    finalPayloadDigest: browserActionDigest(typedAction),
  });
}

export function buildNavigationEffectRequest({
  session,
  page,
  intent,
  effectGrantDigest,
  authorityEpoch,
  deadlineMs,
}) {
  requireRecord(session, "session");
  requireRecord(page, "page");
  if (session.kind !== "BrowserSessionV1") {
    throw new TypeError("session is not BrowserSessionV1");
  }
  if (page.kind !== "PageObservationV1") {
    throw new TypeError("page is not PageObservationV1");
  }
  if (page.terminalObserved !== true || page.originAllowed !== true || page.quarantined === true) {
    throw new TypeError("page is not an admitted actionable observation");
  }
  const profileId = stableId(session.profileId, "session.profileId");
  const principalId = stableId(session.principalId, "session.principalId");
  const processId = stableId(session.processId, "session.processId");
  const generation = positiveInteger(session.generation, "session.generation");
  if (
    page.profileId !== profileId ||
    page.processId !== processId ||
    page.profileGeneration !== generation
  ) {
    throw new TypeError("page observation does not belong to the browser session");
  }
  const pageGeneration = positiveInteger(page.pageGeneration, "page.pageGeneration");
  digest(page.documentDigest, "page.documentDigest");
  const typedAction = navigationActionFromIntent(intent);
  return Object.freeze({
    profileId,
    principalId,
    generation,
    operationId: stableId(intent.navigationId, "intent.navigationId"),
    pageGeneration,
    typedAction,
    destinationOrigin: new URL(typedAction.url).origin,
    finalPayloadDigest: browserActionDigest(typedAction),
    effectGrantDigest: digest(effectGrantDigest, "effectGrantDigest"),
    authorityEpoch: positiveInteger(authorityEpoch, "authorityEpoch"),
    deadlineMs: positiveInteger(deadlineMs, "deadlineMs"),
  });
}
