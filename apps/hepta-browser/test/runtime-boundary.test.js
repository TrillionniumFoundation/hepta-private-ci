import assert from "node:assert/strict";
import test from "node:test";

import {
  callWithDeadline,
  exclusive,
} from "../src/runtime-boundary.js";

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
