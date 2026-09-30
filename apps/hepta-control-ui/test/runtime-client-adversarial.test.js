import assert from "node:assert/strict";
import test from "node:test";
import { RuntimeClient, SameOriginHttpTransport, UI_CONTROL_ERROR_CODES as C } from "../src/index.js";
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

for (const method of ["requestStart", "requestStop"]) {
  test(`operation wrappers reject accessors before ${method} copies input`, async () => {
    const { client, transport } = await ready();
    let reads = 0;
    const hostile = { ...input(), get reason() { reads += 1; return "Copied getter."; } };
    await assert.rejects(client[method](hostile), error => error.code === C.INVALID_INPUT);
    assert.equal(reads, 0);
    assert.equal(transport.state.requestCount, 0);
  });
}

test("recovery arrays reject accessors without executing them", async () => {
  const { client } = await ready();
  await client.submitRequest(input());
  const saved = client.exportRecoveryState();
  let reads = 0;
  const operations = [];
  Object.defineProperty(operations, "0", { enumerable: true,
    get() { reads += 1; return saved.operations[0]; } });
  assert.throws(() => client.restoreRecoveryState({ ...saved, operations }), error => error.code === C.INVALID_INPUT);
  assert.equal(reads, 0);
  assert.equal(client.readView().pendingCount, 1);
});

test("recovery arrays cannot substitute an inherited iteration hook", async () => {
  const { client } = await ready();
  await client.submitRequest(input());
  const saved = client.exportRecoveryState();
  let calls = 0;
  class Operations extends Array { *[Symbol.iterator]() { calls += 1; } }
  const recovering = new RuntimeClient({ transport: createTransport() });
  const view = recovering.restoreRecoveryState({ ...saved,
    operations: new Operations(saved.operations[0]) });
  assert.equal(calls, 0);
  assert.equal(view.pendingCount, 1);
});

test("recovery validation accepts the supported 4096-operation capacity", async () => {
  const { client } = await ready();
  await client.submitRequest(input());
  const saved = client.exportRecoveryState();
  const operations = Array.from({ length: 4096 }, (_, index) =>
    ({ ...saved.operations[0], operationId: `restored-${index}` }));
  const recovering = new RuntimeClient({ transport: createTransport(), maxPending: 4096 });
  assert.equal(recovering.restoreRecoveryState({ ...saved, operations }).pendingCount, 4096);
});

test("acknowledgement accessors cannot trigger premature recovery cleanup", async () => {
  const { client, transport } = await ready();
  let reads = 0;
  let discarded = 0;
  client.setRecoveryPersistence(async () => ({ discardRejected() { discarded += 1; } }));
  const original = transport.request;
  transport.request = async (...args) => {
    const accepted = await original(...args);
    return { ...accepted, get accepted() { reads += 1; return false; } };
  };
  await assert.rejects(client.submitRequest(input()), error => error.code === C.AMBIGUOUS_SUBMISSION);
  assert.equal(reads, 0);
  assert.equal(discarded, 0);
  assert.equal(client.readView().pendingCount, 1);
  assert.equal((await client.recoverOperation("audit-operation")).state, "pending");
  assert.equal(transport.state.requestCount, 1);
});

for (const field of ["sessionId", "permissions"]) {
  test(`invalid session ${field} accessors never reach cleanup callbacks`, async () => {
    let reads = 0;
    let closed = 0;
    const raw = session();
    if (field === "sessionId") Object.defineProperty(raw, "sessionId", {
      enumerable: true, get() { reads += 1; return "unsafe-session"; },
    });
    else {
      raw.permissions = [];
      Object.defineProperty(raw.permissions, "0", { enumerable: true,
        get() { reads += 1; return "hepta://ui.control/runtime.read"; } });
    }
    const transport = createTransport({ connect: async () => raw,
      async close(value) { closed += 1; void value.sessionId; void value.permissions[0]; } });
    const client = new RuntimeClient({ transport });
    await assert.rejects(client.connect({}), error => error.code === C.INVALID_INPUT);
    assert.equal(reads, 0);
    assert.equal(closed, 0);
    assert.equal(client.readView().connected, false);
  });
}

test("operation digest input is captured before asynchronous hashing", async () => {
  const { client } = await ready();
  const mutable = input();
  let reads = 0;
  const submitted = client.submitRequest(mutable);
  Object.defineProperty(mutable, "semanticDigest", { enumerable: true,
    get() { reads += 1; return undefined; } });
  const accepted = await submitted;
  assert.equal(accepted.state, "pending");
  assert.equal(reads, 0);
});

test("a rejection outcome stays immutable while recovery cleanup awaits", async () => {
  let acknowledgement;
  const { client } = await ready({ async request(method, request) {
    acknowledgement = { accepted: false, operationId: request.operationId,
      semanticDigest: request.semanticDigest, status: "accepted", auditTraceId: "audit-unadmitted" };
    return acknowledgement;
  } });
  client.setRecoveryPersistence(async () => ({ async discardRejected() {
    acknowledgement.accepted = true;
  } }));
  await assert.rejects(client.submitRequest(input()), error => error.code === C.BACKEND_REJECTED);
  assert.equal(client.readView().pendingCount, 0);
});

async function switchIdentity(client, transport, identityId) {
  await client.close();
  transport.state.session = session({ identityId, sessionId: `session-${identityId}` });
  transport.state.snapshot = snapshot({ sessionId: `session-${identityId}` });
  await client.connect({});
  await client.refreshView();
}

test("another principal cannot view, export or automatically query retained operations", async () => {
  const { client, transport } = await ready();
  const admitted = await client.submitRequest(input());
  await switchIdentity(client, transport, "operator-2");
  assert.equal(client.readView().pendingCount, 0);
  assert.equal(client.exportRecoveryState().operations.length, 0);
  assert.deepEqual(await client.recoverPending(), []);
  await assert.rejects(client.recoverOperation(admitted.operationId), { code: C.INVALID_INPUT });
  assert.equal(transport.state.lookupCount, 0);
  await switchIdentity(client, transport, "operator-1");
  assert.equal(client.readView().pending[0].auditTraceId, admitted.auditTraceId);
  assert.equal((await client.recoverOperation(admitted.operationId)).state, "pending");
});

test("completed history stays scoped when the authenticated principal changes", async () => {
  const { client, transport } = await ready();
  const admitted = await client.submitRequest(input());
  const terminal = { operationId: admitted.operationId, semanticDigest: admitted.semanticDigest,
    status: "succeeded", terminalObserved: true, auditTraceId: admitted.auditTraceId };
  client.reconcile(terminal);
  await switchIdentity(client, transport, "operator-2");
  assert.equal(client.readView().completedCount, 0);
  assert.throws(() => client.reconcile(terminal), { code: C.INVALID_INPUT });
  await switchIdentity(client, transport, "operator-1");
  assert.equal(client.readView().completed[0].terminalStatus, "succeeded");
});

test("a late acknowledgement remains with its original principal after a switch", async () => {
  const dispatched = deferred();
  const released = deferred();
  const { client, transport } = await ready({ async request(method, request) {
    dispatched.resolve();
    await released.promise;
    return { accepted: true, operationId: request.operationId, semanticDigest: request.semanticDigest,
      status: "accepted", auditTraceId: "audit-original-principal" };
  } });
  const submitting = client.submitRequest(input());
  await dispatched.promise;
  try {
    await switchIdentity(client, transport, "operator-2");
    client.restoreRecoveryState({ schema: "hepta.ui-control.recovery-state.v1", operations: [] });
  } finally { released.resolve(); await submitting; }
  assert.equal(client.readView().pendingCount, 0);
  await switchIdentity(client, transport, "operator-1");
  assert.equal(client.readView().pending[0].auditTraceId, "audit-original-principal");
});

test("principal switching cannot bypass the shared pending capacity", async () => {
  const { client, transport } = await ready({}, { maxPending: 1 });
  await client.submitRequest(input());
  await switchIdentity(client, transport, "operator-2");
  assert.equal(client.readView().pendingCount, 0);
  await assert.rejects(client.submitRequest({ ...input(), operationId: "other-principal-operation" }),
    { code: C.PENDING_LIMIT });
  assert.equal(transport.state.requestCount, 1);
  await switchIdentity(client, transport, "operator-1");
  assert.equal(client.readView().pendingCount, 1);
});

test("a reused session envelope cannot expose another principal's duplicate reservation", async () => {
  const { client, transport } = await ready();
  await client.submitRequest(input());
  await client.close();
  transport.state.session = session({ identityId: "operator-2" });
  await client.connect({});
  await client.refreshView();
  await assert.rejects(client.submitRequest(input()), { code: C.OPERATION_CONFLICT });
  assert.equal(client.readView().pendingCount, 0);
  assert.equal(transport.state.requestCount, 1);
});

test("an import cannot reassign a retained operation to another principal", async () => {
  const { client, transport } = await ready();
  await client.submitRequest(input());
  const originalScope = client.exportRecoveryState();
  await switchIdentity(client, transport, "operator-2");
  assert.throws(() => client.restoreRecoveryState(originalScope), { code: C.OPERATION_CONFLICT });
  assert.equal(client.readView().pendingCount, 0);
  await switchIdentity(client, transport, "operator-1");
  assert.deepEqual(client.exportRecoveryState(), originalScope);
});

test("actual HTTP preflight failure retires only the unsent recovery reservation", async () => {
  let csrf = "csrf-valid";
  let sent = 0;
  let discarded = 0;
  const transport = new SameOriginHttpTransport({ origin: "https://control.example",
    csrfTokenProvider: () => csrf, fetchImpl: async url => {
      const path = new URL(url).pathname;
      if (path.endsWith("/operations")) sent += 1;
      return new Response(JSON.stringify(path.endsWith("/session/connect") ? session() : snapshot()),
        { headers: { "content-type": "application/json" } });
    } });
  const client = new RuntimeClient({ transport });
  await client.connect({});
  await client.refreshView();
  client.setRecoveryPersistence(async () => ({ discardRejected() { discarded += 1; } }));
  csrf = "csrf\ninvalid";
  await assert.rejects(client.submitRequest(input()), { code: C.INVALID_INPUT });
  assert.equal(sent, 0);
  assert.equal(discarded, 1);
  assert.equal(client.readView().pendingCount, 0);
});
