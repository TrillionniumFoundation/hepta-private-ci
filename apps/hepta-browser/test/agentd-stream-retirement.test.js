import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import test from "node:test";
import { AgentdBrowserChannel, ParentFinalUseAuthority } from "../src/agentd-service.js";
import { buildAgentdBrowserFrame, encodeAgentdBrowserFrame } from "../src/agentd-protocol.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));
const encode = (sequence = 1, kind = "request", payload = {}) => encodeAgentdBrowserFrame(
  buildAgentdBrowserFrame({ sequence, kind, requestId: "r.1", payload }),
);
function fixture(t) {
  const input = new EventEmitter();
  const output = new EventEmitter();
  const callbacks = [];
  output.write = (_bytes, callback) => { callbacks.push(callback); return false; };
  const channel = new AgentdBrowserChannel({ input, output });
  t.after(() => channel.invalidate(new Error("fixture cleanup")));
  return { input, output, callbacks, channel };
}
function watch(promise) {
  const state = { status: "pending" };
  state.done = promise.then(
    (value) => { state.status = "fulfilled"; state.value = value; },
    (error) => { state.status = "rejected"; state.error = error; },
  );
  return state;
}

for (const [side, event] of [["input", "close"], ["output", "close"], ["output", "finish"]]) {
  test(`${side} ${event} rejects pending reads and writes without an error event`, async (t) => {
    const f = fixture(t);
    const read = watch(f.channel.nextFrame());
    const write = watch(f.channel.send("response", "r.1", {}));
    f[side].emit(event);
    await tick();
    assert.equal(read.status, "rejected");
    assert.equal(write.status, "rejected");
    assert.throws(() => f.channel.assertUsable(), /closed|ended|finished/);
    const count = f.callbacks.length;
    await assert.rejects(f.channel.send("response", "r.2", {}));
    assert.equal(f.callbacks.length, count);
    for (const callback of f.callbacks) callback();
    await tick();
    assert.equal(write.status, "rejected", "late write success must not undo failure");
  });
}

 test("input EOF rejects a write whose callback never arrived", async (t) => {
  const f = fixture(t);
  const pending = watch(f.channel.send("response", "r.1", {}));
  f.input.emit("end");
  await tick();
  assert.equal(pending.status, "rejected");
  f.callbacks[0]();
  await pending.done;
  assert.equal(pending.status, "rejected");
});

 test("clean EOF discards unconsumed requests instead of exposing closed-channel work", async (t) => {
  const f = fixture(t);
  f.input.emit("data", encode());
  f.input.emit("end");
  assert.equal(await f.channel.nextFrame(), null);
  await assert.rejects(f.channel.send("response", "r.1", {}), /closed/);
  assert.equal(f.callbacks.length, 0);
});

 test("idle EOF and its following close preserve a clean end", async (t) => {
  const f = fixture(t);
  const pending = f.channel.nextFrame();
  f.input.emit("end");
  f.input.emit("close");
  f.output.emit("finish");
  f.output.emit("close");
  assert.equal(await pending, null);
  assert.equal(await f.channel.nextFrame(), null);
});

for (const [side, property] of [["input", "destroyed"], ["input", "readableEnded"],
  ["output", "destroyed"], ["output", "writableEnded"]]) {
  test(`construction rejects an already ${property} ${side}`, async () => {
    const input = new EventEmitter();
    const output = new EventEmitter();
    let writes = 0;
    output.write = (_bytes, callback) => { writes++; callback(); };
    const streams = { input, output };
    streams[side][property] = true;
    const channel = new AgentdBrowserChannel(streams);
    await assert.rejects(channel.send("response", "r.1", {}), /closed|ended|finished/);
    assert.equal(writes, 0);
    await assert.rejects(channel.nextFrame());
  });
}

test("real readable destroy without error cannot strand an authority wait", async (t) => {
  const input = new PassThrough();
  const output = new PassThrough();
  t.after(() => { input.destroy(); output.destroy(); });
  const channel = new AgentdBrowserChannel({ input, output });
  const authority = new ParentFinalUseAuthority(channel);
  let effects = 0;
  const pending = watch(authority.withRequest("r.1", () => authority.withVerifiedUse(
    { requestDigest: "1".repeat(64), authorityEpoch: 1 }, () => { effects++; },
  )));
  await tick();
  input.destroy();
  await tick();
  assert.equal(pending.status, "rejected");
  assert.equal(effects, 0);
});

test("output closure fences an authority-enter already queued in the same turn", async (t) => {
  const f = fixture(t);
  const authority = new ParentFinalUseAuthority(f.channel);
  let effects = 0;
  const pending = watch(authority.withRequest("r.1", () => authority.withVerifiedUse(
    { requestDigest: "1".repeat(64), authorityEpoch: 1 }, () => { effects++; },
  )));
  f.callbacks[0]();
  f.input.emit("data", encode(1, "authority_enter", {
    requestDigest: "1".repeat(64), authorityEpoch: 1, authorized: true,
    witnessDigest: "2".repeat(64),
  }));
  f.output.emit("close");
  await tick();
  assert.equal(pending.status, "rejected");
  assert.equal(effects, 0);
});

test("closure after an entered consumer never invents an external terminal result", async (t) => {
  const f = fixture(t);
  const authority = new ParentFinalUseAuthority(f.channel);
  let release;
  let effects = 0;
  const pending = watch(authority.withRequest("r.1", () => authority.withVerifiedUse(
    { requestDigest: "1".repeat(64), authorityEpoch: 1 }, () => {
      effects++;
      return new Promise((resolve) => { release = resolve; });
    },
  )));
  f.callbacks[0]();
  f.input.emit("data", encode(1, "authority_enter", {
    requestDigest: "1".repeat(64), authorityEpoch: 1, authorized: true,
    witnessDigest: "2".repeat(64),
  }));
  await tick();
  assert.equal(effects, 1);
  f.output.emit("close");
  release({ terminalObserved: true });
  await tick();
  assert.equal(pending.status, "rejected");
  assert.equal(effects, 1);
  assert.equal(f.callbacks.length, 1, "no dispatch-boundary or success frame after closure");
});
