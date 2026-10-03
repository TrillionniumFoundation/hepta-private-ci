import assert from "node:assert/strict";
import test from "node:test";
import { ScopedRecoveryStore } from "../src/recovery-store.js";

class Storage {
  values = new Map();

  get length() {
    return this.values.size;
  }

  key(index) {
    return [...this.values.keys()][index] ?? null;
  }

  getItem(key) {
    return this.values.get(key) ?? null;
  }

  setItem(key, value) {
    this.values.set(key, value);
  }

  removeItem(key) {
    this.values.delete(key);
  }
}

class Locks {
  tail = Promise.resolve();

  request(_name, options, callback) {
    const work = this.tail.then(() => {
      options.signal?.throwIfAborted();
      return callback();
    });
    this.tail = work.catch(() => {});
    return work;
  }
}

const operation = {
  operationId: "op-1",
  protocolVersion: "hepta.ui.control.v1",
  method: "runtime/stop",
  semanticDigest: "a".repeat(64),
  action: "request_stop",
  targetId: "runtime.agentd",
  reason: "Maintenance",
  sessionId: "session-1",
  connectionGeneration: 1,
  generation: 7,
  displayedRevision: 12,
  snapshotDigest: "b".repeat(64),
  state: "submitting",
  createdAt: 1,
  updatedAt: 1,
  auditTraceId: null,
};

const identity = [
  operation.protocolVersion,
  operation.method,
  operation.operationId,
  operation.semanticDigest,
  operation.action,
  operation.targetId,
  operation.reason,
  operation.sessionId,
  operation.connectionGeneration,
  operation.generation,
  operation.displayedRevision,
  operation.snapshotDigest,
];

function options() {
  return {
    storage: new Storage(),
    locks: new Locks(),
    endpoint: "https://console.test/api/ui-control/v1/",
    identityId: "operator-1",
    protocolVersion: "hepta.ui-control.v1",
  };
}

function entries(storage) {
  const directory = [...storage.values].find(([key]) =>
    key.startsWith("hepta.ui-control.scoped-recovery-directory.v1:"));
  const record = [...storage.values].find(([key]) =>
    key.startsWith("hepta.ui-control.scoped-recovery.v2:"));
  return { directory, record };
}

test("a ready directory entry without its exact record fails closed", async () => {
  const config = options();
  const store = await ScopedRecoveryStore.create(config);
  await store.prepare(operation);

  const { record } = entries(config.storage);
  assert.ok(record);
  config.storage.removeItem(record[0]);

  assert.throws(
    () => store.load(),
    error =>
      error?.code === "UI_CONTROL_STORAGE" &&
      error?.details?.storageReason === "directory_record_missing",
  );

  const reopened = await ScopedRecoveryStore.create(config);
  assert.throws(
    () => reopened.load(),
    error =>
      error?.code === "UI_CONTROL_STORAGE" &&
      error?.details?.storageReason === "directory_record_missing",
  );
  assert.equal(reopened.diagnostics().entries, 1);
});

test("an unlocked load tolerates only a verified concurrent removing transition", async () => {
  const config = options();
  const store = await ScopedRecoveryStore.create(config);
  await store.prepare(operation);

  const { directory, record } = entries(config.storage);
  assert.ok(directory);
  assert.ok(record);

  const originalGet = config.storage.getItem.bind(config.storage);
  let raced = false;
  config.storage.getItem = key => {
    if (!raced && key === record[0]) {
      raced = true;
      const value = JSON.parse(originalGet(directory[0]));
      value.entries = [{
        operationId: operation.operationId,
        state: "removing",
        identity,
      }];
      config.storage.setItem(directory[0], JSON.stringify(value));
      config.storage.removeItem(record[0]);
      return null;
    }
    return originalGet(key);
  };

  assert.deepEqual(store.load(), {
    schema: "hepta.ui-control.recovery-state.v1",
    operations: [],
  });
  assert.equal(raced, true);
});
