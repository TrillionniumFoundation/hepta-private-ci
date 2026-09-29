import assert from "node:assert/strict";
import test from "node:test";

import {
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

test("different profile keys run concurrently while each key remains ordered", async () => {
  const locks = new Map();
  const first = deferred();
  const second = deferred();
  const order = [];

  const a1 = exclusive(locks, "profile.a", async () => {
    order.push("a1-start");
    await first.promise;
    order.push("a1-end");
  });
  await Promise.resolve();
  const a2 = exclusive(locks, "profile.a", async () => {
    order.push("a2-start");
    await second.promise;
    order.push("a2-end");
  });
  const b1 = exclusive(locks, "profile.b", async () => {
    order.push("b1");
  });
  await b1;

  let snapshot = exclusiveQueueSnapshot(locks);
  assert.equal(snapshot.active, 1);
  assert.equal(snapshot.waiting, 1);
  assert.equal(snapshot.admittedButUnsettled, 2);
  assert.ok(snapshot.maxActive >= 2);
  assert.deepEqual(order.slice(0, 2), ["a1-start", "b1"]);

  first.resolve();
  await Promise.resolve();
  second.resolve();
  await Promise.all([a1, a2]);
  assert.deepEqual(order, ["a1-start", "b1", "a1-end", "a2-start", "a2-end"]);

  snapshot = exclusiveQueueSnapshot(locks);
  assert.equal(snapshot.admittedButUnsettled, 0);
  assert.equal(snapshot.completed, 3);
});

test("aggregate capacity is independent from each per-profile queue bound", async () => {
  const locks = new Map();
  const holdA = deferred();
  const holdB = deferred();
  const a = exclusive(locks, "profile.a", () => holdA.promise, {
    maxQueued: 8,
    maxQueuedTotal: 2,
  });
  const b = exclusive(locks, "profile.b", () => holdB.promise, {
    maxQueued: 8,
    maxQueuedTotal: 2,
  });
  await Promise.resolve();

  await assert.rejects(
    exclusive(locks, "profile.c", async () => {}, {
      maxQueued: 8,
      maxQueuedTotal: 2,
    }),
    (error) => error.code === "BROWSER_GLOBAL_BACKPRESSURE",
  );
  assert.equal(
    exclusiveQueueSnapshot(locks).aggregateBackpressureRejects,
    1,
  );

  holdA.resolve();
  holdB.resolve();
  await Promise.all([a, b]);
});

test("capacity is retained until the admitted operation actually settles", async () => {
  const locks = new Map();
  const cleanupObserved = deferred();
  const operation = exclusive(
    locks,
    "profile.a",
    async () => {
      await cleanupObserved.promise;
    },
    { maxQueuedTotal: 1 },
  );
  await Promise.resolve();
  assert.equal(exclusiveQueueSnapshot(locks).admittedButUnsettled, 1);

  await assert.rejects(
    exclusive(locks, "profile.b", async () => {}, { maxQueuedTotal: 1 }),
    (error) => error.code === "BROWSER_GLOBAL_BACKPRESSURE",
  );

  cleanupObserved.resolve();
  await operation;
  assert.equal(exclusiveQueueSnapshot(locks).admittedButUnsettled, 0);
});

test("queue telemetry records worst observed wait without authorizing work", async () => {
  const locks = new Map();
  const gate = deferred();
  let clock = 10;
  const first = exclusive(locks, "profile.a", () => gate.promise, {
    now: () => clock,
  });
  await Promise.resolve();
  clock = 25;
  const second = exclusive(locks, "profile.a", async () => {}, {
    now: () => clock,
  });
  clock = 100;
  gate.resolve();
  await Promise.all([first, second]);
  assert.equal(exclusiveQueueSnapshot(locks).maxWaitMs, 75);
});
