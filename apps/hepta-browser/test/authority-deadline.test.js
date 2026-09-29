import assert from "node:assert/strict";
import test from "node:test";
import { setTimeout as delay } from "node:timers/promises";

import { browserActionDigest } from "../src/action.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";
import { BrowserProfileHost } from "../src/runtime.js";
import { callWithDeadline } from "../src/runtime-boundary.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);
const ACTION = Object.freeze({ kind: "click", selector: "#approved" });
const ACTION_DIGEST = browserActionDigest(ACTION);

function witness(request) {
  return {
    authorized: true, witnessDigest: D4,
    authorityEpoch: request.authorityEpoch, requestDigest: request.requestDigest,
  };
}

async function fixture({ authorize, clock = () => 1_000, expiresAtMs = 9_000,
                         grantExpiresAtMs = 8_000, journal, timeout = 30, dispatch, reconcile } = {}) {
  const observed = { dispatches: 0, stops: 0 };
  const durable = journal ?? new MemoryBrowserOperationJournal();
  const driver = {
    async start() { return { started: true, processId: "worker.1" }; },
    async observe() {
      return { pageGeneration: 1, documentDigest: D3, origin: "https://example.test" };
    },
    async dispatch(...args) {
      observed.dispatches++;
      return dispatch ? dispatch(...args) : { terminalObserved: false };
    },
    async reconcile(...args) {
      return reconcile ? reconcile(...args) : { terminalObserved: false };
    },
    async stop() { observed.stops++; return { stopped: true }; },
  };
  const host = new BrowserProfileHost({
    driver, journal: durable, clock, driverCallTimeoutMs: timeout,
    authority: { withVerifiedUse: authorize ?? ((request, consumer) => consumer(witness(request))) },
  });
  const scope = { profileId: "profile.1", principalId: "principal.1", generation: 1 };
  await host.openProfile({
    ...scope, manifestDigest: D1, grantDigest: D2, expiresAtMs,
    allowedOrigins: ["https://example.test"],
    effectGrants: [{ grantDigest: D4, action: "click", destinationOrigin: "https://example.test",
                    finalPayloadDigest: ACTION_DIGEST, authorityEpoch: 7, expiresAtMs: grantExpiresAtMs }],
  });
  await host.observePage({ ...scope, observationBudget: 64 });
  return {
    host, observed, durable, scope,
    operation: { ...scope, operationId: "operation.1", pageGeneration: 1,
                 typedAction: ACTION, destinationOrigin: "https://example.test",
                 finalPayloadDigest: ACTION_DIGEST, effectGrantDigest: D4,
                 authorityEpoch: 7, deadlineMs: 7_000 },
  };
}

test("timed-out authority cannot enter after the caller has closed the profile", async () => {
  let late;
  const f = await fixture({ authorize(request, consumer) {
    late = () => consumer(witness(request));
    return new Promise(() => {});
  } });
  await assert.rejects(f.host.navigateOrAct(f.operation), { name: "BrowserAuthorityTimeoutError" });
  await f.host.closeProfile(f.scope);
  await assert.rejects(late(), /closed|expired|timeout/i);
  assert.deepEqual(f.observed, { dispatches: 0, stops: 1 });
  assert.deepEqual(await f.durable.listOperations("profile.1", 1), []);
});

test("an authority failure closes its retained callback before a later invocation", async () => {
  let late;
  const f = await fixture({ authorize(request, consumer) {
    late = () => consumer(witness(request));
    throw new Error("injected authority failure");
  } });
  await assert.rejects(f.host.navigateOrAct(f.operation), /injected authority failure/);
  await assert.rejects(late(), /closed|expired|timeout/i);
  assert.equal(f.observed.dispatches, 0);
  assert.deepEqual(await f.durable.listOperations("profile.1", 1), []);
});

test("profile and effect-grant expiry are checked at callback entry, not just initial admission", async () => {
  for (const boundary of ["profile", "grant", "operation"]) {
    let now = 1_000;
    const expiry = 2_000;
    const f = await fixture({
      clock: () => now,
      expiresAtMs: boundary === "profile" ? expiry : 9_000,
      grantExpiresAtMs: boundary === "grant" ? expiry : 8_000,
      authorize(request, consumer) { now = boundary === "operation" ? 7_000 : expiry; return consumer(witness(request)); },
    });
    await assert.rejects(f.host.navigateOrAct(f.operation), /expired|timeout/i);
    assert.equal(f.observed.dispatches, 0);
    assert.deepEqual(await f.durable.listOperations("profile.1", 1), []);
  }
});

test("blocked event loop cannot beat the authority monotonic entry budget", async () => {
  const f = await fixture({ timeout: 10, authorize(request, consumer) {
    const end = performance.now() + 25;
    while (performance.now() < end) { /* simulate synchronous verifier stall */ }
    return consumer(witness(request));
  } });
  await assert.rejects(f.host.navigateOrAct(f.operation), /expired|timeout/i);
  assert.equal(f.observed.dispatches, 0);
});

test("an original late callback cannot duplicate a later admitted same-ID operation", async () => {
  let late;
  let calls = 0;
  const f = await fixture({ authorize(request, consumer) {
    calls++;
    if (calls === 1) {
      late = () => consumer(witness(request));
      return new Promise(() => {});
    }
    return consumer(witness(request));
  } });
  await assert.rejects(f.host.navigateOrAct(f.operation), { name: "BrowserAuthorityTimeoutError" });
  const result = await f.host.navigateOrAct(f.operation);
  await assert.rejects(late(), /closed|expired|timeout/i);
  assert.equal(result.status, "indeterminate");
  assert.equal(f.observed.dispatches, 1);
  assert.deepEqual(await f.host.navigateOrAct(f.operation), result);
  assert.equal(f.observed.dispatches, 1);
});

test("time expiring during durable intent never grants a driver a one-millisecond grace dispatch", async () => {
  let now = 1_000;
  const base = new MemoryBrowserOperationJournal();
  const journal = {
    async recordDispatch(record) { const result = await base.recordDispatch(record); now = 7_000; return result; },
    recordObservation: (...args) => base.recordObservation(...args),
    getOperation: (...args) => base.getOperation(...args),
    listOperations: (...args) => base.listOperations(...args),
  };
  const f = await fixture({ clock: () => now, journal });
  const result = await f.host.navigateOrAct(f.operation);
  assert.equal(result.status, "indeterminate");
  assert.equal(f.observed.dispatches, 0);
  const records = await base.listOperations("profile.1", 1);
  assert.equal(records.length, 1);
  assert.equal(records[0].terminalObserved, false);
  await assert.rejects(f.host.navigateOrAct(f.operation), /expired/);
  assert.equal(f.observed.dispatches, 0);
});

test("authority cannot report a result without entering the local consumer", async () => {
  let late;
  const f = await fixture({ authorize(request, consumer) {
    late = () => consumer(witness(request));
    return { terminalObserved: true, status: "succeeded", outcomeDigest: D1 };
  } });
  await assert.rejects(f.host.navigateOrAct(f.operation), /consumer|entry/i);
  await assert.rejects(late(), /closed|expired|timeout/i);
  assert.equal(f.observed.dispatches, 0);
});

test("wall-clock regression during authority verification is fail-closed", async () => {
  let now = 1_000;
  const f = await fixture({ clock: () => now, authorize(request, consumer) {
    now = 999;
    return consumer(witness(request));
  } });
  await assert.rejects(f.host.navigateOrAct(f.operation), /regressed|clock|expired/i);
  assert.equal(f.observed.dispatches, 0);
});

test("deadline wrapper rejects expired work before invoking a driver", async () => {
  for (const now of [() => 1000, () => Number.NaN, () => Infinity]) {
    let calls = 0;
    await assert.rejects(callWithDeadline({
      call: () => { calls++; return "not eligible"; }, payload: null, now,
      deadlineMs: 1000, timeoutCapMs: 30, abortable: true, timeoutName: "browser driver",
    }), /expired|clock|deadline/i);
    assert.equal(calls, 0);
  }
});

test("deadline wrapper rechecks time at actual invocation after a queued microtask", async () => {
  let now = 1_000;
  let calls = 0;
  queueMicrotask(() => { now = 2_000; });
  await assert.rejects(callWithDeadline({
    call: () => { calls++; return "not eligible"; }, payload: null, now: () => now,
    deadlineMs: 2000, timeoutCapMs: 30, abortable: true, timeoutName: "browser driver",
  }), /expired|deadline/i);
  assert.equal(calls, 0);
});

test("normal authority and after-dispatch timeout retain existing operation semantics", async () => {
  const f = await fixture({ authorize: async (request, consumer) => {
    const value = await consumer(witness(request));
    await delay(1);
    return value;
  } });
  const first = await f.host.navigateOrAct(f.operation);
  assert.equal(first.terminalObserved, false);
  assert.equal(f.observed.dispatches, 1);
  assert.deepEqual(await f.host.navigateOrAct(f.operation), first);
  assert.equal(f.observed.dispatches, 1);
});

test("a driver result after the original wall deadline stays unknown until fresh reconciliation", async () => {
  let now = 1_000;
  let reconciliations = 0;
  const f = await fixture({ clock: () => now, timeout: 1_000,
    dispatch() {
      now = 7_000;
      return { terminalObserved: true, status: "succeeded", outcomeDigest: D1 };
    },
    reconcile() {
      reconciliations++;
      return { terminalObserved: true, status: "succeeded", outcomeDigest: D1 };
    },
  });
  const late = await f.host.navigateOrAct(f.operation);
  assert.equal(late.status, "indeterminate");
  assert.equal(late.terminalObserved, false);
  assert.equal(f.observed.dispatches, 1);
  const pending = await f.durable.getOperation(f.scope.profileId, f.scope.generation, f.operation.operationId);
  assert.equal(pending.terminalObserved, false);
  await assert.rejects(f.host.navigateOrAct(f.operation), /expired/);
  assert.equal(f.observed.dispatches, 1);
  const resolved = await f.host.reconcileOperation(f.operation);
  assert.equal(resolved.status, "succeeded");
  assert.equal(resolved.terminalObserved, true);
  assert.equal(reconciliations, 1);
  assert.equal(f.observed.dispatches, 1);
});
