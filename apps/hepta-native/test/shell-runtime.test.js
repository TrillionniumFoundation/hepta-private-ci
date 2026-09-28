import assert from "node:assert/strict";
import test from "node:test";

import { NativeShellRuntime } from "../src/shell-runtime.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);

function fixture({ permission = true, terminal = true, restarted = true } = {}) {
  const calls = [];
  return {
    calls,
    backend: {
      async connect(input) {
        calls.push(["connect", input]);
        return {
          authenticated: true,
          protocolVersion: input.protocolVersion,
          sessionId: "session.1",
          generation: 3,
        };
      },
      async request() {
        throw new Error("not used");
      },
      async close(input) {
        calls.push(["close", input]);
      },
    },
    platform: {
      async permission(input) {
        calls.push(["permission", input]);
        return { allowed: permission, outcomeDigest: D4 };
      },
      async invoke(input) {
        calls.push(["invoke", input]);
        return terminal
          ? { terminalObserved: true, status: "succeeded", outcomeDigest: D4 }
          : { terminalObserved: false };
      },
    },
    updater: {
      async verify(input) {
        calls.push(["verify", input]);
        return { accepted: true };
      },
      async apply(input) {
        calls.push(["apply", input]);
        return { terminalObserved: terminal, restarted };
      },
      async rollback(input) {
        calls.push(["rollback", input]);
      },
    },
  };
}

async function connectedRuntime(options) {
  const io = fixture(options);
  const runtime = new NativeShellRuntime(io);
  await runtime.connectRuntime({
    endpointId: "runtime.1",
    manifestDigest: D1,
    protocolVersion: 1,
  });
  runtime.renderRuntimeView({
    sessionId: "session.1",
    sessionGeneration: 3,
    generation: 9,
    revision: 11,
    digest: D2,
    modules: [],
  });
  return { runtime, io };
}

test("executes a final-payload-bound platform request", async () => {
  const { runtime } = await connectedRuntime();
  const receipt = await runtime.requestPlatformCapability({
    operationId: "operation.1",
    action: "notify",
    resource: "notification.channel.1",
    displayedRevision: 11,
    finalPayloadDigest: D3,
    grantPayloadDigest: D3,
  });
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.notificationAuthority, false);
});

test("permission denial is terminal and does not invoke the platform", async () => {
  const { runtime, io } = await connectedRuntime({ permission: false });
  const receipt = await runtime.requestPlatformCapability({
    operationId: "operation.2",
    action: "open_path",
    resource: "path.reference.1",
    displayedRevision: 11,
    finalPayloadDigest: D3,
    grantPayloadDigest: D3,
  });
  assert.equal(receipt.status, "rejected");
  assert.equal(io.calls.some(([name]) => name === "invoke"), false);
});

test("failed restart quarantines update and rolls back", async () => {
  const { runtime, io } = await connectedRuntime({ terminal: false, restarted: false });
  const receipt = await runtime.applyShellUpdate({
    packageDigest: D2,
    predecessorDigest: D1,
    evidenceDigest: D3,
    selectedBy: "reviewer.1",
    generatorPrincipal: "generator.1",
    platform: "linux",
    architecture: "x86_64",
  });
  assert.equal(receipt.status, "quarantined");
  assert.equal(io.calls.some(([name]) => name === "rollback"), true);
});

test("self-selected update is rejected", async () => {
  const { runtime } = await connectedRuntime();
  await assert.rejects(
    runtime.applyShellUpdate({
      packageDigest: D2,
      predecessorDigest: D1,
      evidenceDigest: D3,
      selectedBy: "generator.1",
      generatorPrincipal: "generator.1",
      platform: "linux",
      architecture: "x86_64",
    }),
    /cannot be selected by its generator/,
  );
});

function platformRequest(overrides = {}) {
  return { operationId: "operation.race", action: "notify",
    resource: "notification.channel.1", displayedRevision: 11,
    finalPayloadDigest: D3, grantPayloadDigest: D3, ...overrides };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("concurrent identical requests invoke the platform once", async () => {
  const { runtime, io } = await connectedRuntime();
  const gate = deferred();
  io.platform.permission = async () => { await gate.promise; return { allowed: true }; };
  const first = runtime.requestPlatformCapability(platformRequest());
  const second = runtime.requestPlatformCapability(platformRequest());
  gate.resolve();
  assert.deepEqual(await first, await second);
  assert.equal(io.calls.filter(([name]) => name === "invoke").length, 1);
});

test("same digest cannot hide a changed action or resource", async () => {
  const { runtime } = await connectedRuntime();
  await runtime.requestPlatformCapability(platformRequest());
  for (const change of [{ resource: "notification.other" }, { action: "open_path" }]) {
    await assert.rejects(runtime.requestPlatformCapability(platformRequest(change)), /changed semantics/);
  }
});

test("input is frozen before asynchronous permission", async () => {
  const { runtime, io } = await connectedRuntime();
  const gate = deferred();
  io.platform.permission = async () => { await gate.promise; return { allowed: true }; };
  const input = platformRequest();
  const pending = runtime.requestPlatformCapability(input);
  input.resource = "notification.substituted";
  input.action = "open_path";
  gate.resolve();
  await pending;
  const actual = io.calls.find(([name]) => name === "invoke")[1];
  assert.equal(actual.resource, "notification.channel.1");
  assert.equal(actual.action, "notify");
});

test("accessors and unknown input fields reject without evaluating getters", async () => {
  const { runtime } = await connectedRuntime();
  let evaluated = 0;
  const input = platformRequest();
  Object.defineProperty(input, "resource", { enumerable: true, get() { evaluated++; return "x"; } });
  await assert.rejects(runtime.requestPlatformCapability(input), /own data fields/);
  assert.equal(evaluated, 0);
  await assert.rejects(runtime.requestPlatformCapability(platformRequest({ extra: 1 })), /own data fields/);
});

test("lost reply or malformed terminal is indeterminate and never reinvoked", async () => {
  for (const mode of ["throw", "status", "digest"]) {
    const { runtime, io } = await connectedRuntime();
    let calls = 0;
    io.platform.invoke = async () => {
      calls++;
      if (mode === "throw") throw new Error("lost after apply");
      return { terminalObserved: true, status: mode === "status" ? "accepted" : "succeeded",
        outcomeDigest: "bad" };
    };
    const first = await runtime.requestPlatformCapability(platformRequest());
    const retry = await runtime.requestPlatformCapability(platformRequest());
    assert.equal(first.status, "indeterminate");
    assert.deepEqual(retry, first);
    assert.equal(calls, 1);
  }
});

test("view change during permission rejects before effect", async () => {
  const { runtime, io } = await connectedRuntime();
  const gate = deferred();
  io.platform.permission = async () => { await gate.promise; return { allowed: true }; };
  const pending = runtime.requestPlatformCapability(platformRequest());
  runtime.renderRuntimeView({ sessionId: "session.1", sessionGeneration: 3,
    generation: 9, revision: 12, digest: D4, modules: [] });
  gate.resolve();
  await assert.rejects(pending, /context changed/);
  assert.equal(io.calls.some(([name]) => name === "invoke"), false);
});

test("close rejects pending permission without replacing original session", async () => {
  const { runtime, io } = await connectedRuntime();
  const gate = deferred();
  io.platform.permission = async () => { await gate.promise; return { allowed: true }; };
  const pending = runtime.requestPlatformCapability(platformRequest());
  await runtime.close();
  gate.resolve();
  await assert.rejects(pending, /context changed/);
  assert.equal(io.calls.some(([name]) => name === "invoke"), false);
});

test("pre-invoke permission error releases only its local reservation", async () => {
  const { runtime, io } = await connectedRuntime();
  io.platform.permission = async () => { throw new Error("permission unavailable"); };
  await assert.rejects(runtime.requestPlatformCapability(platformRequest()), /permission unavailable/);
  io.platform.permission = async () => ({ allowed: true });
  assert.equal((await runtime.requestPlatformCapability(platformRequest())).status, "succeeded");
  assert.equal(io.calls.filter(([name]) => name === "invoke").length, 1);
});

test("operation history backpressures instead of evicting prior identities", async () => {
  const { runtime, io } = await connectedRuntime();
  for (let n = 0; n < 1024; n++) {
    await runtime.requestPlatformCapability(platformRequest({ operationId: `op.${n}` }));
  }
  await assert.rejects(runtime.requestPlatformCapability(platformRequest()), /capacity exceeded/);
  await runtime.requestPlatformCapability(platformRequest({ operationId: "op.0" }));
  assert.equal(io.calls.filter(([name]) => name === "invoke").length, 1024);
});

test("close also fences a connection that has not finished authenticating", async () => {
  const io = fixture();
  const runtime = new NativeShellRuntime(io);
  const gate = deferred();
  io.backend.connect = async (input) => {
    await gate.promise;
    return { authenticated: true, protocolVersion: input.protocolVersion,
      sessionId: "session.late", generation: 1 };
  };
  const pending = runtime.connectRuntime({ endpointId: "runtime.1", manifestDigest: D1, protocolVersion: 1 });
  await runtime.close();
  gate.resolve();
  await assert.rejects(pending, /superseded/);
  await assert.rejects(runtime.requestPlatformCapability(platformRequest()), /not connected/);
});

test("older connect cannot overwrite a newer authenticated session", async () => {
  const io = fixture();
  const runtime = new NativeShellRuntime(io);
  const gate = deferred();
  io.backend.connect = async (input) => {
    if (input.endpointId === "runtime.old") await gate.promise;
    return { authenticated: true, protocolVersion: 1, sessionId: input.endpointId, generation: 1 };
  };
  const old = runtime.connectRuntime({ endpointId: "runtime.old", manifestDigest: D1, protocolVersion: 1 });
  await runtime.connectRuntime({ endpointId: "runtime.new", manifestDigest: D1, protocolVersion: 1 });
  gate.resolve();
  await assert.rejects(old, /superseded/);
  runtime.renderRuntimeView({ sessionId: "runtime.new", sessionGeneration: 1,
    generation: 9, revision: 11, digest: D2, modules: [] });
});
