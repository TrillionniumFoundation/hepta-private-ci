import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { chmod, mkdtemp, open, readFile, rename, rm, truncate, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FileBrowserOperationJournal } from "../src/journal.js";

const intent = (id = "op.1") => ({
  profileId: "profile.1", generation: 1, operationId: id,
  requestDigest: "1".repeat(64), semanticDigest: "2".repeat(64),
  status: "indeterminate", terminalObserved: false, outcomeDigest: null,
  observationReason: "dispatch_fenced",
});
const outcome = (id = "op.1") => ({ ...intent(id), status: "succeeded",
  terminalObserved: true, outcomeDigest: "3".repeat(64), observationReason: "terminal_observed" });
const query = (journal) => journal.getOperation("profile.1", 1, "op.1");
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "browser-frontier-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "operations.jsonl");
  const journal = new FileBrowserOperationJournal(path);
  await journal.recordDispatch(intent());
  const before = await readFile(path);
  await journal.recordObservation(outcome());
  return { path, journal, before, complete: await readFile(path) };
}

for (const method of ["lookup", "new dispatch"]) {
  test(`a known journal cannot disappear and become empty during ${method}`, async (t) => {
    const { path, journal } = await fixture(t);
    await rm(path);
    await assert.rejects(method === "lookup" ? query(journal) : journal.recordDispatch(intent("op.2")));
    await assert.rejects(readFile(path), { code: "ENOENT" });
  });
}

test("a checksummed dispatch prefix cannot roll back an observed terminal result", async (t) => {
  const { path, journal, before } = await fixture(t);
  await truncate(path, before.length);
  await assert.rejects(query(journal), /journal/);
});

test("a checksummed same-length prefix rewrite cannot replace operation identity", async (t) => {
  const { path, journal, complete } = await fixture(t);
  const changed = complete.toString().trimEnd().split("\n").map((line) => {
    const envelope = JSON.parse(line);
    envelope.record.operationId = "op.9";
    const { checksum: _old, ...unsigned } = envelope;
    envelope.checksum = createHash("sha256").update(JSON.stringify(unsigned)).digest("hex");
    return JSON.stringify(envelope) + "\n";
  }).join("");
  assert.equal(Buffer.byteLength(changed), complete.length);
  await writeFile(path, changed, { mode: 0o600 });
  await assert.rejects(query(journal), /journal/);
});

test("a new inode with identical valid bytes is not this live journal", async (t) => {
  const { path, journal, complete } = await fixture(t);
  await rename(path, `${path}.old`);
  await writeFile(path, complete, { mode: 0o600 });
  await assert.rejects(query(journal), /journal/);
});

test("read-only observation also establishes a non-regressing live frontier", async (t) => {
  const { path, before } = await fixture(t);
  const reader = new FileBrowserOperationJournal(path);
  assert.deepEqual(await query(reader), outcome());
  await truncate(path, before.length);
  await assert.rejects(query(reader), /journal/);
});

test("restoring bytes after corruption does not silently unpoison a live handle", async (t) => {
  const { path, journal, complete } = await fixture(t);
  await writeFile(path, "not-json\n", { mode: 0o600 });
  await assert.rejects(query(journal));
  await writeFile(path, complete, { mode: 0o600 });
  await assert.rejects(query(journal), /recovery/);
  assert.deepEqual(await query(new FileBrowserOperationJournal(path)), outcome());
});

test("queued operations cannot append after a read frontier failure", async (t) => {
  const { path, journal, before } = await fixture(t);
  await truncate(path, before.length);
  const results = await Promise.allSettled([query(journal), journal.recordDispatch(intent("op.2"))]);
  assert.deepEqual(results.map((r) => r.status), ["rejected", "rejected"]);
  assert.deepEqual(await readFile(path), before);
});

test("valid external append preserving the observed prefix can be read", async (t) => {
  const { path, journal } = await fixture(t);
  const next = new FileBrowserOperationJournal(path);
  await next.recordDispatch(intent("op.2"));
  await next.recordObservation(outcome("op.2"));
  assert.deepEqual(await journal.listOperations("profile.1", 1), [outcome(), outcome("op.2")]);
});

test("exact retries preserve complete bytes and a legitimate reopen", async (t) => {
  const { path, journal, complete } = await fixture(t);
  for (let i = 0; i < 4; i += 1) {
    await journal.recordDispatch(intent());
    await journal.recordObservation(outcome());
  }
  assert.deepEqual(await readFile(path), complete);
  assert.deepEqual(await query(new FileBrowserOperationJournal(path)), outcome());
});

test("permission failure cannot be repaired underneath an already failed handle", async (t) => {
  const { path, journal } = await fixture(t);
  await chmod(path, 0o644);
  await assert.rejects(query(journal));
  await chmod(path, 0o600);
  await assert.rejects(query(journal), /recovery/);
});

test("replacement after file sync is not acknowledged as this journal's append", async (t) => {
  const { path, journal, complete } = await fixture(t);
  const handle = await open(path, "r");
  const proto = Object.getPrototypeOf(handle);
  const original = proto.sync;
  await handle.close();
  let swapped = false;
  const mocked = t.mock.method(proto, "sync", async function () {
    await original.call(this);
    if (!swapped && (await this.stat()).isFile()) {
      swapped = true;
      await rename(path, `${path}.old`);
      await writeFile(path, complete, { mode: 0o600 });
    }
  });
  try {
    await assert.rejects(journal.recordDispatch(intent("op.2")), /journal/);
    assert.equal(swapped, true);
    await assert.rejects(query(journal), /recovery/);
  } finally { mocked.mock.restore(); }
});
