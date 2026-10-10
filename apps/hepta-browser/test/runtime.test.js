import assert from "node:assert/strict";
import test from "node:test";

import { browserActionDigest } from "../src/action.js";
import { BrowserProfileHost } from "../src/runtime.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D5 = "5".repeat(64);
const W1 = "a".repeat(64);

function navigationAction(url = "https://example.com/path") {
  return Object.freeze({
    kind: "navigate",
    url,
    policyDigest: D1,
    expectedRevision: 7,
  });
}

const NAV = navigationAction();
const NAV_DIGEST = browserActionDigest(NAV);

function effectGrant(overrides = {}) {
  return {
    grantDigest: D5,
    action: "navigate",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: NAV_DIGEST,
    authorityEpoch: 7,
    expiresAtMs: 9_500,
    ...overrides,
  };
}

function input(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: 10_000,
    allowedOrigins: ["https://example.com"],
    effectGrants: [effectGrant()],
    ...overrides,
  };
}

function authority({ authorized = true, witnessDigest = W1, delay = 0 } = {}) {
  let calls = 0;
  return {
    get calls() {
      return calls;
    },
    async withVerifiedUse(request, consumer) {
      calls += 1;
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      if (!authorized) throw new TypeError("final-use authority was denied");
      return consumer({
        authorized: true,
        witnessDigest,
        authorityEpoch: request.authorityEpoch,
        requestDigest: request.requestDigest,
      });
    },
  };
}

function driver({ terminalOnReconcile = true, dispatchImpl } = {}) {
  let dispatchCalls = 0;
  let stopCalls = 0;
  return {
    get actCalls() {
      return dispatchCalls;
    },
    get dispatchCalls() {
      return dispatchCalls;
    },
    get stopCalls() {
      return stopCalls;
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
    async dispatch(semantics, context) {
      dispatchCalls += 1;
      if (dispatchImpl) return dispatchImpl(semantics, context);
      return { terminalObserved: false };
    },
    async reconcile() {
      return terminalOnReconcile
        ? { terminalObserved: true, status: "succeeded", outcomeDigest: D1 }
        : { terminalObserved: false };
    },
    async stop() {
      stopCalls += 1;
      return { stopped: true };
    },
  };
}

function operation(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
    pageGeneration: 1,
    typedAction: NAV,
    destinationOrigin: "https://example.com",
    finalPayloadDigest: NAV_DIGEST,
    effectGrantDigest: D5,
    authorityEpoch: 7,
    deadlineMs: 9_000,
    ...overrides,
  };
}

async function preparedHost(options = {}) {
  const fakeDriver = options.driver ?? driver();
  const finalAuthority = options.authority ?? authority();
  const clock = options.clock ?? (() => 1_000);
  const journal = options.journal ?? new MemoryBrowserOperationJournal();
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: finalAuthority,
    journal,
    clock,
    driverCallTimeoutMs: options.driverCallTimeoutMs ?? 50,
  });
  await host.openProfile(input());
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 2048,
  });
  return { host, fakeDriver, finalAuthority, journal };
}

test("opens, observes, reconciles indeterminate action, and closes", async () => {
  const { host } = await preparedHost();
  const effect = await host.navigateOrAct(operation());
  assert.equal(effect.status, "indeterminate");
  await assert.rejects(
    host.closeProfile({ profileId: "profile.1", principalId: "principal.1", generation: 1 }),
    /requiring reconciliation/,
  );
  const terminal = await host.reconcileOperation(operation());
  assert.equal(terminal.status, "succeeded");
  assert.equal(terminal.terminalObserved, true);
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, terminal.semanticDigest);
  const closed = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);
});

test("same operation is single-flight and never double-dispatches", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const fakeDriver = driver({
    dispatchImpl: async () => {
      await gate;
      return { terminalObserved: false };
    },
  });
  const { host, finalAuthority } = await preparedHost({ driver: fakeDriver });
  const first = host.navigateOrAct(operation());
  const second = host.navigateOrAct(operation());
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(fakeDriver.dispatchCalls, 1);
  assert.equal(finalAuthority.calls, 1);
  release();
  const [left, right] = await Promise.all([first, second]);
  assert.equal(fakeDriver.dispatchCalls, 1);
  assert.equal(left.semanticDigest, right.semanticDigest);
});

test("driver throw after dispatch boundary becomes indeterminate and retry never redispatches", async () => {
  const fakeDriver = driver({
    dispatchImpl: async () => {
      throw new Error("connection lost after submit");
    },
  });
  const { host } = await preparedHost({ driver: fakeDriver });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  assert.equal(first.observationReason, "driver_error_after_dispatch_boundary");
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, first.semanticDigest);
  assert.equal(fakeDriver.dispatchCalls, 1);
});

test("reconciliation and cleanup remain available after grant and deadline expiry", async () => {
  let now = 1_000;
  const { host } = await preparedHost({ clock: () => now });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  now = 20_000;
  await assert.rejects(
    host.navigateOrAct(operation({ operationId: "operation.new" })),
    /profile grant has expired/,
  );
  const terminal = await host.reconcileOperation(operation());
  assert.equal(terminal.status, "succeeded");
  const closed = await host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  assert.equal(closed.terminalObserved, true);
});

test("typed action bytes are bound to final payload digest and destination", async () => {
  const { host, fakeDriver } = await preparedHost();
  await assert.rejects(
    host.navigateOrAct(operation({ typedAction: navigationAction("https://example.com/other") })),
    /does not bind typedAction/,
  );
  const evil = navigationAction("https://other.example/path");
  await assert.rejects(
    host.navigateOrAct(operation({ typedAction: evil, finalPayloadDigest: browserActionDigest(evil) })),
    /does not match destinationOrigin/,
  );
  assert.equal(fakeDriver.dispatchCalls, 0);
});

test("final-use authority denial cannot reach the driver", async () => {
  const denied = authority({ authorized: false });
  const { host, fakeDriver } = await preparedHost({ authority: denied });
  await assert.rejects(host.navigateOrAct(operation()), /final-use authority was denied/);
  assert.equal(denied.calls, 1);
  assert.equal(fakeDriver.dispatchCalls, 0);
});

test("durable intent and local dispatch occur inside the final-use fence", async () => {
  let insideFence = false;
  const baseJournal = new MemoryBrowserOperationJournal();
  const journal = {
    ...baseJournal,
    async recordDispatch(record) {
      assert.equal(insideFence, true);
      return baseJournal.recordDispatch(record);
    },
    async recordObservation(record) {
      return baseJournal.recordObservation(record);
    },
    async getOperation(...args) {
      return baseJournal.getOperation(...args);
    },
    async listOperations(...args) {
      return baseJournal.listOperations(...args);
    },
  };
  const finalAuthority = {
    async withVerifiedUse(request, consumer) {
      insideFence = true;
      try {
        return await consumer({
          authorized: true,
          witnessDigest: W1,
          authorityEpoch: request.authorityEpoch,
          requestDigest: request.requestDigest,
        });
      } finally {
        insideFence = false;
      }
    },
  };
  const fakeDriver = driver({
    dispatchImpl: async () => {
      assert.equal(insideFence, true);
      return { terminalObserved: false };
    },
  });
  const { host } = await preparedHost({ driver: fakeDriver, authority: finalAuthority, journal });
  await host.navigateOrAct(operation());
  assert.equal(insideFence, false);
});

test("profile serialization prevents close racing an in-flight effect", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const fakeDriver = driver({
    dispatchImpl: async () => {
      await gate;
      return { terminalObserved: false };
    },
  });
  const { host } = await preparedHost({ driver: fakeDriver });
  const effect = host.navigateOrAct(operation());
  const close = host.closeProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
  });
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(fakeDriver.stopCalls, 0);
  release();
  await effect;
  await assert.rejects(close, /requiring reconciliation/);
  assert.equal(fakeDriver.stopCalls, 0);
});

test("driver timeout aborts dispatch and preserves an indeterminate operation", async () => {
  let aborted = false;
  const fakeDriver = driver({
    dispatchImpl: async (_semantics, { signal }) =>
      new Promise(() => {
        signal.addEventListener("abort", () => { aborted = true; }, { once: true });
      }),
  });
  const { host } = await preparedHost({ driver: fakeDriver, driverCallTimeoutMs: 10 });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  assert.equal(first.observationReason, "driver_timeout");
  assert.equal(aborted, true);
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, first.semanticDigest);
  assert.equal(fakeDriver.dispatchCalls, 1);
});

test("replay rejects immutable semantic substitution", async () => {
  const { host } = await preparedHost({ driver: driver({ terminalOnReconcile: false }) });
  await host.navigateOrAct(operation());
  const changed = navigationAction("https://example.com/changed");
  await assert.rejects(
    host.navigateOrAct(operation({
      typedAction: changed,
      finalPayloadDigest: browserActionDigest(changed),
    })),
    /changed semantics|does not bind/,
  );
});

test("disallowed observed origin is quarantined and cannot authorize an action", async () => {
  const fakeDriver = driver();
  fakeDriver.observe = async () => ({
    pageGeneration: 1,
    documentDigest: D3,
    origin: "https://other.example",
  });
  const finalAuthority = authority();
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: finalAuthority,
    journal: new MemoryBrowserOperationJournal(),
    clock: () => 1_000,
    driverCallTimeoutMs: 50,
  });
  await host.openProfile(input());
  const page = await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 128,
  });
  assert.equal(page.originAllowed, false);
  assert.equal(page.quarantined, true);
  await assert.rejects(host.navigateOrAct(operation()), /stale page generation/);
  assert.equal(fakeDriver.dispatchCalls, 0);
});

test("persisted indeterminate operation reconciles after host process loss without redispatch", async () => {
  const journal = new MemoryBrowserOperationJournal();
  const firstDriver = driver({
    dispatchImpl: async () => {
      throw new Error("process lost after submit");
    },
  });
  const first = await preparedHost({ driver: firstDriver, journal });
  const unknown = await first.host.navigateOrAct(operation());
  assert.equal(unknown.status, "indeterminate");
  assert.equal(firstDriver.dispatchCalls, 1);

  const secondDriver = driver();
  const recoveredHost = new BrowserProfileHost({
    driver: secondDriver,
    authority: authority(),
    journal,
    clock: () => 20_000,
    driverCallTimeoutMs: 50,
  });
  const recovered = await recoveredHost.reconcilePersistedOperation(operation());
  assert.equal(recovered.status, "succeeded");
  assert.equal(recovered.terminalObserved, true);
  assert.equal(secondDriver.dispatchCalls, 0);
});

test("terminal operation retention uses durable tombstones instead of exhausting active capacity", async () => {
  const fakeDriver = driver({
    dispatchImpl: async () => ({
      terminalObserved: true,
      status: "succeeded",
      outcomeDigest: D1,
    }),
  });
  const { host } = await preparedHost({ driver: fakeDriver });
  for (let index = 0; index < 300; index += 1) {
    const receipt = await host.navigateOrAct(operation({ operationId: `operation.${index}` }));
    assert.equal(receipt.terminalObserved, true);
  }
  assert.equal(fakeDriver.dispatchCalls, 300);
  const replay = await host.navigateOrAct(operation({ operationId: "operation.0" }));
  assert.equal(replay.terminalObserved, true);
  assert.equal(fakeDriver.dispatchCalls, 300);
});

test("effect grants can be admitted after profile open without widening final-use authority", async () => {
  const fakeDriver = driver();
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: authority(),
    journal: new MemoryBrowserOperationJournal(),
    clock: () => 1_000,
    driverCallTimeoutMs: 50,
  });
  await host.openProfile(input({ effectGrants: [] }));
  const admitted = await host.admitEffectGrant({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    effectGrant: effectGrant(),
  });
  assert.equal(admitted.effectGrantCount, 1);
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 128,
  });
  const result = await host.navigateOrAct(operation());
  assert.equal(result.status, "indeterminate");
});
