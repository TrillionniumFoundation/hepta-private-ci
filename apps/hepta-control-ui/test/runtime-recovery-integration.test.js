import assert from "node:assert/strict";
import test from "node:test";
import { RuntimeClient, UI_CONTROL_PERMISSIONS } from "../src/runtime-client.js";
import { ScopedRecoveryStore } from "../src/recovery-store.js";
import { captureConfirmation } from "../src/confirmation.js";
import { UI_CONTROL_ERROR_CODES as C, uiControlError } from "../src/errors.js";

function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function session() { return { authenticated: true, protocolVersion: "hepta.ui-control.v1", sessionId: "session-1",
  identityId: "operator-1", permissionRevision: 1, connectionGeneration: 1, expiresAt: Date.now() + 600000,
  permissions: Object.values(UI_CONTROL_PERMISSIONS) }; }
function snapshot(generation = 7) { return { sessionId: "session-1", connectionGeneration: 1, generation, revision: 12,
  modules: [{ id: "runtime.agentd", status: "ready", revision: 9, semanticDigest: "a".repeat(64) }] }; }
function input(id = "operation-1") { return { operationId: id, action: "request_stop", targetId: "runtime.agentd",
  reason: "Maintenance", displayedRevision: 12 }; }
function recoveryRecord(id = "operation-1") { return {
  protocolVersion: "hepta.ui-control.v1", method: "runtime/stop", operationId: id,
  semanticDigest: "c".repeat(64), action: "request_stop", targetId: "runtime.agentd",
  reason: "Maintenance", sessionId: "session-1", connectionGeneration: 1,
  generation: 7, displayedRevision: 12, snapshotDigest: "d".repeat(64),
  state: "submitting", auditTraceId: null, createdAt: 1, updatedAt: 1,
}; }
async function setup(overrides = {}) {
  const state = { calls: 0, lookups: 0, records: new Map() };
  const transport = {
    async connect() { return session(); }, async readSnapshot() { return snapshot(); }, async close() {},
    async request(method, request) {
      state.calls += 1; state.records.set(request.operationId, request);
      return { accepted: true, operationId: request.operationId, semanticDigest: request.semanticDigest,
        status: "accepted", auditTraceId: `audit-${request.operationId}` };
    },
    async lookup(request) {
      state.lookups += 1;
      return { found: true, operationId: request.operationId, semanticDigest: request.semanticDigest,
        status: "pending", auditTraceId: `audit-${request.operationId}` };
    }, ...overrides,
  };
  const client = new RuntimeClient({ transport }); await client.connect({}); await client.refreshView();
  return { client, state, transport };
}
class Storage {
  data = new Map(); get length() { return this.data.size; }
  key(i) { return [...this.data.keys()][i] ?? null; }
  getItem(k) { return this.data.get(k) ?? null; }
  setItem(k,v) { this.data.set(k,v); } removeItem(k) { this.data.delete(k); }
}
async function store(storage = new Storage()) {
  return ScopedRecoveryStore.create({ storage, locks: { request: async (_, options, run) => {
    if (options.signal?.aborted) throw options.signal.reason; return run();
  } }, endpoint: "https://console.test/api/ui-control/v1/", identityId: "operator-1", protocolVersion: "hepta.ui-control.v1" });
}

test("actual RuntimeClient rejects a stale full confirmation before any dispatch", async () => {
  const { client, state } = await setup(); const operation = input();
  const confirmation = captureConfirmation(client.readView(), operation);
  await client.applySnapshot(snapshot(8));
  await assert.rejects(client.requestStop({ ...operation, confirmation }), { code: C.STALE_REVISION });
  assert.equal(state.calls, 0);
});

test("actual dispatch sees the recovery record already persisted, before any acknowledgement", async () => {
  const recovery = await store(); const sent = deferred(); const response = deferred();
  const { client } = await setup({ async request(method, request) {
    assert.equal(recovery.load().operations[0].operationId, request.operationId);
    assert.equal(recovery.load().operations[0].state, "submitting");
    sent.resolve(request); await response.promise;
    return { accepted: true, ...request, status: "accepted", auditTraceId: "audit-held" };
  } });
  client.setRecoveryPersistence((record, options) => recovery.prepare(record, options));
  const pending = client.requestStop(input()); const request = await sent.promise;
  // Start a new client from persisted data while the old response is still held.
  const replacement = await setup(); replacement.client.restoreRecoveryState(recovery.load());
  const recovered = await replacement.client.recoverOperation(request.operationId);
  assert.equal(recovered.state, "pending"); assert.equal(replacement.state.calls, 0);
  assert.equal(replacement.state.lookups, 1);
  response.resolve(); await pending;
});

test("authenticated found:false retains an unresolved pre-dispatch crash without replay", async () => {
  let lookups = 0; const recovery = await store(); await recovery.prepare(recoveryRecord());
  const { client, state } = await setup({ async lookup() { lookups += 1; return { found: false }; } });
  client.restoreRecoveryState(recovery.load());
  const resolved = await client.recoverOperation("operation-1");
  assert.equal(resolved.state, "indeterminate"); assert.equal(resolved.terminalStatus, null);
  assert.equal(client.readView().pendingCount, 1); assert.equal(state.calls, 0); assert.equal(lookups, 1);
  assert.equal(await recovery.complete(resolved), false);
  assert.equal(recovery.load().operations.length, 1);
  assert.equal(state.calls, 0);
});

test("found:false after an accepted acknowledgement remains unresolved", async () => {
  const { client } = await setup({ async lookup() { return { found: false }; } });
  const accepted = await client.requestStop(input());
  await assert.rejects(client.recoverOperation(accepted.operationId), { code: C.ACK_MISMATCH });
  assert.equal(client.readView().pendingCount, 1); assert.equal(client.readView().completedCount, 0);
});

test("saving failure prevents real transport dispatch and retires the unsent local reservation", async () => {
  const { client, state } = await setup();
  client.setRecoveryPersistence(async () => { throw uiControlError(C.STORAGE, "denied", { details: { requestDispatched: false } }); });
  await assert.rejects(client.requestStop(input()), { code: C.STORAGE });
  assert.equal(state.calls, 0); assert.equal(client.readView().pendingCount, 0);
});

test("snapshot changes during persistence fail revalidation and discard only the unsent record", async () => {
  const { client, state } = await setup(); const recovery = await store();
  client.setRecoveryPersistence(async (record, options) => {
    const prepared = await recovery.prepare(record, options); await client.applySnapshot(snapshot(8)); return prepared;
  });
  await assert.rejects(client.requestStop(input()), { code: C.STALE_REVISION });
  assert.equal(state.calls, 0); assert.equal(recovery.load().operations.length, 0);
});

test("concurrent duplicates persist once and dispatch once", async () => {
  const { client, state } = await setup(); const recovery = await store(); let writes = 0;
  client.setRecoveryPersistence(async (record, options) => { writes += 1; return recovery.prepare(record, options); });
  const [a, b] = await Promise.all([client.requestStop(input()), client.requestStop(input())]);
  assert.equal(a.operationId, b.operationId); assert.equal(writes, 1); assert.equal(state.calls, 1);
});

test("malformed acceptance is ambiguous rather than a false definite rejection", async () => {
  const { client } = await setup({ async request() { return {}; } });
  await assert.rejects(client.requestStop(input()), { code: C.AMBIGUOUS_SUBMISSION });
  assert.equal(client.readView().indeterminateCount, 1);
});

test("explicit backend rejection discards its own prepared record", async () => {
  const { client } = await setup({ async request() { return { accepted: false, errorCode: "DENIED" }; } });
  const recovery = await store(); client.setRecoveryPersistence((record, options) => recovery.prepare(record, options));
  await assert.rejects(client.requestStop(input()), { code: C.BACKEND_REJECTED });
  assert.equal(recovery.load().operations.length, 0);
});

test("RuntimeClient fair recovery reaches beyond the first 32 and isolates a poison lookup", async () => {
  const seen = new Set(); const { client } = await setup({ async lookup(request) {
    seen.add(request.operationId); if (request.operationId === "op-000") throw new Error("unavailable");
    return { found: false };
  } });
  for (let i = 0; i < 40; i += 1) await client.requestStop(input(`op-${String(i).padStart(3,"0")}`));
  await client.recoverPending(); await client.recoverPending();
  assert.equal(seen.size, 40); assert.ok(client.readView().recoveryMetrics.failures > 0);
});

test("simultaneous recovery of one identity shares one lookup", async () => {
  const gate = deferred(); let lookups = 0; const { client } = await setup({ async lookup(request) {
    lookups += 1; await gate.promise;
    return { found: true, ...request, status: "succeeded", auditTraceId: `audit-${request.operationId}` };
  } });
  await client.requestStop(input());
  const one = client.recoverOperation("operation-1"); const two = client.recoverOperation("operation-1");
  gate.resolve(); const [a,b] = await Promise.all([one,two]);
  assert.equal(lookups, 1); assert.deepEqual(a,b); assert.equal(a.terminalStatus, "succeeded");
});

test("late nonterminal lookup cannot overwrite a terminal observation", async () => {
  const gate = deferred(); const { client } = await setup({ async lookup(request) {
    await gate.promise; return { found: true, ...request, status: "pending", auditTraceId: "audit-late" };
  } });
  const accepted = await client.requestStop(input()); const pending = client.recoverOperation(accepted.operationId);
  client.reconcile({ operationId: accepted.operationId, semanticDigest: accepted.semanticDigest,
    status: "succeeded", terminalObserved: true, auditTraceId: accepted.auditTraceId });
  gate.resolve(); assert.equal((await pending).terminalStatus, "succeeded");
  assert.equal(client.readView().pendingCount, 0);
});
