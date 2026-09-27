import assert from "node:assert/strict";
import test from "node:test";
import {
  RuntimeClient,
  UI_CONTROL_ERROR_CODES,
  UI_CONTROL_PERMISSIONS,
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
  assert.equal(view.identityId, "operator-1");

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
  assert.equal(client.readView().completedCount, 1);
  assert.equal(client.readView().completed[0].terminalStatus, "succeeded");

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

test("request preparation rejects a snapshot change during asynchronous digest", { concurrency: false }, async t => {
  const { client, transport } = await connectedClient();
  const subtlePrototype = Object.getPrototypeOf(globalThis.crypto.subtle);
  const originalDigest = subtlePrototype.digest;
  const gate = deferred();
  let digestBlocked = false;

  subtlePrototype.digest = async function controlledDigest(...args) {
    if (!digestBlocked) {
      digestBlocked = true;
      await gate.promise;
    }
    return originalDigest.apply(this, args);
  };
  t.after(() => {
    subtlePrototype.digest = originalDigest;
    gate.resolve();
  });

  const submission = client.submitRequest(operation());
  await waitFor(() => digestBlocked, "operation intent digest");
  await client.applySnapshot(snapshot({ revision: 12 }));
  gate.resolve();

  await assert.rejects(
    submission,
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.STALE_REVISION,
  );
  assert.equal(transport.state.requestCount, 0);
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
  assert.equal(client.readView().completed[0].operationId, "operation-1");
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

test("session refresh rejects permission revision regression", async () => {
  const transport = createTransport();
  transport.state.session = session({ permissionRevision: 2 });
  transport.refresh = async () => session({ permissionRevision: 1 });
  const client = new RuntimeClient({ transport });
  await client.connect({});
  await assert.rejects(
    client.refreshSession(),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.STALE_PERMISSION_REVISION,
  );
  assert.equal(client.readView().permissionRevision, 2);
});

test("session refresh rejects permission drift without a revision change", async () => {
  const transport = createTransport();
  transport.refresh = async () => session({
    permissionRevision: 1,
    permissions: [
      UI_CONTROL_PERMISSIONS.READ,
      UI_CONTROL_PERMISSIONS.REQUEST,
      UI_CONTROL_PERMISSIONS.START,
    ],
  });
  const client = new RuntimeClient({ transport });
  await client.connect({});
  await assert.rejects(
    client.refreshSession(),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.STALE_PERMISSION_REVISION,
  );
  assert.equal(client.readView().permissions.includes(UI_CONTROL_PERMISSIONS.STOP), true);
});

test("session refresh rejects authenticated identity drift", async () => {
  const transport = createTransport({
    async refresh() {
      return session({ permissionRevision: 2, identityId: "operator-2" });
    },
  });
  const client = new RuntimeClient({ transport });
  await client.connect({});
  await assert.rejects(
    client.refreshSession(),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.SESSION_IDENTITY_CHANGED,
  );
  assert.equal(client.readView().identityId, "operator-1");
});

test("in-flight refresh cannot resurrect a closed session", async () => {
  const gate = deferred();
  let started = false;
  const transport = createTransport({
    async refresh() {
      started = true;
      return gate.promise;
    },
  });
  const client = new RuntimeClient({ transport });
  await client.connect({});
  const refreshing = client.refreshSession();
  await waitFor(() => started, "session refresh dispatch");
  await client.close();
  gate.resolve(session({ permissionRevision: 2 }));
  await assert.rejects(
    refreshing,
    error => error instanceof UiControlError && error.code === UI_CONTROL_ERROR_CODES.STALE_GENERATION,
  );
  assert.equal(client.readView().connected, false);
});

test("revoke and close fail locally closed when transport cleanup fails", async () => {
  const revokeTransport = createTransport({
    async revoke() {
      throw new Error("revoke response lost");
    },
  });
  const revoking = new RuntimeClient({ transport: revokeTransport });
  await revoking.connect({});
  await assert.rejects(revoking.revokeSession());
  assert.equal(revoking.readView().connected, false);
  assert.equal(revoking.readView().stale, true);

  const closeTransport = createTransport({
    async close() {
      throw new Error("close response lost");
    },
  });
  const closing = new RuntimeClient({ transport: closeTransport });
  await closing.connect({});
  await assert.rejects(closing.close());
  assert.equal(closing.readView().connected, false);
  assert.equal(closing.readView().stale, true);
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
