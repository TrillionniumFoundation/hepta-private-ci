import assert from "node:assert/strict";
import {
  mkdtemp,
  open,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { FileBrowserOperationJournal } from "../src/journal.js";

const OPTIONS = { timeout: 5_000 };
function record(operationId = "operation.1") {
  return {
    profileId: "profile.1",
    generation: 1,
    operationId,
    requestDigest: "1".repeat(64),
    semanticDigest: "2".repeat(64),
    status: "indeterminate",
    terminalObserved: false,
    outcomeDigest: null,
  };
}
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "hepta-journal-owner-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "operations.jsonl");
  const probe = await open(join(root, "probe"), "w", 0o600);
  const prototype = Object.getPrototypeOf(probe);
  await probe.close();
  return { path, prototype, journal: new FileBrowserOperationJournal(path) };
}
function ioFailure() {
  return Object.assign(new Error("injected journal sync failure"), {
    code: "EIO",
  });
}

test(
  "same-path journal instances serialize unrelated admissions without lost history",
  OPTIONS,
  async (t) => {
    const { path, journal } = await fixture(t);
    const second = new FileBrowserOperationJournal(path);
    await Promise.all([
      journal.recordDispatch(record()),
      second.recordDispatch(record("operation.2")),
    ]);
    assert.deepEqual(await journal.listOperations("profile.1", 1), [
      record(),
      record("operation.2"),
    ]);
    assert.deepEqual(await second.listOperations("profile.1", 1), [
      record(),
      record("operation.2"),
    ]);
  },
);

test(
  "complete-looking failed-sync bytes retain a recovery fence for a fresh owner",
  OPTIONS,
  async (t) => {
    const { path, prototype, journal } = await fixture(t);
    const sync = prototype.sync;
    t.mock.method(prototype, "sync", async function () {
      if ((await this.stat()).isFile()) throw ioFailure();
      return sync.call(this);
    });
    await assert.rejects(journal.recordDispatch(record()), { code: "EIO" });
    const before = await readFile(path);
    assert.ok(before.toString("utf8").endsWith("\n"));
    const fresh = new FileBrowserOperationJournal(path);
    await assert.rejects(
      fresh.getOperation("profile.1", 1, "operation.1"),
      /owner recovery/,
    );
    await assert.rejects(
      fresh.recordDispatch(record("operation.2")),
      /owner recovery/,
    );
    assert.deepEqual(await readFile(path), before);
  },
);

test(
  "writer lock directory barrier precedes the risky file write",
  OPTIONS,
  async (t) => {
    const { path, prototype, journal } = await fixture(t);
    await journal.recordDispatch(record());
    const before = await readFile(path);
    const sync = prototype.sync;
    let fileWrites = 0;
    const write = prototype.writeFile;
    t.mock.method(prototype, "writeFile", async function (...args) {
      fileWrites += 1;
      return write.apply(this, args);
    });
    let failed = false;
    t.mock.method(prototype, "sync", async function () {
      if ((await this.stat()).isDirectory() && !failed) {
        failed = true;
        throw ioFailure();
      }
      return sync.call(this);
    });
    await assert.rejects(journal.recordDispatch(record("operation.2")), {
      code: "EIO",
    });
    assert.equal(fileWrites, 0);
    assert.deepEqual(await readFile(path), before);
    await assert.rejects(
      new FileBrowserOperationJournal(path).listOperations("profile.1", 1),
      /owner recovery/,
    );
  },
);

test(
  "file replacement during sync cannot acknowledge detached history",
  OPTIONS,
  async (t) => {
    const { path, prototype, journal } = await fixture(t);
    const sync = prototype.sync;
    let replaced = false;
    t.mock.method(prototype, "sync", async function () {
      if ((await this.stat()).isFile() && !replaced) {
        replaced = true;
        await rename(path, `${path}.detached`);
        await writeFile(path, "", { mode: 0o600 });
      }
      return sync.call(this);
    });
    await assert.rejects(
      journal.recordDispatch(record()),
      /file identity changed/,
    );
    await assert.rejects(
      new FileBrowserOperationJournal(path).listOperations("profile.1", 1),
      /owner recovery/,
    );
    assert.equal(await readFile(path, "utf8"), "");
    assert.match(await readFile(`${path}.detached`, "utf8"), /operation.1/);
  },
);

test(
  "deletion after verified history poisons the owner and retains its acquired lock",
  OPTIONS,
  async (t) => {
    const { path, journal } = await fixture(t);
    await journal.recordDispatch(record());
    await rm(path);
    await assert.rejects(
      journal.getOperation("profile.1", 1, "operation.1"),
      /history disappeared/,
    );
    await assert.rejects(
      new FileBrowserOperationJournal(path).recordDispatch(record()),
      /owner recovery/,
    );
    await assert.rejects(readFile(path), { code: "ENOENT" });
  },
);
