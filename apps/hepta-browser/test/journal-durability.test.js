import assert from "node:assert/strict";
import { mkdtemp, open, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";

import { FileBrowserOperationJournal } from "../src/journal.js";

function record(operationId = "operation.1") {
  return {
    profileId: "profile.1", generation: 1, operationId,
    requestDigest: "1".repeat(64), semanticDigest: "2".repeat(64),
    status: "indeterminate", terminalObserved: false, outcomeDigest: null,
  };
}

async function fixture(t, nested = false) {
  const root = await mkdtemp(join(tmpdir(), "hepta-journal-durability-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, ...(nested ? ["owner", "generation"] : []), "operations.jsonl");
  const probe = await open(join(root, "prototype-probe"), "w", 0o600);
  const prototype = Object.getPrototypeOf(probe);
  await probe.close();
  return { root, path, prototype, journal: new FileBrowserOperationJournal(path) };
}

function identity(info) {
  return `${info.dev}:${info.ino}`;
}

function observeSync(t, prototype, before = async () => {}) {
  const events = [];
  const sync = prototype.sync;
  t.mock.method(prototype, "sync", async function () {
    const info = await this.stat();
    const event = { kind: info.isDirectory() ? "directory" : "file", id: identity(info) };
    events.push(event);
    await before(event, events);
    return sync.call(this);
  });
  return events;
}

function ioFailure() {
  return Object.assign(new Error("injected journal durability failure"), { code: "EIO" });
}

test("dispatch awaits the file barrier followed by its parent-directory barrier", async (t) => {
  const { root, prototype, journal } = await fixture(t);
  const events = observeSync(t, prototype);
  await journal.recordDispatch(record());
  const parentId = identity(await stat(root));
  assert.deepEqual(events.slice(-2).map((event) => event.kind), ["file", "directory"]);
  assert.equal(events.at(-1).id, parentId);
});

test("new nested parents and their directory entries are synchronized", async (t) => {
  const { root, path, prototype, journal } = await fixture(t, true);
  const events = observeSync(t, prototype);
  await journal.recordDispatch(record());
  const synchronized = new Set(events.filter((event) => event.kind === "directory").map((event) => event.id));
  for (const directory of [root, join(root, "owner"), dirname(path)]) {
    assert.ok(synchronized.has(identity(await stat(directory))), directory);
  }
});

test("successful parent initialization is not repeated on every append", async (t) => {
  const { prototype, journal } = await fixture(t, true);
  const events = observeSync(t, prototype);
  await journal.recordDispatch(record());
  events.length = 0;
  await journal.recordDispatch(record("operation.2"));
  assert.deepEqual(events.map((event) => event.kind), ["file", "directory"]);
});

test("a file-sync failure fences queued writes, retries and ordinary reads", async (t) => {
  const { path, prototype, journal } = await fixture(t);
  let failed = false;
  observeSync(t, prototype, async (event) => {
    if (event.kind === "file" && !failed) {
      failed = true;
      throw ioFailure();
    }
  });
  const results = await Promise.allSettled([
    journal.recordDispatch(record()), journal.recordDispatch(record("operation.2")),
  ]);
  assert.equal(results[0].status, "rejected");
  assert.equal(results[0].reason.code, "EIO");
  assert.equal(results[1].status, "rejected");
  assert.match(results[1].reason.message, /owner recovery/);
  const bytes = await readFile(path);
  await assert.rejects(journal.recordDispatch(record()), /owner recovery/);
  await assert.rejects(journal.getOperation("profile.1", 1, "operation.1"), /owner recovery/);
  await assert.rejects(journal.listOperations("profile.1", 1), /owner recovery/);
  assert.deepEqual(await readFile(path), bytes);
});

test("a directory-sync failure after writing cannot become successful dedupe", async (t) => {
  const { path, prototype, journal } = await fixture(t);
  let sawFile = false;
  let failed = false;
  observeSync(t, prototype, async (event) => {
    sawFile ||= event.kind === "file";
    if (event.kind === "directory" && sawFile && !failed) {
      failed = true;
      throw ioFailure();
    }
  });
  await assert.rejects(journal.recordDispatch(record()), { code: "EIO" });
  const bytes = await readFile(path);
  await assert.rejects(journal.recordDispatch(record()), /owner recovery/);
  await assert.rejects(journal.recordObservation({ ...record(), terminalObserved: true, status: "succeeded" }), /owner recovery/);
  assert.deepEqual(await readFile(path), bytes);
});

test("a parent-initialization failure never creates or acknowledges a journal", async (t) => {
  const { path, prototype, journal } = await fixture(t, true);
  observeSync(t, prototype, async (event) => {
    if (event.kind === "directory") throw ioFailure();
  });
  await assert.rejects(journal.recordDispatch(record()), { code: "EIO" });
  await assert.rejects(stat(path), { code: "ENOENT" });
  await assert.rejects(journal.recordDispatch(record()), /owner recovery/);
});

test("a short failed write is fenced and a fresh reader rejects its torn tail", async (t) => {
  const { path, prototype, journal } = await fixture(t);
  const writeFile = prototype.writeFile;
  let failed = false;
  t.mock.method(prototype, "writeFile", async function (data, ...options) {
    if (!failed) {
      failed = true;
      await writeFile.call(this, data.slice(0, 17), ...options);
      throw ioFailure();
    }
    return writeFile.call(this, data, ...options);
  });
  await assert.rejects(journal.recordDispatch(record()), { code: "EIO" });
  const bytes = await readFile(path);
  await assert.rejects(journal.recordDispatch(record("operation.2")), /owner recovery/);
  await assert.rejects(new FileBrowserOperationJournal(path).getOperation("profile.1", 1, "operation.1"), /incomplete/);
  assert.deepEqual(await readFile(path), bytes);
});

test("semantic rejection before writing does not fence unrelated work", async (t) => {
  const { journal } = await fixture(t);
  await journal.recordDispatch(record());
  await assert.rejects(journal.recordDispatch({ ...record(), semanticDigest: "3".repeat(64) }), /semantics/);
  await journal.recordDispatch(record("operation.2"));
  assert.deepEqual(await journal.getOperation("profile.1", 1, "operation.2"), record("operation.2"));
});

test("ENOENT from a directory barrier is not mistaken for an absent journal", async (t) => {
  const { path, prototype, journal } = await fixture(t, true);
  observeSync(t, prototype, async (event) => {
    if (event.kind === "directory") {
      throw Object.assign(new Error("injected directory race"), { code: "ENOENT" });
    }
  });
  await assert.rejects(journal.recordDispatch(record()), { code: "ENOENT" });
  await assert.rejects(stat(path), { code: "ENOENT" });
  await assert.rejects(journal.listOperations("profile.1", 1), /owner recovery/);
});

test("failed terminal persistence cannot be exposed as an ordinary success", async (t) => {
  const { prototype, journal } = await fixture(t);
  await journal.recordDispatch(record());
  observeSync(t, prototype, async (event) => {
    if (event.kind === "file") throw ioFailure();
  });
  await assert.rejects(journal.recordObservation({
    ...record(), status: "succeeded", terminalObserved: true,
    outcomeDigest: "3".repeat(64),
  }), { code: "EIO" });
  await assert.rejects(journal.getOperation("profile.1", 1, "operation.1"), /owner recovery/);
});

test("a close failure after a write also fences the live owner", async (t) => {
  const { prototype, journal } = await fixture(t);
  const sync = prototype.sync;
  let failed = false;
  t.mock.method(prototype, "sync", async function () {
    if ((await this.stat()).isFile() && !failed) {
      // Node owns close on each FileHandle, rather than on its prototype.
      // Install the fault on the actual journal handle after writing starts.
      const close = this.close;
      t.mock.method(this, "close", async function () {
        await close.call(this);
        failed = true;
        throw ioFailure();
      });
    }
    return sync.call(this);
  });
  await assert.rejects(journal.recordDispatch(record()), { code: "EIO" });
  await assert.rejects(journal.recordDispatch(record("operation.2")), /owner recovery/);
});
