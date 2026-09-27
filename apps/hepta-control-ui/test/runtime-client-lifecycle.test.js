import assert from "node:assert/strict";
import test from "node:test";
import {
  RuntimeClient,
  SessionProvider,
  UI_CONTROL_ERROR_CODES,
  UiControlError,
} from "../src/index.js";
import {
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

function operation(overrides = {}) {
  return {
    operationId: "operation-session-boundary",
    action: "request_reconcile",
    targetId: "runtime.agentd",
    displayedRevision: 11,
    reason: "Reconcile the degraded worker.",
    ...overrides,
  };
}

test("concurrent connect calls share one transport attempt and reconnect fails closed", async () => {
  const gate = deferred();
  let connectCount = 0;
  const transport = createTransport({
    async connect() {
      connectCount += 1;
      await gate.promise;
      return session();
    },
  });
  const client = new RuntimeClient({ transport });

  const first = client.connect({ endpoint: "fixture" });
  const second = client.connect({ endpoint: "fixture" });
  await waitFor(() => connectCount === 1, "shared connection dispatch");
  gate.resolve();

  const [one, two] = await Promise.all([first, second]);
  assert.equal(one.connected, true);
  assert.equal(two.connected, true);
  assert.equal(connectCount, 1);

  await assert.rejects(
    client.connect({ endpoint: "different" }),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.ALREADY_CONNECTED,
  );
});

test("close during connect prevents a late session from becoming authoritative", async () => {
  const gate = deferred();
  let closeCount = 0;
  const transport = createTransport({
    async connect() {
      return gate.promise;
    },
    async close() {
      closeCount += 1;
    },
  });
  const client = new RuntimeClient({ transport });

  const connecting = client.connect({ endpoint: "fixture" });
  await client.close();
  gate.resolve(session());

  await assert.rejects(
    connecting,
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.ABORTED,
  );
  assert.equal(closeCount, 1);
  assert.equal(client.readView().connected, false);
  assert.equal(client.readView().stale, true);
});

test("invalid authenticated sessions are cleaned up and cannot omit operator identity", async () => {
  let closeCount = 0;
  const transport = createTransport({
    async connect() {
      return session({ identityId: undefined });
    },
    async close() {
      closeCount += 1;
    },
  });
  const client = new RuntimeClient({ transport });

  await assert.rejects(
    client.connect({ endpoint: "fixture" }),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.INVALID_INPUT,
  );
  assert.equal(closeCount, 1);
  assert.equal(client.readView().connected, false);
});

test("asynchronous snapshot verification cannot write through a closed session", { concurrency: false }, async t => {
  const transport = createTransport();
  const client = new RuntimeClient({ transport });
  await client.connect({ endpoint: "fixture" });

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

  const applying = client.applySnapshot(snapshot());
  await waitFor(() => digestBlocked, "snapshot semantic digest");
  await client.close();
  gate.resolve();

  await assert.rejects(
    applying,
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.STALE_GENERATION,
  );
  assert.equal(client.readView().connected, false);
  assert.equal(client.readView().snapshot, null);
});

test("operation ids cannot be rebound across authenticated sessions", async () => {
  const transport = createTransport();
  const client = new RuntimeClient({ transport });
  await client.connect({ endpoint: "fixture" });
  await client.refreshView();
  await client.submitRequest(operation());
  assert.equal(transport.state.requestCount, 1);

  await client.close();
  transport.state.session = session({
    sessionId: "session-2",
    connectionGeneration: 2,
  });
  transport.state.snapshot = snapshot({
    sessionId: "session-2",
    connectionGeneration: 2,
  });
  await client.connect({ endpoint: "fixture-2" });
  await client.refreshView();

  await assert.rejects(
    client.submitRequest(operation()),
    error =>
      error instanceof UiControlError &&
      error.code === UI_CONTROL_ERROR_CODES.OPERATION_CONFLICT,
  );
  assert.equal(transport.state.requestCount, 1);
});

test("concurrent session-provider starts share one connection without self-closing", async () => {
  const gate = deferred();
  let connectCount = 0;
  let closeCount = 0;
  const transport = createTransport({
    async connect() {
      connectCount += 1;
      await gate.promise;
      return session();
    },
    async close() {
      closeCount += 1;
    },
  });
  const client = new RuntimeClient({ transport });
  const provider = new SessionProvider({
    client,
    endpointManifest: { endpoint: "fixture" },
  });

  const first = provider.start();
  const second = provider.start();
  await waitFor(() => connectCount === 1, "provider connection dispatch");
  gate.resolve();

  const [one, two] = await Promise.all([first, second]);
  assert.equal(one.connected, true);
  assert.equal(two.connected, true);
  assert.equal(client.readView().connected, true);
  assert.equal(connectCount, 1);
  assert.equal(closeCount, 0);
  provider.stop();
});
