import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { appendFile, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
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
    observationReason: "dispatching", ...overrides,
  };
}
function terminal(overrides = {}) {
  return record({ status: "succeeded", outcomeDigest: D3, terminalObserved: true,
    observationReason: "terminal_observed", ...overrides });
}
async function fixture(t, kind = "file") {
  if (kind === "memory") return { journal: new MemoryBrowserOperationJournal() };
  const root = await mkdtemp(join(tmpdir(), "hepta-monotonicity-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const path = join(root, "operations.jsonl");
  return { path, journal: new FileBrowserOperationJournal(path) };
}
function line(type, recordValue) {
  const unsigned = { schema: "hepta.browser.operation-journal.v1", version: 1,
    type, record: recordValue };
  return JSON.stringify({ ...unsigned,
    checksum: createHash("sha256").update(JSON.stringify(unsigned)).digest("hex") }) + "\n";
}

for (const kind of ["memory", "file"]) {
  test(`${kind}: duplicate dispatch cannot erase an observed terminal result`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    await journal.recordObservation(terminal());
    await journal.recordDispatch(record());
    assert.deepEqual(await journal.getOperation("profile.1", 1, "operation.1"), terminal());
  });
  test(`${kind}: same request digest does not permit changed semantic digest`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    await assert.rejects(journal.recordDispatch(record({ semanticDigest: D3 })), /semantics/);
    assert.equal((await journal.getOperation("profile.1", 1, "operation.1")).semanticDigest, D2);
  });
  test(`${kind}: terminal result cannot return to indeterminate`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    await journal.recordObservation(terminal());
    await assert.rejects(journal.recordObservation(record()), /terminal/);
    assert.equal((await journal.getOperation("profile.1", 1, "operation.1")).terminalObserved, true);
  });
  test(`${kind}: conflicting terminal result rejects without changing stored result`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    await journal.recordObservation(terminal());
    await assert.rejects(journal.recordObservation(terminal({ outcomeDigest: D2 })), /terminal/);
    assert.deepEqual(await journal.getOperation("profile.1", 1, "operation.1"), terminal());
  });
  test(`${kind}: entry snapshots caller-owned scalar fields before awaiting`, async (t) => {
    const { journal } = await fixture(t, kind);
    const input = record();
    const operation = journal.recordDispatch(input);
    input.operationId = "mutated";
    input.requestDigest = D3;
    await operation;
    assert.equal((await journal.getOperation("profile.1", 1, "operation.1")).requestDigest, D1);
    assert.equal(await journal.getOperation("profile.1", 1, "mutated"), null);
  });
  test(`${kind}: unknown observation can still reconcile to an observed terminal result`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    await journal.recordObservation(record({ observationReason: "provider_disconnected" }));
    await journal.recordObservation(terminal());
    assert.equal((await journal.getOperation("profile.1", 1, "operation.1")).status, "succeeded");
  });
  test(`${kind}: rejected rollback does not block an unrelated operation`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    await journal.recordObservation(terminal());
    await assert.rejects(journal.recordObservation(record()), /terminal/);
    await journal.recordDispatch(record({ operationId: "operation.2" }));
    await journal.recordObservation(terminal({ operationId: "operation.2" }));
    assert.equal((await journal.getOperation("profile.1", 1, "operation.1")).status, "succeeded");
    assert.equal((await journal.getOperation("profile.1", 1, "operation.2")).status, "succeeded");
  });
  test(`${kind}: independently named generations retain separate records`, async (t) => {
    const { journal } = await fixture(t, kind);
    await journal.recordDispatch(record());
    await journal.recordObservation(terminal());
    await journal.recordDispatch(record({ generation: 2 }));
    assert.equal((await journal.getOperation("profile.1", 1, "operation.1")).status, "succeeded");
    assert.equal((await journal.getOperation("profile.1", 2, "operation.1")).status, "indeterminate");
  });
}

test("file: same dispatch/observation retries write no extra journal bytes", async (t) => {
  const { path, journal } = await fixture(t);
  await journal.recordDispatch(record());
  const dispatch = await readFile(path);
  for (let i = 0; i < 4; i++) await journal.recordDispatch(record());
  assert.deepEqual(await readFile(path), dispatch);
  await journal.recordObservation(terminal());
  const final = await readFile(path);
  for (let i = 0; i < 4; i++) await journal.recordObservation(terminal());
  assert.deepEqual(await readFile(path), final);
});

test("file: replay of an old duplicate dispatch cannot erase a later observation", async (t) => {
  const { path, journal } = await fixture(t);
  await journal.recordDispatch(record());
  const duplicate = await readFile(path);
  await journal.recordObservation(terminal());
  await appendFile(path, duplicate);
  const reopened = new FileBrowserOperationJournal(path);
  assert.deepEqual(await reopened.getOperation("profile.1", 1, "operation.1"), terminal());
});

test("file: even valid checksums cannot authorize terminal-state rollback on replay", async (t) => {
  const { path, journal } = await fixture(t);
  await journal.recordDispatch(record());
  await journal.recordObservation(terminal());
  await appendFile(path, line("observation", record()));
  await assert.rejects(new FileBrowserOperationJournal(path).listOperations("profile.1", 1), /terminal/);
});

test("file: valid JSON without final newline is incomplete and cannot be appended to", async (t) => {
  const { path, journal } = await fixture(t);
  await journal.recordDispatch(record());
  const complete = await readFile(path);
  const incomplete = complete.subarray(0, complete.length - 1);
  await writeFile(path, incomplete, { mode: 0o600 });
  const reopened = new FileBrowserOperationJournal(path);
  await assert.rejects(reopened.getOperation("profile.1", 1, "operation.1"), /incomplete/);
  await assert.rejects(reopened.recordDispatch(record({ operationId: "operation.2" })), /incomplete/);
  assert.deepEqual(await readFile(path), incomplete);
});

test("file: abrupt process exit after synced observation preserves terminal dedupe on reopen", async (t) => {
  const { path } = await fixture(t);
  const source = new URL("../src/journal.js", import.meta.url).href;
  const code = `import {FileBrowserOperationJournal} from ${JSON.stringify(source)};
    const journal = new FileBrowserOperationJournal(${JSON.stringify(path)});
    await journal.recordDispatch(${JSON.stringify(record())});
    await journal.recordObservation(${JSON.stringify(terminal())});
    process.exit(73);`;
  const child = spawnSync(process.execPath,
    ["--experimental-default-type=module", "--input-type=module", "-e", code],
    { encoding: "utf8", timeout: 15000 });
  assert.equal(child.status, 73, child.stderr);
  const before = await readFile(path);
  const reopened = new FileBrowserOperationJournal(path);
  await reopened.recordDispatch(record());
  assert.deepEqual(await reopened.getOperation("profile.1", 1, "operation.1"), terminal());
  assert.deepEqual(await readFile(path), before);
});

test("file: queued observations use their entry-time identity", async (t) => {
  const { journal } = await fixture(t);
  await journal.recordDispatch(record());
  const input = terminal();
  const pending = journal.recordObservation(input);
  input.operationId = "mutated";
  await pending;
  assert.equal((await journal.getOperation("profile.1", 1, "operation.1")).status, "succeeded");
});
