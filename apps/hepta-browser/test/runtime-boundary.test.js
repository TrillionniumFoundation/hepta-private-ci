import assert from "node:assert/strict";
import test from "node:test";

import { exclusive } from "../src/runtime-boundary.js";

test("exclusive applies bounded per-profile backpressure", async () => {
  const locks = new Map();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let entered = 0;

  const first = exclusive(locks, "profile.1", async () => {
    entered += 1;
    await gate;
    return "first";
  }, { maxQueued: 2 });
  await new Promise((resolve) => setImmediate(resolve));

  const second = exclusive(locks, "profile.1", async () => {
    entered += 1;
    return "second";
  }, { maxQueued: 2 });

  await assert.rejects(
    exclusive(locks, "profile.1", async () => "third", { maxQueued: 2 }),
    (error) => error?.name === "BrowserBackpressureError" && error?.code === "BROWSER_BACKPRESSURE",
  );
  assert.equal(entered, 1);
  release();
  assert.deepEqual(await Promise.all([first, second]), ["first", "second"]);
  assert.equal(entered, 2);

  assert.equal(
    await exclusive(locks, "profile.1", async () => "recovered", { maxQueued: 2 }),
    "recovered",
  );
});
