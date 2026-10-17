import assert from "node:assert/strict";
import test from "node:test";

import { createAuthorityFreeAgentdBridge } from "../src/agentd_bridge.js";

const digest = "ab".repeat(32);

function proposal(overrides = {}) {
  return {
    scopeId: "scope-1",
    operationId: "operation-1",
    subjectId: "runtime.agentd",
    payloadDigest: digest,
    action: "request_reconcile",
    expectedResourceRevision: 9,
    expectedBodyGeneration: 4,
    expectedAuthorityEpoch: 12,
    clientRequestId: "request-1",
    payload: { reason: "operator-request" },
    ...overrides,
  };
}

function fakePort(overrides = {}) {
  return {
    readRuntime: () => ({
      moduleId: "runtime.agentd",
      generation: 4,
      lifecycle: "ready",
      revision: 9,
      stateDigest: digest,
      ready: true,
      providerPayload: { secret: "must-not-cross" },
    }),
    submitProposal: (value) => ({
      scopeId: value.scopeId,
      operationId: value.operationId,
      payloadDigest: value.payloadDigest,
      status: "accepted",
      observedResourceRevision: value.expectedResourceRevision,
      observedBodyGeneration: value.expectedBodyGeneration,
      observedAuthorityEpoch: value.expectedAuthorityEpoch,
    }),
    ...overrides,
  };
}

test("bridge exposes only a bounded runtime projection", () => {
  const bridge = createAuthorityFreeAgentdBridge(fakePort());
  const snapshot = bridge.readRuntime({
    moduleId: "runtime.agentd",
    expectedGeneration: 4,
  });
  assert.deepEqual(snapshot, {
    moduleId: "runtime.agentd",
    generation: 4,
    lifecycle: "ready",
    revision: 9,
    stateDigest: digest,
    ready: true,
    authorityGranted: false,
    directStoreWrite: false,
  });
  assert.equal("providerPayload" in snapshot, false);
  assert.equal("socketPath" in bridge, false);
  assert.equal("controlFd" in snapshot, false);
  assert.equal(Object.isFrozen(snapshot), true);
});

test("bridge rejects stale runtime generations", () => {
  const bridge = createAuthorityFreeAgentdBridge(fakePort());
  assert.throws(
    () => bridge.readRuntime({ moduleId: "runtime.agentd", expectedGeneration: 5 }),
    /stale generation/,
  );
});

test("bridge forwards a value-only proposal and returns admission receipt", () => {
  let forwarded;
  const bridge = createAuthorityFreeAgentdBridge(
    fakePort({
      submitProposal: (value) => {
        forwarded = value;
        return {
          scopeId: value.scopeId,
          operationId: value.operationId,
          payloadDigest: value.payloadDigest,
          status: "accepted",
          observedResourceRevision: 9,
          observedBodyGeneration: 4,
          observedAuthorityEpoch: 12,
        };
      },
    }),
  );
  const receipt = bridge.submitProposal(proposal());
  assert.equal(forwarded.scopeId, "scope-1");
  assert.equal(forwarded.operationId, "operation-1");
  assert.deepEqual(receipt, {
    scopeId: "scope-1",
    operationId: "operation-1",
    payloadDigest: digest,
    status: "accepted",
    observedResourceRevision: 9,
    observedBodyGeneration: 4,
    observedAuthorityEpoch: 12,
    message: "",
    exposesDeliveryIdentity: false,
  });
  assert.equal(Object.isFrozen(receipt), true);
  assert.equal("bootId" in receipt, false);
  assert.equal("capSpaceId" in receipt, false);
  assert.equal("sequence" in receipt, false);
});

test("bridge rejects pointer, socket, and final-use fields", () => {
  for (const key of [
    "requestAddr",
    "controlFd",
    "deviceFd",
    "capSpaceId",
    "bootId",
    "sequence",
    "finalUse",
    "signature",
    "socketPath",
  ]) {
    assert.throws(
      () => createAuthorityFreeAgentdBridge(fakePort()).submitProposal(
        proposal({ payload: { [key]: "forbidden" } }),
      ),
      /forbidden field/,
      key,
    );
    assert.throws(
      () => createAuthorityFreeAgentdBridge(fakePort()).submitProposal(
        proposal({ [key]: "forbidden" }),
      ),
      /forbidden field/,
      `top-level ${key}`,
    );
  }
});

test("bridge rejects digest, action, receipt, and authority mismatches", () => {
  const bridge = createAuthorityFreeAgentdBridge(fakePort());
  assert.throws(
    () => bridge.submitProposal(proposal({ payloadDigest: "not-a-digest" })),
    /digest/,
  );
  assert.throws(
    () => bridge.submitProposal(proposal({ action: "grant_capability" })),
    /not registered/,
  );
  assert.throws(
    () =>
      createAuthorityFreeAgentdBridge(
        fakePort({
          submitProposal: (value) => ({
            scopeId: value.scopeId,
            operationId: "different-operation",
            payloadDigest: value.payloadDigest,
            status: "accepted",
            observedResourceRevision: 9,
            observedBodyGeneration: 4,
            observedAuthorityEpoch: 12,
          }),
        }),
      ).submitProposal(proposal()),
    /changed durable K/,
  );
  assert.throws(
    () =>
      createAuthorityFreeAgentdBridge(
        fakePort({
          readRuntime: () => ({
            moduleId: "runtime.agentd",
            generation: 4,
            lifecycle: "ready",
            revision: 9,
            stateDigest: digest,
            ready: true,
            authorityGranted: true,
          }),
        }),
      ).readRuntime({ moduleId: "runtime.agentd", expectedGeneration: 4 }),
    /cannot advertise authority/,
  );
  assert.throws(
    () =>
      createAuthorityFreeAgentdBridge(
        fakePort({
          submitProposal: (value) => ({
            scopeId: value.scopeId,
            operationId: value.operationId,
            payloadDigest: value.payloadDigest,
            status: "accepted",
            observedResourceRevision: 8,
            observedBodyGeneration: 4,
            observedAuthorityEpoch: 12,
          }),
        }),
      ).submitProposal(proposal()),
    /regressed resource revision/,
  );
});

test("bridge requires a narrow module-port shape and does not expose the port", () => {
  assert.throws(() => createAuthorityFreeAgentdBridge({}), /implement/);
  const bridge = createAuthorityFreeAgentdBridge(fakePort());
  assert.equal(Object.keys(bridge).sort().join(","), "readRuntime,submitProposal");
});

