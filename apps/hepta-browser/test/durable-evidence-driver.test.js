import assert from "node:assert/strict";
import test from "node:test";

import { DurableEvidenceBrowserDriver } from "../src/durable-evidence-driver.js";
import { canonicalDigest } from "../src/runtime-contract.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);
const D5 = "5".repeat(64);

function semantics() {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    processId: "servo.process.1",
    profileGeneration: 1,
    pageGeneration: 1,
    documentDigest: D1,
    operationId: "operation.1",
    action: "navigate",
    typedAction: {
      kind: "navigate",
      url: "https://example.com/path",
      policyDigest: D2,
      expectedRevision: 7,
    },
    destinationOrigin: "https://example.com",
    finalPayloadDigest: D3,
    profileGrantDigest: D4,
    effectGrantDigest: D5,
    authorityEpoch: 7,
    deadlineMs: 10_000,
    verifiedUseTokenWitnessDigest: "a".repeat(64),
  };
}

function innerDriver(dispatchImpl) {
  return {
    supportsAbort: true,
    maxActiveProfiles: 16,
    maxOutstandingOperations: 1,
    async start(input) {
      return input;
    },
    async observe(input) {
      return input;
    },
    dispatch: dispatchImpl,
    async reconcile(input) {
      return input;
    },
    async reconcilePersisted(input) {
      return input;
    },
    async contain() {
      return { contained: true };
    },
    async stop() {
      return { stopped: true };
    },
  };
}

test("worker admission is persisted before dispatch returns and deferred egress is bound", async () => {
  const input = semantics();
  const admission = {
    kind: "BrowserEffectAdmissionV1",
    operationId: input.operationId,
    semanticDigest: canonicalDigest(input),
    workerGeneration: 1,
    pageRevision: 1,
    admittedAt: 2_000,
    durableOrRecoverable: true,
  };
  const egressReceipt = {
    schema: "hepta.browser.egress-operation-receipt.v1",
    operationId: input.operationId,
  };
  const events = [];
  const journal = {
    async recordAdmission(record) {
      events.push(["admission", record]);
    },
    async recordEgress(record) {
      events.push(["egress", record]);
    },
  };
  const driver = new DurableEvidenceBrowserDriver({
    journal,
    driver: innerDriver(async () => ({
      terminalObserved: false,
      admission,
      settlement: Promise.resolve({
        terminalObserved: true,
        status: "succeeded",
        egressReceipt,
      }),
    })),
  });

  const observed = await driver.dispatch(input);
  assert.equal(events.length, 1);
  assert.equal(events[0][0], "admission");
  assert.equal(events[0][1].profileId, input.profileId);
  assert.equal(events[0][1].generation, input.profileGeneration);
  assert.equal(events[0][1].operationId, input.operationId);
  assert.equal(events[0][1].semanticDigest, canonicalDigest(input));
  const requestSemantics = { ...input };
  delete requestSemantics.verifiedUseTokenWitnessDigest;
  assert.equal(
    events[0][1].requestDigest,
    canonicalDigest(requestSemantics),
  );

  const terminal = await observed.settlement;
  assert.equal(terminal.status, "succeeded");
  assert.equal(events.length, 2);
  assert.equal(events[1][0], "egress");
  assert.deepEqual(events[1][1].receipt, egressReceipt);
  assert.equal(events[1][1].requestDigest, events[0][1].requestDigest);
  assert.equal(events[1][1].semanticDigest, events[0][1].semanticDigest);
});

test("a dispatch without a worker admission receipt fails closed", async () => {
  let admissions = 0;
  const driver = new DurableEvidenceBrowserDriver({
    journal: {
      async recordAdmission() {
        admissions += 1;
      },
      async recordEgress() {},
    },
    driver: innerDriver(async () => ({ terminalObserved: false })),
  });
  await assert.rejects(
    driver.dispatch(semantics()),
    /worker admission must be an object/,
  );
  assert.equal(admissions, 0);
});
