import assert from "node:assert/strict";
import test from "node:test";

import { callWithDeadline } from "../src/runtime-boundary.js";

const outcome = Object.freeze({ terminalObserved: true, status: "succeeded" });

function invoke(call, overrides = {}) {
  return callWithDeadline({
    call, payload: null, now: () => 1_000, deadlineMs: 9_000,
    timeoutCapMs: 1_000, abortable: true, timeoutName: "browser driver",
    ...overrides,
  });
}

// A timer cannot preempt synchronous code. The settled Promise runs before an
// already-expired timer callback; completion must recheck the original horizon.
test("synchronous late completion is not an eligible driver result", async () => {
  let signal;
  await assert.rejects(invoke((_, context) => {
    signal = context.signal;
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 40);
    return outcome;
  }, { timeoutCapMs: 10 }), { name: "BrowserDriverTimeoutError" });
  assert.equal(signal.aborted, true);
});

test("microtask completion cannot bypass a forward wall-clock deadline", async () => {
  let now = 1_000;
  let signal;
  await assert.rejects(invoke(async (_, context) => {
    signal = context.signal;
    await Promise.resolve();
    now = 9_000;
    return outcome;
  }, { now: () => now }), { name: "BrowserDriverTimeoutError" });
  assert.equal(signal.aborted, true);
});

test("completion clock is compared with actual entry, not only initial admission", async () => {
  let sample = 0;
  const times = [1_000, 1_100, 1_099];
  await assert.rejects(invoke(() => outcome, { now: () => times[sample++] }), /regressed/);
});

test("a non-finite or non-integer completion clock cannot publish a result", async () => {
  for (const invalid of [NaN, Infinity, 1_000.5]) {
    let now = 1_000;
    await assert.rejects(invoke(() => { now = invalid; return outcome; },
      { now: () => now }), /clock/);
  }
});

test("authority completion uses the same final deadline check without an AbortSignal", async () => {
  let now = 1_000;
  await assert.rejects(invoke((_, context) => {
    assert.equal(context, undefined);
    now = 9_000;
    return outcome;
  }, { now: () => now, abortable: false, timeoutName: "browser authority" }),
  { name: "BrowserAuthorityTimeoutError" });
});

test("timely results and original errors retain their identity", async () => {
  assert.equal(await invoke(() => outcome), outcome);
  const error = new Error("original driver failure");
  await assert.rejects(invoke(() => { throw error; }), (observed) => observed === error);
});
