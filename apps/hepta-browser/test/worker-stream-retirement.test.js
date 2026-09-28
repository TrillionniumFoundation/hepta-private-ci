import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import test from "node:test";
import { PrivateWorkerClient } from "../src/worker-client.js";
import { buildWorkerFrame, encodeWorkerFrame, WorkerFrameDecoder } from "../src/worker-protocol.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));
function fixture(t, initial = () => {}) {
  const child = new EventEmitter();
  child.stdin = new EventEmitter(); child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
  const writes = [], callbacks = [], kills = [];
  child.stdin.write = (bytes, callback) => { writes.push(bytes); callbacks.push(callback); };
  child.stdin.end = () => {};
  child.kill = (signal) => { kills.push(signal); return false; };
  initial(child);
  const client = new PrivateWorkerClient({ child, sessionId: "p.1", generation: 1 });
  t.after(() => client.close());
  return { child, client, writes, callbacks, kills };
}
function watch(promise) {
  const state = { status: "pending" };
  state.done = promise.then(
    (value) => { state.status = "fulfilled"; state.value = value; },
    (error) => { state.status = "rejected"; state.error = error; },
  );
  return state;
}
function reply(f) {
  const request = new WorkerFrameDecoder().push(f.writes[0])[0];
  return encodeWorkerFrame(buildWorkerFrame({ ...request, sequence: 1, kind: "response",
    payload: { ok: true, observation: { terminalObserved: true } } }));
}

for (const [stream, event] of [["stdout", "close"], ["stdin", "close"], ["stdin", "finish"]]) {
  test(`${stream} ${event} fences requests without waiting for a child exit or error`, async (t) => {
    const f = fixture(t);
    let boundaries = 0;
    const pending = watch(f.client.request("dispatch", "op.1", {}, { onDispatched: () => boundaries++ }));
    f.child[stream].emit(event);
    await tick();
    assert.equal(pending.status, "rejected");
    await assert.rejects(f.client.request("observe", "op.2", {}));
    assert.equal(f.writes.length, 1);
    f.callbacks[0]();
    f.child.stdout.emit("data", reply(f));
    await tick();
    assert.equal(boundaries, 0);
    assert.equal(pending.status, "rejected");
    assert.deepEqual(f.kills, ["SIGKILL"], "signal denial never reopens admission");
  });
}

for (const [stream, property] of [["stdin", "destroyed"], ["stdin", "writableEnded"],
  ["stdout", "destroyed"], ["stdout", "readableEnded"]]) {
  test(`already ${property} ${stream} rejects without writing`, async (t) => {
    const f = fixture(t, (child) => { child[stream][property] = true; });
    const pending = watch(f.client.request("start", "p.1", {}));
    await tick();
    assert.equal(pending.status, "rejected");
    assert.equal(f.writes.length, 0);
  });
}

test("a destroyed flag fences a pending write callback before the close event", async (t) => {
  const f = fixture(t);
  let boundaries = 0;
  const pending = watch(f.client.request("dispatch", "op.1", {}, { onDispatched: () => boundaries++ }));
  f.child.stdin.destroyed = true;
  f.callbacks[0]();
  await tick();
  assert.equal(pending.status, "rejected");
  assert.equal(boundaries, 0);
});

test("reply delivery cannot pass synchronous retired-stream flags", async (t) => {
  const f = fixture(t);
  const pending = watch(f.client.request("observe", "op.1", {}));
  f.child.stdout.destroyed = true;
  f.child.stdout.emit("data", reply(f));
  await tick();
  assert.equal(pending.status, "rejected");
});

test("real output stream destruction rejects a pending request without an error event", async (t) => {
  const f = fixture(t, (child) => { child.stdout = new PassThrough(); });
  const pending = watch(f.client.request("observe", "op.1", {}));
  f.child.stdout.destroy();
  await tick();
  assert.equal(pending.status, "rejected");
});

test("normal process exit then pipe closure does not send another cleanup signal", async (t) => {
  const f = fixture(t);
  const pending = watch(f.client.request("observe", "op.1", {}));
  f.child.emit("exit", 0, null);
  f.child.stdout.emit("close");
  f.child.stdin.emit("close");
  await tick();
  assert.equal(pending.status, "rejected");
  assert.equal(f.kills.length, 0);
});

test("closing a diagnostic-only pipe is not a fabricated process failure", async (t) => {
  const f = fixture(t);
  const pending = watch(f.client.request("observe", "op.1", {}));
  f.child.stderr.emit("close");
  f.callbacks[0]();
  f.child.stdout.emit("data", reply(f));
  await pending.done;
  assert.equal(pending.status, "fulfilled");
  assert.equal(f.kills.length, 0);
});
