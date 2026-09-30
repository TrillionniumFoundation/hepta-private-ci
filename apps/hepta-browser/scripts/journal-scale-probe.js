#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmod, mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";

import { FileBrowserOperationJournal } from "../src/journal.js";

const TERMINAL_OPERATION_COUNT = 128;
const UNRESOLVED_OPERATION_COUNT = 64;
const TOTAL_OPERATION_COUNT =
  TERMINAL_OPERATION_COUNT + UNRESOLVED_OPERATION_COUNT;
const PROFILE_ID = "scale.profile";
const PRINCIPAL_ID = "scale.principal";
const PROCESS_ID = "scale.worker";
const GENERATION = 1;
const DESTINATION_ORIGIN = "https://example.com";
const DEADLINE_MS = 4_000_000_000_000;
const JOURNAL_HARD_CEILING_BYTES = 64 * 1024 * 1024;
const JOURNAL_COMPACTION_THRESHOLD_BYTES = 48 * 1024 * 1024;

function digest(value) {
  return createHash("sha256").update(value).digest("hex");
}

function operation(index) {
  const operationId = `scale.operation.${index}`;
  const requestDigest = digest(`request:${index}`);
  const semanticDigest = digest(`semantic:${index}`);
  const finalPayloadDigest = digest(`payload:${index}`);
  const profileGrantDigest = digest("profile-grant");
  const effectGrantDigest = digest(`effect-grant:${index}`);
  const witnessDigest = digest(`witness:${index}`);
  return {
    profileId: PROFILE_ID,
    principalId: PRINCIPAL_ID,
    generation: GENERATION,
    operationId,
    requestDigest,
    semanticDigest,
    processId: PROCESS_ID,
    pageGeneration: index + 1,
    documentDigest: digest(`document:${index}`),
    action: "click",
    destinationOrigin: DESTINATION_ORIGIN,
    finalPayloadDigest,
    profileGrantDigest,
    effectGrantDigest,
    authorityEpoch: 1,
    deadlineMs: DEADLINE_MS,
    verifiedUseTokenWitnessDigest: witnessDigest,
    status: "indeterminate",
    outcomeDigest: null,
    terminalEvidenceDigest: null,
    terminalObserved: false,
    observationReason: "dispatching",
  };
}

function admission(record, index) {
  return {
    profileId: record.profileId,
    generation: record.generation,
    operationId: record.operationId,
    requestDigest: record.requestDigest,
    semanticDigest: record.semanticDigest,
    admission: {
      kind: "BrowserEffectAdmissionV1",
      operationId: record.operationId,
      semanticDigest: record.semanticDigest,
      workerGeneration: record.generation,
      pageRevision: record.pageGeneration,
      admittedAt: index + 1,
      durableOrRecoverable: true,
    },
  };
}

function egress(record, index) {
  const unsigned = {
    schema: "hepta.browser.egress-operation-receipt.v1",
    operationId: record.operationId,
    profileGrantDigest: record.profileGrantDigest,
    effectGrantDigest: record.effectGrantDigest,
    destinationOrigin: record.destinationOrigin,
    status: "succeeded",
    admittedAtMs: index + 1,
    completedAtMs: index + 2,
    requestBytes: 128,
    responseBytes: 1024,
    connectionCount: 1,
    boundedAbort: false,
    maxRequestBytes: 4096,
    maxResponseBytes: 4096,
  };
  return {
    profileId: record.profileId,
    generation: record.generation,
    operationId: record.operationId,
    requestDigest: record.requestDigest,
    semanticDigest: record.semanticDigest,
    receipt: {
      ...unsigned,
      receiptDigest: createHash("sha256")
        .update(JSON.stringify(unsigned))
        .digest("hex"),
    },
  };
}

function terminal(record, index) {
  return {
    ...record,
    status: "succeeded",
    outcomeDigest: digest(`outcome:${index}`),
    terminalObserved: true,
    observationReason: "terminal_observed",
  };
}

function percentile(values, proportion) {
  const ordered = [...values].sort((left, right) => left - right);
  const index = Math.min(
    ordered.length - 1,
    Math.max(0, Math.ceil(ordered.length * proportion) - 1),
  );
  return Number(ordered[index].toFixed(3));
}

function latencySummary(values) {
  return {
    p50: percentile(values, 0.5),
    p95: percentile(values, 0.95),
    p99: percentile(values, 0.99),
    max: Number(Math.max(...values).toFixed(3)),
  };
}

const root = await mkdtemp(join(tmpdir(), "hepta-browser-journal-scale-"));
await chmod(root, 0o700);
const journalPath = join(root, "operations.jsonl");

try {
  const journal = new FileBrowserOperationJournal(journalPath);
  const terminalLatenciesMs = [];
  const unresolvedLatenciesMs = [];
  const startedAt = performance.now();

  for (let index = 0; index < TERMINAL_OPERATION_COUNT; index += 1) {
    const record = operation(index);
    const operationStartedAt = performance.now();
    await journal.recordDispatch(record);
    await journal.recordAdmission(admission(record, index));
    await journal.recordEgress(egress(record, index));
    await journal.recordObservation(terminal(record, index));
    terminalLatenciesMs.push(performance.now() - operationStartedAt);
  }

  for (
    let offset = 0;
    offset < UNRESOLVED_OPERATION_COUNT;
    offset += 1
  ) {
    const index = TERMINAL_OPERATION_COUNT + offset;
    const record = operation(index);
    const operationStartedAt = performance.now();
    await journal.recordDispatch(record);
    await journal.recordAdmission(admission(record, index));
    await journal.recordEgress(egress(record, index));
    unresolvedLatenciesMs.push(performance.now() - operationStartedAt);
  }

  const writeCompletedAt = performance.now();
  const warmStatistics = journal.statistics;
  const totalDurableTransitions =
    TERMINAL_OPERATION_COUNT * 4 + UNRESOLVED_OPERATION_COUNT * 3;
  const expectedMinimumCacheHits = totalDurableTransitions - 1;
  assert.equal(warmStatistics.fullLoads, 1);
  assert.equal(warmStatistics.diskReadBytes, 0);
  assert.ok(warmStatistics.cacheHits >= expectedMinimumCacheHits);
  assert.equal(warmStatistics.appends, totalDurableTransitions);

  const beforeCompactionBytes = (await stat(journalPath)).size;
  const compactionStartedAt = performance.now();
  await journal.compact();
  const compactionMs = performance.now() - compactionStartedAt;
  const afterCompactionBytes = (await stat(journalPath)).size;

  const reopened = new FileBrowserOperationJournal(journalPath);
  const reopenStartedAt = performance.now();
  const recovered = await reopened.listOperations(PROFILE_ID, GENERATION);
  const reopenMs = performance.now() - reopenStartedAt;
  const recoveredTerminal = recovered.filter(
    (record) => record.terminalObserved === true,
  );
  const recoveredUnresolved = recovered.filter(
    (record) => record.terminalObserved === false,
  );
  assert.equal(recovered.length, TOTAL_OPERATION_COUNT);
  assert.equal(recoveredTerminal.length, TERMINAL_OPERATION_COUNT);
  assert.equal(recoveredUnresolved.length, UNRESOLVED_OPERATION_COUNT);
  assert.ok(
    recoveredUnresolved.every(
      (record) =>
        record.status === "indeterminate" &&
        record.observationReason === "dispatching",
    ),
  );
  assert.equal(reopened.statistics.fullLoads, 1);
  assert.equal(reopened.statistics.diskReadBytes, afterCompactionBytes);

  const receipt = {
    schema: "hepta.browser.journal-scale-receipt.v2",
    operationCount: TOTAL_OPERATION_COUNT,
    terminalOperationCount: TERMINAL_OPERATION_COUNT,
    unresolvedOperationCount: UNRESOLVED_OPERATION_COUNT,
    totalDurableTransitions,
    writeDurationMs: Number((writeCompletedAt - startedAt).toFixed(3)),
    terminalOperationLatencyMs: latencySummary(terminalLatenciesMs),
    unresolvedOperationLatencyMs: latencySummary(unresolvedLatenciesMs),
    compactionMs: Number(compactionMs.toFixed(3)),
    reopenMs: Number(reopenMs.toFixed(3)),
    journalBytes: {
      beforeCompaction: beforeCompactionBytes,
      afterCompaction: afterCompactionBytes,
      compactionThreshold: JOURNAL_COMPACTION_THRESHOLD_BYTES,
      hardCeiling: JOURNAL_HARD_CEILING_BYTES,
      utilizationBeforeCompaction: Number(
        (beforeCompactionBytes / JOURNAL_HARD_CEILING_BYTES).toFixed(6),
      ),
    },
    warmOwnerStatistics: warmStatistics,
    reopenedOwnerStatistics: reopened.statistics,
    incrementalIndexReused: true,
    warmPathFullReloads: warmStatistics.fullLoads,
    restartSnapshotValidated: true,
    unresolvedBacklogSurvivedCompactionAndRestart: true,
    nearCapacityQualification: false,
    slowStorageQualification: false,
    performanceQualification: false,
  };

  process.stdout.write(`${JSON.stringify(receipt)}\n`);
} finally {
  await rm(root, { recursive: true, force: true });
}
