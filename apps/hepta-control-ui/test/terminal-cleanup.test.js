import assert from "node:assert/strict";
import test from "node:test";
import { TerminalCleanupQueue } from "../src/terminal-cleanup.js";
import { ScopedRecoveryStore } from "../src/recovery-store.js";
import { deferred, operation, terminal, storageOptions } from "./browser-fixture.js";

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
  assert.equal(options.storage.length, 1000);
});

test("origin inventory remains bounded and malformed records are retained", async () => {
  const options = storageOptions(); const store = await ScopedRecoveryStore.create(options);
  await store.prepare(operation()); const key = options.storage.key(0);
  options.storage.setItem(key, "malformed");
  assert.throws(() => store.load(), { code: "UI_CONTROL_STORAGE" });
  assert.equal(options.storage.getItem(key), "malformed");
  for (let i = 0; i < 16384; i += 1) options.storage.setItem(`other-${i}`, "x");
  const before = options.storage.enumerations;
  await assert.rejects(store.prepare(operation("new")), { code: "UI_CONTROL_STORAGE" });
  assert.equal(options.storage.enumerations, before);
  assert.equal(options.storage.length, 16385);
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
