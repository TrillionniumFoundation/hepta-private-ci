import assert from "node:assert/strict";
import test from "node:test";
import { captureConfirmation, assertConfirmation, retainedTarget } from "../src/confirmation.js";
import { ScopedRecoveryStore } from "../src/recovery-store.js";
import { RecoveryScheduler } from "../src/recovery-scheduler.js";
import { UI_CONTROL_ERROR_CODES as C, uiControlError } from "../src/errors.js";

class Storage {
  values = new Map();
  get length() { return this.values.size; }
  key(i) { return [...this.values.keys()][i] ?? null; }
  getItem(k) { return this.values.get(k) ?? null; }
  setItem(k, v) { this.values.set(k, v); }
  removeItem(k) { this.values.delete(k); }
}
class Locks {
  chains = new Map();
  request(name, options, callback) {
    const prior = this.chains.get(name) ?? Promise.resolve();
    const result = prior.catch(() => {}).then(() => {
      if (options.signal?.aborted) throw options.signal.reason;
      return callback();
    });
    this.chains.set(name, result);
    return result;
  }
}
const op = (id = "op-1") => ({
  operationId: id, protocolVersion: "hepta.ui-control.v1", method: "runtime/stop",
  semanticDigest: "a".repeat(64), action: "request_stop", targetId: "runtime.agentd",
  reason: "Maintenance", sessionId: "session-1", connectionGeneration: 1,
  generation: 7, displayedRevision: 12, snapshotDigest: "b".repeat(64),
  state: "submitting", createdAt: 1, updatedAt: 1, auditTraceId: null,
});
const view = () => ({
  connected: true, authenticated: true, stale: false, sessionId: "session-1",
  identityId: "operator-1", permissionRevision: 1, connectionGeneration: 1,
  snapshot: { generation: 7, revision: 12, semanticDigest: "b".repeat(64),
    modules: [{ id: "runtime.agentd", revision: 9, semanticDigest: "c".repeat(64) }] },
});
const config = (storage = new Storage(), locks = new Locks()) => ({
  storage, locks, endpoint: "https://console.test/api/ui-control/v1/",
  identityId: "operator-1", protocolVersion: "hepta.ui-control.v1",
});
const recordCount = storage => [...storage.values.keys()]
  .filter(key => key.startsWith("hepta.ui-control.scoped-recovery.v2:")).length;

test("confirmation rejects generation rollover at the same displayed revision", () => {
  const before = view(); const consent = captureConfirmation(before, op());
  const after = view(); after.snapshot.generation = 8;
  assert.throws(() => assertConfirmation(consent, after, op()), { code: C.STALE_REVISION });
});

test("confirmation binds identity, permissions, session, snapshot, target and action", () => {
  const consent = captureConfirmation(view(), op());
  for (const field of ["identityId", "permissionRevision", "sessionId", "connectionGeneration"]) {
    const changed = view(); changed[field] = typeof changed[field] === "number" ? 2 : "other";
    assert.throws(() => assertConfirmation(consent, changed, op()), { code: C.STALE_REVISION });
  }
  for (const field of ["revision", "semanticDigest"]) {
    const changed = view(); changed.snapshot[field] = field === "revision" ? 13 : "d".repeat(64);
    assert.throws(() => assertConfirmation(consent, changed, op()), { code: C.STALE_REVISION });
  }
  for (const field of ["action", "reason", "operationId"]) {
    assert.throws(() => assertConfirmation(consent, view(), { ...op(), [field]: "changed" }), { code: C.STALE_REVISION });
  }
  const changed = view(); changed.snapshot.modules[0].revision += 1;
  assert.throws(() => assertConfirmation(consent, changed, op()), { code: C.STALE_REVISION });
});

test("target selection survives refresh and removal never picks a different target", () => {
  assert.equal(retainedTarget("runtime.fleet", ["runtime.agentd", "runtime.fleet"], true), "runtime.fleet");
  assert.equal(retainedTarget("runtime.fleet", ["runtime.agentd"], true), "");
  assert.equal(retainedTarget("", ["runtime.agentd"], false), "runtime.agentd");
});

test("prepared record survives loss of the entire client before any response", async () => {
  const options = config(); let store = await ScopedRecoveryStore.create(options);
  await store.prepare(op());
  store = null;
  const reopened = await ScopedRecoveryStore.create(options);
  assert.equal(reopened.load().operations[0].operationId, "op-1");
});

test("different tabs cannot overwrite each other's operation records", async () => {
  const options = config();
  const one = await ScopedRecoveryStore.create(options);
  const two = await ScopedRecoveryStore.create(options);
  await Promise.all([one.prepare(op("one")), two.prepare(op("two"))]);
  assert.deepEqual(one.load().operations.map(x => x.operationId).sort(), ["one", "two"]);
  await one.complete({ ...op("one"), state: "terminal", terminalStatus: "succeeded" });
  assert.deepEqual(two.load().operations.map(x => x.operationId), ["two"]);
});

test("terminal cleanup retains a conflicting later identity", async () => {
  const options = config(); const store = await ScopedRecoveryStore.create(options);
  await store.prepare(op());
  const key = [...options.storage.values.keys()]
    .find(value => value.startsWith("hepta.ui-control.scoped-recovery.v2:"));
  const stored = JSON.parse(options.storage.getItem(key));
  stored.operation.semanticDigest = "d".repeat(64);
  options.storage.setItem(key, JSON.stringify(stored));
  await assert.rejects(
    store.complete({ ...op(), state: "terminal", terminalStatus: "succeeded" }),
    { code: C.STORAGE },
  );
  assert.equal(recordCount(options.storage), 1);
});

test("concurrent same identity across tabs is admitted once and the loser must lookup", async () => {
  const options = config();
  const one = await ScopedRecoveryStore.create(options);
  const two = await ScopedRecoveryStore.create(options);
  const results = await Promise.allSettled([one.prepare(op()), two.prepare(op())]);
  assert.equal(results.filter(result => result.status === "fulfilled").length, 1);
  assert.equal(results.find(result => result.status === "rejected").reason.code, C.AMBIGUOUS_SUBMISSION);
  assert.equal(one.load().operations.length, 1);
});

test("same identity with changed semantics is rejected", async () => {
  const store = await ScopedRecoveryStore.create(config()); await store.prepare(op());
  await assert.rejects(store.prepare({ ...op(), reason: "Different" }), { code: C.OPERATION_CONFLICT });
});

test("recovery is isolated by actual endpoint, principal, protocol and namespace", async () => {
  const options = config(); const store = await ScopedRecoveryStore.create(options); await store.prepare(op());
  for (const changed of [{ endpoint: "https://console.test/other/" }, { identityId: "operator-2" },
    { protocolVersion: "hepta.ui-control.v2" }, { namespace: "another" }]) {
    assert.equal((await ScopedRecoveryStore.create({ ...options, ...changed })).load().operations.length, 0);
  }
});

test("denied storage and unavailable locks fail before dispatch", async () => {
  const options = config(); options.storage.setItem = () => { throw new Error("denied"); };
  await assert.rejects(ScopedRecoveryStore.create(options), error =>
    error.code === C.STORAGE && error.details.requestDispatched === false);
  await assert.rejects(ScopedRecoveryStore.create({ ...options, locks: null }), { code: C.STORAGE });
});

test("cross-tab capacity is checked under the admission lock", async () => {
  const options = { ...config(), maxEntries: 1 };
  const one = await ScopedRecoveryStore.create(options); const two = await ScopedRecoveryStore.create(options);
  const results = await Promise.allSettled([one.prepare(op("one")), two.prepare(op("two"))]);
  assert.equal(results.filter(result => result.status === "fulfilled").length, 1);
  assert.equal(one.load().operations.length, 1);
});

test("corrupt recovery is retained for diagnosis, never cleared or adopted", async () => {
  const options = config(); const store = await ScopedRecoveryStore.create(options); await store.prepare(op());
  const key = [...options.storage.values.keys()]
    .find(value => value.startsWith("hepta.ui-control.scoped-recovery.v2:"));
  options.storage.setItem(key, "not json");
  assert.throws(() => store.load(), { code: C.STORAGE });
  assert.equal(recordCount(options.storage), 1);
});

test("round-robin recovery reaches the tail while pending entries are backed off", async () => {
  let now = 100;
  const scheduler = new RecoveryScheduler(() => now, { initialBackoffMs: 10, maxBackoffMs: 40 });
  const operations = Array.from({ length: 40 }, (_, i) => ({ ...op(`op-${String(i).padStart(3, "0")}`), state: "pending" }));
  const seen = new Set(); const lookup = async id => { seen.add(id); return { operationId: id, state: "pending" }; };
  await scheduler.run(operations, lookup); await scheduler.run(operations, lookup);
  assert.equal(seen.size, 40);
  assert.equal(scheduler.metrics().observations, 40);
  assert.ok(scheduler.metrics().deferredByBackoff >= 32);
  now = 110; await scheduler.run(operations, lookup);
  assert.equal(scheduler.metrics().observations, 72);
});

test("recovery applies bounded exponential per-operation backoff", async () => {
  let now = 100; let lookups = 0;
  const scheduler = new RecoveryScheduler(() => now, { initialBackoffMs: 10, maxBackoffMs: 40 });
  const operations = [{ ...op(), state: "pending" }];
  const lookup = async id => { lookups += 1; return { operationId: id, state: "pending" }; };
  await scheduler.run(operations, lookup);
  assert.equal(scheduler.metrics().nextEligibleAt, 110);
  now = 109; assert.deepEqual(await scheduler.run(operations, lookup), []);
  now = 110; await scheduler.run(operations, lookup);
  assert.equal(lookups, 2);
  assert.equal(scheduler.metrics().nextEligibleAt, 130);
  now = 129; assert.deepEqual(await scheduler.run(operations, lookup), []);
  assert.equal(scheduler.metrics().backoffEntries, 1);
});

test("one failed lookup is isolated and later operations are still queried", async () => {
  const scheduler = new RecoveryScheduler(); const seen = [];
  const operations = ["a", "b", "c"].map(id => ({ ...op(id), state: "pending" }));
  const results = await scheduler.run(operations, async id => {
    seen.push(id); if (id === "a") throw new Error("transport"); return { operationId: id };
  });
  assert.equal(results[0].recoveryError, C.TRANSPORT); assert.deepEqual(seen, ["a", "b", "c"]);
});

test("recovery is bounded, single-flight and observes cancellation inside the batch", async () => {
  const scheduler = new RecoveryScheduler(); let resolve; let active = 0; let maxActive = 0;
  const gate = new Promise(r => { resolve = r; }); const controller = new AbortController();
  const operations = Array.from({ length: 10 }, (_, i) => ({ ...op(`op-${i}`), state: "pending" }));
  const lookup = async id => { active += 1; maxActive = Math.max(maxActive, active); await gate; active -= 1; return { operationId: id }; };
  const first = scheduler.run(operations, lookup, { concurrency: 2, signal: controller.signal });
  assert.equal(scheduler.run(operations, lookup), first);
  controller.abort(); resolve(); await assert.rejects(first, { code: C.ABORTED });
  assert.equal(maxActive, 2);
});

test("authority loss stops scheduling the remainder of a recovery batch", async () => {
  const scheduler = new RecoveryScheduler(); let calls = 0;
  await assert.rejects(scheduler.run(["a", "b"].map(id => ({ ...op(id), state: "pending" })), async () => {
    calls += 1; throw uiControlError(C.SESSION_REVOKED, "revoked");
  }, { concurrency: 1 }), { code: C.SESSION_REVOKED });
  assert.equal(calls, 1);
});
