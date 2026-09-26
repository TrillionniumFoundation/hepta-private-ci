import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  appendFile,
  mkdtemp,
  readFile,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";

import {
  FileBrowserOperationJournal,
  MemoryBrowserOperationJournal,
} from "../src/journal.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);

function dispatch(overrides = {}) {
  return {
    profileId: "profile.1",
    principalId: "principal.1",
    generation: 1,
    operationId: "operation.1",
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

function terminal(overrides = {}) {
  return dispatch({
    status: "succeeded",
    outcomeDigest: D3,
    terminalEvidenceDigest: null,
    terminalObserved: true,
    observationReason: "terminal_observed",
    ...overrides,
  });
}

async function fixture(t, kind) {
  if (kind === "memory") {
    return { journal: new MemoryBrowserOperationJournal() };
  }
  const root = await mkdtemp(join(tmpdir(), "hepta-journal-v2-monotonic-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "operations.jsonl");
  return { path, root, journal: new FileBrowserOperationJournal(path) };
}

function envelope(type, record) {
  const unsigned = {
    schema: "hepta.browser.operation-journal.v2",
    version: 2,
    type,
    record,
  };
  const checksum = createHash("sha256")
    .update(JSON.stringify(unsigned))
    .digest("hex");
  return `${JSON.stringify({ ...unsigned, checksum })}\n`;
}

for (const kind of ["memory", "file"]) {
  test(`${kind}: duplicate dispatch cannot erase terminal state`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(dispatch());
    await journal.recordObservation(terminal());
    await journal.recordDispatch(dispatch());
    assert.deepEqual(
      await journal.getOperation("profile.1", 1, "operation.1"),
      terminal(),
    );
  });

  test(`${kind}: semantic identity is immutable`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(dispatch());
    await assert.rejects(
      journal.recordDispatch(dispatch({ semanticDigest: D4 })),
      /changed semantics/,
    );
  });

  test(`${kind}: terminal state cannot roll back or fork`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(dispatch());
    await journal.recordObservation(terminal());
    await assert.rejects(journal.recordObservation(dispatch()), /terminal/);
    await assert.rejects(
      journal.recordObservation(terminal({ outcomeDigest: D4 })),
      /terminal/,
    );
    await journal.recordObservation(terminal());
    assert.deepEqual(
      await journal.getOperation("profile.1", 1, "operation.1"),
      terminal(),
    );
  });
}

test("file: exact retries are byte-for-byte no-ops", async (t) => {
  const { path, journal } = await fixture(t, "file");
  await journal.recordDispatch(dispatch());
  const afterDispatch = await readFile(path);
  await journal.recordDispatch(dispatch());
  assert.deepEqual(await readFile(path), afterDispatch);

  await journal.recordObservation(terminal());
  const afterTerminal = await readFile(path);
  await journal.recordObservation(terminal());
  assert.deepEqual(await readFile(path), afterTerminal);
});

test("file: historical duplicate dispatch is projected and physically migrated", async (t) => {
  const { path, journal } = await fixture(t, "file");
  await writeFile(
    path,
    envelope("dispatch", dispatch()) +
      envelope("observation", terminal()) +
      envelope("dispatch", dispatch()),
    { mode: 0o600 },
  );
  const before = (await stat(path)).size;
  const recovered = await journal.getOperation("profile.1", 1, "operation.1");
  assert.deepEqual(recovered, terminal());
  const migrated = await readFile(path, "utf8");
  assert.match(migrated, /"type":"snapshot"/);
  assert.ok((await stat(path)).size < before);
  assert.equal(migrated.split("\n").filter(Boolean).length, 1);
});

test("file: a live cross-process owner lock fails closed", async (t) => {
  const { path, journal } = await fixture(t, "file");
  await writeFile(
    `${path}.owner.lock`,
    `${JSON.stringify({
      schema: "hepta.browser.journal-owner-lock.v1",
      pid: process.pid,
      createdAtMs: Date.now(),
      token: "live-owner",
    })}\n`,
    { mode: 0o600 },
  );
  await assert.rejects(
    journal.getOperation("profile.1", 1, "operation.1"),
    (error) => error?.code === "BROWSER_JOURNAL_OWNER_LOCKED",
  );
});

test("file: a dead stale owner lock is reclaimed once", async (t) => {
  const { path, journal } = await fixture(t, "file");
  await writeFile(
    `${path}.owner.lock`,
    `${JSON.stringify({
      schema: "hepta.browser.journal-owner-lock.v1",
      pid: 2_147_483_647,
      createdAtMs: 1,
      token: "dead-owner",
    })}\n`,
    { mode: 0o600 },
  );
  const recovering = new FileBrowserOperationJournal(path, { ownerLockStaleMs: 1 });
  assert.equal(
    await recovering.getOperation("profile.1", 1, "operation.1"),
    null,
  );
  await assert.rejects(stat(`${path}.owner.lock`), { code: "ENOENT" });
});

test("file: durability I/O failure fences the live owner", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "hepta-journal-v2-fence-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "operations.jsonl");
  let injected = false;
  const journal = new FileBrowserOperationJournal(path, {
    faultInjector(name) {
      if (!injected && name === "append_created_fsynced_before_parent_fsync") {
        injected = true;
        throw Object.assign(new Error("injected durable fault"), { code: "EIO" });
      }
    },
  });
  await assert.rejects(journal.recordDispatch(dispatch()), { code: "EIO" });
  await assert.rejects(
    journal.getOperation("profile.1", 1, "operation.1"),
    (error) => error?.code === "BROWSER_JOURNAL_FENCED",
  );
  assert.equal(dirname(path), root);
});
