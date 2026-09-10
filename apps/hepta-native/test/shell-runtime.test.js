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
  applyThrows = false,
  rollbackTerminal = true,
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
        return {
          accepted: true,
          packageDigest: input.packageDigest,
          predecessorDigest: input.predecessorDigest,
          evidenceDigest: input.evidenceDigest,
        };
      },
      async apply(input) {
        calls.push(["apply", input]);
        if (applyThrows) {
          throw new Error("simulated apply crash");
        }
        return {
          terminalObserved: terminal,
          restarted,
          packageDigest: input.packageDigest,
        };
      },
      async rollback(input) {
        calls.push(["rollback", input]);
        return {
          terminalObserved: rollbackTerminal,
          restored: rollbackTerminal,
          predecessorDigest: input.predecessorDigest,
        };
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

function platformRequest(overrides = {}) {
  return {
    operationId: "operation.1",
    action: "notify",
    resource: "notification.channel.1",
    displayedRevision: 11,
    finalPayloadDigest: D3,
    grantPayloadDigest: D3,
    ...overrides,
  };
}

function updateRequest(overrides = {}) {
  return {
    operationId: "update.1",
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

test("executes a final-payload-bound platform request", async () => {
  const { runtime } = await connectedRuntime();
  const receipt = await runtime.requestPlatformCapability(platformRequest());
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.notificationAuthority, false);
  assert.equal(receipt.sessionGeneration, 3);
  assert.equal(receipt.viewGeneration, 9);
});

test("permission denial is terminal, cached, and never invokes the platform", async () => {
  const { runtime, io } = await connectedRuntime({ permission: false });
  const input = platformRequest({
    operationId: "operation.denied",
    action: "open_path",
    resource: "path.reference.1",
  });
  const first = await runtime.requestPlatformCapability(input);
  const second = await runtime.requestPlatformCapability(input);
  assert.strictEqual(second, first);
  assert.equal(first.status, "rejected");
  assert.equal(io.calls.some(([name]) => name === "invoke"), false);
  assert.equal(io.calls.filter(([name]) => name === "permission").length, 1);
});

test("platform replay binds action resource session view and payload", async () => {
  const { runtime } = await connectedRuntime();
  await runtime.requestPlatformCapability(platformRequest());
  for (const mutation of [
    { action: "copy_text" },
    { resource: "notification.channel.2" },
    { displayedRevision: 10 },
    { finalPayloadDigest: D4, grantPayloadDigest: D4 },
  ]) {
    await assert.rejects(
      runtime.requestPlatformCapability(platformRequest(mutation)),
      /changed semantics|stale view/,
    );
  }
});

test("failed restart quarantines update only after terminal rollback", async () => {
  const { runtime, io } = await connectedRuntime({ terminal: false, restarted: false });
  const receipt = await runtime.applyShellUpdate(updateRequest());
  assert.equal(receipt.status, "quarantined");
  assert.equal(receipt.rollbackTerminalObserved, true);
  assert.equal(io.calls.some(([name]) => name === "rollback"), true);
});

test("apply exception is compensated by a verified rollback", async () => {
  const { runtime } = await connectedRuntime({ applyThrows: true });
  const receipt = await runtime.applyShellUpdate(updateRequest());
  assert.equal(receipt.status, "quarantined");
  assert.equal(receipt.rollbackTerminalObserved, true);
});

test("unverified rollback cannot be reported as quarantined success", async () => {
  const { runtime } = await connectedRuntime({
    terminal: false,
    restarted: false,
    rollbackTerminal: false,
  });
  await assert.rejects(runtime.applyShellUpdate(updateRequest()), /not terminally observed/);
});

test("update replay binds full selection and platform semantics", async () => {
  const { runtime, io } = await connectedRuntime();
  const first = await runtime.applyShellUpdate(updateRequest());
  const second = await runtime.applyShellUpdate(updateRequest());
  assert.strictEqual(second, first);
  assert.equal(io.calls.filter(([name]) => name === "apply").length, 1);
  for (const mutation of [
    { packageDigest: D4 },
    { predecessorDigest: D4 },
    { evidenceDigest: D4 },
    { selectedBy: "reviewer.2" },
    { platform: "macos" },
    { architecture: "aarch64" },
  ]) {
    await assert.rejects(
      runtime.applyShellUpdate(updateRequest(mutation)),
      /changed semantics/,
    );
  }
});

test("self-selected update is rejected", async () => {
  const { runtime } = await connectedRuntime();
  await assert.rejects(
    runtime.applyShellUpdate(
      updateRequest({ selectedBy: "generator.1", generatorPrincipal: "generator.1" }),
    ),
    /cannot be selected by its generator/,
  );
});
