import assert from "node:assert/strict";
import test from "node:test";

import { RuntimeClient } from "../src/runtime-client.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);

function transport() {
  const calls = [];
  return {
    calls,
    async connect(input) {
      calls.push(["connect", input]);
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      calls.push([method, input]);
      return {
        accepted: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
      };
    },
    async close(input) {
      calls.push(["close", input]);
    },
  };
}

test("submits and reconciles a generation-bound stop request", async () => {
  const io = transport();
  const client = new RuntimeClient({ transport: io });
  await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  client.applySnapshot({
    sessionId: "session.1",
    connectionGeneration: 1,
    generation: 7,
    revision: 9,
    digest: D2,
    modules: [{ id: "runtime.agentd", status: "ready" }],
  });
  const acknowledgement = await client.requestStop({
    operationId: "stop.1",
    semanticDigest: D3,
    displayedRevision: 9,
  });
  assert.equal(acknowledgement.status, "pending");
  assert.equal(acknowledgement.authorityGranted, false);
  const disposition = client.reconcile({
    operationId: "stop.1",
    semanticDigest: D3,
    status: "succeeded",
    terminalObserved: true,
    outcomeDigest: D2,
  });
  assert.equal(disposition.status, "succeeded");
  assert.equal(client.readView().pending, 0);
  assert.equal(io.calls.some(([method]) => method === "runtime/stop"), true);
});

test("blocks mutation from a stale view and preserves indeterminate work", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  client.applySnapshot({
    sessionId: "session.1",
    connectionGeneration: 1,
    generation: 1,
    revision: 2,
    digest: D2,
    modules: [],
  });
  await assert.rejects(
    client.submitRequest({
      operationId: "operation.1",
      semanticDigest: D3,
      displayedRevision: 1,
    }),
    /stale/,
  );
  await client.submitRequest({
    operationId: "operation.1",
    semanticDigest: D3,
    displayedRevision: 2,
  });
  const disposition = client.reconcile({
    operationId: "operation.1",
    semanticDigest: D3,
    status: "indeterminate",
    terminalObserved: false,
  });
  assert.equal(disposition.status, "indeterminate");
  assert.equal(client.readView().pending, 1);
});
