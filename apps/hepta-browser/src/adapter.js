import { typedActionDigest } from "./actions.js";

const LOCAL_NAVIGATION_PROPOSAL_SCHEMA =
  "hepta.browser.local-navigation-proposal.v1";

function requireRecord(value, name) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
  return value;
}

export function prepareNavigationEffect(proposal) {
  requireRecord(proposal, "proposal");
  if (
    proposal.localSchema !== LOCAL_NAVIGATION_PROPOSAL_SCHEMA ||
    proposal.networkAuthority !== false ||
    proposal.effectAuthority !== false ||
    proposal.directStoreWrite !== false
  ) {
    throw new TypeError("proposal is not an authority-free local navigation proposal");
  }
  const typedAction = Object.freeze({ kind: "navigate", url: proposal.url });
  return Object.freeze({
    typedAction,
    action: "navigate",
    destinationOrigin: new URL(proposal.url).origin,
    finalPayloadDigest: typedActionDigest(typedAction),
    navigationId: proposal.navigationId,
    policyDigest: proposal.policyDigest,
    expectedRevision: proposal.expectedRevision,
  });
}

export class BrowserServoAdapter {
  #host;

  constructor(host) {
    if (!host || typeof host.navigateOrAct !== "function") {
      throw new TypeError("host must expose navigateOrAct");
    }
    this.#host = host;
  }

  async executePreparedNavigation({
    prepared,
    session,
    operationId,
    pageGeneration,
    effectGrantDigest,
    authorityEpoch,
    deadlineMs,
    verifiedUse,
  }) {
    requireRecord(prepared, "prepared");
    requireRecord(session, "session");
    return this.#host.navigateOrAct({
      profileId: session.profileId,
      principalId: session.principalId,
      generation: session.generation,
      operationId,
      pageGeneration,
      action: prepared.action,
      typedAction: prepared.typedAction,
      destinationOrigin: prepared.destinationOrigin,
      finalPayloadDigest: prepared.finalPayloadDigest,
      effectGrantDigest,
      authorityEpoch,
      deadlineMs,
      verifiedUse,
    });
  }
}
