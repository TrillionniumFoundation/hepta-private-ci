import assert from "node:assert/strict";
import test from "node:test";

import { BrowserServoAdapter, prepareNavigationEffect } from "../src/adapter.js";

const proposal = Object.freeze({
  localSchema: "hepta.browser.local-navigation-proposal.v1",
  navigationId: "navigation:1",
  tabId: "tab:1",
  url: "https://example.com/path",
  policyDigest: "a".repeat(64),
  expectedRevision: 7,
  networkAuthority: false,
  effectAuthority: false,
  directStoreWrite: false,
});

test("authority-free proposal becomes a typed digest-bound effect request", () => {
  const prepared = prepareNavigationEffect(proposal);
  assert.equal(prepared.action, "navigate");
  assert.equal(prepared.typedAction.url, proposal.url);
  assert.equal(prepared.destinationOrigin, "https://example.com");
  assert.match(prepared.finalPayloadDigest, /^[0-9a-f]{64}$/);
});

test("adapter bridges a prepared proposal without minting authority", async () => {
  let received;
  const host = {
    async navigateOrAct(value) {
      received = value;
      return { status: "indeterminate" };
    },
  };
  const adapter = new BrowserServoAdapter(host);
  const prepared = prepareNavigationEffect(proposal);
  const result = await adapter.executePreparedNavigation({
    prepared,
    session: { profileId: "profile.1", principalId: "principal.1", generation: 1 },
    operationId: "operation.1",
    pageGeneration: 2,
    effectGrantDigest: "1".repeat(64),
    authorityEpoch: 4,
    deadlineMs: 10_000,
    verifiedUse: { witnessDigest: "2".repeat(64) },
  });
  assert.equal(result.status, "indeterminate");
  assert.equal(received.typedAction.kind, "navigate");
  assert.equal(received.finalPayloadDigest, prepared.finalPayloadDigest);
  assert.equal(received.effectGrantDigest, "1".repeat(64));
});
