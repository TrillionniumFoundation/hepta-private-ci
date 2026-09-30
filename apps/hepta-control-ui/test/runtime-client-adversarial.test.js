import assert from "node:assert/strict";
import test from "node:test";
import { RuntimeClient, UI_CONTROL_ERROR_CODES as C } from "../src/index.js";
import { createTransport, deferred, session, snapshot, DIGEST_C } from "./helpers.js";

const input = () => ({ operationId: "audit-operation", action: "request_reconcile",
  targetId: "runtime.agentd", displayedRevision: 11, reason: "Inspect recovery." });

async function ready(overrides = {}, options = {}) {
  const transport = createTransport(overrides);
  const client = new RuntimeClient({ transport, ...options });
  await client.connect({ endpoint: "fixture" });
  await client.refreshView();
  return { client, transport };
}

for (const status of ["pending", "succeeded"]) {
  for (const trace of [undefined, "audit-replacement"]) {
    test(`lookup preserves the admitted audit identity for ${status} with ${trace ?? "missing trace"}`, async () => {
      const { client, transport } = await ready();
      const accepted = await client.submitRequest(input());
      transport.state.operations.set(accepted.operationId, {
        found: true, operationId: accepted.operationId, semanticDigest: accepted.semanticDigest,
        status, ...(trace ? { auditTraceId: trace } : {}), outcomeDigest: DIGEST_C,
      });
      await assert.rejects(client.recoverOperation(accepted.operationId), error => error.code === C.ACK_MISMATCH);
      assert.equal(client.readView().pending[0].auditTraceId, accepted.auditTraceId);
      assert.equal(client.readView().completedCount, 0);
      assert.equal(transport.state.requestCount, 1);
    });
  }
}

test("direct terminal reconciliation rejects an audit identity substitution", async () => {
  const { client } = await ready();
  const accepted = await client.submitRequest(input());
  assert.throws(() => client.reconcile({ operationId: accepted.operationId,
    semanticDigest: accepted.semanticDigest, status: "succeeded", terminalObserved: true,
    auditTraceId: "audit-replacement", outcomeDigest: DIGEST_C }), error => error.code === C.ACK_MISMATCH);
  assert.equal(client.readView().pendingCount, 1);
});

test("a failed snapshot refresh disables mutation until a new snapshot is observed", async () => {
  const { client, transport } = await ready();
  transport.readSnapshot = async () => { throw new Error("connection lost"); };
  await assert.rejects(client.refreshView());
  assert.equal(client.readView().stale, true);
  await assert.rejects(client.submitRequest(input()), error => error.code === C.STALE_REVISION);
  assert.equal(transport.state.requestCount, 0);
  await client.applySnapshot(snapshot());
  assert.equal(client.readView().stale, false);
});

test("readView fences expiry without waiting for a poll or an operator action", async () => {
  let now = 1000;
  const { client } = await ready({ connect: async () => session({ expiresAt: 2000 }) }, { clock: () => now });
  now = 2000;
  const view = client.readView();
  assert.equal(view.connected, false);
  assert.equal(view.stale, true);
  assert.equal(view.snapshot, null);
  assert.deepEqual(view.permissions, []);
});

test("restoring recovery cannot erase a live submission reservation", async () => {
  const dispatched = deferred();
  const response = deferred();
  const { client } = await ready({ async request(method, request) {
    dispatched.resolve();
    await response.promise;
    return { accepted: true, operationId: request.operationId, semanticDigest: request.semanticDigest,
      status: "accepted", auditTraceId: "audit-live" };
  } });
  const submitting = client.submitRequest(input());
  await dispatched.promise;
  try {
    client.restoreRecoveryState({ schema: "hepta.ui-control.recovery-state.v1", operations: [] });
    assert.equal(client.readView().pendingCount, 1);
  } finally { response.resolve(); await submitting; }
});

test("restoring an older recovery image cannot resurrect a completed operation", async () => {
  const { client } = await ready();
  const accepted = await client.submitRequest(input());
  const oldState = client.exportRecoveryState();
  client.reconcile({ operationId: accepted.operationId, semanticDigest: accepted.semanticDigest,
    status: "succeeded", terminalObserved: true, auditTraceId: accepted.auditTraceId, outcomeDigest: DIGEST_C });
  client.restoreRecoveryState(oldState);
  assert.equal(client.readView().pendingCount, 0);
  assert.equal(client.readView().completedCount, 1);
});

test("snapshot validation does not invoke accessor-shaped backend fields", async () => {
  const { client } = await ready();
  let reads = 0;
  const hostile = { ...snapshot(), get semanticDigest() { reads += 1; return undefined; } };
  await assert.rejects(client.applySnapshot(hostile), error => error.code === C.INVALID_INPUT);
  assert.equal(reads, 0);
  assert.equal(client.readView().stale, true);
});

test("module-array accessors are rejected before snapshot projection", async () => {
  const { client } = await ready();
  let reads = 0;
  const modules = [];
  Object.defineProperty(modules, "0", { enumerable: true, get() { reads += 1; return snapshot().modules[0]; } });
  await assert.rejects(client.applySnapshot(snapshot({ modules })), error => error.code === C.INVALID_INPUT);
  assert.equal(reads, 0);
});

test("the documented 1000-module ceiling is accepted on projection and snapshot paths", async () => {
  const { client } = await ready();
  const modules = Array.from({ length: 1000 }, (_, index) => ({ ...snapshot().modules[0], id: `module-${index}` }));
  const view = await client.applySnapshot(snapshot({ revision: 12, modules }));
  assert.equal(view.snapshot.modules.length, 1000);
  await assert.rejects(client.applySnapshot(snapshot({ revision: 13, modules: [...modules, modules[0]] })),
    error => error.code === C.INVALID_INPUT);
});

test("recovery import joins identical pending work and rejects conflicts atomically", async () => {
  const { client, transport } = await ready();
  await client.submitRequest(input());
  const state = client.exportRecoveryState();
  client.restoreRecoveryState(state);
  assert.equal(client.readView().pending[0].state, "pending");
  assert.throws(() => client.restoreRecoveryState({ ...state,
    operations: [{ ...state.operations[0], reason: "Different semantics" }] }),
    error => error.code === C.OPERATION_CONFLICT);
  const duplicate = await client.submitRequest(input());
  assert.equal(duplicate.state, "pending");
  assert.equal(transport.state.requestCount, 1);
});

test("recovery import enforces combined capacity without losing existing identities", async () => {
  const { client } = await ready({}, { maxPending: 1 });
  await client.submitRequest(input());
  const state = client.exportRecoveryState();
  assert.throws(() => client.restoreRecoveryState({ ...state,
    operations: [{ ...state.operations[0], operationId: "second-operation" }] }),
    error => error.code === C.PENDING_LIMIT);
  assert.equal(client.readView().pending[0].operationId, "audit-operation");
});

test("a second tab cannot erase recovery while admission is delayed behind lookup", async () => {
  const { ScopedRecoveryStore } = await import("../src/recovery-store.js");
  const { storageOptions } = await import("./browser-fixture.js");
  const store = await ScopedRecoveryStore.create(storageOptions());
  const { client, transport } = await ready();
  client.setRecoveryPersistence((record, options) => store.prepare(record, options));
  const entered = deferred();
  const admit = deferred();
  const original = transport.request;
  transport.request = async (method, request) => { entered.resolve(); await admit.promise; return original(method, request); };
  const submitting = client.submitRequest(input());
  await entered.promise;
  const other = new RuntimeClient({ transport });
  await other.connect({ endpoint: "fixture" });
  other.restoreRecoveryState(store.load());
  try {
    const missing = await other.recoverOperation("audit-operation");
    assert.equal(missing.state, "indeterminate");
    assert.equal(missing.terminalStatus, null);
    assert.equal(await store.complete(missing), false);
    assert.equal(store.load().operations.length, 1);
  } finally { admit.resolve(); await submitting; }
  const recovered = await other.recoverOperation("audit-operation");
  assert.equal(recovered.state, "pending");
  assert.equal(transport.state.requestCount, 1);
});

test("failed refresh retains the generation/revision fence for the next snapshot", async () => {
  const { client, transport } = await ready();
  transport.readSnapshot = async () => { throw new Error("Lost refresh"); };
  await assert.rejects(client.refreshView());
  await assert.rejects(client.applySnapshot(snapshot({ revision: 10 })), error => error.code === C.STALE_REVISION);
  assert.equal(client.readView().stale, true);
  await client.applySnapshot(snapshot({ revision: 12 }));
  assert.equal(client.readView().snapshot.revision, 12);
});

test("projection does not execute an inherited array mapping hook", async () => {
  const { projectRuntime } = await import("../src/control.js");
  let calls = 0;
  class Modules extends Array { map() { calls += 1; return []; } }
  const modules = new Modules(...snapshot().modules);
  const projected = projectRuntime({ generation: 7, revision: 11, modules });
  assert.equal(calls, 0);
  assert.equal(projected.modules.length, 2);
});

test("session permission accessors are rejected without executing them", async () => {
  let reads = 0;
  const permissions = [];
  Object.defineProperty(permissions, "0", { enumerable: true,
    get() { reads += 1; return "hepta://ui.control/runtime.read"; } });
  const client = new RuntimeClient({ transport: createTransport({ connect: async () => session({ permissions }) }) });
  await assert.rejects(client.connect({}), error => error.code === C.INVALID_INPUT);
  assert.equal(reads, 0);
  assert.equal(client.readView().connected, false);
});
