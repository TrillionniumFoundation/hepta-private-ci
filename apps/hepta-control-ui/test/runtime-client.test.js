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

async function prepared(io) {
  const client = new RuntimeClient({ transport: io });
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
  return client;
}

const REQUEST = {
  operationId: "operation.1",
  semanticDigest: D3,
  displayedRevision: 2,
};

test("concurrent retries reserve one backend dispatch and bind the method", async () => {
  const io = transport();
  let release;
  const wait = new Promise((resolve) => {
    release = resolve;
  });
  let count = 0;
  io.request = async (_, input) => {
    count++;
    await wait;
    return {
      accepted: true,
      operationId: input.operationId,
      semanticDigest: input.semanticDigest,
    };
  };
  const client = await prepared(io);
  const first = client.submitRequest(REQUEST);
  const retry = client.submitRequest(REQUEST);
  await assert.rejects(client.requestStop(REQUEST), /changed semantics/);
  release();
  assert.deepEqual(await first, await retry);
  assert.equal(count, 1);
});

test("uncertain transport retains the operation fence and can reconcile", async () => {
  const io = transport();
  let count = 0;
  io.request = async () => {
    count++;
    throw new Error("lost response after delivery");
  };
  const client = await prepared(io);
  await assert.rejects(client.submitRequest(REQUEST), /lost response/);
  await assert.rejects(client.submitRequest(REQUEST), /lost response/);
  assert.equal(count, 1);
  assert.equal(client.readView().pending, 1);
  client.reconcile({
    ...REQUEST,
    status: "failed",
    terminalObserved: true,
    outcomeDigest: D2,
  });
  assert.equal(client.readView().pending, 0);
});

test("a late acknowledgement cannot cross a runtime connection change", async () => {
  const io = transport();
  let release;
  io.request = (_, input) =>
    new Promise((resolve) => {
      release = () =>
        resolve({
          accepted: true,
          operationId: input.operationId,
          semanticDigest: input.semanticDigest,
        });
    });
  const client = await prepared(io);
  const pending = client.submitRequest(REQUEST);
  const rejected = assert.rejects(pending, /connection changed/);
  await Promise.resolve();
  await client.close();
  await client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  release();
  await rejected;
  assert.throws(
    () =>
      client.reconcile({
        ...REQUEST,
        status: "succeeded",
        terminalObserved: true,
        outcomeDigest: D2,
      }),
    /previous runtime connection/,
  );
});

test("concurrent connects and close reject superseded connection responses", async () => {
  const io = transport();
  const releases = [];
  io.connect = (input) =>
    new Promise((resolve) =>
      releases.push(() =>
        resolve({
          authenticated: true,
          sessionId: `session.${releases.length}`,
          connectionGeneration: releases.length,
          protocolVersion: input.protocolVersion,
        }),
      ),
    );
  const client = new RuntimeClient({ transport: io });
  const manifest = {
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  };
  const first = client.connect(manifest);
  const rejectedFirst = assert.rejects(first, /superseded/);
  const second = client.connect(manifest);
  releases[1]();
  const current = await second;
  releases[0]();
  await rejectedFirst;
  assert.equal(client.readView().sessionId, current.sessionId);
  const late = client.connect(manifest);
  const rejectedLate = assert.rejects(late, /superseded/);
  await client.close();
  releases[2]();
  await rejectedLate;
  assert.throws(() => client.readView(), /not connected/);
});

test("runtime module snapshots own and freeze nested data", async () => {
  const client = await prepared(transport());
  const modules = [
    {
      id: "runtime.agentd",
      status: "quarantined",
      diagnostic: { reasons: ["blocked"] },
    },
  ];
  const view = client.applySnapshot({
    sessionId: "session.1",
    connectionGeneration: 1,
    generation: 1,
    revision: 3,
    digest: D2,
    modules,
  });
  modules[0].status = "ready";
  modules[0].diagnostic.reasons[0] = "cleared";
  assert.equal(view.modules[0].status, "quarantined");
  assert.deepEqual(view.modules[0].diagnostic.reasons, ["blocked"]);
  assert.throws(() => {
    view.modules[0].status = "ready";
  }, TypeError);
  assert.throws(() => {
    view.modules[0].diagnostic.reasons.push("injected");
  }, TypeError);
});

test("snapshot arrays cannot bypass cloning through methods or accessors", async () => {
  const client = await prepared(transport());
  for (const modules of [
    Object.assign([{ status: "quarantined" }], {
      map: () => [{ status: "ready" }],
    }),
    new Array(1),
    Object.defineProperty([], "0", {
      get() {
        throw new Error("getter executed");
      },
      enumerable: true,
    }),
    new Array(257).fill(null),
  ]) {
    assert.throws(
      () =>
        client.applySnapshot({
          sessionId: "session.1",
          connectionGeneration: 1,
          generation: 1,
          revision: 3,
          digest: D2,
          modules,
        }),
      /array|data properties/,
    );
  }
  assert.equal(client.readView().revision, 2);
});

test("reconnect waits for the generation-bound close to finish", async () => {
  const io = transport();
  let release;
  let closes = 0;
  io.close = async (input) => {
    closes++;
    assert.deepEqual(input, {
      sessionId: "session.1",
      connectionGeneration: 1,
    });
    await new Promise((resolve) => {
      release = resolve;
    });
  };
  const client = await prepared(io);
  const closing = client.close();
  const repeated = client.close();
  await Promise.resolve();
  const connected = client.connect({
    endpointId: "runtime.1",
    protocolVersion: 1,
    manifestDigest: D1,
  });
  assert.equal(io.calls.filter(([method]) => method === "connect").length, 1);
  release();
  await Promise.all([closing, repeated, connected]);
  assert.equal(closes, 1);
  assert.equal(io.calls.filter(([method]) => method === "connect").length, 2);
  assert.equal(client.readView().sessionId, "session.1");
});

test("uncertain close fences reconnect without another transport call", async () => {
  const io = transport();
  io.close = async () => {
    throw new Error("lost close acknowledgement");
  };
  const client = await prepared(io);
  await assert.rejects(client.close(), /lost close acknowledgement/);
  await assert.rejects(
    client.connect({
      endpointId: "runtime.1",
      protocolVersion: 1,
      manifestDigest: D1,
    }),
    /lost close acknowledgement/,
  );
  assert.equal(io.calls.filter(([method]) => method === "connect").length, 1);
  assert.throws(() => client.readView(), /not connected/);
});

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
  assert.equal(
    io.calls.some(([method]) => method === "runtime/stop"),
    true,
  );
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
