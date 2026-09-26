import assert from "node:assert/strict";
import test from "node:test";
import {
  chmod,
  mkdtemp,
  readFile,
  stat,
  writeFile,
} from "node:fs/promises";
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
    terminalEvidenceDigest: null,
    terminalObserved: false,
    observationReason: "dispatching",
    ...overrides,
  };
}

async function journalFixture() {
  const root = await mkdtemp(join(tmpdir(), "hepta-browser-journal-"));
  const path = join(root, "operations.jsonl");
  return { root, path, journal: new FileBrowserOperationJournal(path) };
}

test("file journal fsyncs dispatch intent and restores latest observation", async () => {
  const { path, journal } = await journalFixture();
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

test("file journal fails closed on checksum tampering", async () => {
  const { path, journal } = await journalFixture();
  await journal.recordDispatch(record());
  const source = await readFile(path, "utf8");
  await writeFile(path, source.replace("dispatching", "tampered___"), { mode: 0o600 });
  const reopened = new FileBrowserOperationJournal(path);
  await assert.rejects(
    reopened.getOperation("profile.1", 1, "operation.1"),
    /checksum mismatch/,
  );
});

test("file journal recovers a validated prefix after a crash-torn final append", async () => {
  const { path, journal } = await journalFixture();
  await journal.recordDispatch(record());
  await journal.recordObservation(record({
    status: "succeeded",
    outcomeDigest: D1,
    terminalObserved: true,
    observationReason: "terminal_observed",
  }));

  const complete = await readFile(path, "utf8");
  const lines = complete.split("\n").filter(Boolean);
  assert.equal(lines.length, 2);
  const tornObservation = lines[1].slice(0, Math.floor(lines[1].length / 2));
  await writeFile(path, `${lines[0]}\n${tornObservation}`, { mode: 0o600 });

  const reopened = new FileBrowserOperationJournal(path);
  const stored = await reopened.getOperation("profile.1", 1, "operation.1");
  assert.equal(stored.status, "indeterminate");
  assert.equal(stored.terminalObserved, false);

  // The first reopen must physically repair the torn tail before continuing.
  await reopened.recordObservation(record({
    status: "failed",
    outcomeDigest: D2,
    terminalObserved: true,
    observationReason: "terminal_observed",
  }));
  const reopenedAgain = new FileBrowserOperationJournal(path);
  const repaired = await reopenedAgain.getOperation("profile.1", 1, "operation.1");
  assert.equal(repaired.status, "failed");
  assert.equal(repaired.terminalObserved, true);

  await writeFile(path, `${lines[0]}\n{"broken":\n`, { mode: 0o600 });
  const newlineTerminatedCorruption = new FileBrowserOperationJournal(path);
  await assert.rejects(
    newlineTerminatedCorruption.getOperation("profile.1", 1, "operation.1"),
    /malformed JSON/,
  );
});

test("first journal creation reaches the parent-directory durability boundary", async () => {
  const { path } = await journalFixture();
  let reached = false;
  const journal = new FileBrowserOperationJournal(path, {
    faultInjector(name) {
      if (name === "append_created_fsynced_before_parent_fsync") {
        reached = true;
        throw new Error("qualification crash before parent fsync");
      }
    },
  });
  await assert.rejects(
    journal.recordDispatch(record()),
    /qualification crash before parent fsync/,
  );
  assert.equal(reached, true);

  // The injected cut is before the directory fsync. On a live filesystem the
  // file may still be visible, but no production dispatch can proceed because
  // recordDispatch did not return success.
  const reopened = new FileBrowserOperationJournal(path);
  const stored = await reopened.getOperation("profile.1", 1, "operation.1");
  assert.notEqual(stored, null);
});

test("journal validates every hydrated record and rejects secret-bearing unknown fields", async () => {
  const { journal } = await journalFixture();
  await assert.rejects(
    journal.recordDispatch({
      ...record(),
      typedAction: { kind: "type", selector: "#password", text: "do-not-persist" },
    }),
    /missing or unknown fields/,
  );
  await assert.rejects(
    journal.recordDispatch(record({ requestDigest: "0".repeat(64) })),
    /non-zero lowercase SHA-256 digest/,
  );
  await assert.rejects(
    journal.recordDispatch(record({ terminalObserved: true })),
    /indeterminate journal record cannot claim a terminal outcome/,
  );
});

test("explicit compaction preserves latest immutable operations", async () => {
  const { path, journal } = await journalFixture();
  for (let index = 0; index < 25; index += 1) {
    const operationId = `operation.${index}`;
    await journal.recordDispatch(record({ operationId }));
    await journal.recordObservation(record({
      operationId,
      status: "succeeded",
      outcomeDigest: D1,
      terminalObserved: true,
      observationReason: "terminal_observed",
    }));
  }
  const before = (await readFile(path, "utf8")).split("\n").filter(Boolean).length;
  assert.equal(before, 50);
  await journal.compact();
  const after = (await readFile(path, "utf8")).split("\n").filter(Boolean).length;
  assert.equal(after, 25);
  const reopened = new FileBrowserOperationJournal(path);
  assert.equal((await reopened.listOperations("profile.1", 1)).length, 25);
  assert.equal((await reopened.getOperation("profile.1", 1, "operation.0")).status, "succeeded");
});

test("compaction crash cuts retain a reopenable validated operation", async () => {
  for (const point of [
    "compact_temp_fsynced_before_rename",
    "compact_renamed_before_parent_fsync",
  ]) {
    const { path } = await journalFixture();
    const journal = new FileBrowserOperationJournal(path, {
      faultInjector(name) {
        if (name === point) throw new Error(`qualification crash at ${name}`);
      },
    });
    await journal.recordDispatch(record());
    await assert.rejects(journal.compact(), /qualification crash/);

    const reopened = new FileBrowserOperationJournal(path);
    const stored = await reopened.getOperation("profile.1", 1, "operation.1");
    assert.equal(stored.status, "indeterminate", point);
    assert.equal(stored.terminalObserved, false, point);
  }
});

test("retirement crash cuts never resurrect a terminal profile generation", async () => {
  for (const point of [
    "retired_temp_fsynced_before_rename",
    "retired_renamed_before_parent_fsync",
    "retired_high_water_committed_before_journal_rewrite",
  ]) {
    const { path, journal } = await journalFixture();
    await journal.recordDispatch(record());
    await journal.recordObservation(record({
      status: "succeeded",
      outcomeDigest: D1,
      terminalEvidenceDigest: null,
      terminalObserved: true,
      observationReason: "terminal_observed",
    }));

    const crashing = new FileBrowserOperationJournal(path, {
      faultInjector(name) {
        if (name === point) throw new Error(`qualification crash at ${name}`);
      },
    });
    await assert.rejects(
      crashing.retireProfile("profile.1", 1),
      /qualification crash/,
    );

    const reopened = new FileBrowserOperationJournal(path);
    await assert.rejects(
      reopened.assertProfileGenerationAvailable("profile.1", 1),
      /durable operation history|already been retired/,
      point,
    );
    assert.notEqual(
      await reopened.getOperation("profile.1", 1, "operation.1"),
      null,
      point,
    );
  }
});

test("durable history blocks generation resurrection and unresolved cross-generation advance", async () => {
  const { journal } = await journalFixture();
  await journal.recordDispatch(record({ operationId: "operation.unknown" }));
  await assert.rejects(
    journal.assertProfileGenerationAvailable("profile.1", 1),
    /durable operation history/,
  );
  await assert.rejects(
    journal.assertProfileGenerationAvailable("profile.1", 2),
    /unresolved durable effects/,
  );

  await journal.recordObservation(
    record({
      operationId: "operation.unknown",
      status: "succeeded",
      outcomeDigest: D1,
      terminalObserved: true,
      observationReason: "terminal_observed",
    }),
  );
  await journal.assertProfileGenerationAvailable("profile.1", 2);
  await assert.rejects(
    journal.assertProfileGenerationAvailable("profile.1", 1),
    /durable operation history/,
  );
});

test("profile retirement removes records and durably fences generation resurrection", async () => {
  const { path, journal } = await journalFixture();
  await journal.recordDispatch(record({ operationId: "operation.old" }));
  await journal.recordObservation(record({
    operationId: "operation.old",
    status: "failed",
    outcomeDigest: D2,
    terminalObserved: true,
    observationReason: "terminal_observed",
  }));
  await journal.recordDispatch(record({
    profileId: "profile.2",
    operationId: "operation.keep",
  }));
  await journal.retireProfile("profile.1", 1);
  await assert.rejects(
    journal.assertProfileGenerationAvailable("profile.1", 1),
    /already been retired/,
  );
  await journal.assertProfileGenerationAvailable("profile.1", 2);

  const reopened = new FileBrowserOperationJournal(path);
  assert.equal(await reopened.getOperation("profile.1", 1, "operation.old"), null);
  assert.notEqual(await reopened.getOperation("profile.2", 1, "operation.keep"), null);
  await assert.rejects(
    reopened.assertProfileGenerationAvailable("profile.1", 1),
    /already been retired/,
  );
  await reopened.assertProfileGenerationAvailable("profile.1", 2);
});


test("file journal rejects a pre-existing broad parent directory", async (t) => {
  if (process.platform === "win32") {
    t.skip("Unix mode bits are not authoritative on Windows");
    return;
  }
  const { root, journal } = await journalFixture();
  await chmod(root, 0o755);
  await assert.rejects(
    journal.recordDispatch(record()),
    /parent directory permissions are too broad/,
  );
});
