import assert from "node:assert/strict";
import test from "node:test";

import { buildNavigationIntent } from "../src/browser.js";
import {
  buildInitialNavigationEffectRequest,
  buildNavigationEffectRequest,
  navigationGrantBinding,
} from "../src/bridge.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);

function intent(overrides = {}) {
  return buildNavigationIntent({
    navigationId: "navigation.1",
    tabId: "tab.1",
    url: "https://example.com/path",
    policyDigest: D1,
    expectedRevision: 7,
    ...overrides,
  });
}

function session(overrides = {}) {
  return {
    kind: "BrowserSessionV1",
    profileId: "profile.1",
    principalId: "principal.1",
    processId: "servo.process.1",
    generation: 3,
    ...overrides,
  };
}

function page(overrides = {}) {
  return {
    kind: "PageObservationV1",
    profileId: "profile.1",
    processId: "servo.process.1",
    profileGeneration: 3,
    pageGeneration: 9,
    documentDigest: D2,
    origin: "https://example.com",
    originAllowed: true,
    quarantined: false,
    terminalObserved: true,
    ...overrides,
  };
}

test("initial navigation is a page-generation-zero authorized effect", () => {
  const source = intent();
  const binding = navigationGrantBinding(source);
  const request = buildInitialNavigationEffectRequest({
    session: session(),
    intent: source,
    effectGrantDigest: D2,
    authorityEpoch: 11,
    deadlineMs: 50_000,
  });
  assert.equal(request.pageGeneration, 0);
  assert.equal(request.operationId, "navigation.1");
  assert.equal(request.destinationOrigin, binding.destinationOrigin);
  assert.equal(request.finalPayloadDigest, binding.finalPayloadDigest);
});

test("navigation intent becomes the exact typed runtime payload and grant binding", () => {
  const source = intent();
  const binding = navigationGrantBinding(source);
  const request = buildNavigationEffectRequest({
    session: session(),
    page: page(),
    intent: source,
    effectGrantDigest: D2,
    authorityEpoch: 11,
    deadlineMs: 50_000,
  });
  assert.deepEqual(request.typedAction, {
    kind: "navigate",
    url: "https://example.com/path",
    policyDigest: D1,
    expectedRevision: 7,
  });
  assert.equal(request.operationId, "navigation.1");
  assert.equal(request.pageGeneration, 9);
  assert.equal(request.destinationOrigin, binding.destinationOrigin);
  assert.equal(request.finalPayloadDigest, binding.finalPayloadDigest);
  assert.equal(binding.action, "navigate");
});

test("bridge refuses authority-bearing intents and mismatched session/page generations", () => {
  const source = { ...intent(), effectAuthority: true };
  assert.throws(() => navigationGrantBinding(source), /authority-free/);
  assert.throws(
    () =>
      buildNavigationEffectRequest({
        session: session(),
        page: page({ profileGeneration: 4 }),
        intent: intent(),
        effectGrantDigest: D2,
        authorityEpoch: 11,
        deadlineMs: 50_000,
      }),
    /does not belong/,
  );
});

test("bridge refuses quarantined or off-origin observations", () => {
  for (const observed of [
    page({ originAllowed: false, quarantined: true }),
    page({ terminalObserved: false }),
  ]) {
    assert.throws(
      () =>
        buildNavigationEffectRequest({
          session: session(),
          page: observed,
          intent: intent(),
          effectGrantDigest: D2,
          authorityEpoch: 11,
          deadlineMs: 50_000,
        }),
      /not an admitted actionable observation/,
    );
  }
});
