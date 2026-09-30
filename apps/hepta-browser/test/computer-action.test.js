import assert from "node:assert/strict";
import test from "node:test";

import { browserActionDigest } from "../src/action.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";
import {
  computerActionAuthorityBindingDigestV1,
  computerActionPayloadDigestV1,
  encodeComputerActionFrameV1,
} from "../../../codex-rs/hepta-wire/js/computer-action-ir.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D5 = "5".repeat(64);
const W1 = "a".repeat(64);

function clickAction(selector = "#submit") {
  return Object.freeze({ kind: "click", selector });
}

function frameFor(action, overrides = {}) {
  const payload = { kind: "none" };
  return {
    operationId: "operation.binary.1",
    subjectId: "principal.1",
    actuatorId: "browser-servo",
    opcode: "activate_target",
    targetRef: "element.submit",
    bodyGeneration: 1,
    sessionGeneration: 1,
    observationRevision: 1,
    deadlineMonotonicMicros: 2_000_000,
    preconditionDigest: D3,
    argumentPayloadDigest: computerActionPayloadDigestV1("activate_target", payload),
    finalPayloadDigest: browserActionDigest(action),
    expectedPostconditionDigest: D2,
    payload,
    ...overrides,
  };
}

function effectGrant(finalPayloadDigest) {
  return {
    grantDigest: D5,
    action: "click",
    destinationOrigin: "https://example.com",
    finalPayloadDigest,
    authorityEpoch: 7,
    expiresAtMs: 9_500,
  };
}

function authority(events) {
  let calls = 0;
  return {
    get calls() {
      return calls;
    },
    async withVerifiedUse(request, consumer) {
      calls += 1;
      events.push("authority-enter");
      const result = await consumer({
        authorized: true,
        witnessDigest: W1,
        authorityEpoch: request.authorityEpoch,
        requestDigest: request.requestDigest,
      });
      events.push("authority-exit");
      return result;
    },
  };
}

function driver(events) {
  let dispatchCalls = 0;
  return {
    get dispatchCalls() {
      return dispatchCalls;
    },
    async start() {
      return { started: true, processId: "servo.process.1" };
    },
    async observe() {
      return {
        pageGeneration: 1,
        documentDigest: D3,
        origin: "https://example.com",
      };
    },
    async dispatch(semantics) {
      dispatchCalls += 1;
      events.push("driver-dispatch");
      return {
        terminalObserved: true,
        status: "succeeded",
        outcomeDigest: D1,
        observedSourceActionDigest: semantics.sourceActionDigest,
      };
    },
    async reconcile() {
      return { terminalObserved: false };
    },
    async stop() {
      return { stopped: true };
    },
  };
}

async function prepared({ resolver, action = clickAction() } = {}) {
  const events = [];
  const finalAuthority = authority(events);
  const fakeDriver = driver(events);
  const journal = new MemoryBrowserOperationJournal();
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: finalAuthority,
    journal,
    clock: () => 1_000,
    driverCallTimeoutMs: 50,
    binaryResolver: resolver ?? {
      async resolve(request) {
        assert.equal(request.kind, "target");
        assert.equal(request.targetRef, "element.submit");
        assert.equal(request.observationRevision, 1);
        return { selector: action.selector };
      },
    },
  });
  await host.openProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: 10_000,
    allowedOrigins: ["https://example.com"],
    effectGrants: [effectGrant(browserActionDigest(action))],
  });
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  return { host, fakeDriver, finalAuthority, journal, events, action };
}

function binaryInput(frame, overrides = {}) {
  return {
    frameBytes: encodeComputerActionFrameV1(frame),
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    effectGrantDigest: D5,
    authorityEpoch: 7,
    admittedMonotonicMicros: 1_000_000,
    admittedWallTimeMs: 1_000,
    ...overrides,
  };
}

test("binary action resolves inside the existing Browser owner and dispatches once", async () => {
  const { host, fakeDriver, finalAuthority, journal, events, action } = await prepared();
  const frame = frameFor(action);
  const receipt = await host.navigateOrActBinary(binaryInput(frame));
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.terminalObserved, true);
  assert.equal(fakeDriver.dispatchCalls, 1);
  assert.equal(finalAuthority.calls, 1);
  assert.deepEqual(events, ["authority-enter", "driver-dispatch", "authority-exit"]);
  const durable = await journal.getOperation("profile.1", 1, "operation.binary.1");
  assert.equal(
    durable.sourceActionDigest,
    computerActionAuthorityBindingDigestV1(frame),
  );
  assert.equal(durable.finalPayloadDigest, browserActionDigest(action));
  const replay = await host.navigateOrActBinary(binaryInput(frame));
  assert.equal(replay.semanticDigest, receipt.semanticDigest);
  assert.equal(fakeDriver.dispatchCalls, 1);
  assert.equal(finalAuthority.calls, 1);
});

test("resolver substitution and stale observation fail before authority or dispatch", async () => {
  const action = clickAction();
  const resolver = {
    async resolve() {
      return { selector: "#different" };
    },
  };
  const { host, fakeDriver, finalAuthority } = await prepared({ resolver, action });
  await assert.rejects(
    host.navigateOrActBinary(binaryInput(frameFor(action))),
    /does not match finalPayloadDigest/,
  );
  await assert.rejects(
    host.navigateOrActBinary(binaryInput(frameFor(action, { observationRevision: 2 }))),
    /observation revision mismatch/,
  );
  assert.equal(finalAuthority.calls, 0);
  assert.equal(fakeDriver.dispatchCalls, 0);
});

test("expired monotonic ComputerAction deadline fails before final-use authority", async () => {
  const { host, fakeDriver, finalAuthority, action } = await prepared();
  const frame = frameFor(action, { deadlineMonotonicMicros: 1_000_000 });
  await assert.rejects(
    host.navigateOrActBinary(binaryInput(frame)),
    /deadline has expired/,
  );
  assert.equal(finalAuthority.calls, 0);
  assert.equal(fakeDriver.dispatchCalls, 0);
});


test("binary input cannot replace the host-owned reference resolver", async () => {
  const { host, fakeDriver, finalAuthority, action } = await prepared();
  let called = false;
  await assert.rejects(host.navigateOrActBinary(binaryInput(frameFor(action), {
    resolver: { async resolve() { called = true; return { selector: action.selector }; } },
  })), /resolver is host-owned/);
  assert.equal(called, false);
  assert.equal(fakeDriver.dispatchCalls, 0);
  assert.equal(finalAuthority.calls, 0);
});
