import assert from "node:assert/strict";
import test from "node:test";

import { buildNavigationEffectInput } from "../src/bridge.js";
import { browserTypedActionDigest } from "../src/runtime.js";

const D1 = "1".repeat(64);

test("navigation intent is closed into an exact typed browser effect input", () => {
  const session = {
    kind: "BrowserSessionV1",
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 3,
  };
  const page = {
    kind: "PageObservationV1",
    profileId: "profile.1",
    profileGeneration: 3,
    pageGeneration: 9,
  };
  const intent = {
    kind: "BrowserNavigationIntentV1",
    navigationId: "navigation.1",
    tabId: "tab.1",
    url: "https://example.com/path",
  };
  const effect = buildNavigationEffectInput({
    session,
    page,
    intent,
    operationId: "operation.1",
    effectGrantDigest: D1,
    authorityEpoch: 7,
    deadlineMs: 99_000,
  });
  assert.deepEqual(effect.typedAction, {
    kind: "navigate",
    url: "https://example.com/path",
  });
  assert.equal(effect.destinationOrigin, "https://example.com");
  assert.equal(effect.finalPayloadDigest, browserTypedActionDigest(effect.typedAction));
  assert.equal(effect.pageGeneration, 9);
});

test("navigation bridge rejects mixed session/page generations", () => {
  assert.throws(
    () => buildNavigationEffectInput({
      session: { profileId: "profile.1", principalId: "principal.1", generation: 3 },
      page: { profileId: "profile.1", profileGeneration: 4, pageGeneration: 9 },
      intent: { kind: "BrowserNavigationIntentV1", url: "https://example.com" },
      operationId: "operation.1",
      effectGrantDigest: D1,
      authorityEpoch: 7,
      deadlineMs: 99_000,
    }),
    /generations do not match/,
  );
});
