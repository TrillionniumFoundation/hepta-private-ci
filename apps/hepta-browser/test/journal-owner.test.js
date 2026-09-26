import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { FileBrowserOperationJournal } from "../src/journal.js";
import {
  BrowserJournalFencedError,
  BrowserJournalOwnershipError,
  OwnedMonotonicBrowserOperationJournal,
} from "../src/journal-owner.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
const D4 = "4".repeat(64);

function record(overrides = {}) {
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
  return record({
    status: "succeeded",
    outcomeDigest: D3,
    terminalEvidenceDigest: null,
    terminalObserved: true,
    observationReason: "terminal_observed",
    ...overrides,
  });
}

async function fixture(t, name = "owner") {
  const root = await mkdtemp(join(tmpdir(), `hepta-browser-${name}-`));
  t.after(() => rm(root, { recursive: true, force: true }));
  const journalPath = join(root, "operations.jsonl");
  const lockPath = `${journalPath}.owner.lock`;
  const backing = new FileBrowserOperationJournal(journalPath);
  const journal = new OwnedMonotonicBrowserOperationJournal({
    journal: backing,
    lockPath,
  });
  t.after(() => journal.close().catch(() => {}));
  return { root, journalPath, lockPath, backing, journal };
}

test("owned journal makes exact retries byte-stable and terminal observations monotonic", async (t) => {
  const { journalPath, journal } = await fixture(t, "monotonic");
  await journal.recordDispatch(record());
  const firstDispatch = await readFile(journalPath);
  await journal.recordDispatch(record());
  assert.deepEqual(await readFile(journalPath), firstDispatch);

  await journal.recordObservation(terminal());
  const firstTerminal = await readFile(journalPath);
  await journal.recordObservation(terminal());
  await journal.recordDispatch(record());
  assert.deepEqual(await readFile(journalPath), firstTerminal);

  await assert.rejects(
    journal.recordObservation(record({ observationReason: "late_indeterminate" })),
    /cannot change or return to indeterminate/,
  );
  await assert.rejects(
    journal.recordObservation(terminal({ outcomeDigest: D4 })),
    /cannot change or return to indeterminate/,
  );
  await assert.rejects(
    journal.recordDispatch(record({ semanticDigest: D4 })),
    /changed semantics/,
  );
  assert.deepEqual(await journal.getOperation("profile.1", 1, "operation.1"), terminal());
});

test("only one live process owner can open a journal path", async (t) => {
  const { journalPath, lockPath, journal: first } = await fixture(t, "exclusive");
  await first.acquire();
  const second = new OwnedMonotonicBrowserOperationJournal({
    journal: new FileBrowserOperationJournal(journalPath),
    lockPath,
  });
  t.after(() => second.close().catch(() => {}));

  await assert.rejects(second.acquire(), BrowserJournalOwnershipError);
  await first.close();
  await second.acquire();
  await second.recordDispatch(record());
  assert.notEqual(await second.getOperation("profile.1", 1, "operation.1"), null);
});

test("a durable I/O failure fences all later reads and writes", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "hepta-browser-fence-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const failure = Object.assign(new Error("injected durable write failure"), { code: "EIO" });
  const backing = {
    durable: true,
    async assertProfileGenerationAvailable() {},
    async getOperation() { return null; },
    async listOperations() { return []; },
    async recordDispatch() { throw failure; },
    async recordObservation() {},
    async retireProfile() {},
  };
  const journal = new OwnedMonotonicBrowserOperationJournal({
    journal: backing,
    lockPath: join(root, "operations.owner.lock"),
  });
  t.after(() => journal.close().catch(() => {}));

  await assert.rejects(journal.recordDispatch(record()), { code: "EIO" });
  await assert.rejects(
    journal.getOperation("profile.1", 1, "operation.1"),
    BrowserJournalFencedError,
  );
});
