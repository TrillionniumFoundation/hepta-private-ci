import assert from "node:assert/strict";
import test from "node:test";

import { RuntimeClient } from "../src/runtime-client.js";
import { ERROR_CODES, MAX_VIEW_BYTES, UiControlError } from "../src/protocol.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);

function moduleObservation(index = 1, extra = {}) {
  return {
    moduleId: `runtime.module.${index}`,
    status: "ready",
    revision: index,
    digest: `${(index % 9) + 1}`.repeat(64),
    ...extra,
  };
}

function makeTransport({ requestImpl, reconcileImpl } = {}) {
  const calls = [];
  let connectionGeneration = 0;
  return {
    calls,
    async connect(input) {
      calls.push(["connect", input]);
      connectionGeneration += 1;
      return {
        authenticated: true,
        sessionId: `session.${connectionGeneration}`,
        connectionGeneration,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      calls.push([method, input]);
      if (requestImpl) {
        return requestImpl(method, input, { connectionGeneration });
      }
      return {
        accepted: true,
        method,
        sessionId: input.sessionId,
        connectionGeneration: input.connectionGeneration,
        runtimeGeneration: input.runtimeGeneration,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
      };
    },
    async reconcile(input) {
      calls.push(["reconcile", input]);
      if (reconcileImpl) {
        return reconcileImpl(input, { connectionGeneration });
      }
      return null;
    },
    async close(input) {
      calls.push(["close", input]);
    },
  };
}

function displayedViewBinding({
  sessionId = "session.1",
  connectionGeneration = 1,
  generation = 7,
  revision = 9,
  digest = D2,
} = {}) {
  return Object.freeze({ sessionId, connectionGeneration, generation, revision, digest });
}

async function connectedClient(io = makeTransport()) {
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
    modules: [moduleObservation(1)],
  });
  return { client, io };
}

function terminalObservation({
  sessionId = "session.1",
  connectionGeneration = 1,
  method = "operation/request",
  operationId = "operation.1",
  semanticDigest,
  originSessionId = "session.1",
  originConnectionGeneration = 1,
  runtimeGeneration = 7,
  status = "succeeded",
} = {}) {
  return {
    sessionId,
    connectionGeneration,
    method,
    operationId,
    semanticDigest,
    originSessionId,
    originConnectionGeneration,
    runtimeGeneration,
    status,
    terminalObserved: true,
    outcomeDigest: D3,
  };
}

test("snapshot ingress projects registered safe fields before readView", async () => {
  const io = makeTransport();
  const client = new RuntimeClient({ transport: io });
  await client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });
  const original = moduleObservation(1, {
    secret: "must-not-leak",
    providerPayload: { token: "must-not-leak" },
  });
  client.applySnapshot({
    sessionId: "session.1",
    connectionGeneration: 1,
    generation: 1,
    revision: 1,
    digest: D2,
    modules: [original],
  });
  original.status = "degraded";
  original.providerPayload.token = "mutated";

  const view = client.readView();
  assert.equal(view.modules[0].status, "ready");
  assert.equal("secret" in view.modules[0], false);
  assert.equal("providerPayload" in view.modules[0], false);
  assert.equal(Object.isFrozen(view.modules), true);
  assert.equal(Object.isFrozen(view.modules[0]), true);
});

test("submitRequest transmits the proposal and computes semantic digest internally", async () => {
  const { client, io } = await connectedClient();
  const acknowledgement = await client.submitRequest({
    operationId: "operation.1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
    semanticDigest: "f".repeat(64),
  });

  assert.equal(acknowledgement.status, "pending");
  assert.equal(acknowledgement.accepted, true);
  assert.notEqual(acknowledgement.semanticDigest, "f".repeat(64));
  const [, request] = io.calls.find(([method]) => method === "operation/request");
  assert.equal(request.intent.kind, "UiOperationProposalV1");
  assert.equal(request.intent.action, "request_retry");
  assert.equal(request.intent.expectedRevision, 4);
  assert.equal(request.intent.authorityGranted, false);
  assert.equal(request.semanticDigest, acknowledgement.semanticDigest);
  assert.equal(request.schema, "hepta.ui-control.transport-request.v1");
});

test("requestStop transmits a deeply frozen scope bound into semantic digest", async () => {
  const { client, io } = await connectedClient();
  const scope = {
    target: { moduleId: "runtime.agentd", reason: "operator" },
    force: false,
  };
  const acknowledgement = await client.requestStop({
    operationId: "stop.1",
    displayedView: displayedViewBinding(),
    scope,
  });
  scope.target.moduleId = "mutated";

  const [, request] = io.calls.find(([method]) => method === "runtime/stop");
  assert.equal(Object.isFrozen(request), true);
  assert.equal(request.scope.target.moduleId, "runtime.agentd");
  assert.equal(Object.isFrozen(request.scope), true);
  assert.equal(Object.isFrozen(request.scope.target), true);
  assert.equal(request.semanticDigest, acknowledgement.semanticDigest);
});

test("changed semantics cannot reuse an operation identity", async () => {
  const { client } = await connectedClient();
  await client.submitRequest({
    operationId: "operation.1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 9,
    displayedView: displayedViewBinding(),
  });
  await assert.rejects(
    client.submitRequest({
      operationId: "operation.1",
      subjectId: "runtime.agentd",
      action: "request_rollback",
      expectedRevision: 9,
      displayedView: displayedViewBinding(),
    }),
    (error) =>
      error instanceof UiControlError && error.code === ERROR_CODES.RECONCILIATION_MISMATCH,
  );
});

test("transport ambiguity is preserved as indeterminate and reconciled after reconnect", async () => {
  let firstRequest = true;
  let captured;
  const io = makeTransport({
    requestImpl(method, input) {
      captured = { method, ...input };
      if (firstRequest) {
        firstRequest = false;
        throw new Error("response lost after backend accept");
      }
      throw new Error("unexpected retry");
    },
    reconcileImpl(input, state) {
      return terminalObservation({
        sessionId: `session.${state.connectionGeneration}`,
        connectionGeneration: state.connectionGeneration,
        method: input.method,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        originSessionId: input.originSessionId,
        originConnectionGeneration: input.originConnectionGeneration,
        runtimeGeneration: input.runtimeGeneration,
      });
    },
  });
  const { client } = await connectedClient(io);
  const ack = await client.submitRequest({
    operationId: "operation.1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 9,
    displayedView: displayedViewBinding(),
  });
  assert.equal(ack.status, "indeterminate");
  assert.equal(ack.errorCode, ERROR_CODES.BACKEND_UNAVAILABLE);
  assert.equal(client.readView().indeterminate, 1);

  const session = await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  assert.equal(session.sessionId, "session.2");
  assert.equal(session.pendingReconciliation, 0);
  assert.equal(io.calls.filter(([method]) => method === "operation/request").length, 1);
  assert.equal(io.calls.filter(([method]) => method === "reconcile").length, 1);
  assert.equal(captured.operationId, "operation.1");
});

test("reconciliation rejects wrong current-session or origin provenance", async () => {
  const { client } = await connectedClient();
  const ack = await client.submitRequest({
    operationId: "operation.1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 9,
    displayedView: displayedViewBinding(),
  });
  assert.throws(
    () =>
      client.reconcile(
        terminalObservation({
          semanticDigest: ack.semanticDigest,
          sessionId: "session.other",
        }),
      ),
    (error) => error.code === ERROR_CODES.RECONCILIATION_MISMATCH,
  );
  assert.throws(
    () =>
      client.reconcile(
        terminalObservation({
          semanticDigest: ack.semanticDigest,
          originConnectionGeneration: 2,
        }),
      ),
    (error) => error.code === ERROR_CODES.RECONCILIATION_MISMATCH,
  );
  assert.equal(client.readView().pending, 1);
});

test("terminal reconciliation removes pending work only with terminal observation", async () => {
  const { client } = await connectedClient();
  const ack = await client.requestStop({
    operationId: "stop.1",
    displayedView: displayedViewBinding(),
    scope: { targetId: "runtime.agentd" },
  });
  assert.throws(
    () =>
      client.reconcile({
        ...terminalObservation({
          method: "runtime/stop",
          operationId: "stop.1",
          semanticDigest: ack.semanticDigest,
        }),
        terminalObserved: false,
      }),
    (error) => error.code === ERROR_CODES.PROTOCOL_VIOLATION,
  );
  const disposition = client.reconcile(
    terminalObservation({
      method: "runtime/stop",
      operationId: "stop.1",
      semanticDigest: ack.semanticDigest,
    }),
  );
  assert.equal(disposition.status, "succeeded");
  assert.equal(client.readView().pending, 0);
});

test("stale confirmations and incompatible protocols return stable typed errors", async () => {
  const io = makeTransport();
  const client = new RuntimeClient({ transport: io });
  await assert.rejects(
    client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 }).then(
      async () => {
        client.applySnapshot({
          sessionId: "session.1",
          connectionGeneration: 1,
          generation: 1,
          revision: 2,
          digest: D2,
          modules: [],
        });
        return client.submitRequest({
          operationId: "operation.1",
          subjectId: "runtime.agentd",
          action: "request_retry",
          expectedRevision: 1,
          displayedView: displayedViewBinding({ generation: 1, revision: 1 }),
        });
      },
    ),
    (error) => error.code === ERROR_CODES.STALE_SNAPSHOT,
  );

  const bad = makeTransport();
  bad.connect = async (input) => ({
    authenticated: true,
    sessionId: "session.bad",
    connectionGeneration: 1,
    protocolVersion: input.protocolVersion + 1,
  });
  const incompatible = new RuntimeClient({ transport: bad });
  await assert.rejects(
    incompatible.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 }),
    (error) => error.code === ERROR_CODES.INCOMPATIBLE_PROTOCOL,
  );
});

test("projected runtime view enforces the 1 MiB bound after redaction", async () => {
  const io = makeTransport();
  const client = new RuntimeClient({ transport: io });
  await client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });
  const modules = Array.from({ length: 4096 }, (_, index) => ({
    moduleId: `m${String(index).padStart(4, "0")}.${"x".repeat(118)}`,
    status: "degraded",
    revision: index + 1,
    digest: D3,
    providerPayload: { giantSecret: "z".repeat(MAX_VIEW_BYTES) },
  }));
  assert.throws(
    () =>
      client.applySnapshot({
        sessionId: "session.1",
        connectionGeneration: 1,
        generation: 1,
        revision: 1,
        digest: D2,
        modules,
      }),
    (error) => error.code === ERROR_CODES.VIEW_TOO_LARGE,
  );
});

test("retains at most the prior coherent snapshot generation marker", async () => {
  const { client } = await connectedClient();
  assert.equal(client.readView().previousSnapshotRetained, false);
  client.applySnapshot({
    sessionId: "session.1",
    connectionGeneration: 1,
    generation: 8,
    revision: 10,
    digest: D3,
    modules: [moduleObservation(2)],
  });
  assert.equal(client.readView().previousSnapshotRetained, true);
});

test("pending capacity is bounded at exactly 1024 operations", async () => {
  const { client } = await connectedClient();
  for (let index = 0; index < 1024; index += 1) {
    await client.submitRequest({
      operationId: `operation.${index}`,
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 9,
      displayedView: displayedViewBinding(),
    });
  }
  await assert.rejects(
    client.submitRequest({
      operationId: "operation.overflow",
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 9,
      displayedView: displayedViewBinding(),
    }),
    (error) => error.code === ERROR_CODES.CAPACITY_EXHAUSTED,
  );
  assert.equal(client.readView().pending, 1024);
});

test("backend rejection clears local pending identity", async () => {
  const io = makeTransport({
    requestImpl(method, input) {
      return {
        accepted: false,
        method,
        sessionId: input.sessionId,
        connectionGeneration: input.connectionGeneration,
        runtimeGeneration: input.runtimeGeneration,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
      };
    },
  });
  const { client } = await connectedClient(io);
  await assert.rejects(
    client.submitRequest({
      operationId: "operation.1",
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 9,
      displayedView: displayedViewBinding(),
    }),
    (error) => error.code === ERROR_CODES.REQUEST_REJECTED,
  );
  assert.equal(client.readView().pending, 0);
});

test("connect maps arbitrary transport error codes to stable BACKEND_UNAVAILABLE", async () => {
  const io = makeTransport();
  io.connect = async () => {
    const error = new Error("connection reset");
    error.code = "ECONNRESET";
    throw error;
  };
  const client = new RuntimeClient({ transport: io });
  await assert.rejects(
    client.connect({
      endpointId: "runtime.1",
      protocolVersion: 1,
      manifestDigest: D1,
    }),
    (error) =>
      error instanceof UiControlError && error.code === ERROR_CODES.BACKEND_UNAVAILABLE,
  );
});

test("close clears local session and maps raw transport failure to typed error", async () => {
  const io = makeTransport();
  const { client } = await connectedClient(io);
  io.close = async () => {
    throw new Error("close response lost");
  };

  await assert.rejects(
    client.close(),
    (error) =>
      error instanceof UiControlError && error.code === ERROR_CODES.BACKEND_UNAVAILABLE,
  );
  assert.throws(
    () => client.readView(),
    (error) => error instanceof UiControlError && error.code === ERROR_CODES.NOT_CONNECTED,
  );
});

test("snapshot module array must be dense indexed data", async () => {
  const io = makeTransport();
  const client = new RuntimeClient({ transport: io });
  await client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });
  const modules = new Array(1);
  assert.throws(
    () =>
      client.applySnapshot({
        sessionId: "session.1",
        connectionGeneration: 1,
        generation: 1,
        revision: 1,
        digest: D2,
        modules,
      }),
    (error) => error instanceof UiControlError && error.code === ERROR_CODES.INVALID_INPUT,
  );
});
