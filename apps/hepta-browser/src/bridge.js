import { browserTypedActionDigest } from "./runtime.js";

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

export function buildNavigationEffectInput({
  session,
  page,
  intent,
  operationId,
  effectGrantDigest,
  authorityEpoch,
  deadlineMs,
}) {
  requireRecord(session, "session");
  requireRecord(page, "page");
  requireRecord(intent, "intent");
  if (intent.kind !== "BrowserNavigationIntentV1") {
    throw new TypeError("intent must be BrowserNavigationIntentV1");
  }
  if (session.profileId !== page.profileId || session.generation !== page.profileGeneration) {
    throw new TypeError("session and page generations do not match");
  }
  const typedAction = Object.freeze({ kind: "navigate", url: intent.url });
  return Object.freeze({
    profileId: session.profileId,
    principalId: session.principalId,
    generation: session.generation,
    operationId,
    pageGeneration: page.pageGeneration,
    action: "navigate",
    typedAction,
    destinationOrigin: new URL(intent.url).origin,
    finalPayloadDigest: browserTypedActionDigest(typedAction),
    effectGrantDigest,
    authorityEpoch,
    deadlineMs,
  });
}
