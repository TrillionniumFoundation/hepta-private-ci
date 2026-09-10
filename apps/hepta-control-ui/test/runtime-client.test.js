import assert from "node:assert/strict";
import test from "node:test";

import { RuntimeClient } from "../src/runtime-client.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);

function transport() {
  const calls = [];
  let connectionGeneration = 0;
  return {
    calls,
    async connect(input) {
      connectionGeneration += 1;
      calls.push(["connect", input]);
      return {
        authenticated: true,
        sessionId: `session.${connectionGeneration}`,
        connectionGeneration,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      calls.push([method, input]);
      return { accepted: true, ...input };
    },
    async close(input) {
      calls.push(["close", input]);
    },
  };
}

async function connected(client, sessionNumber = 1) {
  await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  client.applySnapshot({
    sessionId: `session.${sessionNumber}`,
    connectionGeneration: sessionNumber,
    generation: 7,
    revision: 9,
    digest: D2,
    modules: [{ id: "runtime.agentd", status: "ready" }],
  });
}

function terminal(acknowledgement, overrides = {}) {
  return {
    method: acknowledgement.method,
    sessionId: acknowledgement.sessionId,
    connectionGeneration: acknowledgement.connectionGeneration,
    runtimeGeneration: acknowledgement.runtimeGeneration,
    displayedRevision: acknowledgement.displayedRevision,
    snapshotDigest: acknowledgement.snapshotDigest,
    operationId: acknowledgement.operationId,
    semanticDigest: acknowledgement.semanticDigest,
    status: "succeeded",
    terminalObserved: true,
    outcomeDigest: D4,
    ...overrides,
  };
}

test("submits and reconciles a generation-bound stop request", async () => {
  const io = transport();
  const client = new RuntimeClient({ transport: io });
  await connected(client);
  const acknowledgement = await client.requestStop({
    operationId: "stop.1",
    semanticDigest: D3,
    displayedRevision: 9,
  });
  assert.equal(acknowledgement.status, "pending");
  assert.equal(acknowledgement.authorityGranted, false);
  const disposition = client.reconcile(terminal(acknowledgement));
  assert.equal(disposition.status, "succeeded");
  assert.equal(client.readView().pending, 0);
  assert.equal(io.calls.some(([method]) => method === "runtime/stop"), true);
});

test("blocks mutation from a stale view and preserves indeterminate work", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await connected(client);
  await assert.rejects(
    client.submitRequest({
      operationId: "operation.1",
      semanticDigest: D3,
      displayedRevision: 8,
    }),
    /stale/,
  );
  const acknowledgement = await client.submitRequest({
    operationId: "operation.1",
    semanticDigest: D3,
    displayedRevision: 9,
  });
  const disposition = client.reconcile(
    terminal(acknowledgement, {
      status: "indeterminate",
      terminalObserved: false,
      outcomeDigest: null,
    }),
  );
  assert.equal(disposition.status, "indeterminate");
  assert.equal(client.readView().pending, 1);
});

test("operation and stop methods cannot share one replay identity", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await connected(client);
  await client.submitRequest({
    operationId: "operation.shared",
    semanticDigest: D3,
    displayedRevision: 9,
  });
  await assert.rejects(
    client.requestStop({
      operationId: "operation.shared",
      semanticDigest: D3,
      displayedRevision: 9,
    }),
    /changed semantics/,
  );
});

test("disconnect moves pending work to a generation-bound unresolved set", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await connected(client);
  const oldAcknowledgement = await client.submitRequest({
    operationId: "operation.old",
    semanticDigest: D3,
    displayedRevision: 9,
  });
  await client.close();
  await connected(client, 2);
  assert.equal(client.readView().pending, 0);
  assert.equal(client.readView().unresolvedPreviousSessionOperations, 1);
  await assert.rejects(
    client.submitRequest({
      operationId: "operation.old",
      semanticDigest: D3,
      displayedRevision: 9,
    }),
    /unresolved previous session/,
  );
  assert.throws(
    () =>
      client.reconcile(
        terminal(oldAcknowledgement, {
          sessionId: "session.2",
          connectionGeneration: 2,
        }),
      ),
    /binding does not match/,
  );
  const resolved = client.reconcile(terminal(oldAcknowledgement));
  assert.equal(resolved.status, "succeeded");
  assert.equal(client.readView().unresolvedPreviousSessionOperations, 0);
});

test("acknowledgement and terminal observations must echo the complete binding", async () => {
  const io = transport();
  const originalRequest = io.request;
  io.request = async (method, input) => {
    const response = await originalRequest.call(io, method, input);
    return { ...response, snapshotDigest: D4 };
  };
  const client = new RuntimeClient({ transport: io });
  await connected(client);
  await assert.rejects(
    client.submitRequest({
      operationId: "operation.bad-ack",
      semanticDigest: D3,
      displayedRevision: 9,
    }),
    /acknowledgement binding mismatch/,
  );
});
