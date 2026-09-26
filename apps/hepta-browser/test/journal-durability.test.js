import assert from "node:assert/strict";
import { hostname } from "node:os";
import {
  mkdtemp,
  open,
  readFile,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";

import { FileBrowserOperationJournal } from "../src/journal.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);

function record(operationId = "operation.1", overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId,
    requestDigest: D1,
    semanticDigest: D2,
    processId: "servo.process.1",
    pageGeneration: 1,
    documentDigest: D1,
    action: "navigate",
    destinationOrigin: "https://example.com",
    finalPayloadDigest: D1,
    profileGrantDigest: D1,
    effectGrantDigest: D2,
    authorityEpoch: 7,
    deadlineMs: 9_000,
    verifiedUseTokenWitnessDigest: D1,
    status: "indeterminate",
    outcomeDigest: null,
    terminalEvidenceDigest: null,
    terminalObserved: false,
    observationReason: "dispatching",
    ...overrides,
  };
}

function terminal(operationId = "operation.1", overrides = {}) {
  return record(operationId, {
    status: "succeeded",
    outcomeDigest: D3,
    terminalObserved: true,
    observationReason: "terminal_observed",
    ...overrides,
  });
}

async function fixture(t, nested = false) {
  const root = await mkdtemp(join(tmpdir(), "hepta-journal-durability-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(
    root,
    ...(nested ? ["owner", "generation"] : []),
    "operations.jsonl",
  );
  const probe = await open(join(root, "prototype-probe"), "w", 0o600);
  const prototype = Object.getPrototypeOf(probe);
  await probe.close();
  return {
    root,
    path,
    prototype,
    journal: new FileBrowserOperationJournal(path),
  };
}

function identity(info) {
  return `${info.dev}:${info.ino}`;
}

function observeSync(t, prototype, before = async () => {}) {
  const events = [];
  const sync = prototype.sync;
  t.mock.method(prototype, "sync", async function () {
    const info = await this.stat();
    const event = {
      kind: info.isDirectory() ? "directory" : "file",
      id: identity(info),
    };
    events.push(event);
    await before(event, events);
    return sync.call(this);
  });
  return events;
}

function ioFailure() {
  return Object.assign(new Error("injected journal durability failure"), {
    code: "EIO",
  });
}

test("dispatch awaits the file barrier followed by its parent-directory barrier", async (t) => {
  const { root, prototype, journal } = await fixture(t);
  const events = observeSync(t, prototype);
  await journal.recordDispatch(record());
  const parentId = identity(await stat(root));
  assert.deepEqual(
    events.slice(-2).map((event) => event.kind),
    ["file", "directory"],
  );
  assert.equal(events.at(-1).id, parentId);
});

test("new nested parents and their directory entries are synchronized", async (t) => {
  const { root, path, prototype, journal } = await fixture(t, true);
  const events = observeSync(t, prototype);
  await journal.recordDispatch(record());
  const synchronized = new Set(
    events
      .filter((event) => event.kind === "directory")
      .map((event) => event.id),
  );
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
  assert.deepEqual(
    events.map((event) => event.kind),
    ["file", "directory"],
  );
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
    journal.recordDispatch(record()),
    journal.recordDispatch(record("operation.2")),
  ]);
  assert.equal(results[0].status, "rejected");
  assert.equal(results[0].reason.code, "EIO");
  assert.equal(results[1].status, "rejected");
  assert.match(results[1].reason.message, /owner requires recovery/);
  const bytes = await readFile(path);
  await assert.rejects(
    journal.recordDispatch(record()),
    /owner requires recovery/,
  );
  await assert.rejects(
    journal.getOperation("profile.1", 1, "operation.1"),
    /owner requires recovery/,
  );
  await assert.rejects(
    journal.listOperations("profile.1", 1),
    /owner requires recovery/,
  );
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
  await assert.rejects(
    journal.recordDispatch(record()),
    /owner requires recovery/,
  );
  await assert.rejects(
    journal.recordObservation(terminal()),
    /owner requires recovery/,
  );
  assert.deepEqual(await readFile(path), bytes);
});

test("a parent-initialization failure never creates or acknowledges a journal", async (t) => {
  const { path, prototype, journal } = await fixture(t, true);
  observeSync(t, prototype, async (event) => {
    if (event.kind === "directory") throw ioFailure();
  });
  await assert.rejects(journal.recordDispatch(record()), { code: "EIO" });
  await assert.rejects(stat(path), { code: "ENOENT" });
  await assert.rejects(
    journal.recordDispatch(record()),
    /owner requires recovery/,
  );
});

test("a short failed journal write is fenced and a fresh owner repairs its torn tail", async (t) => {
  const { path, prototype, journal } = await fixture(t);
  const writeFileOriginal = prototype.writeFile;
  let calls = 0;
  t.mock.method(prototype, "writeFile", async function (data, ...options) {
    calls += 1;
    // The first write is ephemeral owner-lock metadata; the second is the
    // journal append whose partial write must never be acknowledged.
    if (calls === 2) {
      await writeFileOriginal.call(this, data.slice(0, 17), ...options);
      throw ioFailure();
    }
    return writeFileOriginal.call(this, data, ...options);
  });
  await assert.rejects(journal.recordDispatch(record()), { code: "EIO" });
  const bytes = await readFile(path);
  await assert.rejects(
    journal.recordDispatch(record("operation.2")),
    /owner requires recovery/,
  );
  const fresh = new FileBrowserOperationJournal(path);
  assert.equal(
    await fresh.getOperation("profile.1", 1, "operation.1"),
    null,
  );
  assert.equal(await readFile(path, "utf8"), "");
  assert.notDeepEqual(await readFile(path), bytes);
});

test("semantic rejection before writing does not fence unrelated work", async (t) => {
  const { journal } = await fixture(t);
  await journal.recordDispatch(record());
  await assert.rejects(
    journal.recordDispatch(
      record("operation.1", { semanticDigest: D3 }),
    ),
    /semantics/,
  );
  await journal.recordDispatch(record("operation.2"));
  assert.deepEqual(
    await journal.getOperation("profile.1", 1, "operation.2"),
    record("operation.2"),
  );
});

test("ENOENT from a directory barrier is not mistaken for an absent journal", async (t) => {
  const { path, prototype, journal } = await fixture(t, true);
  observeSync(t, prototype, async (event) => {
    if (event.kind === "directory") {
      throw Object.assign(new Error("injected directory race"), {
        code: "ENOENT",
      });
    }
  });
  await assert.rejects(journal.recordDispatch(record()), { code: "ENOENT" });
  await assert.rejects(stat(path), { code: "ENOENT" });
  await assert.rejects(
    journal.listOperations("profile.1", 1),
    /owner requires recovery/,
  );
});

test("failed terminal persistence cannot be exposed as an ordinary success", async (t) => {
  const { prototype, journal } = await fixture(t);
  await journal.recordDispatch(record());
  observeSync(t, prototype, async (event) => {
    if (event.kind === "file") throw ioFailure();
  });
  await assert.rejects(
    journal.recordObservation(terminal()),
    { code: "EIO" },
  );
  await assert.rejects(
    journal.getOperation("profile.1", 1, "operation.1"),
    /owner requires recovery/,
  );
});

test("a close failure after a write also fences the live owner", async (t) => {
  const { prototype, journal } = await fixture(t);
  const sync = prototype.sync;
  let failed = false;
  t.mock.method(prototype, "sync", async function () {
    if ((await this.stat()).isFile() && !failed) {
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
  await assert.rejects(
    journal.recordDispatch(record("operation.2")),
    /owner requires recovery/,
  );
});

test("a second journal owner waits for the interprocess lock instead of racing the first", async (t) => {
  const { path, prototype } = await fixture(t);
  const first = new FileBrowserOperationJournal(path);
  const second = new FileBrowserOperationJournal(path);
  const sync = prototype.sync;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  let entered;
  const enteredPromise = new Promise((resolve) => {
    entered = resolve;
  });
  let blocked = false;
  t.mock.method(prototype, "sync", async function () {
    if ((await this.stat()).isFile() && !blocked) {
      blocked = true;
      entered();
      await gate;
    }
    return sync.call(this);
  });
  const left = first.recordDispatch(record());
  await enteredPromise;
  const right = second.recordDispatch(record("operation.2"));
  await new Promise((resolve) => setTimeout(resolve, 25));
  release();
  await Promise.all([left, right]);
  assert.equal((await second.listOperations("profile.1", 1)).length, 2);
});

test("a dead same-host owner lock is recovered before ordinary reads", async (t) => {
  const { path, journal } = await fixture(t);
  await writeFile(
    `${path}.owner-lock`,
    `${JSON.stringify({
      schema: "hepta.browser.journal-owner-lock.v1",
      pid: 2_147_483_000,
      hostname: hostname(),
      token: "dead-owner",
      path,
      createdAtMs: Date.now() - 60_000,
    })}\n`,
    { mode: 0o600 },
  );
  assert.equal(
    await journal.getOperation("profile.1", 1, "operation.1"),
    null,
  );
  await assert.rejects(stat(`${path}.owner-lock`), { code: "ENOENT" });
});
