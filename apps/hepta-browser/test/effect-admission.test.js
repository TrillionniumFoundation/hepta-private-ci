import assert from "node:assert/strict";
import test from "node:test";

import {
  AdmissionBoundBrowserDriver,
  browserEffectPageRevision,
  createBrowserEffectAdmission,
  normalizeBrowserEffectAdmission,
} from "../src/effect-admission.js";
import { canonicalDigest } from "../src/runtime-contract.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);
const D5 = "5".repeat(64);
const W1 = "a".repeat(64);

function effect(overrides = {}) {
  return Object.freeze({
    profileId: "profile.1",
    principalId: "principal.1",
    processId: "servo.process.1",
    profileGeneration: 7,
    pageGeneration: 11,
    documentDigest: D1,
    operationId: "operation.1",
    action: "click",
    typedAction: Object.freeze({ kind: "click", selector: "button.primary" }),
    destinationOrigin: "https://example.com",
    finalPayloadDigest: D2,
    profileGrantDigest: D3,
    effectGrantDigest: D4,
    authorityEpoch: 9,
    deadlineMs: 50_000,
    verifiedUseTokenWitnessDigest: W1,
    ...overrides,
  });
}

function baseDriver(dispatchObservation = {}) {
  return {
    supportsAbort: true,
    maxActiveProfiles: 4,
    maxOutstandingOperations: 32,
    async start() { return { started: true }; },
    async observe() { return {}; },
    async dispatch() {
      return {
        terminalObserved: false,
        settlement: Promise.resolve({ terminalObserved: false }),
        ...dispatchObservation,
      };
    },
    async reconcile() { return {}; },
    async reconcilePersisted() { return {}; },
    async contain() { return { contained: true }; },
    async stop() { return { stopped: true }; },
  };
}

test("admission-bound driver emits an exact recoverable effect receipt", async () => {
  const semantics = effect();
  const driver = new AdmissionBoundBrowserDriver({
    driver: baseDriver(),
    clock: () => 12_345,
  });
  const observed = await driver.dispatch(semantics);
  assert.equal(observed.terminalObserved, false);
  assert.equal(observed.admission.kind, "BrowserEffectAdmissionV1");
  assert.equal(observed.admission.operationId, semantics.operationId);
  assert.equal(observed.admission.semanticDigest, canonicalDigest(semantics));
  assert.equal(observed.admission.workerGeneration, 7);
  assert.equal(
    observed.admission.pageRevision,
    browserEffectPageRevision(semantics),
  );
  assert.equal(observed.admission.admittedAt, 12_345);
  assert.equal(observed.admission.durableOrRecoverable, true);
  assert.equal(driver.maxActiveProfiles, 4);
  assert.equal(driver.maxOutstandingOperations, 32);
});

test("admission normalization rejects semantic, generation and page drift", () => {
  const semantics = effect();
  const admission = createBrowserEffectAdmission(semantics, {
    clock: () => 12_345,
  });
  assert.deepEqual(
    normalizeBrowserEffectAdmission(admission, {
      operationId: semantics.operationId,
      semanticDigest: canonicalDigest(semantics),
      workerGeneration: semantics.profileGeneration,
      pageRevision: browserEffectPageRevision(semantics),
    }),
    admission,
  );
  for (const tampered of [
    { ...admission, operationId: "operation.other" },
    { ...admission, semanticDigest: D5 },
    { ...admission, workerGeneration: 8 },
    { ...admission, pageRevision: D5 },
    { ...admission, durableOrRecoverable: false },
  ]) {
    assert.throws(
      () =>
        normalizeBrowserEffectAdmission(tampered, {
          operationId: semantics.operationId,
          semanticDigest: canonicalDigest(semantics),
          workerGeneration: semantics.profileGeneration,
          pageRevision: browserEffectPageRevision(semantics),
        }),
      /admission|durable|recoverable/,
    );
  }
});

test("driver cannot skip the worker admission boundary with a terminal result", async () => {
  const driver = new AdmissionBoundBrowserDriver({
    driver: baseDriver({
      terminalObserved: true,
      status: "succeeded",
      outcomeDigest: D5,
    }),
  });
  await assert.rejects(
    driver.dispatch(effect()),
    /must return at the worker admission boundary/,
  );
});
