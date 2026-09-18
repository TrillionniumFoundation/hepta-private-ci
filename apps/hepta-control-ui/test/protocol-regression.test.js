import assert from "node:assert/strict";
import test from "node:test";

import {
  buildLocalOperationProposalFromCanonicalJson,
  projectRuntimeFromLocalCanonicalJson,
} from "../src/control.js";
import { RuntimeClient } from "../src/runtime-client.js";
import { snapshotCanonical } from "../src/protocol.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const runtimeSchema = "hepta.ui-control.local-runtime-observation.v1";
const operationSchema = "hepta.ui-control.local-operation-proposal-input.v1";

function displayedViewBinding({
  sessionId = "session.1",
  connectionGeneration = 1,
  generation = 7,
  revision = 9,
  digest = D2,
} = {}) {
  return Object.freeze({ sessionId, connectionGeneration, generation, revision, digest });
}

function canonicalJson(value) {
  return JSON.stringify(
    Object.fromEntries(
      Object.entries(value).sort(([left], [right]) =>
        left < right ? -1 : left > right ? 1 : 0,
      ),
    ),
  );
}

test("local canonical entrypoints reject hostile objects without invoking traps", () => {
  for (const call of [
    projectRuntimeFromLocalCanonicalJson,
    buildLocalOperationProposalFromCanonicalJson,
  ]) {
    let traps = 0;
    const hostile = new Proxy(
      {},
      {
        get() {
          traps += 1;
          throw new Error("unexpected get");
        },
        ownKeys() {
          traps += 1;
          throw new Error("unexpected ownKeys");
        },
      },
    );
    assert.throws(() => call(hostile), /bounded canonical JSON/);
    assert.equal(traps, 0);
  }
});

test("local canonical byte and stable-identity boundaries remain exact", () => {
  const exactBytes = `"${"é".repeat(2047)}"`;
  assert.equal(Buffer.byteLength(exactBytes), 4096);
  assert.throws(
    () => projectRuntimeFromLocalCanonicalJson(exactBytes),
    /must be an object/,
  );
  assert.throws(
    () => projectRuntimeFromLocalCanonicalJson(`${exactBytes}a`),
    /canonical JSON byte limit/,
  );

  const operation = {
    schema: operationSchema,
    operationId: "x".repeat(128),
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 1,
  };
  assert.equal(
    buildLocalOperationProposalFromCanonicalJson(canonicalJson(operation)).operationId.length,
    128,
  );
  assert.throws(
    () =>
      buildLocalOperationProposalFromCanonicalJson(
        canonicalJson({ ...operation, operationId: "x".repeat(129) }),
      ),
    /bounded stable identifier/,
  );
  assert.throws(
    () =>
      projectRuntimeFromLocalCanonicalJson(
        canonicalJson({
          schema: runtimeSchema,
          moduleId: "runtime.agentd",
          status: "invented",
          revision: 1,
          digest: D3,
        }),
      ),
    /registered runtime state/,
  );
});

test("runtime request binds target revision independently from displayed view revision", async () => {
  let sent;
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request(method, input) {
      sent = { method, input };
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
    async reconcile() {
      return null;
    },
    async close() {},
  };
  const client = new RuntimeClient({ transport });
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
    modules: [
      {
        moduleId: "runtime.agentd",
        status: "ready",
        revision: 4,
        digest: D3,
      },
    ],
  });

  await client.submitRequest({
    operationId: "operation.separate-revisions",
    subjectId: "runtime.agentd",
    action: "request_retry",
    expectedRevision: 4,
    displayedView: displayedViewBinding(),
  });

  assert.equal(sent.method, "operation/request");
  assert.equal(sent.input.intent.expectedRevision, 4);
  assert.equal(sent.input.displayedRevision, 9);
});


test("stop scope must be an explicit record", async () => {
  const transport = {
    async connect(input) {
      return { authenticated: true, sessionId: "session.1", connectionGeneration: 1, protocolVersion: input.protocolVersion };
    },
    async request() {
      assert.fail("request should not cross transport");
    },
    async reconcile() { return null; },
    async close() {},
  };
  const client = new RuntimeClient({ transport });
  await client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });
  client.applySnapshot({
    sessionId: "session.1", connectionGeneration: 1, generation: 1, revision: 1, digest: D2, modules: [],
  });
  await assert.rejects(
    client.requestStop({ operationId: "stop.invalid", displayedRevision: 1, scope: "runtime.agentd" }),
    /scope must be an object/,
  );
});

test("unbound backend rejection cannot erase pending work", async () => {
  const transport = {
    async connect(input) {
      return {
        authenticated: true,
        sessionId: "session.1",
        connectionGeneration: 1,
        protocolVersion: input.protocolVersion,
      };
    },
    async request() {
      return { accepted: false };
    },
    async reconcile() { return null; },
    async close() {},
  };
  const client = new RuntimeClient({ transport });
  await client.connect({ endpointId: "runtime.1", protocolVersion: 1, manifestDigest: D1 });
  client.applySnapshot({
    sessionId: "session.1", connectionGeneration: 1, generation: 1, revision: 1, digest: D2, modules: [],
  });
  await assert.rejects(
    client.submitRequest({
      operationId: "operation.bad-reject",
      subjectId: "runtime.agentd",
      action: "request_retry",
      expectedRevision: 1,
      displayedView: displayedViewBinding({ generation: 1, revision: 1 }),
    }),
    (error) => error.code === "PROTOCOL_VIOLATION",
  );
  assert.equal(client.readView().pending, 1);
  assert.equal(client.readView().indeterminate, 1);
});


test("canonical snapshot treats __proto__ as data instead of mutating prototypes", () => {
  const input = JSON.parse('{"__proto__":{"polluted":true},"safe":1}');
  const snapshot = snapshotCanonical(input, "prototype-safe input");

  assert.equal(Object.getPrototypeOf(snapshot), Object.prototype);
  assert.equal(Object.hasOwn(snapshot, "__proto__"), true);
  assert.equal(snapshot.__proto__.polluted, true);
  assert.equal(Object.prototype.polluted, undefined);
  assert.equal(
    JSON.stringify(snapshot),
    '{"__proto__":{"polluted":true},"safe":1}',
  );
});
