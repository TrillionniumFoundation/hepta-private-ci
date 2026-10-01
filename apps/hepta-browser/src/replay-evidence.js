const REPLAYS = new WeakMap();

// Only the owner calls this after finding an immutable existing operation.
// A fresh clone prevents another caller's replay from marking its first result.
export function createBrowserReplayReceipt(receipt, identity) {
  const replay = Object.freeze({
    schema: "hepta.browser.replay-observation.v1",
    profileId: identity.profileId,
    principalId: identity.principalId,
    generation: identity.generation,
    operationId: identity.operationId,
    requestDigest: identity.requestDigest,
    semanticDigest: identity.semanticDigest,
  });
  const clone = Object.freeze({ ...receipt });
  REPLAYS.set(clone, replay);
  return clone;
}

export function browserReplayEvidence(receipt) {
  return REPLAYS.get(receipt);
}
