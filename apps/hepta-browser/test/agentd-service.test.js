import assert from "node:assert/strict";
import test from "node:test";
import { PassThrough } from "node:stream";

import {
  AgentdBrowserChannel,
  BrowserAgentdService,
  ParentFinalUseAuthority,
} from "../src/agentd-service.js";
import {
  createBrowserEffectAdmission,
} from "../src/effect-admission.js";
import {
  buildAgentdBrowserFrame,
  encodeAgentdBrowserFrame,
  normalizeAgentdBrowserFrame,
} from "../src/agentd-protocol.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);
const D5 = "5".repeat(64);
const W1 = "a".repeat(64);

function finalUseRequest(input) {
  return Object.freeze({
    profileId: "profile.1",
    principalId: "principal.1",
    processId: "servo.process.1",
    profileGeneration: 1,
    pageGeneration: 1,
    documentDigest: D2,
    operationId: input.operationId,
    action: input.typedAction?.kind ?? "click",
    typedAction:
      input.typedAction ??
      Object.freeze({ kind: "click", selector: "button.primary" }),
    destinationOrigin: "https://example.com",
    finalPayloadDigest: D3,
    profileGrantDigest: D4,
    effectGrantDigest: D5,
    authorityEpoch: 7,
    deadlineMs: 9_000,
    requestDigest: D1,
  });
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
      const request = finalUseRequest(input);
      return authority.withVerifiedUse(request, async (witness) => {
        events.push("inside_fence");
        assert.equal(witness.witnessDigest, W1);
        const { requestDigest: _requestDigest, ...requestSemantics } = request;
        const effectSemantics = Object.freeze({
          ...requestSemantics,
          verifiedUseTokenWitnessDigest: witness.witnessDigest,
        });
        // The worker-originated admission receipt is returned before remote
        // page execution settles. Agentd must validate it before releasing the
        // final-use fence.
        return {
          kind: "BrowserEffectObservationV1",
          status: "indeterminate",
          terminalObserved: false,
          admission: createBrowserEffectAdmission(effectSemantics, {
            clock: () => 1_234,
          }),
        };
      });
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

test("navigate request challenges Agentd then returns a bound effect-admission receipt", async () => {
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
  assert.equal(
    boundary.payload.admission.kind,
    "BrowserEffectAdmissionV1",
  );
  assert.equal(boundary.payload.admission.operationId, "operation.1");
  assert.equal(boundary.payload.admission.workerGeneration, 1);
  assert.equal(boundary.payload.admission.admittedAt, 1_234);
  assert.equal(boundary.payload.admission.durableOrRecoverable, true);
  assert.deepEqual(events, ["host_admitted", "inside_fence"]);

  const response = await channels.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, true);
  assert.equal(response.payload.result.status, "indeterminate");

  channels.close();
  await running;
});

test("admission drift fails closed before Agentd receives dispatch boundary", async () => {
  const channels = pairedChannels();
  const events = [];
  const authority = new ParentFinalUseAuthority(channels.child);
  const host = fakeHost(authority, events);
  host.navigateOrAct = async (input) => {
    const request = finalUseRequest(input);
    return authority.withVerifiedUse(request, async (witness) => {
      const { requestDigest: _requestDigest, ...requestSemantics } = request;
      const effectSemantics = Object.freeze({
        ...requestSemantics,
        verifiedUseTokenWitnessDigest: witness.witnessDigest,
      });
      return {
        terminalObserved: false,
        admission: {
          ...createBrowserEffectAdmission(effectSemantics, {
            clock: () => 1_234,
          }),
          workerGeneration: 2,
        },
      };
    });
  };
  const service = new BrowserAgentdService({
    host,
    channel: channels.child,
    authority,
  });
  const running = service.run();

  await channels.parent.send("request", "request.drift", {
    method: "navigate_or_act",
    input: { operationId: "operation.drift" },
  });
  await channels.parent.nextFrame();
  await channels.parent.send("authority_enter", "request.drift", {
    authorized: true,
    witnessDigest: W1,
    authorityEpoch: 7,
    requestDigest: D1,
  });
  const response = await channels.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, false);
  assert.match(response.payload.error, /workerGeneration does not bind/);

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
        finalUseRequest(input),
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
