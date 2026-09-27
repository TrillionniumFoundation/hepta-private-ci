import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FileBrowserOperationJournal, MemoryBrowserOperationJournal } from "../src/journal.js";
const D = "1".repeat(64), E = "2".repeat(64);
const hash = x => createHash("sha256").update(JSON.stringify(x)).digest("hex");
function dispatch() {
  return { profileId: "p", principalId: "owner", generation: 1, operationId: "op", requestDigest: D,
    semanticDigest: E, processId: "worker", pageGeneration: 0, documentDigest: null, action: "navigate",
    destinationOrigin: "https://example.com", finalPayloadDigest: D, profileGrantDigest: D, effectGrantDigest: E,
    authorityEpoch: 1, deadlineMs: 10000, verifiedUseTokenWitnessDigest: D, status: "indeterminate",
    outcomeDigest: null, terminalEvidenceDigest: null, terminalObserved: false, observationReason: "dispatching" };
}
function admission() {
  return { admission: { kind: "BrowserEffectAdmissionV1", operationId: "op", semanticDigest: E,
    workerGeneration: 1, pageRevision: 0, admittedAt: 100, durableOrRecoverable: true },
    profileId: "p", generation: 1, operationId: "op", requestDigest: D, semanticDigest: E };
}
function egress() {
  const unsigned = { schema: "hepta.browser.egress-operation-receipt.v1", operationId: "op",
    profileGrantDigest: D, effectGrantDigest: E, destinationOrigin: "https://example.com", status: "succeeded",
    admittedAtMs: 100, completedAtMs: 200, requestBytes: 123, responseBytes: 456, connectionCount: 1,
    boundedAbort: false, maxRequestBytes: 1024, maxResponseBytes: 1024 };
  return { profileId: "p", generation: 1, operationId: "op", requestDigest: D, semanticDigest: E,
    receipt: { ...unsigned, receiptDigest: hash(unsigned) } };
}
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "browser-evidence-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "journal"); return { path, journal: new FileBrowserOperationJournal(path) };
}
test("worker admission and network receipts survive reopen/compaction; reordered exact duplicates append no bytes", async t => {
  const { path, journal } = await fixture(t);
  await journal.recordDispatch(dispatch()); await journal.recordAdmission(admission()); await journal.recordEgress(egress());
  const before = (await stat(path)).size;
  const reordered = Object.fromEntries(Object.entries(admission()).reverse());
  reordered.admission = Object.fromEntries(Object.entries(reordered.admission).reverse());
  await journal.recordAdmission(reordered); await journal.recordEgress(egress());
  assert.equal((await stat(path)).size, before);
  await journal.compact();
  const recovered = new FileBrowserOperationJournal(path);
  assert.equal((await recovered.getAdmission("p", 1, "op")).admission.admittedAt, 100);
  assert.equal((await recovered.getEgress("p", 1, "op")).receipt.requestBytes, 123);
  assert.equal((await recovered.getOperation("p", 1, "op")).terminalObserved, false,
    "network completion is not business terminality");
  assert.equal((await readFile(path, "utf8")).includes("type.text"), false);
});
test("worker admission rejects operation, semantic, generation, page and deadline drift", async t => {
  for (const [key, value] of [["operationId", "other"], ["semanticDigest", D], ["workerGeneration", 2], ["pageRevision", 1], ["admittedAt", 10000]]) {
    const { journal } = await fixture(t); await journal.recordDispatch(dispatch());
    const bad = admission(); bad.admission[key] = value;
    await assert.rejects(journal.recordAdmission(bad), /drifted|bind/);
    assert.equal(await journal.getAdmission("p", 1, "op"), null);
  }
});
test("egress receipt cannot change grant identity or overwrite a persisted terminal network observation", async t => {
  const { journal } = await fixture(t); await journal.recordDispatch(dispatch()); await journal.recordEgress(egress());
  const changed = egress(); changed.receipt.effectGrantDigest = D;
  const { receiptDigest, ...unsigned } = changed.receipt; changed.receipt.receiptDigest = hash(unsigned);
  await assert.rejects(journal.recordEgress(changed), /identity/);
  const altered = egress(); altered.receipt.requestBytes = 124;
  const { receiptDigest: _, ...other } = altered.receipt; altered.receipt.receiptDigest = hash(other);
  await assert.rejects(journal.recordEgress(altered), /immutable/);
  assert.equal((await journal.getEgress("p", 1, "op")).receipt.requestBytes, 123);
});
test("retirement removes operation side evidence in memory and durable indexes without permitting resurrection", async t => {
  const { path, journal } = await fixture(t);
  for (const owner of [journal, new MemoryBrowserOperationJournal()]) {
    await owner.recordDispatch(dispatch()); await owner.recordAdmission(admission()); await owner.recordEgress(egress());
    await owner.recordObservation({ ...dispatch(), status: "succeeded", terminalObserved: true, outcomeDigest: D, observationReason: "terminal_observed" });
    await owner.retireProfile("p", 1);
    assert.equal(await owner.getAdmission("p", 1, "op"), null);
    assert.equal(await owner.getEgress("p", 1, "op"), null);
    await assert.rejects(owner.recordDispatch(dispatch()), /retired/);
  }
  const recovered = new FileBrowserOperationJournal(path);
  assert.equal(await recovered.getAdmission("p", 1, "op"), null);
  assert.equal(await recovered.getEgress("p", 1, "op"), null);
});
