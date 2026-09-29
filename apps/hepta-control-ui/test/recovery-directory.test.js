import assert from "node:assert/strict";
import test from "node:test";
import { ScopedRecoveryStore } from "../src/recovery-store.js";

class Storage {
  values = new Map();
  enumerations = 0;
  reads = 0;
  writes = 0;
  removals = 0;
  get length() { return this.values.size; }
  key(index) { this.enumerations += 1; return [...this.values.keys()][index] ?? null; }
  getItem(key) { this.reads += 1; return this.values.get(key) ?? null; }
  setItem(key, value) { this.writes += 1; this.values.set(key, value); }
  removeItem(key) { this.removals += 1; this.values.delete(key); }
}
class Locks {
  tail = Promise.resolve();
  requests = 0;
  request(name, options, callback) {
    this.requests += 1;
    const work = this.tail.then(() => {
      options.signal?.throwIfAborted();
      return callback();
    });
    this.tail = work.catch(() => {});
    return work;
  }
}
const op = (id = "op-1") => ({
  operationId: id, protocolVersion: "hepta.ui-control.v1", method: "runtime/stop",
  semanticDigest: "a".repeat(64), action: "request_stop", targetId: "runtime.agentd",
  reason: "Maintenance", sessionId: "session-1", connectionGeneration: 1,
  generation: 7, displayedRevision: 12, snapshotDigest: "b".repeat(64),
  state: "submitting", createdAt: 1, updatedAt: 1, auditTraceId: null,
});
const config = (storage = new Storage(), locks = new Locks()) => ({
  storage, locks, endpoint: "https://console.test/api/ui-control/v1/",
  identityId: "operator-1", protocolVersion: "hepta.ui-control.v1",
});
const records = storage => [...storage.values].filter(([key]) => key.startsWith("hepta.ui-control.scoped-recovery.v2:"));
const directory = storage => [...storage.values].find(([key]) => key.startsWith("hepta.ui-control.scoped-recovery-directory.v1:"));

test("initialization creates one empty scope directory", async () => {
  const options = config();
  const store = await ScopedRecoveryStore.create(options);
  assert.equal(records(options.storage).length, 0);
  assert.ok(directory(options.storage));
  assert.deepEqual(store.diagnostics(), {
    schema: "hepta.ui-control.scoped-recovery-directory.v1",
    entries: 0,
    maxEntries: 1024,
    states: { ready: 0, reserving: 0, removing: 0 },
    migrationScans: 1,
    migrationKeys: 0,
  });
});

test("steady state ignores unrelated origin inventory", async () => {
  const options = config();
  const store = await ScopedRecoveryStore.create(options);
  const baseline = options.storage.enumerations;
  for (let i = 0; i < 20000; i += 1) options.storage.setItem(`unrelated-${i}`, "x");
  await store.prepare(op());
  assert.equal(store.load().operations.length, 1);
  await store.complete({ ...op(), state: "terminal" });
  assert.equal(store.load().operations.length, 0);
  assert.equal(options.storage.enumerations, baseline);
  assert.equal(records(options.storage).length, 0);
});

test("legacy records migrate once and later opens do not enumerate origin", async () => {
  const options = config();
  const first = await ScopedRecoveryStore.create(options);
  await first.prepare(op());
  const [directoryKey] = directory(options.storage);
  options.storage.values.delete(directoryKey);
  const before = options.storage.enumerations;
  const migrated = await ScopedRecoveryStore.create(options);
  assert.equal(migrated.load().operations[0].operationId, "op-1");
  assert.ok(options.storage.enumerations > before);
  const after = options.storage.enumerations;
  const reopened = await ScopedRecoveryStore.create(options);
  assert.equal(reopened.load().operations[0].operationId, "op-1");
  assert.equal(options.storage.enumerations, after);
});

test("first migration remains bounded", async () => {
  const options = config();
  for (let i = 0; i < 16385; i += 1) options.storage.setItem(`unrelated-${i}`, "x");
  await assert.rejects(ScopedRecoveryStore.create(options), error =>
    error.code === "UI_CONTROL_STORAGE" &&
    error.details.storageReason === "migration_inventory_exceeded");
  assert.equal(options.storage.enumerations, 0);
});

test("failed record write is repaired without becoming recoverable", async () => {
  const options = config();
  const store = await ScopedRecoveryStore.create(options);
  const original = options.storage.setItem.bind(options.storage);
  options.storage.setItem = (key, value) => {
    if (key.startsWith("hepta.ui-control.scoped-recovery.v2:")) throw new Error("denied");
    original(key, value);
  };
  await assert.rejects(store.prepare(op()), error =>
    error.code === "UI_CONTROL_STORAGE" && error.details.requestDispatched === false);
  options.storage.setItem = original;
  assert.equal(store.load().operations.length, 0);
  const reopened = await ScopedRecoveryStore.create(options);
  assert.equal(reopened.load().operations.length, 0);
  assert.equal(records(options.storage).length, 0);
  assert.equal(reopened.diagnostics().entries, 0);
});

test("failed directory finalization removes an unadmitted reservation on reopen", async () => {
  const options = config();
  const store = await ScopedRecoveryStore.create(options);
  const original = options.storage.setItem.bind(options.storage);
  let directoryWrites = 0;
  options.storage.setItem = (key, value) => {
    if (key.startsWith("hepta.ui-control.scoped-recovery-directory.v1:")) {
      directoryWrites += 1;
      if (directoryWrites === 2) throw new Error("directory denied");
    }
    original(key, value);
  };
  await assert.rejects(store.prepare(op()), { code: "UI_CONTROL_STORAGE" });
  options.storage.setItem = original;
  assert.equal(records(options.storage).length, 1);
  const reopened = await ScopedRecoveryStore.create(options);
  assert.equal(records(options.storage).length, 0);
  assert.equal(reopened.load().operations.length, 0);
});

test("failed removal is restored to ready and remains recoverable", async () => {
  const options = config();
  const store = await ScopedRecoveryStore.create(options);
  await store.prepare(op());
  const original = options.storage.removeItem.bind(options.storage);
  options.storage.removeItem = () => {};
  await assert.rejects(store.complete({ ...op(), state: "terminal" }), error =>
    error.details.storageReason === "record_remove_readback_failed");
  options.storage.removeItem = original;
  const reopened = await ScopedRecoveryStore.create(options);
  assert.equal(reopened.load().operations[0].operationId, "op-1");
  assert.equal(await reopened.complete({ ...op(), state: "terminal" }), true);
  assert.equal(records(options.storage).length, 0);
});

test("corrupt directory and corrupt records are retained", async () => {
  const options = config();
  const store = await ScopedRecoveryStore.create(options);
  await store.prepare(op());
  const [recordKey] = records(options.storage)[0];
  options.storage.setItem(recordKey, "broken");
  assert.throws(() => store.load(), error => error.details.storageReason === "record_corrupt");
  assert.equal(options.storage.getItem(recordKey), "broken");
  const [directoryKey] = directory(options.storage);
  options.storage.setItem(directoryKey, "broken");
  await assert.rejects(ScopedRecoveryStore.create(options), error =>
    error.details.storageReason === "directory_corrupt");
  assert.equal(options.storage.getItem(directoryKey), "broken");
});

test("two tabs share exact directory and admit one identical identity", async () => {
  const options = config();
  const one = await ScopedRecoveryStore.create(options);
  const two = await ScopedRecoveryStore.create(options);
  const result = await Promise.allSettled([one.prepare(op()), two.prepare(op())]);
  assert.equal(result.filter(x => x.status === "fulfilled").length, 1);
  assert.equal(result.find(x => x.status === "rejected").reason.code,
    "UI_CONTROL_AMBIGUOUS_SUBMISSION");
  assert.equal(records(options.storage).length, 1);
  assert.equal(one.diagnostics().entries, 1);
});

test("a ready marker written before a reported failure remains conservatively recoverable", async () => {
  const options = config();
  const store = await ScopedRecoveryStore.create(options);
  const original = options.storage.setItem.bind(options.storage);
  let directoryWrites = 0;
  options.storage.setItem = (key, value) => {
    original(key, value);
    if (key.startsWith("hepta.ui-control.scoped-recovery-directory.v1:")) {
      directoryWrites += 1;
      if (directoryWrites === 2) throw new Error("readback channel failed");
    }
  };
  await assert.rejects(store.prepare(op()), { code: "UI_CONTROL_STORAGE" });
  options.storage.setItem = original;
  const reopened = await ScopedRecoveryStore.create(options);
  assert.equal(reopened.load().operations[0].operationId, "op-1");
});

test("an existing unindexed record stays ambiguous when directory repair fails", async () => {
  const options = config();
  const store = await ScopedRecoveryStore.create(options);
  await store.prepare(op());
  const [directoryKey, raw] = directory(options.storage);
  const value = JSON.parse(raw); value.entries = [];
  options.storage.setItem(directoryKey, JSON.stringify(value));
  const original = options.storage.setItem.bind(options.storage);
  options.storage.setItem = (key, next) => {
    if (key === directoryKey) throw new Error("repair denied");
    original(key, next);
  };
  await assert.rejects(store.prepare(op()), error =>
    error.code === "UI_CONTROL_AMBIGUOUS_SUBMISSION" &&
    error.details.requestDispatched === true &&
    error.details.storageReason === "directory_write_failed");
  assert.equal(records(options.storage).length, 1);
});

test("an unindexed terminal record can be removed while the directory is full", async () => {
  const options = { ...config(), maxEntries: 1 };
  const store = await ScopedRecoveryStore.create(options);
  await store.prepare(op("indexed"));
  const [recordKey, recordRaw] = records(options.storage)[0];
  const prefix = recordKey.slice(0, -"indexed".length);
  const legacy = op("legacy");
  const envelope = JSON.parse(recordRaw); envelope.operation = legacy;
  options.storage.setItem(`${prefix}legacy`, JSON.stringify(envelope));
  assert.equal(await store.complete({ ...legacy, state: "terminal" }), true);
  assert.equal(options.storage.getItem(`${prefix}legacy`), null);
  assert.equal(store.load().operations[0].operationId, "indexed");
});
