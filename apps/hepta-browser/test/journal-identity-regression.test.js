import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { appendFile, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { FileBrowserOperationJournal, MemoryBrowserOperationJournal } from "../src/journal.js";

const D1 = "1".repeat(64);
const D2 = "2".repeat(64);
const D3 = "3".repeat(64);
function record(overrides = {}) {
  return {
    profileId: "profile.1", principalId: "principal.1", generation: 1,
    operationId: "operation.1", requestDigest: D1, semanticDigest: D2,
    processId: "servo.process.1", pageGeneration: 1, documentDigest: D1,
    action: "navigate", destinationOrigin: "https://example.com",
    finalPayloadDigest: D1, profileGrantDigest: D1, effectGrantDigest: D2,
    authorityEpoch: 7, deadlineMs: 9000, verifiedUseTokenWitnessDigest: D1,
    status: "indeterminate", outcomeDigest: null, terminalObserved: false,
    terminalEvidenceDigest: null, observationReason: "dispatching", ...overrides,
  };
}
function terminal(overrides = {}) {
  return record({ status: "succeeded", outcomeDigest: D3, terminalObserved: true,
    observationReason: "terminal_observed", ...overrides });
}
async function fixture(t, kind = "file") {
  if (kind === "memory") return { journal: new MemoryBrowserOperationJournal() };
  const root = await mkdtemp(join(tmpdir(), "browser-journal-identity-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "journal.jsonl");
  return { path, journal: new FileBrowserOperationJournal(path) };
}
function line(type, value) {
  const unsigned = { schema: "hepta.browser.operation-journal.v2", version: 2, type,
    record: Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) };
  return JSON.stringify({ ...unsigned,
    checksum: createHash("sha256").update(JSON.stringify(unsigned)).digest("hex") }) + "\n";
}
const substitutions = {
  principalId: "principal.other", processId: "servo.process.other", action: "click",
  destinationOrigin: "https://other.example", pageGeneration: 2, documentDigest: D3,
  finalPayloadDigest: D3, profileGrantDigest: D3, effectGrantDigest: D3,
  authorityEpoch: 8, deadlineMs: 10000, verifiedUseTokenWitnessDigest: D3,
};
for (const kind of ["memory", "file"]) {
  for (const [field, value] of Object.entries(substitutions)) {
    test(`${kind}: matching digests cannot substitute immutable ${field}`, async (t) => {
      const { journal, path } = await fixture(t, kind);
      await journal.recordDispatch(record());
      const bytes = path ? await readFile(path) : null;
      await assert.rejects(journal.recordDispatch(record({ [field]: value })), /semantics/);
      await assert.rejects(journal.recordObservation(terminal({ [field]: value })), /semantics/);
      assert.deepEqual(await journal.getOperation("profile.1", 1, "operation.1"), record());
      if (path) assert.deepEqual(await readFile(path), bytes);
      await journal.recordObservation(terminal());
      await journal.recordDispatch(record({ operationId: "operation.unrelated" }));
      assert.equal((await journal.getOperation("profile.1", 1, "operation.1")).status, "succeeded");
    });
  }
  test(`${kind}: retired generation cannot resurrect through direct journal dispatch`, async (t) => {
    const { journal, path } = await fixture(t, kind);
    await journal.recordDispatch(record());
    await journal.recordObservation(terminal());
    await journal.retireProfile("profile.1", 1);
    const reopened = path ? new FileBrowserOperationJournal(path) : journal;
    await assert.rejects(reopened.recordDispatch(record()), /retired/);
    await reopened.recordDispatch(record({ generation: 2 }));
    assert.equal(await reopened.getOperation("profile.1", 1, "operation.1"), null);
  });
}

for (const type of ["observation", "snapshot", "dispatch"]) {
  test(`file: checksum-valid ${type} replay cannot substitute principal identity`, async (t) => {
    const { journal, path } = await fixture(t);
    await journal.recordDispatch(record());
    const replacement = type === "dispatch" ? record({ principalId: "principal.other" })
      : terminal({ principalId: "principal.other" });
    await appendFile(path, line(type, replacement));
    await assert.rejects(new FileBrowserOperationJournal(path).listOperations("profile.1", 1), /semantics/);
  });
}

test("retirement ledger round-trips mixed-case, punctuation and numeric profile identities", async (t) => {
  const { journal, path } = await fixture(t);
  const ids = ["profile.a", "profile.A", "profile_a", "profile-a", "2", "10", "__proto__"];
  for (const profileId of ids) await journal.retireProfile(profileId, 1);
  const reopened = new FileBrowserOperationJournal(path);
  for (const profileId of ids) {
    await assert.rejects(reopened.assertProfileGenerationAvailable(profileId, 1), /retired/);
    await reopened.assertProfileGenerationAvailable(profileId, 2);
  }
});

test("terminal identity survives compaction and exact dispatch remains a no-op", async (t) => {
  const { journal, path } = await fixture(t);
  await journal.recordDispatch(record());
  await journal.recordObservation(terminal());
  await journal.compact();
  const bytes = await readFile(path);
  const reopened = new FileBrowserOperationJournal(path);
  await reopened.recordDispatch(record());
  await reopened.recordObservation(terminal());
  assert.deepEqual(await readFile(path), bytes);
  assert.deepEqual(await reopened.getOperation("profile.1", 1, "operation.1"), terminal());
});
