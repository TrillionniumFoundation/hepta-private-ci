import assert from "node:assert/strict";
import test from "node:test";

import { NativeShellRuntime } from "../src/shell-runtime.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);

function fixture({
  permission = true,
  terminal = true,
  restarted = true,
} = {}) {
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
  assert.equal(
    io.calls.some(([name]) => name === "invoke"),
    false,
  );
});

test("failed restart quarantines update and rolls back", async () => {
  const { runtime, io } = await connectedRuntime({
    terminal: false,
    restarted: false,
  });
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
  assert.equal(
    io.calls.some(([name]) => name === "rollback"),
    true,
  );
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
  return {
    operationId: "operation.bound",
    action: "notify",
    resource: "notification.channel.1",
    displayedRevision: 11,
    finalPayloadDigest: D3,
    grantPayloadDigest: D3,
    ...overrides,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

test("concurrent copies of one operation dispatch once", async () => {
  const { runtime, io } = await connectedRuntime();
  const permission = deferred();
  io.platform.permission = async () => permission.promise;
  const first = runtime.requestPlatformCapability(platformRequest());
  const second = runtime.requestPlatformCapability(platformRequest());
  permission.resolve({ allowed: true });
  assert.deepEqual(await first, await second);
  assert.equal(io.calls.filter(([name]) => name === "invoke").length, 1);
});

test("synchronous platform adapter reentry receives the same terminal decision", async () => {
  const { runtime, io } = await connectedRuntime();
  let reentrant;
  io.platform.permission = () => {
    reentrant = runtime.requestPlatformCapability(platformRequest());
    return { allowed: true };
  };
  const first = await runtime.requestPlatformCapability(platformRequest());
  assert.deepEqual(await reentrant, first);
  assert.equal(io.calls.filter(([name]) => name === "invoke").length, 1);
});

test("request binding cannot mutate during permission wait", async () => {
  const { runtime, io } = await connectedRuntime();
  const permission = deferred();
  io.platform.permission = async () => permission.promise;
  const input = platformRequest();
  const pending = runtime.requestPlatformCapability(input);
  input.action = "open_path";
  input.resource = "different.path";
  permission.resolve({ allowed: true });
  await pending;
  const dispatched = io.calls.find(([name]) => name === "invoke")[1];
  assert.equal(dispatched.action, "notify");
  assert.equal(dispatched.resource, "notification.channel.1");
});

test("changed action or resource cannot reuse an operation digest", async () => {
  const { runtime } = await connectedRuntime();
  await runtime.requestPlatformCapability(platformRequest());
  for (const overrides of [
    { action: "open_path" },
    { resource: "other.reference" },
  ]) {
    await assert.rejects(
      runtime.requestPlatformCapability(platformRequest(overrides)),
      /changed binding/,
    );
  }
});

test("view change during permission admission prevents dispatch", async () => {
  const { runtime, io } = await connectedRuntime();
  const permission = deferred();
  io.platform.permission = async () => permission.promise;
  const pending = runtime.requestPlatformCapability(platformRequest());
  runtime.renderRuntimeView({
    sessionId: "session.1",
    sessionGeneration: 3,
    generation: 9,
    revision: 12,
    digest: D4,
    modules: [],
  });
  permission.resolve({ allowed: true });
  await assert.rejects(pending, /changed before dispatch/);
  assert.equal(
    io.calls.some(([name]) => name === "invoke"),
    false,
  );
});

test("close during permission admission prevents dispatch", async () => {
  const { runtime, io } = await connectedRuntime();
  const permission = deferred();
  io.platform.permission = async () => permission.promise;
  const pending = runtime.requestPlatformCapability(platformRequest());
  await runtime.close();
  permission.resolve({ allowed: true });
  await assert.rejects(pending, /changed before dispatch/);
  assert.equal(
    io.calls.some(([name]) => name === "invoke"),
    false,
  );
});

test("lost effect acknowledgement remains indeterminate and is not replayed", async () => {
  const { runtime, io } = await connectedRuntime();
  let invoked = 0;
  io.platform.invoke = async () => {
    invoked += 1;
    throw new Error("lost acknowledgement");
  };
  const first = await runtime.requestPlatformCapability(platformRequest());
  assert.equal(first.status, "indeterminate");
  assert.deepEqual(
    await runtime.requestPlatformCapability(platformRequest()),
    first,
  );
  assert.equal(invoked, 1);
});

test("permission denial is retained under the operation identity", async () => {
  const { runtime, io } = await connectedRuntime({ permission: false });
  const first = await runtime.requestPlatformCapability(platformRequest());
  assert.deepEqual(
    await runtime.requestPlatformCapability(platformRequest()),
    first,
  );
  assert.equal(io.calls.filter(([name]) => name === "permission").length, 1);
});

test("native runtime rejects request accessors without evaluating them", async () => {
  const { runtime } = await connectedRuntime();
  let read = false;
  const input = platformRequest();
  Object.defineProperty(input, "action", {
    enumerable: true,
    get() {
      read = true;
      return "notify";
    },
  });
  await assert.rejects(
    runtime.requestPlatformCapability(input),
    /own data properties/,
  );
  assert.equal(read, false);
});

test("close fences an in-flight connection", async () => {
  const io = fixture();
  const connection = deferred();
  io.backend.connect = async () => connection.promise;
  const runtime = new NativeShellRuntime(io);
  const pending = runtime.connectRuntime({
    endpointId: "runtime.1",
    manifestDigest: D1,
    protocolVersion: 1,
  });
  await runtime.close();
  connection.resolve({
    authenticated: true,
    protocolVersion: 1,
    sessionId: "session.1",
    generation: 3,
  });
  await assert.rejects(pending, /superseded/);
  assert.throws(() => runtime.renderRuntimeView({}), /not connected/);
});

function updateRequest(overrides = {}) {
  return {
    packageDigest: D2,
    predecessorDigest: D1,
    evidenceDigest: D3,
    selectedBy: "reviewer.1",
    generatorPrincipal: "generator.1",
    platform: "linux",
    architecture: "x86_64",
    ...overrides,
  };
}

test("concurrent identical updates share one apply operation", async () => {
  const { runtime, io } = await connectedRuntime();
  const verification = deferred();
  io.updater.verify = async () => verification.promise;
  const first = runtime.applyShellUpdate(updateRequest());
  const duplicate = runtime.applyShellUpdate(updateRequest());
  await assert.rejects(
    runtime.applyShellUpdate(updateRequest({ packageDigest: D4 })),
    /already in progress/,
  );
  verification.resolve({ accepted: true });
  assert.deepEqual(await first, await duplicate);
  assert.equal(io.calls.filter(([name]) => name === "apply").length, 1);
  assert.throws(() => runtime.renderRuntimeView({}), /not connected/);
});

test("synchronous updater reentry receives the same terminal disposition", async () => {
  const { runtime, io } = await connectedRuntime();
  let reentrant;
  io.updater.verify = () => {
    reentrant = runtime.applyShellUpdate(updateRequest());
    return { accepted: true };
  };
  const first = await runtime.applyShellUpdate(updateRequest());
  assert.deepEqual(await reentrant, first);
  assert.equal(io.calls.filter(([name]) => name === "apply").length, 1);
});

test("an in-flight update fences connection until restart is observed", async () => {
  const { runtime, io } = await connectedRuntime();
  const applying = deferred();
  const entered = deferred();
  io.updater.apply = () => {
    entered.resolve();
    return applying.promise;
  };
  const pending = runtime.applyShellUpdate(updateRequest());
  await entered.promise;
  const duplicate = runtime.applyShellUpdate(updateRequest());
  await assert.rejects(
    runtime.connectRuntime({
      endpointId: "runtime.1",
      manifestDigest: D1,
      protocolVersion: 1,
    }),
    /already in progress/,
  );
  assert.equal(io.calls.filter(([name]) => name === "connect").length, 1);
  applying.resolve({ terminalObserved: true, restarted: true });
  const disposition = await pending;
  assert.equal(disposition.status, "succeeded");
  assert.deepEqual(await duplicate, disposition);
  await runtime.connectRuntime({
    endpointId: "runtime.1",
    manifestDigest: D1,
    protocolVersion: 1,
  });
  assert.equal(io.calls.filter(([name]) => name === "connect").length, 2);
});

test("unknown apply outcome is retained across reconnect without reapplying", async () => {
  const { runtime, io } = await connectedRuntime();
  let applied = 0;
  io.updater.apply = async () => {
    applied += 1;
    throw new Error("lost update observation");
  };
  const quarantined = await runtime.applyShellUpdate(updateRequest());
  assert.equal(quarantined.status, "quarantined");
  await runtime.connectRuntime({
    endpointId: "runtime.1",
    manifestDigest: D1,
    protocolVersion: 1,
  });
  assert.deepEqual(
    await runtime.applyShellUpdate(updateRequest()),
    quarantined,
  );
  assert.equal(applied, 1);
  assert.equal(io.calls.filter(([name]) => name === "rollback").length, 1);
});

test("update generator identity is required before verification", async () => {
  const { runtime, io } = await connectedRuntime();
  await assert.rejects(
    runtime.applyShellUpdate(updateRequest({ generatorPrincipal: undefined })),
    /generatorPrincipal/,
  );
  assert.equal(
    io.calls.some(([name]) => name === "verify"),
    false,
  );
});
