import {
  canonicalOrigin,
  digest,
  freezeResult,
  positiveInteger,
  stableId,
} from "./runtime-primitives.js";

export function encodeState(state) {
  return {
    schema: "hepta.browser.profile-state.v1",
    profileId: state.profileId,
    principalId: state.principalId,
    manifestDigest: state.manifestDigest,
    grantDigest: state.grantDigest,
    generation: state.generation,
    expiresAtMs: state.expiresAtMs,
    processId: state.processId,
    lifecycle: state.lifecycle,
    pageGeneration: state.pageGeneration,
    documentDigest: state.documentDigest,
    origin: state.origin,
    quarantinedReason: state.quarantinedReason,
    allowedOrigins: [...state.allowedOrigins],
    effectGrants: [...state.effectGrants.values()],
    operations: [...state.operations.entries()].map(([operationId, entry]) => ({ operationId, ...entry })),
    retiredOperations: [...state.retiredOperations.entries()].map(([operationId, entry]) => ({ operationId, ...entry })),
    nextOperationSequence: state.nextOperationSequence,
  };
}

export function decodeState(record) {
  if (record?.schema !== "hepta.browser.profile-state.v1") {
    throw new TypeError("persisted browser profile schema is unsupported");
  }
  const allowedOrigins = new Set(record.allowedOrigins.map(canonicalOrigin));
  const effectGrants = new Map();
  for (const grant of record.effectGrants) {
    const parsed = Object.freeze({
      grantDigest: digest(grant.grantDigest, "effectGrant.grantDigest"),
      action: stableId(grant.action, "effectGrant.action"),
      destinationOrigin: canonicalOrigin(grant.destinationOrigin),
      finalPayloadDigest: digest(grant.finalPayloadDigest, "effectGrant.finalPayloadDigest"),
      authorityEpoch: positiveInteger(grant.authorityEpoch, "effectGrant.authorityEpoch"),
      expiresAtMs: positiveInteger(grant.expiresAtMs, "effectGrant.expiresAtMs"),
    });
    effectGrants.set(parsed.grantDigest, parsed);
  }
  const operations = new Map((record.operations ?? []).map((entry) => [entry.operationId, {
    sequence: entry.sequence,
    semanticDigest: entry.semanticDigest,
    semantics: entry.semantics,
    receipt: entry.receipt,
    phase: entry.phase,
  }]));
  const retiredOperations = new Map((record.retiredOperations ?? []).map((entry) => [entry.operationId, {
    semanticDigest: entry.semanticDigest,
    semantics: entry.semantics ?? null,
    receipt: entry.receipt,
  }]));
  return {
    profileId: stableId(record.profileId, "profileId"),
    principalId: stableId(record.principalId, "principalId"),
    manifestDigest: digest(record.manifestDigest, "manifestDigest"),
    grantDigest: digest(record.grantDigest, "grantDigest"),
    generation: positiveInteger(record.generation, "generation"),
    expiresAtMs: positiveInteger(record.expiresAtMs, "expiresAtMs"),
    processId: record.processId === null ? null : stableId(record.processId, "processId"),
    lifecycle: record.lifecycle,
    pageGeneration: Number.isSafeInteger(record.pageGeneration) ? record.pageGeneration : 0,
    documentDigest: record.documentDigest,
    origin: record.origin,
    quarantinedReason: record.quarantinedReason ?? null,
    allowedOrigins,
    effectGrants,
    operations,
    retiredOperations,
    nextOperationSequence: positiveInteger(record.nextOperationSequence ?? 1, "nextOperationSequence"),
  };
}

export function activeOperationCount(state) {
  let count = 0;
  for (const entry of state.operations.values()) {
    if (entry.receipt.terminalObserved !== true) count += 1;
  }
  return count;
}

export function indeterminateReceipt(profileId, operationId, semanticDigest) {
  return freezeResult({
    kind: "BrowserEffectObservationV1",
    profileId,
    operationId,
    semanticDigest,
    status: "indeterminate",
    outcomeDigest: null,
    terminalObserved: false,
  });
}

export function effectReceipt(profileId, operationId, semanticDigest, observed) {
  if (observed.terminalObserved !== true) {
    return indeterminateReceipt(profileId, operationId, semanticDigest);
  }
  if (observed.status !== "succeeded" && observed.status !== "failed") {
    throw new TypeError("terminal browser status is not registered");
  }
  return freezeResult({
    kind: "BrowserEffectObservationV1",
    profileId,
    operationId,
    semanticDigest,
    status: observed.status,
    outcomeDigest: digest(observed.outcomeDigest, "outcomeDigest"),
    terminalObserved: true,
  });
}
