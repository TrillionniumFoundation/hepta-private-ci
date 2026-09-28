import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { AgentdBrowserChannel, ParentFinalUseAuthority } from "../src/agentd-service.js";
import { buildAgentdBrowserFrame, encodeAgentdBrowserFrame } from "../src/agentd-protocol.js";

const D = "1".repeat(64);
const W = "2".repeat(64);
const request = { requestDigest: D, authorityEpoch: 7 };
const witness = { ...request, authorized: true, witnessDigest: W };
const frame = (sequence, payload = {}, kind = "request", requestId = "r.1") =>
  encodeAgentdBrowserFrame(buildAgentdBrowserFrame({ sequence, kind, requestId, payload }));
const tick = () => new Promise((resolve) => setImmediate(resolve));

function channel(output = new PassThrough()) {
  const input = new PassThrough();
  return { input, output, value: new AgentdBrowserChannel({ input, output }) };
}

function pair() {
  const a = new PassThrough();
  const b = new PassThrough();
  return {
    parent: new AgentdBrowserChannel({ input: b, output: a }),
    child: new AgentdBrowserChannel({ input: a, output: b }),
    close: () => { a.end(); b.end(); },
  };
}

test("failed input discards queued requests instead of delivering after failure", async () => {
  const c = channel();
  c.input.write(frame(1));
  c.input.emit("error", new Error("lost input"));
  await assert.rejects(c.value.nextFrame(), /lost input/);
});

test("one malformed sequence poisons the whole batch before resolving a reader", async () => {
  const c = channel();
  const next = assert.rejects(c.value.nextFrame(), /not monotonic/);
  c.input.write(Buffer.concat([frame(1), frame(1)]));
  await next;
  await assert.rejects(c.value.nextFrame(), /not monotonic/);
});

test("receive queue count is bounded across multiple separately valid chunks", async () => {
  const c = channel();
  for (let sequence = 1; sequence <= 65; sequence++) c.input.write(frame(sequence));
  await assert.rejects(c.value.nextFrame(), /capacity/);
});

test("receive queue bytes are bounded even below the frame-count ceiling", async () => {
  const c = channel();
  for (let sequence = 1; sequence <= 5; sequence++) {
    c.input.write(frame(sequence, { text: "a".repeat(900_000) }));
  }
  await assert.rejects(c.value.nextFrame(), /capacity/);
});

test("consuming queued input returns capacity without resetting sequence identity", async () => {
  const c = channel();
  for (let sequence = 1; sequence <= 160; sequence++) {
    c.input.write(frame(sequence));
    assert.equal((await c.value.nextFrame()).sequence, sequence);
  }
  c.input.end();
  assert.equal(await c.value.nextFrame(), null);
});

test("write callback failure also prevents queued input and future writes", async () => {
  const output = new EventEmitter();
  output.write = (_bytes, done) => done(new Error("write lost"));
  const c = channel(output);
  c.input.write(frame(1));
  await assert.rejects(c.value.send("response", "r.1", {}), /write lost/);
  await assert.rejects(c.value.nextFrame(), /write lost/);
  await assert.rejects(c.value.send("response", "r.2", {}), /write lost/);
});

test("synchronous write failure poisons the same channel", async () => {
  const output = { write() { throw new Error("synchronous write lost"); } };
  const c = channel(output);
  c.input.write(frame(1));
  await assert.rejects(c.value.send("response", "r.1", {}), /write lost/);
  await assert.rejects(c.value.nextFrame(), /write lost/);
});

test("output pending-count backpressure does not consume an outgoing sequence", async () => {
  const callbacks = [];
  const output = { write(bytes, done) { callbacks.push({ bytes, done }); } };
  const c = channel(output);
  const writes = Array.from({ length: 8 }, (_, i) => c.value.send("response", `r.${i}`, {}));
  // Catch a regression's extra write without hanging the test on its callback.
  let state = "pending";
  const extra = c.value.send("response", "r.extra", {}).then(
    () => { state = "resolved"; }, () => { state = "rejected"; },
  );
  await tick();
  const observed = state;
  for (const item of [...callbacks]) item.done();
  await Promise.all([...writes, extra]);
  assert.equal(observed, "rejected");
  const next = c.value.send("response", "r.next", {});
  assert.equal(JSON.parse(callbacks.at(-1).bytes.subarray(4)).sequence, 9);
  callbacks.at(-1).done();
  await next;
});

test("output stream failure promptly rejects all outstanding writes", async () => {
  const output = new EventEmitter();
  const callbacks = [];
  output.write = (_bytes, done) => callbacks.push(done);
  const c = channel(output);
  const pending = [c.value.send("response", "r.1", {}), c.value.send("response", "r.2", {})];
  const settled = pending.map((promise) => promise.then(() => "success", () => "failure"));
  output.emit("error", new Error("stream failed"));
  await tick();
  let completed = false;
  const all = Promise.all(settled).then((values) => { completed = true; return values; });
  await tick();
  const promptly = completed;
  for (const done of callbacks) done();
  assert.deepEqual(await all, ["failure", "failure"]);
  assert.equal(promptly, true);
});

test("invalid output payload does not create a sequence hole", async () => {
  const p = pair();
  try {
    await assert.rejects(async () => p.parent.send("request", "r.invalid", { value: NaN }));
    await p.parent.send("request", "r.valid", {});
    assert.equal((await p.child.nextFrame()).sequence, 1);
  } finally { p.close(); }
});

test("cancelled reader is removed and cannot consume a later request", async () => {
  const c = channel();
  const cancel = new AbortController();
  let disposition = "pending";
  const pending = c.value.nextFrame({ signal: cancel.signal }).then(
    () => { disposition = "delivered"; }, () => { disposition = "cancelled"; },
  );
  cancel.abort();
  c.input.write(frame(1));
  await pending;
  assert.equal(disposition, "cancelled");
  assert.equal((await c.value.nextFrame()).sequence, 1);
});

test("request exit cancels a pending authority receive and rejects same-ID reuse", async () => {
  const p = pair();
  const authority = new ParentFinalUseAuthority(p.child);
  let effects = 0;
  let pending;
  let disposition = "pending";
  try {
    await authority.withRequest("r.same", async () => {
      pending = authority.withVerifiedUse(request, () => { effects++; }).then(
        () => { disposition = "completed"; }, () => { disposition = "rejected"; },
      );
      assert.equal((await p.parent.nextFrame()).kind, "authority_challenge");
      await tick();
      // Return without awaiting: models a host whose timeout won the race.
    });
    await p.parent.send("authority_enter", "r.same", witness);
    await pending;
    assert.equal(disposition, "rejected");
    assert.equal(effects, 0);
    await assert.rejects(p.child.nextFrame(), /outlived/);
    await assert.rejects(authority.withRequest("r.same", () =>
      authority.withVerifiedUse(request, () => { effects++; })), /outlived/);
  } finally { p.close(); }
});

test("only one final-use handshake is allowed inside a request scope", async () => {
  const p = pair();
  const authority = new ParentFinalUseAuthority(p.child);
  let effects = 0;
  try {
    await authority.withRequest("r.once", async () => {
      const first = authority.withVerifiedUse(request, () => { effects++; return 42; });
      await p.parent.nextFrame();
      await p.parent.send("authority_enter", "r.once", witness);
      await p.parent.nextFrame();
      assert.equal(await first, 42);
      // Race-safe assertion: release an old implementation's extra waiter so
      // the regression reports a failure rather than waiting indefinitely.
      const second = authority.withVerifiedUse(request, () => { effects++; });
      const result = second.then(() => "accepted", () => "rejected");
      await p.parent.send("authority_enter", "r.once", witness);
      assert.equal(await result, "rejected");
      assert.equal(effects, 1);
    });
  } finally { p.close(); }
});

test("late completion of an entered consumer cannot publish a boundary after scope exit", async () => {
  const p = pair();
  const authority = new ParentFinalUseAuthority(p.child);
  let finish;
  let pending;
  let disposition;
  try {
    await authority.withRequest("r.delayed", async () => {
      pending = authority.withVerifiedUse(request, () => new Promise((resolve) => { finish = resolve; }))
        .then(() => { disposition = "published"; }, () => { disposition = "rejected"; });
      await p.parent.nextFrame();
      await p.parent.send("authority_enter", "r.delayed", witness);
      await tick();
      assert.equal(typeof finish, "function");
    });
    finish("late result");
    await pending;
    assert.equal(disposition, "rejected");
  } finally { p.close(); }
});
