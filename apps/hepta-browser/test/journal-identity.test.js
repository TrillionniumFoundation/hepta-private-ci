import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { appendFile, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FileBrowserOperationJournal, MemoryBrowserOperationJournal } from "../src/journal.js";

const D1 = "1".repeat(64), D2 = "2".repeat(64), D3 = "3".repeat(64);
function record(extra = {}) {
  return { profileId: "profile.1", generation: 1, operationId: "operation.1",
    requestDigest: D1, semanticDigest: D2, principalId: "principal.1", processId: "worker.1",
    pageGeneration: 1, documentDigest: D3, finalPayloadDigest: D1, deadlineMs: 7000,
    authorityEpoch: 7, status: "indeterminate", terminalObserved: false, outcomeDigest: null,
    ...extra };
}
function terminal() {
  return record({ status: "succeeded", terminalObserved: true, outcomeDigest: D3 });
}
async function fixture(t, kind) {
  if (kind === "memory") return { journal: new MemoryBrowserOperationJournal() };
  const root = await mkdtemp(join(tmpdir(), "hepta-journal-identity-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "operations.jsonl");
  return { path, journal: new FileBrowserOperationJournal(path) };
}
function envelope(type, value) {
  const unsigned = { schema: "hepta.browser.operation-journal.v1", version: 1, type, record: value };
  return JSON.stringify({ ...unsigned, checksum: createHash("sha256").update(JSON.stringify(unsigned)).digest("hex") }) + "\n";
}

for (const kind of ["memory", "file"]) {
  test(`${kind}: matching hashes cannot substitute owner, target, process, epoch or deadline`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    for (const replacement of [ { principalId: "other" }, { processId: "worker.2" },
      { pageGeneration: 2 }, { documentDigest: D1 }, { finalPayloadDigest: D2 },
      { deadlineMs: 9000 }, { authorityEpoch: 8 }, { unregisteredIdentity: "new" } ]) {
      await assert.rejects(journal.recordDispatch(record(replacement)), /semantics/);
      await assert.rejects(journal.recordObservation(record(replacement)), /semantics/);
    }
    assert.deepEqual(await journal.getOperation("profile.1", 1, "operation.1"), record());
    await journal.recordObservation(terminal());
    assert.deepEqual(await journal.getOperation("profile.1", 1, "operation.1"), terminal());
  });

  test(`${kind}: inconsistent outcomes, nested values and identity delimiters reject`, async (t) => {
    const { journal } = await fixture(t, kind);
    for (const replacement of [ { profileId: "bad\u0000key" }, { operationId: [] },
      { generation: 1.5 }, { requestDigest: "0".repeat(64) }, { semanticDigest: D1.toUpperCase().replace("1", "A") },
      { terminalObserved: true }, { status: "succeeded" }, { outcomeDigest: D3 },
      { status: "indeterminate", terminalObserved: true, outcomeDigest: D3 },
      { mutation: { nested: 1 } }, { deadlineMs: Number.NaN } ]) {
      await assert.rejects(journal.recordDispatch(record(replacement)), /identity|terminal|scalar/);
    }
    assert.deepEqual(await journal.listOperations("profile.1", 1), []);
  });

  test(`${kind}: a dispatch cannot manufacture a completed operation`, async (t) => {
    const { journal } = await fixture(t, kind);
    await assert.rejects(journal.recordDispatch(terminal()), /dispatch.*terminal/);
    assert.deepEqual(await journal.listOperations("profile.1", 1), []);
  });

  test(`${kind}: legacy presentation fields never become durable authority`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    for (const field of ["networkAuthority", "filesystemAuthority", "credentialExportAuthority"]) {
      await assert.rejects(journal.recordObservation({ ...terminal(), [field]: true }), /authority/);
    }
    await journal.recordObservation({ ...terminal(), kind: "BrowserEffectObservationV1",
      networkAuthority: false, filesystemAuthority: false, credentialExportAuthority: false });
    assert.deepEqual(await journal.getOperation("profile.1", 1, "operation.1"), terminal());
  });
}

test("old V1 public-projection observation bytes restore without schema or checksum reinterpretation", async (t) => {
  const { path, journal } = await fixture(t, "file");
  await journal.recordDispatch(record());
  await appendFile(path, envelope("observation", { ...terminal(), kind: "BrowserEffectObservationV1",
    networkAuthority: false, filesystemAuthority: false, credentialExportAuthority: false }));
  const before = await readFile(path);
  const reopened = new FileBrowserOperationJournal(path);
  assert.deepEqual(await reopened.getOperation("profile.1", 1, "operation.1"), terminal());
  await reopened.recordDispatch(record());
  assert.deepEqual(await readFile(path), before);
});

test("valid V1 checksums do not authorize forged public authority projections", async (t) => {
  const { path, journal } = await fixture(t, "file");
  await journal.recordDispatch(record());
  await appendFile(path, envelope("observation", { ...terminal(), networkAuthority: true }));
  await assert.rejects(new FileBrowserOperationJournal(path).listOperations("profile.1", 1), /authority/);
});
