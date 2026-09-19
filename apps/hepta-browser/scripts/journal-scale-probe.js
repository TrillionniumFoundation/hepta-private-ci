// Measurements of the actual journal on a local filesystem. This is NOT an
// inference-store, full application, provider-effect or physical power-loss test.
import { mkdtemp, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import { FileBrowserOperationJournal } from "../src/journal.js";

const D1 = "1".repeat(64), D2 = "2".repeat(64);
function record(i, terminal = false) {
  return { profileId: "scale.profile", principalId: "scale.principal", generation: 1,
    operationId: `operation.${i}`, requestDigest: D1, semanticDigest: D2,
    status: terminal ? "succeeded" : "indeterminate", terminalObserved: terminal,
    outcomeDigest: terminal ? D1 : null,
    observationReason: terminal ? "terminal_observed" : "dispatching" };
}
function percentile(values, fraction) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)];
}
async function probe(count) {
  const root = await mkdtemp(join(tmpdir(), "hepta-journal-scale-"));
  try {
    const path = join(root, "operations.jsonl");
    const journal = new FileBrowserOperationJournal(path);
    const latency = [];
    const start = performance.now();
    for (let i = 0; i < count; i++) {
      const update = performance.now();
      await journal.recordDispatch(record(i));
      await journal.recordObservation(record(i, true));
      if (i >= count - 64) latency.push(performance.now() - update);
    }
    const ingestMs = performance.now() - start;
    const before = (await stat(path)).size;
    const recoveryStart = performance.now();
    const recovered = await new FileBrowserOperationJournal(path).listOperations("scale.profile", 1);
    const recoveryMs = performance.now() - recoveryStart;
    if (recovered.length !== count || recovered.some(r => r.terminalObserved !== true)) {
      throw new Error("recovery did not preserve all observed terminal results");
    }
    await new FileBrowserOperationJournal(path).recordDispatch(record(0));
    const retryExtraBytes = (await stat(path)).size - before;
    if (retryExtraBytes !== 0) throw new Error("idempotent retry grew the journal");
    return { scope: "browser-journal-only-local-filesystem", records: count,
      durable_appends: count * 2, ingest_ms: ingestMs,
      last_64_update_p50_ms: percentile(latency, 0.5),
      last_64_update_p95_ms: percentile(latency, 0.95),
      last_64_update_p99_ms: percentile(latency, 0.99),
      recovery_ms: recoveryMs, journal_bytes: before, retry_extra_bytes: retryExtraBytes,
      process_max_rss_kib: process.resourceUsage().maxRSS,
      node: process.version, platform: process.platform, arch: process.arch };
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}
const args = process.argv.slice(2);
if (args[0] === "--single") {
  const count = Number(args[1]);
  if (!Number.isSafeInteger(count) || count < 1 || count > 4096 || args.length !== 2) {
    throw new Error("--single requires a record count from 1 to 4096");
  }
  console.log(JSON.stringify(await probe(count)));
} else {
  if (args.length !== 0 && (args[0] !== "--records" || args.length !== 2)) {
    throw new Error("usage: node journal-scale-probe.js [--records 128,512,2048]");
  }
  const counts = (args[1] ?? "128,512,2048").split(",").map(Number);
  if (counts.some(n => !Number.isSafeInteger(n) || n < 1 || n > 4096)) {
    throw new Error("record counts must be integers from 1 to 4096");
  }
  for (const count of counts) {
    const child = spawnSync(process.execPath,
      ["--experimental-default-type=module", fileURLToPath(import.meta.url), "--single", String(count)],
      { encoding: "utf8", timeout: 300000, maxBuffer: 1024 * 1024 });
    if (child.error || child.status !== 0) {
      throw new Error(`scale probe failed for ${count}: ${child.error ?? child.stderr}`);
    }
    process.stdout.write(child.stdout);
  }
}
