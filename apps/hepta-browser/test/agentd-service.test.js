import assert from "node:assert/strict";
import test from "node:test";
import { PassThrough } from "node:stream";

import {
  AgentdBrowserChannel,
  BrowserAgentdService,
  ParentFinalUseAuthority,
} from "../src/agentd-service.js";
import {
  buildAgentdBrowserFrame,
  encodeAgentdBrowserFrame,
  normalizeAgentdBrowserFrame,
} from "../src/agentd-protocol.js";

const D1 = "1".repeat(64);
const W1 = "a".repeat(64);

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
        { requestDigest: D1, authorityEpoch: 7, operationId: input.operationId },
        async (witness) => {
          events.push("inside_fence");
          assert.equal(witness.witnessDigest, W1);
          // This resolves at the durable/local-dispatch boundary. Remote page
          // terminality is deliberately not part of the authority callback.
          return { kind: "BrowserEffectObservationV1", status: "indeterminate", terminalObserved: false };
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

test("navigate request challenges Agentd before local dispatch and reports the boundary before response", async () => {
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
    input: { operationId: "operation.1" },
  });

  const challenge = await channels.parent.nextFrame();
  assert.equal(challenge.kind, "authority_challenge");
  assert.equal(challenge.requestId, "request.1");
  assert.equal(challenge.payload.requestDigest, D1);
  assert.equal(challenge.payload.authorityEpoch, 7);
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
    payload: { method: "observe_page", input: { profileId: "profile.1" } },
  });
  assert.throws(
    () => normalizeAgentdBrowserFrame({ ...frame, payloadDigest: D1 }),
    /payload digest mismatch/,
  );
  const encoded = encodeAgentdBrowserFrame(frame);
  assert.equal(encoded.readUInt32BE(0), encoded.length - 4);
});
