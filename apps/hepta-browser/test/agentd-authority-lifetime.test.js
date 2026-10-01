import assert from "node:assert/strict";
import test from "node:test";
import { once } from "node:events";
import { PassThrough, Writable } from "node:stream";
import {
  AgentdBrowserChannel,
  ParentFinalUseAuthority,
} from "../src/agentd-service.js";
import {
  AgentdBrowserFrameDecoder,
  buildAgentdBrowserFrame,
  encodeAgentdBrowserFrame,
} from "../src/agentd-protocol.js";
import { BrowserProfileHost } from "../src/runtime.js";
import { MemoryBrowserOperationJournal } from "../src/journal.js";
import { browserActionDigest } from "../src/action.js";

const D1 = "1".repeat(64);
const W1 = "a".repeat(64);
const REQUEST_ID = "request.final-use";
const REQUEST = { requestDigest: D1, authorityEpoch: 7 };

function authorization() {
  return encodeAgentdBrowserFrame(
    buildAgentdBrowserFrame({
      sequence: 1,
      kind: "authority_enter",
      requestId: REQUEST_ID,
      payload: {
        authorized: true,
        requestDigest: D1,
        authorityEpoch: 7,
        witnessDigest: W1,
      },
    }),
  );
}

test(
  "parent EOF cancels a blocked challenge and discards its buffered authorization",
  { timeout: 1_000 },
  async (t) => {
    const input = new PassThrough();
    let release;
    const output = new Writable({
      write(_chunk, _encoding, callback) {
        release = callback;
      },
    });
    t.after(() => {
      release?.();
      output.destroy();
    });
    const channel = new AgentdBrowserChannel({ input, output });
    const authority = new ParentFinalUseAuthority(channel);
    let consumed = 0;
    const call = authority.withRequest(REQUEST_ID, () =>
      authority.withVerifiedUse(REQUEST, async () => {
        consumed += 1;
      }),
    );
    const rejected = assert.rejects(call, /channel is closed/);
    const ended = once(input, "end");
    input.end(authorization());
    await ended;
    release();
    await rejected;
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(consumed, 0);
    assert.equal(await channel.nextFrame(), null);
  },
);

test("an authorization delivered immediately before EOF cannot enter the consumer microtask", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  output.resume();
  const channel = new AgentdBrowserChannel({ input, output });
  const authority = new ParentFinalUseAuthority(channel);
  let consumed = 0;
  const call = authority.withRequest(REQUEST_ID, () =>
    authority.withVerifiedUse(REQUEST, async () => {
      consumed += 1;
    }),
  );
  await new Promise((resolve) => setImmediate(resolve));
  input.write(authorization());
  input.emit("end");
  await assert.rejects(call, /channel is closed/);
  assert.equal(consumed, 0);
  output.destroy();
});

for (const closeOutput of ["destroy", "end"]) {
  test(`output ${closeOutput} fences authorization whose read already resolved`, async () => {
    const input = new PassThrough();
    const output = new PassThrough();
    output.resume();
    const channel = new AgentdBrowserChannel({ input, output });
    const authority = new ParentFinalUseAuthority(channel);
    let consumed = 0;
    const call = authority.withRequest(REQUEST_ID, () =>
      authority.withVerifiedUse(REQUEST, async () => {
        consumed += 1;
      }),
    );
    await new Promise((resolve) => setImmediate(resolve));
    input.write(authorization());
    output[closeOutput]();
    await assert.rejects(call, /output closed/);
    assert.equal(consumed, 0);
    input.end();
    output.destroy();
  });
}

test("parent EOF during a durable intent write cannot dispatch after the journal completes", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  const channel = new AgentdBrowserChannel({ input, output });
  const authority = new ParentFinalUseAuthority(channel);
  let release;
  let entered;
  const journalGate = new Promise((resolve) => {
    release = resolve;
  });
  const journalEntered = new Promise((resolve) => {
    entered = resolve;
  });
  const memory = new MemoryBrowserOperationJournal();
  const journal = {
    async recordDispatch(record) {
      await memory.recordDispatch(record);
      entered();
      await journalGate;
    },
    recordObservation: (...args) => memory.recordObservation(...args),
    getOperation: (...args) => memory.getOperation(...args),
    listOperations: (...args) => memory.listOperations(...args),
  };
  let dispatchCalls = 0;
  const driver = {
    async start() {
      return { started: true, processId: "servo.process.1" };
    },
    async observe() {
      return {
        pageGeneration: 1,
        documentDigest: D1,
        origin: "https://example.com",
      };
    },
    async dispatch() {
      dispatchCalls += 1;
      return { terminalObserved: false };
    },
    async reconcile() {
      return { terminalObserved: false };
    },
    async stop() {
      return { stopped: true };
    },
  };
  const host = new BrowserProfileHost({
    driver,
    authority,
    journal,
    clock: () => 1_000,
  });
  const typedAction = {
    kind: "navigate",
    url: "https://example.com/path",
    policyDigest: D1,
    expectedRevision: 7,
  };
  const finalPayloadDigest = browserActionDigest(typedAction);
  await host.openProfile({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    manifestDigest: D1,
    grantDigest: D1,
    expiresAtMs: 10_000,
    allowedOrigins: ["https://example.com"],
    effectGrants: [
      {
        grantDigest: D1,
        action: "navigate",
        destinationOrigin: "https://example.com",
        finalPayloadDigest,
        authorityEpoch: 7,
        expiresAtMs: 10_000,
      },
    ],
  });
  await host.observePage({
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    observationBudget: 128,
  });
  const decoder = new AgentdBrowserFrameDecoder();
  output.on("data", (chunk) => {
    for (const challenge of decoder.push(chunk)) {
      assert.equal(challenge.kind, "authority_challenge");
      input.write(
        encodeAgentdBrowserFrame(
          buildAgentdBrowserFrame({
            sequence: 1,
            kind: "authority_enter",
            requestId: challenge.requestId,
            payload: {
              authorized: true,
              requestDigest: challenge.payload.requestDigest,
              authorityEpoch: 7,
              witnessDigest: W1,
            },
          }),
        ),
      );
    }
  });
  const call = authority.withRequest(REQUEST_ID, () =>
    host.navigateOrAct({
      profileId: "profile.1",
      principalId: "principal.1",
      generation: 1,
      operationId: "operation.1",
      pageGeneration: 1,
      typedAction,
      destinationOrigin: "https://example.com",
      finalPayloadDigest,
      effectGrantDigest: D1,
      authorityEpoch: 7,
      deadlineMs: 9_000,
    }),
  );
  await journalEntered;
  const ended = once(input, "end");
  input.end();
  await ended;
  release();
  const receipt = await call;
  assert.equal(receipt.terminalObserved, false);
  assert.equal(dispatchCalls, 0);
  assert.equal((await memory.listOperations("profile.1", 1)).length, 1);
  output.destroy();
});

test("request cancellation still fences an authorization whose read already resolved", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  output.resume();
  const channel = new AgentdBrowserChannel({ input, output });
  const authority = new ParentFinalUseAuthority(channel);
  let finish;
  let pending;
  let consumed = 0;
  const gate = new Promise((resolve) => {
    finish = resolve;
  });
  const active = authority.withRequest(REQUEST_ID, () => {
    pending = authority.withVerifiedUse(REQUEST, async () => {
      consumed += 1;
    });
    return gate;
  });
  await new Promise((resolve) => setImmediate(resolve));
  const rejected = assert.rejects(pending, /request ended/);
  finish();
  input.write(authorization());
  await active;
  await rejected;
  assert.equal(consumed, 0);
  input.end();
  output.destroy();
});

test("complete queued requests are discarded when their parent channel ends", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  const channel = new AgentdBrowserChannel({ input, output });
  const ended = once(input, "end");
  input.end(
    encodeAgentdBrowserFrame(
      buildAgentdBrowserFrame({
        sequence: 1,
        kind: "request",
        requestId: "request.queued",
        payload: { method: "open_profile", input: {} },
      }),
    ),
  );
  await ended;
  assert.equal(await channel.nextFrame(), null);
  output.destroy();
});
