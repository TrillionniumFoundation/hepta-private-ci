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
