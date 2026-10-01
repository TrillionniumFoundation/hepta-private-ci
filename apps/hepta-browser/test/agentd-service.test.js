import assert from "node:assert/strict";
import test from "node:test";
import { PassThrough } from "node:stream";
import { BrowserProfileHost } from "../src/runtime.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";

import {
  AgentdBrowserChannel,
  BrowserAgentdService,
  ParentFinalUseAuthority,
} from "../src/agentd-service.js";
import {
  AgentdBrowserFrameDecoder,
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
        {
          requestDigest: D1,
          authorityEpoch: 7,
          operationId: input.operationId,
        },
        async (witness) => {
          events.push("inside_fence");
          assert.equal(witness.witnessDigest, W1);
          // This resolves at the durable/local-dispatch boundary. Remote page
          // terminality is deliberately not part of the authority callback.
          return {
            kind: "BrowserEffectObservationV1",
            status: "indeterminate",
            terminalObserved: false,
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
    parent: new AgentdBrowserChannel({
      input: childToParent,
      output: parentToChild,
    }),
    child: new AgentdBrowserChannel({
      input: parentToChild,
      output: childToParent,
    }),
    close() {
      parentToChild.end();
      childToParent.end();
    },
  };
}

test("the private Agentd service accepts the actual BrowserProfileHost class", async () => {
  const channels = pairedChannels();
  const authority = new ParentFinalUseAuthority(channels.child);
  const host = new BrowserProfileHost({
    driver: {
      async start() {},
      async observe() {},
      async dispatch() {},
      async reconcile() {},
      async stop() {},
    },
    authority,
    journal: new MemoryBrowserOperationJournal(),
  });
  const service = new BrowserAgentdService({
    host,
    channel: channels.child,
    authority,
  });
  const running = service.run();
  // A real owner rejection must cross the service, rather than failing to boot.
  await channels.parent.send("request", "request.actual-host", {
    method: "observe_page",
    input: { profileId: "profile.not-open" },
  });
  const response = await channels.parent.nextFrame();
  assert.equal(response.kind, "response");
  assert.equal(response.payload.ok, false);
  channels.close();
  await running;
});

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

test("failed input discards queued requests instead of executing them after protocol drift", async () => {
  const input = new PassThrough();
  const channel = new AgentdBrowserChannel({
    input,
    output: new PassThrough(),
  });
  input.write(
    encodeAgentdBrowserFrame(
      buildAgentdBrowserFrame({
        sequence: 1,
        kind: "request",
        requestId: "queued.1",
        payload: {},
      }),
    ),
  );
  input.write(
    encodeAgentdBrowserFrame(
      buildAgentdBrowserFrame({
        sequence: 3,
        kind: "request",
        requestId: "drift.1",
        payload: {},
      }),
    ),
  );
  await assert.rejects(channel.nextFrame(), /not monotonic/);
});

test("queued requests have a hard count ceiling and overflow fences the channel", async () => {
  const input = new PassThrough();
  const channel = new AgentdBrowserChannel({
    input,
    output: new PassThrough(),
  });
  for (let sequence = 1; sequence <= 65; sequence += 1) {
    input.write(
      encodeAgentdBrowserFrame(
        buildAgentdBrowserFrame({
          sequence,
          kind: "request",
          requestId: `queued.${sequence}`,
          payload: {},
        }),
      ),
    );
  }
  await assert.rejects(channel.nextFrame(), /queue exceeds limit/);
});

test("queued payloads have a byte ceiling as well as a count ceiling", async () => {
  const input = new PassThrough();
  const channel = new AgentdBrowserChannel({
    input,
    output: new PassThrough(),
  });
  for (let sequence = 1; sequence <= 6; sequence += 1) {
    input.write(
      encodeAgentdBrowserFrame(
        buildAgentdBrowserFrame({
          sequence,
          kind: "request",
          requestId: `queued.${sequence}`,
          payload: { text: "x".repeat(800_000) },
        }),
      ),
    );
  }
  await assert.rejects(channel.nextFrame(), /queue exceeds limit/);
});

test("failed output permanently fences the channel", async () => {
  const error = new Error("injected failed write");
  let writes = 0;
  const channel = new AgentdBrowserChannel({
    input: new PassThrough(),
    output: {
      write(_bytes, callback) {
        writes += 1;
        callback(error);
      },
    },
  });
  await assert.rejects(
    channel.send("request", "write.1", {}),
    /injected failed write/,
  );
  await assert.rejects(
    channel.send("request", "write.2", {}),
    /injected failed write/,
  );
  await assert.rejects(channel.nextFrame(), /injected failed write/);
  assert.equal(writes, 1);
});

test("rejected local serialization does not consume an outgoing sequence", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  const chunks = [];
  output.on("data", (chunk) => chunks.push(chunk));
  const channel = new AgentdBrowserChannel({ input, output });
  assert.throws(
    () => channel.send("unregistered", "write.1", {}),
    /not registered/,
  );
  await channel.send("request", "write.1", {});
  const frames = new AgentdBrowserFrameDecoder().push(Buffer.concat(chunks));
  assert.equal(frames[0].sequence, 1);
});

test("unexpected readable close rejects a pending channel read", async () => {
  const input = new PassThrough();
  const channel = new AgentdBrowserChannel({
    input,
    output: new PassThrough(),
  });
  const pending = channel.nextFrame();
  input.destroy();
  await assert.rejects(pending, /closed unexpectedly/);
});

test("Agentd decoding rejects malformed UTF-8 even when lossy decoding would match its digest", () => {
  const encoded = encodeAgentdBrowserFrame(
    buildAgentdBrowserFrame({
      sequence: 1,
      kind: "request",
      requestId: "unicode.1",
      payload: { text: "�" },
    }),
  );
  const start = encoded.indexOf(Buffer.from("�", "utf8"));
  const corrupted = Buffer.concat([
    encoded.subarray(0, start + 2),
    encoded.subarray(start + 3),
  ]);
  corrupted.writeUInt32BE(corrupted.length - 4, 0);
  assert.throws(
    () => new AgentdBrowserFrameDecoder().push(corrupted),
    /not valid UTF-8/,
  );
});

test("Agentd serialization rejects Unicode and sparse arrays that Rust cannot canonicalize", () => {
  for (const payload of [
    { text: "\ud800" },
    { "\udfff": "value" },
    { values: Array(1) },
  ]) {
    assert.throws(() =>
      buildAgentdBrowserFrame({
        sequence: 1,
        kind: "request",
        requestId: "unicode.2",
        payload,
      }),
    );
  }
});

test("an ended authority request cancels its pending read before another request arrives", async () => {
  const channels = pairedChannels();
  const authority = new ParentFinalUseAuthority(channels.child);
  let pending;
  await authority.withRequest("request.cancelled", async () => {
    pending = authority.withVerifiedUse(
      { requestDigest: D1, authorityEpoch: 7 },
      async () => {
        throw new Error("cancelled consumer must not run");
      },
    );
    pending.catch(() => {});
    assert.equal(
      (await channels.parent.nextFrame()).kind,
      "authority_challenge",
    );
  });
  await assert.rejects(pending, /ended before authorization completed/);
  await channels.parent.send("request", "request.next", {
    method: "observe_page",
    input: {},
  });
  assert.equal((await channels.child.nextFrame()).requestId, "request.next");
  channels.close();
});
