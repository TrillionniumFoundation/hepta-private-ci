import assert from "node:assert/strict";
import test from "node:test";

import { UI_CONTROL_ERROR_CODES as ERROR } from "../src/errors.js";
import { RuntimeClient } from "../src/runtime-client.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);

function transport({
  authenticated = true,
  protocolVersion = null,
  requestImpl = null,
} = {}) {
  const calls = [];
  let connections = 0;
  return {
    calls,
    async connect(input) {
      calls.push(["connect", input]);
      connections += 1;
      return {
        authenticated,
        sessionId: `session.${connections}`,
        connectionGeneration: connections,
        protocolVersion: protocolVersion ?? input.protocolVersion,
      };
    },
    async request(method, input) {
      calls.push([method, input]);
      if (requestImpl) {
        return requestImpl(method, input, calls);
      }
      return {
        accepted: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        requestKind: input.requestKind,
        originSessionId: input.sessionId,
        originConnectionGeneration: input.connectionGeneration,
        runtimeGeneration: input.runtimeGeneration,
      };
    },
    async close(input) {
      calls.push(["close", input]);
    },
  };
}

async function connect(client) {
  return client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
}

function snapshot({
  sessionId = "session.1",
  connectionGeneration = 1,
  generation = 7,
  revision = 9,
  modules,
} = {}) {
  return {
    sessionId,
    connectionGeneration,
    generation,
    revision,
    digest: D2,
    modules:
      modules ??
      [
        {
          moduleId: "runtime.agentd",
          status: "ready",
          revision,
          digest: D3,
        },
      ],
  };
}

function observationFromRequest(payload, observerSessionId, overrides = {}) {
  return {
    observerSessionId,
    originSessionId: payload.sessionId,
    originConnectionGeneration: payload.connectionGeneration,
    runtimeGeneration: payload.runtimeGeneration,
    requestKind: payload.requestKind,
    operationId: payload.operationId,
    semanticDigest: payload.semanticDigest,
    status: "succeeded",
    terminalObserved: true,
    outcomeDigest: D2,
    ...overrides,
  };
}

test("submits and reconciles a generation-bound stop request", async () => {
  const io = transport();
  const client = new RuntimeClient({ transport: io });
  await connect(client);
  client.applySnapshot(snapshot());

  const acknowledgement = await client.requestStop({
    operationId: "stop.1",
    scope: { subjectId: "runtime.1" },
    displayedRevision: 9,
  });
  assert.equal(acknowledgement.status, "pending");
  assert.equal(acknowledgement.accepted, true);
  assert.equal(acknowledgement.authorityGranted, false);
  assert.match(acknowledgement.semanticDigest, /^[0-9a-f]{64}$/);

  const [, payload] = io.calls.find(([method]) => method === "runtime/stop");
  assert.equal(payload.request.kind, "UiControlStopRequestV1");
  assert.deepEqual(payload.scope, { subjectId: "runtime.1" });
  assert.equal(payload.semanticDigest, acknowledgement.semanticDigest);
  assert.equal("semanticDigest" in payload.request, false);

  const disposition = client.reconcile(
    observationFromRequest(payload, "session.1"),
  );
  assert.equal(disposition.status, "succeeded");
  assert.equal(client.readView().pending, 0);
});

test("submits full operation intent and derives semantic digest internally", async () => {
  const io = transport();
  const client = new RuntimeClient({ transport: io });
  await connect(client);
  client.applySnapshot(snapshot());

  const acknowledgement = await client.submitRequest({
    displayedRevision: 9,
    intent: {
      operationId: "operation.1",
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 9,
    },
  });
  const [, payload] = io.calls.find(
    ([method]) => method === "operation/request",
  );
  assert.deepEqual(payload.intent, {
    kind: "UiControlOperationRequestV1",
    operationId: "operation.1",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 9,
  });
  assert.equal(acknowledgement.semanticDigest, payload.semanticDigest);
});

test("blocks mutation from stale views with a stable typed error", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await connect(client);
  client.applySnapshot(snapshot({ generation: 1, revision: 2, modules: [] }));

  await assert.rejects(
    client.submitRequest({
      displayedRevision: 1,
      intent: {
        operationId: "operation.1",
        subjectId: "runtime.agentd",
        action: "request_retry",
        expectedRevision: 1,
      },
    }),
    (error) => error.code === ERROR.STALE_SNAPSHOT,
  );
});

test("runtime snapshot path redacts source-only fields and snapshots immutable values", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await connect(client);
  const module = {
    moduleId: "runtime.agentd",
    status: "ready",
    revision: 9,
    digest: D3,
    secret: "must-not-leak",
  };
  Object.defineProperty(module, "providerPayload", {
    enumerable: true,
    get() {
      throw new Error("provider payload getter must not run");
    },
  });

  client.applySnapshot(snapshot({ modules: [module] }));
  module.status = "degraded";
  module.secret = "changed";

  const view = client.readView();
  assert.equal(view.modules[0].status, "ready");
  assert.equal("secret" in view.modules[0], false);
  assert.equal("providerPayload" in view.modules[0], false);
  assert.equal(Object.isFrozen(view.modules), true);
  assert.equal(Object.isFrozen(view.modules[0]), true);
});

test("timeout after backend acceptance is retained as indeterminate and never blindly retried", async () => {
  let requestCalls = 0;
  const io = transport({
    requestImpl(_method, _input) {
      requestCalls += 1;
      throw new Error("response lost after write");
    },
  });
  const client = new RuntimeClient({ transport: io });
  await connect(client);
  client.applySnapshot(snapshot());

  const request = {
    operationId: "stop.timeout",
    scope: { subjectId: "runtime.1" },
    displayedRevision: 9,
  };
  await assert.rejects(
    client.requestStop(request),
    (error) => error.code === ERROR.BACKEND_UNAVAILABLE,
  );
  assert.equal(requestCalls, 1);
  assert.equal(client.readPending().length, 1);
  assert.equal(client.readPending()[0].status, "indeterminate");

  const repeat = await client.requestStop(request);
  assert.equal(repeat.status, "indeterminate");
  assert.equal(requestCalls, 1);

  const [, originalPayload] = io.calls.find(
    ([method]) => method === "runtime/stop",
  );
  await connect(client);
  client.applySnapshot(
    snapshot({
      sessionId: "session.2",
      connectionGeneration: 2,
      generation: 8,
      revision: 10,
    }),
  );
  const disposition = client.reconcile(
    observationFromRequest(originalPayload, "session.2"),
  );
  assert.equal(disposition.status, "succeeded");
  assert.equal(client.readPending().length, 0);
});

test("reconciliation rejects cross-session or changed provenance", async () => {
  const io = transport();
  const client = new RuntimeClient({ transport: io });
  await connect(client);
  client.applySnapshot(snapshot());
  await client.submitRequest({
    displayedRevision: 9,
    intent: {
      operationId: "operation.provenance",
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 9,
    },
  });
  const [, payload] = io.calls.find(
    ([method]) => method === "operation/request",
  );

  assert.throws(
    () => client.reconcile(observationFromRequest(payload, "session.other")),
    (error) => error.code === ERROR.PROTOCOL_VIOLATION,
  );
  assert.throws(
    () =>
      client.reconcile(
        observationFromRequest(payload, "session.1", {
          originConnectionGeneration: 999,
        }),
      ),
    (error) => error.code === ERROR.PROTOCOL_VIOLATION,
  );
  assert.equal(client.readPending().length, 1);
});

test("operation identity cannot be reused with semantic drift", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await connect(client);
  client.applySnapshot(snapshot());
  await client.submitRequest({
    displayedRevision: 9,
    intent: {
      operationId: "operation.same",
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 9,
    },
  });

  await assert.rejects(
    client.submitRequest({
      displayedRevision: 9,
      intent: {
        operationId: "operation.same",
        subjectId: "runtime.agentd",
        action: "request_rollback",
        expectedRevision: 9,
      },
    }),
    (error) => error.code === ERROR.PROTOCOL_VIOLATION,
  );
});

test("non-terminal observations stay pending and cannot claim outcome digests", async () => {
  const io = transport();
  const client = new RuntimeClient({ transport: io });
  await connect(client);
  client.applySnapshot(snapshot());
  await client.submitRequest({
    displayedRevision: 9,
    intent: {
      operationId: "operation.indeterminate",
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 9,
    },
  });
  const [, payload] = io.calls.find(
    ([method]) => method === "operation/request",
  );

  const disposition = client.reconcile(
    observationFromRequest(payload, "session.1", {
      status: "indeterminate",
      terminalObserved: false,
      outcomeDigest: null,
    }),
  );
  assert.equal(disposition.status, "indeterminate");
  assert.equal(client.readView().pending, 1);
  assert.equal(client.readView().indeterminate, 1);

  assert.throws(
    () =>
      client.reconcile(
        observationFromRequest(payload, "session.1", {
          status: "indeterminate",
          terminalObserved: false,
          outcomeDigest: D2,
        }),
      ),
    (error) => error.code === ERROR.PROTOCOL_VIOLATION,
  );
});

test("snapshot generation, revision and duplicate module identity fail closed", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await connect(client);
  client.applySnapshot(snapshot({ generation: 3, revision: 7 }));

  assert.throws(
    () => client.applySnapshot(snapshot({ generation: 2, revision: 8 })),
    (error) => error.code === ERROR.STALE_SNAPSHOT,
  );
  assert.throws(
    () => client.applySnapshot(snapshot({ generation: 3, revision: 7 })),
    (error) => error.code === ERROR.STALE_SNAPSHOT,
  );
  assert.throws(
    () =>
      client.applySnapshot(
        snapshot({
          generation: 4,
          revision: 1,
          modules: [
            {
              moduleId: "runtime.agentd",
              status: "ready",
              revision: 1,
              digest: D1,
            },
            {
              moduleId: "runtime.agentd",
              status: "degraded",
              revision: 1,
              digest: D2,
            },
          ],
        }),
      ),
    (error) => error.code === ERROR.PROTOCOL_VIOLATION,
  );
});

test("projected runtime view enforces the 1 MiB capacity ceiling", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await connect(client);
  const modules = Array.from({ length: 4096 }, (_, index) => ({
    moduleId: `m${index.toString(16).padStart(4, "0")}${"x".repeat(123)}`,
    status: "ready",
    revision: 1,
    digest: D1,
  }));
  assert.equal(modules[0].moduleId.length, 128);
  assert.throws(
    () =>
      client.applySnapshot(
        snapshot({ generation: 1, revision: 1, modules }),
      ),
    (error) => error.code === ERROR.CAPACITY_EXHAUSTED,
  );
});

test("pending operation capacity is bounded at 1024", async () => {
  const io = transport();
  const client = new RuntimeClient({
    transport: io,
    digestSemantic: async (semantics) => {
      const index = Number(semantics.operationId.split(".").at(-1));
      return index.toString(16).padStart(64, "a").slice(-64);
    },
  });
  await connect(client);
  client.applySnapshot(snapshot());

  for (let index = 0; index < 1024; index += 1) {
    await client.requestStop({
      operationId: `stop.${index}`,
      scope: { subjectId: "runtime.1" },
      displayedRevision: 9,
    });
  }
  await assert.rejects(
    client.requestStop({
      operationId: "stop.1024",
      scope: { subjectId: "runtime.1" },
      displayedRevision: 9,
    }),
    (error) => error.code === ERROR.CAPACITY_EXHAUSTED,
  );
  assert.equal(client.readPending().length, 1024);
});

test("authentication and protocol failures expose stable error codes", async () => {
  const unauthenticated = new RuntimeClient({
    transport: transport({ authenticated: false }),
  });
  await assert.rejects(
    connect(unauthenticated),
    (error) => error.code === ERROR.UNAUTHENTICATED,
  );

  const incompatible = new RuntimeClient({
    transport: transport({ protocolVersion: 2 }),
  });
  await assert.rejects(
    connect(incompatible),
    (error) => error.code === ERROR.INCOMPATIBLE_PROTOCOL,
  );
});

test("public validation failures and malformed backend acknowledgements use stable typed codes", async () => {
  const client = new RuntimeClient({ transport: transport() });
  await assert.rejects(
    client.connect({
      endpointId: "runtime.1",
      protocolVersion: 1,
      manifestDigest: "not-a-digest",
    }),
    (error) => error.code === ERROR.INVALID_INPUT,
  );

  const io = transport({
    requestImpl(_method, input) {
      return {
        accepted: true,
        operationId: input.operationId,
        semanticDigest: input.semanticDigest,
        requestKind: input.requestKind,
        originSessionId: input.sessionId,
        originConnectionGeneration: input.connectionGeneration,
        runtimeGeneration: input.runtimeGeneration,
        unknownCriticalField: true,
      };
    },
  });
  const connected = new RuntimeClient({ transport: io });
  await connect(connected);
  connected.applySnapshot(snapshot());
  await assert.rejects(
    connected.requestStop({
      operationId: "stop.protocol",
      scope: { subjectId: "runtime.1" },
      displayedRevision: 9,
    }),
    (error) => error.code === ERROR.PROTOCOL_VIOLATION,
  );
  assert.equal(connected.readPending()[0].status, "indeterminate");
});
