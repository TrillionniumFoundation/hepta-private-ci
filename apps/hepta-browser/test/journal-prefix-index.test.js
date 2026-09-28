import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { appendFile, mkdtemp, open, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { FileBrowserOperationJournal } from "../src/journal.js";

const intent = (operationId = "op.1") => ({
  profileId: "profile.1", generation: 1, operationId,
  requestDigest: "1".repeat(64), semanticDigest: "2".repeat(64),
  status: "indeterminate", terminalObserved: false, outcomeDigest: null,
});
const outcome = (operationId = "op.1") => ({ ...intent(operationId),
  status: "succeeded", terminalObserved: true, outcomeDigest: "3".repeat(64) });
const query = (journal, id = "op.1") => journal.getOperation("profile.1", 1, id);
const frame = (type, record) => {
  const unsigned = { schema: "hepta.browser.operation-journal.v1", version: 1, type, record };
  return JSON.stringify({ ...unsigned,
    checksum: createHash("sha256").update(JSON.stringify(unsigned)).digest("hex") }) + "\n";
};
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "browser-prefix-index-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "operations.jsonl");
  const writer = new FileBrowserOperationJournal(path);
  await writer.recordDispatch(intent());
  await writer.recordObservation(outcome());
  return { path, writer };
}
function countParses(t) {
  const state = { count: 0 };
  const parse = JSON.parse;
  t.mock.method(JSON, "parse", function (text, ...rest) {
    if (typeof text === "string" && text.includes('"schema":"hepta.browser.operation-journal.v1"')) state.count++;
    return parse.call(this, text, ...rest);
  });
  return state;
}

test("repeated lookup revalidates every disk byte but does not reparse the verified prefix", async (t) => {
  const { path } = await fixture(t);
  const reader = new FileBrowserOperationJournal(path);
  const parses = countParses(t);
  assert.deepEqual(await query(reader), outcome());
  assert.equal(parses.count, 2);
  const bytes = await readFile(path);
  const probe = await open(path, "r");
  const prototype = Object.getPrototypeOf(probe);
  const read = prototype.read;
  await probe.close();
  let bytesRead = 0;
  t.mock.method(prototype, "read", async function (...args) {
    const result = await read.apply(this, args);
    bytesRead += result.bytesRead;
    return result;
  });
  assert.deepEqual(await query(reader), outcome());
  assert.deepEqual(await reader.listOperations("profile.1", 1), [outcome()]);
  assert.equal(parses.count, 2, "the authenticated reduction is reused");
  assert.equal(bytesRead, 2 * bytes.length, "both operations still read the complete current file");
});

test("acknowledged local append and exact retries never reparse prior history", async (t) => {
  const { path, writer } = await fixture(t);
  const parses = countParses(t);
  await writer.recordDispatch(intent("op.2"));
  await writer.recordObservation(outcome("op.2"));
  const complete = await readFile(path);
  await writer.recordDispatch(intent("op.2"));
  await writer.recordObservation(outcome("op.2"));
  assert.deepEqual(await query(writer, "op.2"), outcome("op.2"));
  assert.equal(parses.count, 0);
  assert.deepEqual(await readFile(path), complete);
});

test("a reader validates and reduces only newly appended complete frames", async (t) => {
  const { path, writer } = await fixture(t);
  const reader = new FileBrowserOperationJournal(path);
  await query(reader);
  await writer.recordDispatch(intent("op.2"));
  await writer.recordObservation(outcome("op.2"));
  const parses = countParses(t);
  assert.deepEqual(await reader.listOperations("profile.1", 1), [outcome(), outcome("op.2")]);
  assert.equal(parses.count, 2);
  assert.deepEqual(await query(reader, "op.2"), outcome("op.2"));
  assert.equal(parses.count, 2);
});

test("multiple observations in a new suffix reduce against their staged predecessors", async (t) => {
  const { path, writer } = await fixture(t);
  await appendFile(path, frame("dispatch", intent("op.2"))
    + frame("observation", outcome("op.2")) + frame("observation", outcome("op.2")));
  assert.deepEqual(await query(writer, "op.2"), outcome("op.2"));
  assert.equal((await writer.listOperations("profile.1", 1)).length, 2);
});

test("a valid suffix prefix followed by corruption cannot be exposed from the index", async (t) => {
  const { path, writer } = await fixture(t);
  await appendFile(path, frame("dispatch", intent("op.2")) + "not-json\n");
  const results = await Promise.allSettled([query(writer, "op.2"), query(writer)]);
  assert.deepEqual(results.map((entry) => entry.status), ["rejected", "rejected"]);
  const failed = await readFile(path);
  await assert.rejects(writer.recordDispatch(intent("op.3")), /recovery/);
  assert.deepEqual(await readFile(path), failed);
});

test("cached terminal state still rejects a checksummed regressing observation", async (t) => {
  const { path, writer } = await fixture(t);
  await appendFile(path, frame("observation", intent()));
  await assert.rejects(query(writer), /regress|terminal/);
  await assert.rejects(query(writer), /recovery/);
});

test("same-length checksummed old-prefix mutation is not hidden by an indexed result", async (t) => {
  const { path, writer } = await fixture(t);
  const before = await readFile(path);
  const rewritten = frame("dispatch", intent("op.9")) + frame("observation", outcome("op.9"));
  assert.equal(Buffer.byteLength(rewritten), before.length);
  await writeFile(path, rewritten);
  await assert.rejects(query(writer), /prefix changed/);
});

test("a reopened owner reconstructs the same immutable records without sharing a cache", async (t) => {
  const { path, writer } = await fixture(t);
  const old = await query(writer);
  assert.equal(Object.isFrozen(old), true);
  assert.throws(() => { old.status = "failed"; }, TypeError);
  const reopened = new FileBrowserOperationJournal(path);
  const observed = await query(reopened);
  assert.deepEqual(observed, old);
  assert.notEqual(observed, old);
});

test("a blocked disk read admits at most 64 journal operations and recovers capacity", async (t) => {
  const { path, writer } = await fixture(t);
  const probe = await open(path, "r");
  const prototype = Object.getPrototypeOf(probe);
  const read = prototype.read;
  await probe.close();
  let release;
  let entered;
  const blocked = new Promise((resolve) => { release = resolve; });
  const reached = new Promise((resolve) => { entered = resolve; });
  let first = true;
  const mock = t.mock.method(prototype, "read", async function (...args) {
    if (first) { first = false; entered(); await blocked; }
    return read.apply(this, args);
  });
  const pending = Array.from({ length: 64 }, () => query(writer));
  await reached;
  let overflowError;
  const overflow = query(writer).catch((error) => { overflowError = error; });
  await new Promise((resolve) => setImmediate(resolve));
  // Release actual I/O even if the old implementation did not reject overflow.
  release();
  await Promise.all([...pending, overflow]);
  mock.mock.restore();
  assert.match(overflowError?.message ?? "not rejected", /capacity/);
  assert.deepEqual(await query(writer), outcome());
});

test("semantic rejection returns its queue slot without poisoning valid work", async (t) => {
  const { writer } = await fixture(t);
  const invalid = { ...outcome(), requestDigest: "4".repeat(64) };
  for (let i = 0; i < 80; i++) {
    await assert.rejects(writer.recordObservation(invalid), /immutable semantics/);
  }
  assert.deepEqual(await query(writer), outcome());
});
