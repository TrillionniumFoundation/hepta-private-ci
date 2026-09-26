import assert from "node:assert/strict";
import test from "node:test";
import { PassThrough } from "node:stream";
import { canonicalDigest } from "../src/runtime-contract.js";

import {
  AgentdBrowserChannel,
  BrowserAgentdService,
  EffectAdmissionBrowserDriver,
  ParentFinalUseAuthority,
} from "../src/agentd-service.js";
import {
  buildAgentdBrowserFrame,
  encodeAgentdBrowserFrame,
  normalizeAgentdBrowserFrame,
} from "../src/agentd-protocol.js";

const D1 = "1".repeat(64);
const W1 = "a".repeat(64);
const PROCESS_ID = "servo.pid.2147483000.00000000-0000-4000-8000-000000000001";

function admission(operationId, pageRevision = 0, typedAction = undefined) {
  return {
    kind: "BrowserEffectAdmissionV1",
    operationId,
    semanticDigest: canonicalDigest({
      authorityEpoch: 7,
      operationId,
      profileGeneration: 1,
      pageGeneration: pageRevision,
      typedAction,
      verifiedUseTokenWitnessDigest: W1,
    }),
    workerGeneration: 1,
    pageRevision,
    admittedAt: 1_000,
    durableOrRecoverable: true,
  };
}

function fakeHost(authority, events) {
  return {
    async openProfile(input) {
      return { kind: "opened", profileId: input.profileId };
    },
    async admitEffectGrant(input) {
      return { kind: "grant", profileId: input.profileId };
    },
    async observePage(input) {
      return { kind: "page", profileId: input.profileId };
    },
    async navigateOrAct(input) {
      events.push("host_admitted");
      return authority.withVerifiedUse(
        {
          requestDigest: D1,
          authorityEpoch: 7,
          operationId: input.operationId,
          profileGeneration: 1,
          pageGeneration: 0,
          typedAction: input.typedAction,
        },
        async (witness) => {
          events.push("inside_fence");
          assert.equal(witness.witnessDigest, W1);
          // This resolves only after the worker reservation boundary. Remote
          // terminality is deliberately not part of the authority callback.
          return {
            kind: "BrowserEffectObservationV1",
            status: "indeterminate",
            terminalObserved: false,
            admission: admission(input.operationId, 0, input.typedAction),
          };
        },
      );
    },
    async reconcileOperation(input) {
      return { kind: "reconciled", operationId: input.operationId };
    },
    async reconcilePersistedOperation(input) {
      return { kind: "persisted", operationId: input.operationId };
    },
    async closeProfile(input) {
      return { kind: "closed", profileId: input.profileId };
    },
  };
}

function pairedChannels() {
  const parentToChild = new PassThrough();
  const childToParent = new PassThrough();
  return {
    parent: new AgentdBrowserChannel({ input: childToParent, output: parentToChild }),
    child: new AgentdBrowserChannel({ input: parentToChild, output: childToParent }),
    close() {
      parentToChild.end();
      childToParent.end();
    },
  };
}

test("navigate request challenges Agentd before admission and reports the boundary before response", async () => {
  const channels = pairedChannels();
  const events = [];
  const authority = new ParentFinalUseAuthority(channels.child);
  const service = new BrowserAgentdService({
    host: fakeHost(authority, events),
    channel: channels.child,
    authority,
  });
  const running = service.run();

  await channels.parent.send("request", "request.1", {
    method: "navigate_or_act",
    input: {
      operationId: "operation.1",
      typedAction: {
        kind: "type",
        selector: "input:nth-of-type(1)",
        text: "authority-layer-secret-must-not-cross",
      },
    },
  });

  const challenge = await channels.parent.nextFrame();
  assert.equal(challenge.kind, "authority_challenge");
  assert.equal(challenge.requestId, "request.1");
  assert.equal(challenge.payload.requestDigest, D1);
  assert.equal(challenge.payload.authorityEpoch, 7);
  assert.deepEqual(
    Object.keys(challenge.payload).sort(),
    ["authorityEpoch", "requestDigest"],
  );
  assert.equal(
    JSON.stringify(challenge.payload).includes(
      "authority-layer-secret-must-not-cross",
    ),
    false,
  );
  assert.deepEqual(events, ["host_admitted"]);

  await channels.parent.send("authority_enter", "request.1", {
    authorized: true,
    witnessDigest: W1,
    authorityEpoch: 7,
    requestDigest: D1,
  });

  const boundary = await channels.parent.nextFrame();
  assert.equal(boundary.kind, "dispatch_boundary");
  assert.equal(boundary.payload.localDispatchCrossed, true);
  assert.equal(boundary.payload.requestDigest, D1);
  assert.deepEqual(events, ["host_admitted", "inside_fence"]);

  const response = await channels.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, true);
  assert.equal(response.payload.result.status, "indeterminate");

  channels.close();
  await running;
});

test("malformed admission prevents final-use boundary acknowledgement", async () => {
  const channels = pairedChannels();
  const events = [];
  const authority = new ParentFinalUseAuthority(channels.child);
  const host = fakeHost(authority, events);
  host.navigateOrAct = async (input) =>
    authority.withVerifiedUse(
      {
        requestDigest: D1,
        authorityEpoch: 7,
        operationId: input.operationId,
        profileGeneration: 1,
        pageGeneration: 0,
      },
      async () => ({
        kind: "BrowserEffectObservationV1",
        status: "indeterminate",
        terminalObserved: false,
        admission: {
          ...admission(input.operationId),
          durableOrRecoverable: false,
        },
      }),
    );
  const service = new BrowserAgentdService({
    host,
    channel: channels.child,
    authority,
  });
  const running = service.run();

  await channels.parent.send("request", "request.bad-admission", {
    method: "navigate_or_act",
    input: { operationId: "operation.bad-admission" },
  });
  assert.equal((await channels.parent.nextFrame()).kind, "authority_challenge");
  await channels.parent.send("authority_enter", "request.bad-admission", {
    authorized: true,
    witnessDigest: W1,
    authorityEpoch: 7,
    requestDigest: D1,
  });
  const response = await channels.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, false);
  assert.match(response.payload.error, /durable or recoverable/);

  channels.close();
  await running;
});

test("pre-dispatch rejection releases the authority fence without claiming local dispatch", async () => {
  const channels = pairedChannels();
  const events = [];
  const authority = new ParentFinalUseAuthority(channels.child);
  const host = fakeHost(authority, events);
  host.navigateOrAct = async (input) => {
    events.push("host_admitted");
    try {
      return await authority.withVerifiedUse(
        {
          requestDigest: D1,
          authorityEpoch: 7,
          operationId: input.operationId,
        },
        async () => {
          events.push("inside_fence");
          throw Object.assign(new Error("stale worker snapshot"), {
            code: "BROWSER_WORKER_PRE_DISPATCH_REJECTED",
          });
        },
      );
    } catch (error) {
      assert.equal(error.code, "BROWSER_WORKER_PRE_DISPATCH_REJECTED");
      return {
        kind: "BrowserEffectObservationV1",
        status: "failed",
        terminalObserved: true,
        observationReason: "worker_rejected_before_dispatch",
      };
    }
  };
  const service = new BrowserAgentdService({
    host,
    channel: channels.child,
    authority,
  });
  const running = service.run();

  await channels.parent.send("request", "request.reject", {
    method: "navigate_or_act",
    input: { operationId: "operation.reject" },
  });
  const challenge = await channels.parent.nextFrame();
  assert.equal(challenge.kind, "authority_challenge");

  await channels.parent.send("authority_enter", "request.reject", {
    authorized: true,
    witnessDigest: W1,
    authorityEpoch: 7,
    requestDigest: D1,
  });

  const rejected = await channels.parent.nextFrame();
  assert.equal(rejected.kind, "dispatch_rejected");
  assert.equal(rejected.payload.localDispatchCrossed, false);
  assert.equal(rejected.payload.requestDigest, D1);

  const response = await channels.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, true);
  assert.equal(response.payload.result.status, "failed");
  assert.equal(
    response.payload.result.observationReason,
    "worker_rejected_before_dispatch",
  );
  assert.deepEqual(events, ["host_admitted", "inside_fence"]);

  channels.close();
  await running;
});

test("proven containment releases the fence conservatively as crossed", async () => {
  const channels = pairedChannels();
  const authority = new ParentFinalUseAuthority(channels.child);
  const host = fakeHost(authority, []);
  host.navigateOrAct = async (input) => {
    try {
      return await authority.withVerifiedUse(
        {
          requestDigest: D1,
          authorityEpoch: 7,
          operationId: input.operationId,
          profileGeneration: 1,
          pageGeneration: 0,
        },
        async () => {
          throw Object.assign(new Error("admission acknowledgement lost"), {
            workerContained: true,
            containmentDigest: D1,
          });
        },
      );
    } catch {
      return {
        kind: "BrowserEffectObservationV1",
        status: "indeterminate",
        terminalObserved: false,
      };
    }
  };
  const service = new BrowserAgentdService({
    host,
    channel: channels.child,
    authority,
  });
  const running = service.run();

  await channels.parent.send("request", "request.contained", {
    method: "navigate_or_act",
    input: { operationId: "operation.contained" },
  });
  assert.equal((await channels.parent.nextFrame()).kind, "authority_challenge");
  await channels.parent.send("authority_enter", "request.contained", {
    authorized: true,
    witnessDigest: W1,
    authorityEpoch: 7,
    requestDigest: D1,
  });
  const boundary = await channels.parent.nextFrame();
  assert.equal(boundary.kind, "dispatch_boundary");
  assert.equal(boundary.payload.localDispatchCrossed, true);
  const response = await channels.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.result.status, "indeterminate");

  channels.close();
  await running;
});

test("authority witness drift fails closed without a dispatch-boundary acknowledgement", async () => {
  const channels = pairedChannels();
  const events = [];
  const authority = new ParentFinalUseAuthority(channels.child);
  const service = new BrowserAgentdService({
    host: fakeHost(authority, events),
    channel: channels.child,
    authority,
  });
  const running = service.run();

  await channels.parent.send("request", "request.2", {
    method: "navigate_or_act",
    input: { operationId: "operation.2" },
  });
  const challenge = await channels.parent.nextFrame();
  assert.equal(challenge.kind, "authority_challenge");

  await channels.parent.send("authority_enter", "request.2", {
    authorized: true,
    witnessDigest: W1,
    authorityEpoch: 8,
    requestDigest: D1,
  });
  const response = await channels.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, false);
  assert.match(response.payload.error, /does not bind/);
  assert.deepEqual(events, ["host_admitted"]);

  channels.close();
  await running;
});

test("effect admission driver emits exact receipt and makes containment monotonic", async () => {
  let contained = false;
  let dispatchShouldFail = false;
  const inner = {
    supportsAbort: true,
    maxActiveProfiles: 4,
    maxOutstandingOperations: 8,
    async start() {
      return { processId: PROCESS_ID, started: true };
    },
    async observe() {
      return { observed: true };
    },
    async dispatch() {
      if (dispatchShouldFail) throw new Error("boundary acknowledgement lost");
      return { terminalObserved: false };
    },
    async reconcile() {
      return { terminalObserved: false };
    },
    async reconcilePersisted() {
      return { terminalObserved: false };
    },
    async contain() {
      contained = true;
      return { contained: true };
    },
    async stop() {
      return { stopped: true };
    },
  };
  const driver = new EffectAdmissionBrowserDriver({
    driver: inner,
    clock: () => 1_234,
  });
  await driver.start({
    profileId: "profile.1",
    generation: 1,
    expiresAtMs: 10_000,
  });
  const admitted = await driver.dispatch({
    profileId: "profile.1",
    profileGeneration: 1,
    processId: PROCESS_ID,
    pageGeneration: 7,
    operationId: "operation.1",
  });
  assert.deepEqual(
    Object.keys(admitted.admission).sort(),
    [
      "admittedAt",
      "durableOrRecoverable",
      "kind",
      "operationId",
      "pageRevision",
      "semanticDigest",
      "workerGeneration",
    ],
  );
  assert.equal(admitted.admission.kind, "BrowserEffectAdmissionV1");
  assert.equal(admitted.admission.operationId, "operation.1");
  assert.equal(admitted.admission.workerGeneration, 1);
  assert.equal(admitted.admission.pageRevision, 7);
  assert.equal(admitted.admission.admittedAt, 1_234);
  assert.equal(admitted.admission.durableOrRecoverable, true);
  assert.match(admitted.admission.semanticDigest, /^[0-9a-f]{64}$/);

  dispatchShouldFail = true;
  await assert.rejects(
    driver.dispatch({
      profileId: "profile.1",
      profileGeneration: 1,
      processId: PROCESS_ID,
      pageGeneration: 7,
      operationId: "operation.2",
    }),
    (error) => error?.workerContained === true,
  );
  assert.equal(contained, true);
  await assert.rejects(
    driver.observe({ profileId: "profile.1", generation: 1 }),
    /profile is contained/,
  );
  const repeated = await driver.contain({
    profileId: "profile.1",
    generation: 1,
    processId: PROCESS_ID,
  });
  assert.equal(repeated.contained, true);
  assert.match(repeated.containmentDigest, /^[0-9a-f]{64}$/);
  await driver.stop({ profileId: "profile.1", generation: 1 });
});

test("Agentd service protocol rejects payload digest drift", () => {
  const frame = buildAgentdBrowserFrame({
    sequence: 1,
    kind: "request",
    requestId: "request.3",
    payload: {
      method: "observe_page",
      input: { profileId: "profile.1" },
    },
  });
  assert.throws(
    () => normalizeAgentdBrowserFrame({ ...frame, payloadDigest: D1 }),
    /payload digest mismatch/,
  );
  const encoded = encodeAgentdBrowserFrame(frame);
  assert.equal(encoded.readUInt32BE(0), encoded.length - 4);
});

test("Agentd browser channel applies bounded unread-frame backpressure", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  const channel = new AgentdBrowserChannel({ input, output });
  for (let sequence = 1; sequence <= 65; sequence += 1) {
    input.write(
      encodeAgentdBrowserFrame(
        buildAgentdBrowserFrame({
          sequence,
          kind: "request",
          requestId: `request.queue.${sequence}`,
          payload: {
            method: "observe_page",
            input: { profileId: "profile.1" },
          },
        }),
      ),
    );
  }
  await new Promise((resolve) => setImmediate(resolve));
  await assert.rejects(
    channel.nextFrame(),
    /input queue capacity is exhausted/,
  );
  input.destroy();
  output.destroy();
});
