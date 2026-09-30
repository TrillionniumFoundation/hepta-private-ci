import assert from "node:assert/strict";
import test from "node:test";

import {
  callWithDeadline,
  exclusive,
  exclusiveQueueSnapshot,
} from "../src/runtime-boundary.js";

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

test("exclusive applies bounded per-profile backpressure", async () => {
  const locks = new Map();
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  let entered = 0;

  const first = exclusive(
    locks,
    "profile.1",
    async () => {
      entered += 1;
      await gate;
      return "first";
    },
    { maxQueued: 2 },
  );
  await new Promise((resolve) => setImmediate(resolve));

  const second = exclusive(
    locks,
    "profile.1",
    async () => {
      entered += 1;
      return "second";
    },
    { maxQueued: 2 },
  );

  await assert.rejects(
    exclusive(locks, "profile.1", async () => "third", { maxQueued: 2 }),
    (error) =>
      error?.name === "BrowserBackpressureError" &&
      error?.code === "BROWSER_BACKPRESSURE",
  );
  assert.equal(entered, 1);
  release();
  assert.deepEqual(await Promise.all([first, second]), ["first", "second"]);
  assert.equal(entered, 2);

  assert.equal(
    await exclusive(locks, "profile.1", async () => "recovered", {
      maxQueued: 2,
    }),
    "recovered",
  );
});

test("exclusive bounds aggregate admitted work across profile keys", async () => {
  const locks = new Map();
  const firstGate = deferred();
  const secondGate = deferred();
  const first = exclusive(locks, "profile.1", () => firstGate.promise, {
    maxQueued: 8,
    maxQueuedTotal: 2,
  });
  const second = exclusive(locks, "profile.2", () => secondGate.promise, {
    maxQueued: 8,
    maxQueuedTotal: 2,
  });
  await new Promise((resolve) => setImmediate(resolve));

  await assert.rejects(
    exclusive(locks, "profile.3", async () => "third", {
      maxQueued: 8,
      maxQueuedTotal: 2,
    }),
    (error) =>
      error?.name === "BrowserBackpressureError" &&
      error?.code === "BROWSER_GLOBAL_BACKPRESSURE",
  );
  const saturated = exclusiveQueueSnapshot(locks);
  assert.equal(saturated.active, 2);
  assert.equal(saturated.admittedButUnsettled, 2);
  assert.equal(saturated.aggregateBackpressureRejects, 1);
  assert.equal(saturated.maxActive, 2);

  firstGate.resolve("first");
  await first;
  assert.equal(exclusiveQueueSnapshot(locks).admittedButUnsettled, 1);
  secondGate.resolve("second");
  await second;
  assert.equal(exclusiveQueueSnapshot(locks).admittedButUnsettled, 0);
});

test("exclusive records queue wait and releases capacity only after settlement", async () => {
  const locks = new Map();
  const gate = deferred();
  let clock = 10;
  const first = exclusive(locks, "profile.1", () => gate.promise, {
    maxQueuedTotal: 2,
    now: () => clock,
  });
  await new Promise((resolve) => setImmediate(resolve));
  clock = 25;
  const second = exclusive(locks, "profile.1", async () => "second", {
    maxQueuedTotal: 2,
    now: () => clock,
  });
  clock = 100;
  assert.equal(exclusiveQueueSnapshot(locks).admittedButUnsettled, 2);
  gate.resolve("first");
  assert.deepEqual(await Promise.all([first, second]), ["first", "second"]);
  const settled = exclusiveQueueSnapshot(locks);
  assert.equal(settled.admittedButUnsettled, 0);
  assert.equal(settled.maxWaitMs, 75);
  assert.equal(settled.completed, 2);
  assert.equal(settled.startFailures, 0);
});

test("exclusive releases capacity and serialization tails after a post-admission clock failure", async () => {
  const locks = new Map();
  let readings = 0;
  await assert.rejects(
    exclusive(locks, "profile.clock", async () => "must-not-run", {
      maxQueuedTotal: 1,
      now: () => {
        readings += 1;
        if (readings === 1) return 10;
        throw new Error("clock unavailable after admission");
      },
    }),
    /clock unavailable after admission/,
  );
  const failed = exclusiveQueueSnapshot(locks);
  assert.equal(failed.active, 0);
  assert.equal(failed.admittedButUnsettled, 0);
  assert.equal(failed.startFailures, 1);
  assert.equal(failed.completed, 0);
  assert.deepEqual(failed.perKeyDepths, []);

  assert.equal(
    await exclusive(locks, "profile.clock", async () => "recovered", {
      maxQueuedTotal: 1,
    }),
    "recovered",
  );
  const recovered = exclusiveQueueSnapshot(locks);
  assert.equal(recovered.admittedButUnsettled, 0);
  assert.equal(recovered.completed, 1);
  assert.equal(recovered.startFailures, 1);
});

test("driver timeout identity survives a driver-specific AbortError", async () => {
  await assert.rejects(
    callWithDeadline({
      call: (_payload, { signal }) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(Object.assign(new Error("driver aborted"), { name: "AbortError" })),
            { once: true },
          );
        }),
      payload: null,
      now: () => Date.now(),
      deadlineMs: Date.now() + 1_000,
      timeoutCapMs: 5,
      abortable: true,
      timeoutName: "browser driver",
    }),
    (error) => error?.name === "BrowserDriverTimeoutError",
  );
});

test("non-abortable authority work is never detached by a local timeout race", async () => {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const result = callWithDeadline({
    call: async () => {
      await gate;
      return "fenced";
    },
    payload: null,
    now: () => Date.now(),
    deadlineMs: Date.now() + 1_000,
    timeoutCapMs: 5,
    abortable: false,
    timeoutName: "browser authority",
  });
  await new Promise((resolve) => setTimeout(resolve, 15));
  release();
  assert.equal(await result, "fenced");
});
