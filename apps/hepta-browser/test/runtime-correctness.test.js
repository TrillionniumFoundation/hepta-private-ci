import assert from "node:assert/strict";
import test from "node:test";

import { browserActionDigest } from "../src/action.js";
import { BrowserProfileHost } from "../src/runtime.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D5 = "5".repeat(64);
const W1 = "a".repeat(64);
const NAV = Object.freeze({ kind: "navigate", url: "https://example.com/path" });
const NAV_DIGEST = browserActionDigest(NAV);

function input(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    manifestDigest: D1,
    grantDigest: D2,
    generation: 1,
    expiresAtMs: 10_000,
    allowedOrigins: ["https://example.com"],
    effectGrants: [
      {
        grantDigest: D5,
        action: "navigate",
        destinationOrigin: "https://example.com",
        finalPayloadDigest: NAV_DIGEST,
        authorityEpoch: 7,
        expiresAtMs: 9_500,
      },
    ],
    ...overrides,
  };
}

function authority({ authorized = true, witnessDigest = W1, delay = 0 } = {}) {
  let calls = 0;
  return {
    get calls() {
      return calls;
    },
    async verifyFinalUse(request) {
      calls += 1;
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      return {
        authorized,
        witnessDigest,
        authorityEpoch: request.authorityEpoch,
        requestDigest: request.requestDigest,
      };
    },
  };
}

function driver({ terminalOnReconcile = true, actImpl } = {}) {
  let actCalls = 0;
  let stopCalls = 0;
  return {
    get actCalls() {
      return actCalls;
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
    async act(semantics, context) {
      actCalls += 1;
      if (actImpl) return actImpl(semantics, context);
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
  const host = new BrowserProfileHost({
    driver: fakeDriver,
    authority: finalAuthority,
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
  return { host, fakeDriver, finalAuthority };
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
    actImpl: async () => {
      await gate;
      return { terminalObserved: false };
    },
  });
  const { host, finalAuthority } = await preparedHost({ driver: fakeDriver });
  const first = host.navigateOrAct(operation());
  const second = host.navigateOrAct(operation());
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(fakeDriver.actCalls, 1);
  assert.equal(finalAuthority.calls, 1);
  release();
  const [left, right] = await Promise.all([first, second]);
  assert.equal(fakeDriver.actCalls, 1);
  assert.equal(left.semanticDigest, right.semanticDigest);
});

test("driver throw after dispatch boundary becomes indeterminate and retry never redispatches", async () => {
  const fakeDriver = driver({
    actImpl: async () => {
      throw new Error("connection lost after submit");
    },
  });
  const { host } = await preparedHost({ driver: fakeDriver });
  const first = await host.navigateOrAct(operation());
  assert.equal(first.status, "indeterminate");
  assert.equal(first.observationReason, "driver_error_after_dispatch_boundary");
  const replay = await host.navigateOrAct(operation());
  assert.equal(replay.semanticDigest, first.semanticDigest);
  assert.equal(fakeDriver.actCalls, 1);
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
    host.navigateOrAct(operation({ typedAction: { kind: "navigate", url: "https://example.com/other" } })),
    /does not bind typedAction/,
  );
  const evil = { kind: "navigate", url: "https://other.example/path" };
  await assert.rejects(
    host.navigateOrAct(operation({ typedAction: evil, finalPayloadDigest: browserActionDigest(evil) })),
    /does not match destinationOrigin/,
  );
  assert.equal(fakeDriver.actCalls, 0);
});

test("final-use authority is rechecked immediately before the effect boundary", async () => {
  const denied = authority({ authorized: false });
  const { host, fakeDriver } = await preparedHost({ authority: denied });
  await assert.rejects(host.navigateOrAct(operation()), /final-use authority was denied/);
  assert.equal(denied.calls, 1);
  assert.equal(fakeDriver.actCalls, 0);
});

test("profile serialization prevents close racing an in-flight effect", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const fakeDriver = driver({
    actImpl: async () => {
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

test("driver timeout aborts the call and preserves an indeterminate operation", async () => {
  let aborted = false;
  const fakeDriver = driver({
    actImpl: async (_semantics, { signal }) =>
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
  assert.equal(fakeDriver.actCalls, 1);
});

test("replay rejects immutable semantic substitution", async () => {
  const { host } = await preparedHost({ driver: driver({ terminalOnReconcile: false }) });
  await host.navigateOrAct(operation());
  const changed = { kind: "navigate", url: "https://example.com/changed" };
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
  assert.equal(fakeDriver.actCalls, 0);
});
