import {
  MAX_OPERATION_RECORDS,
  MAX_RETIRED_OPERATIONS,
  canonicalDigest,
  canonicalOrigin,
  deadline,
  digest,
  normalizeTypedAction,
  positiveInteger,
  stableId,
} from "./runtime-primitives.js";

export function admitOperation(input, state, now) {
  if (state.lifecycle !== "open") throw new TypeError(`profile is not active: ${state.lifecycle}`);
  if (now >= state.expiresAtMs) throw new TypeError("profile grant has expired");
  const operationId = stableId(input.operationId, "operationId");
  const pageGeneration = positiveInteger(input.pageGeneration, "pageGeneration");
  if (pageGeneration !== state.pageGeneration || state.documentDigest === null) {
    throw new TypeError("stale page generation");
  }
  const normalizedAction = normalizeTypedAction(input.typedAction);
  const action = normalizedAction.action.kind;
  if (input.action !== undefined && input.action !== action) {
    throw new TypeError("action does not match typedAction.kind");
  }
  const destinationOrigin = canonicalOrigin(input.destinationOrigin);
  if (!state.allowedOrigins.has(destinationOrigin)) {
    throw new TypeError("destination origin is outside the profile grant");
  }
  if (action === "navigate" || action === "download") {
    if (new URL(normalizedAction.action.url).origin !== destinationOrigin) {
      throw new TypeError("typedAction URL does not match destination origin");
    }
  } else if (state.origin !== destinationOrigin) {
    throw new TypeError("same-page action destination does not match the observed page origin");
  }
  const finalPayloadDigest = digest(input.finalPayloadDigest, "finalPayloadDigest");
  if (finalPayloadDigest !== normalizedAction.digest) {
    throw new TypeError("finalPayloadDigest does not bind typedAction");
  }
  const effectGrantDigest = digest(input.effectGrantDigest, "effectGrantDigest");
  const authorityEpoch = positiveInteger(input.authorityEpoch, "authorityEpoch");
  const deadlineMs = deadline(input.deadlineMs, now);
  const grant = state.effectGrants.get(effectGrantDigest);
  if (!grant) throw new TypeError("effect grant is not registered for this profile");
  if (now >= grant.expiresAtMs) throw new TypeError("effect grant has expired");
  if (
    grant.action !== action
    || grant.destinationOrigin !== destinationOrigin
    || grant.finalPayloadDigest !== finalPayloadDigest
    || grant.authorityEpoch !== authorityEpoch
  ) {
    throw new TypeError("effect grant does not bind the final browser operation");
  }
  const semantics = Object.freeze({
    profileId: state.profileId,
    principalId: state.principalId,
    processId: state.processId,
    profileGeneration: state.generation,
    pageGeneration,
    documentDigest: state.documentDigest,
    operationId,
    action,
    destinationOrigin,
    finalPayloadDigest,
    profileGrantDigest: state.grantDigest,
    effectGrantDigest,
    authorityEpoch,
    deadlineMs,
  });
  return {
    operationId,
    semantics,
    semanticDigest: canonicalDigest(semantics),
    typedAction: normalizedAction.action,
    grant,
  };
}

export function assertReplayMatches(input, prior) {
  const semantics = prior.semantics;
  if (!semantics) {
    if (input.semanticDigest !== prior.semanticDigest) {
      throw new TypeError("retired operation replay requires the original semanticDigest");
    }
    return;
  }
  const typedAction = normalizeTypedAction(input.typedAction);
  const action = typedAction.action.kind;
  if (input.action !== undefined && input.action !== action) {
    throw new TypeError("operation identity was reused with changed semantics");
  }
  const checks = [
    [positiveInteger(input.pageGeneration, "pageGeneration"), semantics.pageGeneration],
    [action, semantics.action],
    [canonicalOrigin(input.destinationOrigin), semantics.destinationOrigin],
    [digest(input.finalPayloadDigest, "finalPayloadDigest"), semantics.finalPayloadDigest],
    [typedAction.digest, semantics.finalPayloadDigest],
    [digest(input.effectGrantDigest, "effectGrantDigest"), semantics.effectGrantDigest],
    [positiveInteger(input.authorityEpoch, "authorityEpoch"), semantics.authorityEpoch],
    [positiveInteger(input.deadlineMs, "deadlineMs"), semantics.deadlineMs],
  ];
  if (checks.some(([actual, expected]) => actual !== expected)) {
    throw new TypeError("operation identity was reused with changed semantics");
  }
}

export function compactTerminalOperations(state) {
  if (state.operations.size < MAX_OPERATION_RECORDS) return;
  for (const [operationId, entry] of [...state.operations.entries()].sort(
    (left, right) => left[1].sequence - right[1].sequence,
  )) {
    if (state.operations.size < MAX_OPERATION_RECORDS / 2) break;
    if (entry.receipt.terminalObserved !== true) continue;
    if (state.retiredOperations.size >= MAX_RETIRED_OPERATIONS) {
      throw new TypeError("retired operation capacity is exhausted");
    }
    state.operations.delete(operationId);
    state.retiredOperations.set(operationId, {
      semanticDigest: entry.semanticDigest,
      semantics: entry.semantics,
      receipt: entry.receipt,
    });
  }
}

export function finalUseBinding(state, grant, semantics, semanticDigest) {
  return Object.freeze({
    subjectId: state.principalId,
    destinationId: state.processId,
    requestDigest: semanticDigest,
    scopeDigest: grant.grantDigest,
    payloadDigest: semantics.finalPayloadDigest,
    authorityEpoch: semantics.authorityEpoch,
  });
}
