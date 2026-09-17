import assert from "node:assert/strict";
import { mkdtemp, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { FileBrowserOperationJournal } from "../src/journal.js";

const D1 = "1".repeat(64);

test("file journal atomically persists an indeterminate intent and terminal observation", async () => {
  const dir = await mkdtemp(join(tmpdir(), "hepta-browser-journal-"));
  const path = join(dir, "operations.json");
  const journal = new FileBrowserOperationJournal(path);
  await journal.recordIntent({
    profileId: "profile.1",
    generation: 1,
    operationId: "operation.1",
    semanticDigest: D1,
    semantics: { operationId: "operation.1" },
    typedAction: { kind: "click", selector: "#x" },
    receipt: { terminalObserved: false, status: "indeterminate" },
    createdAtMs: 1,
    updatedAtMs: 1,
  });
  const outstanding = await journal.loadOutstandingOperations({ profileId: "profile.1", generation: 1 });
  assert.equal(outstanding.length, 1);
  await journal.recordObservation({
    profileId: "profile.1",
    generation: 1,
    operationId: "operation.1",
    receipt: { terminalObserved: true, status: "succeeded" },
  });
  const reopened = new FileBrowserOperationJournal(path);
  assert.equal(
    (await reopened.loadOutstandingOperations({ profileId: "profile.1", generation: 1 })).length,
    0,
  );
  const found = await reopened.findOperation({
    profileId: "profile.1",
    generation: 1,
    operationId: "operation.1",
  });
  assert.equal(found.receipt.status, "succeeded");
  if (process.platform !== "win32") {
    const metadata = await stat(path);
    assert.equal(metadata.mode & 0o077, 0);
  }
});

test("journal rejects semantic reuse for one operation identity", async () => {
  const dir = await mkdtemp(join(tmpdir(), "hepta-browser-journal-"));
  const journal = new FileBrowserOperationJournal(join(dir, "operations.json"));
  const base = {
    profileId: "profile.1",
    generation: 1,
    operationId: "operation.1",
    semanticDigest: D1,
    semantics: {},
    typedAction: {},
    receipt: { terminalObserved: false },
  };
  await journal.recordIntent(base);
  await assert.rejects(
    journal.recordIntent({ ...base, semanticDigest: "2".repeat(64) }),
    /conflicts/,
  );
});
