import assert from "node:assert/strict";
import test from "node:test";
import {
  RuntimeClient,
  UI_CONTROL_ERROR_CODES,
  UiControlError,
} from "../src/index.js";
import {
  DIGEST_C,
  createTransport,
  deferred,
  session,
  snapshot,
} from "./helpers.js";

async function waitFor(predicate, label) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 1));
  }
  throw new Error(`timed out waiting for ${label}`);
}

async function connectedClient(options = {}) {
  const transport = options.transport ?? createTransport();
  const client = new RuntimeClient({ transport, maxPending: options.maxPending ?? 1024 });
  await client.connect({ endpoint: "fixture" });
  await client.refreshView();
  return { client, transport };
}

function operation(overrides = {}) {
  return {
    operationId: "operation-1",
    action: "request_reconcile",
    targetId: "runtime.agentd",
    displayedRevision: 11,
    reason: "Reconcile the degraded worker.",
    ...overrides,
  };
}

test("client connects, applies a coherent view, submits, and terminally reconciles", async () => {
  const { client } = await connectedClient();
  const view = client.readView();
  assert.equal(view.stale, false);
  assert.equal(view.snapshot.revision, 11);

  const accepted = await client.submitRequest(operation());
  assert.equal(accepted.state, "pending");
  assert.equal(accepted.authorityGranted, false);
  assert.equal(client.readView().pendingCount, 1);

  const terminal = client.reconcile({
    operationId: accepted.operationId,
    semanticDigest: accepted.semanticDigest,
    status: "succeeded",
    terminalObserved: true,
    auditTraceId: accepted.auditTraceId,
    outcomeDigest: DIGEST_C,
  });
  assert.equal(terminal.terminalStatus, "succeeded");
  assert.equal(client.readView().pendingCount, 0);

  const duplicate = await client.submitRequest(operation());
  assert.equal(duplicate.terminalStatus, "succeeded");
});

test("same concurrent operation shares one in-flight request", async () => {
  const gate = deferred();
  const transport = createTransport({
    async request(method, input) {
      transport.state.requestCount += 1;
      await gate.promise;
      return {
        accepted: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        status: "accepted",
        auditTraceId: "audit-shared",
      };
    },
  });
  const { client } = await connectedClient({ transport });
  const first = client.submitRequest(operation());
  const second = client.submitRequest(operation());
  await waitFor(() => transport.state.requestCount === 1, "shared request dispatch");
  assert.equal(transport.state.requestCount, 1);
  gate.resolve();
  const [one, two] = await Promise.all([first, second]);
  assert.deepEqual(one, two);
});

test("pending capacity is reserved before transport awaits", async () => {
  const gate = deferred();
  const transport = createTransport({
    async request(method, input) {
      transport.state.requestCount += 1;
      await gate.promise;
      return {
        accepted: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        status: "accepted",
        auditTraceId: `audit-${input.operationId}`,
      };
    },
  });
  const { client } = await connectedClient({ transport, maxPending: 1 });
  const first = client.submitRequest(operation({ operationId: "operation-first" }));
  await waitFor(() => transport.state.requestCount === 1, "capacity reservation");
  await assert.rejects(
    client.submitRequest(operation({ operationId: "operation-second" })),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.PENDING_LIMIT,
  );
  assert.equal(transport.state.requestCount, 1);
  gate.resolve();
  await first;
});

test("same operation id with different semantics fails closed", async () => {
  const gate = deferred();
  const transport = createTransport({
    async request(method, input) {
      await gate.promise;
      return {
        accepted: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        status: "accepted",
        auditTraceId: "audit-conflict",
      };
    },
  });
  const { client } = await connectedClient({ transport });
  const first = client.submitRequest(operation());
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(
    client.submitRequest(operation({ reason: "Different semantic intent." })),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT,
  );
  gate.resolve();
  await first;
});

test("accepted-but-timeout remains indeterminate and lookup recovers terminal state", async () => {
  const transport = createTransport({
    async request(method, input) {
      transport.state.requestCount += 1;
      transport.state.operations.set(input.operationId, {
        found: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        status: "succeeded",
        auditTraceId: "audit-recovered",
        outcomeDigest: DIGEST_C,
      });
      throw new Error("response lost after acceptance");
    },
  });
  const { client } = await connectedClient({ transport });
  await assert.rejects(
    client.submitRequest(operation()),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.AMBIGUOUS_SUBMISSION,
  );
  assert.equal(client.readView().indeterminateCount, 1);
  const recovered = await client.recoverOperation("operation-1");
  assert.equal(recovered.terminalStatus, "succeeded");
  assert.equal(client.readView().pendingCount, 0);
  assert.equal(transport.state.lookupCount, 1);
});

test("snapshot transition allows exact replay but rejects same-revision semantic drift", async () => {
  const { client } = await connectedClient();
  const replay = await client.applySnapshot(snapshot());
  assert.equal(replay.snapshot.revision, 11);
  await assert.rejects(
    client.applySnapshot(
      snapshot({
        modules: [
          {
            id: "runtime.agentd",
            status: "quarantined",
            revision: 11,
            semanticDigest: DIGEST_C,
          },
        ],
      }),
    ),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.SNAPSHOT_DRIFT,
  );
});

test("stale displayed revisions and expired sessions are rejected", async () => {
  const { client } = await connectedClient();
  await assert.rejects(
    client.submitRequest(operation({ displayedRevision: 10 })),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.STALE_REVISION,
  );

  let now = 1000;
  const transport = createTransport();
  transport.state.session = session({ expiresAt: 2000 });
  const expiring = new RuntimeClient({ transport, clock: () => now });
  await expiring.connect({});
  await expiring.refreshView();
  now = 2001;
  await assert.rejects(
    expiring.refreshView(),
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.SESSION_EXPIRED,
  );
});

test("recovery state survives a client restart without pretending to be authority", async () => {
  const transport = createTransport({
    async request() {
      throw new Error("ambiguous network result");
    },
  });
  const { client } = await connectedClient({ transport });
  await assert.rejects(client.submitRequest(operation()));
  const recovery = client.exportRecoveryState();
  assert.equal(recovery.operations.length, 1);

  const replacement = new RuntimeClient({ transport: createTransport() });
  replacement.restoreRecoveryState(recovery);
  assert.equal(replacement.readView().pending[0].state, "indeterminate");
  assert.equal(replacement.readView().pending[0].authorityGranted, false);
});
