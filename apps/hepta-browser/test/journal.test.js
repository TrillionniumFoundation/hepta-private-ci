import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { FileBrowserOperationJournal } from "../src/journal.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);

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
    terminalObserved: false,
    observationReason: "dispatching",
    ...overrides,
  };
}

test("file journal fsyncs dispatch intent and restores latest observation", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-browser-journal-"));
  const path = join(root, "operations.jsonl");
  const journal = new FileBrowserOperationJournal(path);
  await journal.recordDispatch(record());
  await journal.recordObservation(record({
    status: "succeeded",
    outcomeDigest: D1,
    terminalObserved: true,
    observationReason: "terminal_observed",
  }));
  const reopened = new FileBrowserOperationJournal(path);
  const stored = await reopened.getOperation("profile.1", 1, "operation.1");
  assert.equal(stored.status, "succeeded");
  assert.equal(stored.terminalObserved, true);
  if (process.platform !== "win32") {
    const info = await stat(path);
    assert.equal(info.mode & 0o077, 0);
  }
});

test("file journal fails closed on tampering", async () => {
  const root = await mkdtemp(join(tmpdir(), "hepta-browser-journal-"));
  const path = join(root, "operations.jsonl");
  const journal = new FileBrowserOperationJournal(path);
  await journal.recordDispatch(record());
  const source = await readFile(path, "utf8");
  await writeFile(path, source.replace("dispatching", "tampered___"), { mode: 0o600 });
  const reopened = new FileBrowserOperationJournal(path);
  await assert.rejects(
    reopened.getOperation("profile.1", 1, "operation.1"),
    /checksum mismatch/,
  );
});
