import assert from "node:assert/strict";
import test from "node:test";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, stat, writeFile, rename } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { acquireBrowserJournalLock } from "../src/journal-owner-lock.js";
import { FileBrowserOperationJournal } from "../src/journal.js";

const LOCK_URL = new URL("../src/journal-owner-lock.js", import.meta.url).href;
const JOURNAL_URL = new URL("../src/journal.js", import.meta.url).href;
const D = "1".repeat(64);
function record(operationId) {
  return { profileId: "p", principalId: "principal", generation: 1, operationId,
    requestDigest: D, semanticDigest: D, processId: "worker", pageGeneration: 0,
    documentDigest: null, action: "navigate", destinationOrigin: "https://example.com",
    finalPayloadDigest: D, profileGrantDigest: D, effectGrantDigest: D, authorityEpoch: 1,
    deadlineMs: 10000, verifiedUseTokenWitnessDigest: D, status: "indeterminate",
    outcomeDigest: null, terminalEvidenceDigest: null, terminalObserved: false, observationReason: "dispatching" };
}
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "browser-owner-process-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  return { root, path: join(root, "operations.jsonl") };
}
function child(t, code) {
  const process = spawn(globalThis.process.execPath, ["--input-type=module", "-e", code],
    { stdio: ["ignore", "pipe", "pipe", "ipc"] });
  let stderr = "";
  process.stderr.on("data", data => { stderr += data; });
  const exited = once(process, "exit");
  t.after(async () => {
    if (process.exitCode === null && process.signalCode === null) process.kill("SIGKILL");
    await exited;
  });
  return { process, exited, stderr: () => stderr };
}

test("SIGKILL releases kernel ownership; simultaneous reclaimers never share the critical section", { timeout: 10000 }, async t => {
  const { path } = await fixture(t);
  const holder = child(t, `import {acquireBrowserJournalLock} from ${JSON.stringify(LOCK_URL)};
    const release = await acquireBrowserJournalLock(${JSON.stringify(path)});
    process.send('locked'); setInterval(()=>{},1000);`);
  assert.equal((await once(holder.process, "message"))[0], "locked");
  const before = await stat(`${path}.owner-lock`);
  const contestants = Array.from({ length: 4 }, (_, id) => child(t, `
    import {acquireBrowserJournalLock} from ${JSON.stringify(LOCK_URL)};
    import {open,unlink} from 'node:fs/promises';
    process.send('ready');
    const release = await acquireBrowserJournalLock(${JSON.stringify(path)});
    const marker = await open(${JSON.stringify(`${path}.critical`)}, 'wx', 0o600);
    await new Promise(r=>setTimeout(r,30)); await marker.close();
    await unlink(${JSON.stringify(`${path}.critical`)}); await release();
    process.disconnect();`));
  await Promise.all(contestants.map(({process}) => once(process, "message")));
  holder.process.kill("SIGKILL"); await holder.exited;
  for (const contender of contestants) {
    const [code] = await contender.exited;
    assert.equal(code, 0, contender.stderr());
  }
  const after = await stat(`${path}.owner-lock`);
  assert.equal(after.ino, before.ino);
  assert.equal(await readFile(`${path}.owner-lock`, "utf8"), "hepta.browser.kernel-owner-lock.v2\n");
});

test("a live kernel owner blocks another process even with obsolete PID metadata removed from the protocol", async t => {
  const { path } = await fixture(t);
  const release = await acquireBrowserJournalLock(path);
  try {
    const contender = child(t, `import {acquireBrowserJournalLock,BrowserJournalLockedError} from ${JSON.stringify(LOCK_URL)};
      try { await acquireBrowserJournalLock(${JSON.stringify(path)},50); process.exit(2); }
      catch(error) { process.exit(error instanceof BrowserJournalLockedError ? 0 : 3); }`);
    assert.equal((await contender.exited)[0], 0, contender.stderr());
  } finally { await release(); }
});

test("validated index reuses unchanged history and reloads after a real foreign process append", async t => {
  const { path } = await fixture(t);
  const journal = new FileBrowserOperationJournal(path);
  for (let i = 0; i < 40; i++) await journal.recordDispatch(record(`op.${i}`));
  const before = journal.statistics;
  for (let i = 0; i < 40; i++) assert.ok(await journal.getOperation("p", 1, `op.${i}`));
  assert.equal(journal.statistics.diskReadBytes, before.diskReadBytes);
  assert.equal(journal.statistics.fullLoads, before.fullLoads);
  const writer = child(t, `import {FileBrowserOperationJournal} from ${JSON.stringify(JOURNAL_URL)};
    await new FileBrowserOperationJournal(${JSON.stringify(path)}).recordDispatch(${JSON.stringify(record("foreign"))});`);
  assert.equal((await writer.exited)[0], 0, writer.stderr());
  assert.equal((await journal.getOperation("p", 1, "foreign")).operationId, "foreign");
  assert.equal(journal.statistics.fullLoads, before.fullLoads + 1);
  assert.equal((await journal.listOperations("p", 1)).length, 41);
});

test("inode replacement invalidates a validated cache and cannot hide corruption", async t => {
  const { path } = await fixture(t);
  const journal = new FileBrowserOperationJournal(path);
  await journal.recordDispatch(record("first"));
  const bytes = await readFile(path, "utf8");
  await writeFile(`${path}.replacement`, bytes.replace('"principal"', '"attacker"'), { mode: 0o600 });
  await rename(`${path}.replacement`, path);
  await assert.rejects(journal.getOperation("p", 1, "first"), /checksum/);
  await assert.rejects(journal.recordDispatch(record("second")), /fenced/);
});

test("empty profile retirement is durable and cannot be resurrected", async t => {
  const { path } = await fixture(t);
  await new FileBrowserOperationJournal(path).retireProfile("empty", 3);
  const reopened = new FileBrowserOperationJournal(path);
  await assert.rejects(reopened.assertProfileGenerationAvailable("empty", 3), /retired/);
  await reopened.assertProfileGenerationAvailable("empty", 4);
  assert.match(await readFile(path, "utf8"), /profile-generation-retirement.v1/);
});
