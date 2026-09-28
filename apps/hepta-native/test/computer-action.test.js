import assert from "node:assert/strict";
import test from "node:test";

import {
  InlineNativeReferenceResolver,
  nativePlatformPayloadDigestV1,
} from "../src/computer-action.js";
import { NativeShellRuntime } from "../src/shell-runtime.js";
import {
  computerActionAuthorityBindingDigestV1,
  computerActionPayloadDigestV1,
  encodeComputerActionFrameV1,
} from "../../../codex-rs/hepta-wire/js/computer-action-ir.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);

function ioFixture() {
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
        return { allowed: true, outcomeDigest: D4 };
      },
      async invoke(input) {
        calls.push(["invoke", input]);
        return { terminalObserved: true, status: "succeeded", outcomeDigest: D4 };
      },
    },
    updater: {
      async verify() {
        return { accepted: true };
      },
      async apply() {
        return { terminalObserved: true, restarted: true };
      },
      async rollback() {},
    },
  };
}

function notifyFrame(resource, overrides = {}) {
  const payload = { kind: "reference", referenceId: "notification.1" };
  return {
    operationId: "operation.binary.1",
    subjectId: "principal.1",
    actuatorId: "native-shell",
    opcode: "notify_reference",
    targetRef: null,
    bodyGeneration: 9,
    sessionGeneration: 3,
    observationRevision: 11,
    deadlineMonotonicMicros: 2_000_000,
    preconditionDigest: D2,
    argumentPayloadDigest: computerActionPayloadDigestV1("notify_reference", payload),
    finalPayloadDigest: nativePlatformPayloadDigestV1("notify", resource),
    expectedPostconditionDigest: D3,
    payload,
    ...overrides,
  };
}

async function connected({ resolver, monotonicMicros = () => 1_000_000 } = {}) {
  const io = ioFixture();
  const runtime = new NativeShellRuntime({
    ...io,
    principalId: "principal.1",
    binaryResolver:
      resolver ??
      new InlineNativeReferenceResolver([
        { referenceId: "notification.1", resource: "notification.channel.1" },
      ]),
    clock: () => 1_000,
    monotonicMicros,
  });
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

test("binary native action resolves through the existing platform owner exactly once", async () => {
  const resource = "notification.channel.1";
  const frame = notifyFrame(resource);
  const { runtime, io } = await connected();
  const receipt = await runtime.requestPlatformCapabilityBinary({
    frameBytes: encodeComputerActionFrameV1(frame),
    grantPayloadDigest: frame.finalPayloadDigest,
  });
  assert.equal(receipt.status, "succeeded");
  assert.equal(receipt.operationId, "operation.binary.1");
  assert.equal(
    receipt.sourceActionDigest,
    computerActionAuthorityBindingDigestV1(frame),
  );
  const permission = io.calls.find(([name]) => name === "permission");
  const invoke = io.calls.find(([name]) => name === "invoke");
  assert.equal(permission[1].resource, resource);
  assert.equal(permission[1].sourceActionDigest, receipt.sourceActionDigest);
  assert.equal(invoke[1].finalPayloadDigest, frame.finalPayloadDigest);
  assert.equal(invoke[1].sourceActionDigest, receipt.sourceActionDigest);

  const replay = await runtime.requestPlatformCapabilityBinary({
    frameBytes: encodeComputerActionFrameV1(frame),
    grantPayloadDigest: frame.finalPayloadDigest,
  });
  assert.deepEqual(replay, receipt);
  assert.equal(io.calls.filter(([name]) => name === "permission").length, 1);
  assert.equal(io.calls.filter(([name]) => name === "invoke").length, 1);
});

test("resolved-resource substitution fails before platform permission", async () => {
  const resource = "notification.channel.1";
  const resolver = new InlineNativeReferenceResolver([
    { referenceId: "notification.1", resource: "notification.other" },
  ]);
  const { runtime, io } = await connected({ resolver });
  await assert.rejects(
    runtime.requestPlatformCapabilityBinary({
      frameBytes: encodeComputerActionFrameV1(notifyFrame(resource)),
      grantPayloadDigest: nativePlatformPayloadDigestV1("notify", resource),
    }),
    /does not match finalPayloadDigest/,
  );
  assert.equal(io.calls.some(([name]) => name === "permission"), false);
  assert.equal(io.calls.some(([name]) => name === "invoke"), false);
});

test("subject, view, precondition and deadline drift fail before effect boundary", async () => {
  const resource = "notification.channel.1";
  const { runtime, io } = await connected();
  const cases = [
    [notifyFrame(resource, { subjectId: "principal.other" }), /subject mismatch/],
    [notifyFrame(resource, { sessionGeneration: 4 }), /session generation mismatch/],
    [notifyFrame(resource, { bodyGeneration: 10 }), /view generation mismatch/],
    [notifyFrame(resource, { observationRevision: 12 }), /observation revision mismatch/],
    [notifyFrame(resource, { preconditionDigest: D1 }), /precondition/],
    [notifyFrame(resource, { deadlineMonotonicMicros: 1_000_000 }), /deadline has expired/],
  ];
  for (const [frame, pattern] of cases) {
    await assert.rejects(
      runtime.requestPlatformCapabilityBinary({
        frameBytes: encodeComputerActionFrameV1(frame),
        grantPayloadDigest: frame.finalPayloadDigest,
      }),
      pattern,
    );
  }
  assert.equal(io.calls.some(([name]) => name === "permission"), false);
  assert.equal(io.calls.some(([name]) => name === "invoke"), false);
});

test("grant payload drift and operation reuse with another frame fail closed", async () => {
  const resource = "notification.channel.1";
  const frame = notifyFrame(resource);
  const { runtime, io } = await connected();
  await assert.rejects(
    runtime.requestPlatformCapabilityBinary({
      frameBytes: encodeComputerActionFrameV1(frame),
      grantPayloadDigest: D4,
    }),
    /grant does not bind/,
  );
  assert.equal(io.calls.some(([name]) => name === "permission"), false);

  await runtime.requestPlatformCapabilityBinary({
    frameBytes: encodeComputerActionFrameV1(frame),
    grantPayloadDigest: frame.finalPayloadDigest,
  });
  const changed = notifyFrame(resource, { expectedPostconditionDigest: D4 });
  await assert.rejects(
    runtime.requestPlatformCapabilityBinary({
      frameBytes: encodeComputerActionFrameV1(changed),
      grantPayloadDigest: changed.finalPayloadDigest,
    }),
    /operation identity was reused/,
  );
  assert.equal(io.calls.filter(([name]) => name === "invoke").length, 1);
});

test("inline native resolver is bounded and closed-world", async () => {
  const resolver = new InlineNativeReferenceResolver([
    { referenceId: "text.1", resource: "hello" },
  ]);
  assert.deepEqual(
    await resolver.resolve({
      kind: "reference",
      referenceId: "text.1",
      operationId: "operation.1",
      subjectId: "principal.1",
    }),
    { resource: "hello" },
  );
  await assert.rejects(
    resolver.resolve({
      kind: "reference",
      referenceId: "text.missing",
      operationId: "operation.1",
      subjectId: "principal.1",
    }),
    /not admitted/,
  );
  assert.throws(
    () =>
      new InlineNativeReferenceResolver([
        { referenceId: "text.1", resource: "one" },
        { referenceId: "text.1", resource: "two" },
      ]),
    /duplicated/,
  );
});


test("binary resolution cannot cross a changed view", async () => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const {runtime, io} = await connected({ resolver: { resolve: () => pending } });
  const frame = notifyFrame("notification.channel.1");
  const execution = runtime.requestPlatformCapabilityBinary({
    frameBytes: encodeComputerActionFrameV1(frame), grantPayloadDigest: frame.finalPayloadDigest });
  runtime.renderRuntimeView({ sessionId: "session.1", sessionGeneration: 3,
    generation: 9, revision: 12, digest: D2, modules: [] });
  release({ resource: "notification.channel.1" });
  await assert.rejects(execution, /context changed/);
  assert.equal(io.calls.some(([name]) => name === "invoke"), false);
});

test("binary input bytes are frozen before asynchronous resolution", async () => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const {runtime, io} = await connected({ resolver: { resolve: () => pending } });
  const frame = notifyFrame("notification.channel.1");
  const frameBytes = encodeComputerActionFrameV1(frame);
  const execution = runtime.requestPlatformCapabilityBinary({ frameBytes,
    grantPayloadDigest: frame.finalPayloadDigest });
  frameBytes.fill(0);
  release({ resource: "notification.channel.1" });
  const receipt = await execution;
  assert.equal(receipt.sourceActionDigest, computerActionAuthorityBindingDigestV1(frame));
  assert.equal(io.calls.filter(([name]) => name === "invoke").length, 1);
});

test("binary permission cannot outlive the monotonic deadline", async () => {
  let now = 1_000_000;
  const {runtime, io} = await connected({ monotonicMicros: () => now });
  io.platform.permission = async () => { now = 2_000_000; return {allowed:true}; };
  const frame = notifyFrame("notification.channel.1");
  await assert.rejects(runtime.requestPlatformCapabilityBinary({
    frameBytes: encodeComputerActionFrameV1(frame), grantPayloadDigest: frame.finalPayloadDigest }),
    /deadline has expired/);
  assert.equal(io.calls.some(([name]) => name === "invoke"), false);
});

test("timed out binary invocation remains unknown and never reinvokes", async () => {
  const {runtime, io} = await connected();
  let calls = 0, release;
  io.platform.invoke = () => { calls++; return new Promise((resolve) => { release=resolve; }); };
  const frame = notifyFrame("notification.channel.1", {deadlineMonotonicMicros:1_005_000});
  const input = {frameBytes:encodeComputerActionFrameV1(frame),grantPayloadDigest:frame.finalPayloadDigest};
  const receipt = await runtime.requestPlatformCapabilityBinary(input);
  assert.equal(receipt.status,"indeterminate");
  assert.equal(receipt.terminalObserved,false);
  release({terminalObserved:true,status:"succeeded",outcomeDigest:D4});
  assert.deepEqual(await runtime.requestPlatformCapabilityBinary(input),receipt);
  assert.equal(calls,1);
});

test("late resolver completion cannot dispatch after a timeout", async () => {
  let release;
  const pending = new Promise((resolve) => { release=resolve; });
  const {runtime, io} = await connected({resolver:{resolve:()=>pending}});
  const frame = notifyFrame("notification.channel.1",{deadlineMonotonicMicros:1_005_000});
  await assert.rejects(runtime.requestPlatformCapabilityBinary({
    frameBytes:encodeComputerActionFrameV1(frame),grantPayloadDigest:frame.finalPayloadDigest}), /deadline/);
  release({resource:"notification.channel.1"});
  await new Promise(setImmediate);
  assert.equal(io.calls.some(([name])=>name==="invoke"),false);
});
