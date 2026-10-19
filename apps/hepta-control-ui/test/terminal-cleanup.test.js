import assert from "node:assert/strict";
import test from "node:test";
import { TerminalCleanupQueue } from "../src/terminal-cleanup.js";
import { ScopedRecoveryStore } from "../src/recovery-store.js";
import { deferred, operation, terminal, storageOptions } from "./browser-fixture.js";

const recordCount = storage => [...storage.values.keys()]
  .filter(key => key.startsWith("hepta.ui-control.scoped-recovery.v2:")).length;

test("cleanup coalesces concurrent callers and unchanged terminal history", async () => {
  const gate = deferred(); let calls = 0;
  const queue = new TerminalCleanupQueue(async () => { calls += 1; await gate.promise; });
  const one = queue.sync([terminal()]); const two = queue.sync([terminal()]);
  await Promise.resolve(); assert.equal(calls, 1);
  gate.resolve(); await Promise.all([one, two]);
  for (let i = 0; i < 100; i += 1) await queue.sync([terminal()]);
  assert.equal(calls, 1);
});

test("a failed deletion is retryable; successful siblings are not repeated", async () => {
  const calls = []; let fail = true;
  const queue = new TerminalCleanupQueue(async op => {
    calls.push(op.operationId);
    if (op.operationId === "one" && fail) throw new Error("retained");
  });
  await assert.rejects(queue.sync([terminal("one"), terminal("two")]));
  fail = false; await queue.sync([terminal("one"), terminal("two")]);
  assert.deepEqual(calls, ["one", "two", "one"]);
});

test("changed terminal identity is never hidden by operation-id memoization", async () => {
  const options = storageOptions(); const store = await ScopedRecoveryStore.create(options);
  await store.prepare(operation());
  const queue = new TerminalCleanupQueue((op, opts) => store.complete(op, opts));
  await queue.sync([terminal()]);
  await store.prepare({ ...operation(), semanticDigest: "d".repeat(64) });
  await assert.rejects(queue.sync([{ ...terminal(), displayedRevision: 13 }]));
  assert.equal(store.load().operations[0].semanticDigest, "d".repeat(64));
});

test("unknown operations are not cleaned and dropped display history is pruned", async () => {
  let calls = 0; const queue = new TerminalCleanupQueue(async () => { calls += 1; });
  await queue.sync([{ ...operation(), state: "indeterminate" }]);
  assert.equal(calls, 0);
  await queue.sync([terminal()]); await queue.sync([]); await queue.sync([terminal()]);
  assert.equal(calls, 2);
});

test("aborting an active queue fences all subsequent removals", async () => {
  const gate = deferred(); const abort = new AbortController(); const calls = [];
  const queue = new TerminalCleanupQueue(async op => { calls.push(op.operationId); await gate.promise; });
  const work = queue.sync([terminal("one"), terminal("two")], { signal: abort.signal });
  await Promise.resolve(); abort.abort(); gate.resolve();
  await assert.rejects(work); await queue.drain();
  assert.deepEqual(calls, ["one"]);
});

test("cleanup rejects over-capacity inventory before scheduling any deletion", async () => {
  let calls = 0; const queue = new TerminalCleanupQueue(async () => { calls += 1; }, { maxEntries: 1 });
  await assert.rejects(queue.sync([terminal("one"), terminal("two")]), RangeError);
  assert.equal(calls, 0);
});

test("two tabs clean 1024 terminals without origin enumeration or repeat locks", async () => {
  const options = storageOptions();
  const one = await ScopedRecoveryStore.create(options); const two = await ScopedRecoveryStore.create(options);
  const records = Array.from({ length: 1024 }, (_, i) => operation(`op-${i}`));
  for (const record of records) await one.prepare(record);
  for (let i = 0; i < 1000; i += 1) options.storage.setItem(`unrelated-${i}`, "x");
  const before = options.storage.enumerations;
  const a = new TerminalCleanupQueue((op, opts) => one.complete(op, opts));
  const b = new TerminalCleanupQueue((op, opts) => two.complete(op, opts));
  const completed = records.map(record => ({ ...record, state: "terminal" }));
  for (let i = 0; i < 32; i += 1) await Promise.all([a.sync(completed), b.sync(completed)]);
  const requests = options.locks.requests;
  for (let i = 0; i < 20; i += 1) await Promise.all([a.sync(completed), b.sync(completed)]);
  assert.equal(options.storage.enumerations, before);
  assert.equal(options.locks.requests, requests);
  assert.equal(recordCount(options.storage), 0);
  assert.equal([...options.storage.values.keys()].filter(key => key.startsWith("unrelated-")).length, 1000);
});

test("steady-state scope directory is isolated from a large unrelated origin inventory", async () => {
  const options = storageOptions(); const store = await ScopedRecoveryStore.create(options);
  const before = options.storage.enumerations;
  for (let i = 0; i < 20000; i += 1) options.storage.setItem(`other-${i}`, "x");
  await store.prepare(operation());
  assert.equal(store.load().operations.length, 1);
  await store.complete(terminal());
  assert.equal(options.storage.enumerations, before);
  assert.equal(recordCount(options.storage), 0);
});

test("batch deadline bounds lock waiting and rotation reaches later records", async () => {
  const seen = [];
  const queue = new TerminalCleanupQueue(async (op, { signal }) => {
    seen.push(op.operationId);
    if (op.operationId === "slow") await new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    });
  }, { batchSize: 1, deadlineMs: 10 });
  await assert.rejects(queue.sync([terminal("slow"), terminal("fast")]));
  assert.equal(await queue.sync([terminal("slow"), terminal("fast")]), false);
  assert.deepEqual(seen, ["slow", "fast"]);
});

test("failed cleanup survives terminal display-history eviction", async () => {
  const options = storageOptions(); const store = await ScopedRecoveryStore.create(options);
  await store.prepare(operation());
  const original = options.storage.removeItem;
  options.storage.removeItem = () => {};
  const queue = new TerminalCleanupQueue((op, opts) => store.complete(op, opts));
  await assert.rejects(queue.sync([terminal()]));
  await assert.rejects(queue.sync([]));
  assert.equal(recordCount(options.storage), 1);
  options.storage.removeItem = original;
  assert.equal(await queue.sync([]), true);
  assert.equal(recordCount(options.storage), 0);
});

test("in-flight cleanup remains joined after its display record is removed", async () => {
  const gate = deferred(); let calls = 0;
  const queue = new TerminalCleanupQueue(async () => { calls += 1; await gate.promise; });
  const first = queue.sync([terminal()]);
  const second = queue.sync([]);
  await Promise.resolve(); assert.equal(calls, 1);
  gate.resolve();
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
});

test("cleanup diagnostics report bounded maintenance state only", async () => {
  const gate = deferred();
  const queue = new TerminalCleanupQueue(async () => gate.promise, { maxEntries: 4, batchSize: 2 });
  const work = queue.sync([terminal("one")]);
  await Promise.resolve();
  assert.deepEqual(queue.diagnostics(), {
    visible: 1, pending: 1, outstanding: 1, retainedSuccesses: 0,
    maxEntries: 4, batchSize: 2,
  });
  gate.resolve(); await work;
});
