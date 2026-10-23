# knowledge.graph target-host measurement

This procedure records performance evidence for one exact, clean source commit. It does not grant activation, independent acceptance, promotion, merge, or release authority.

## Required host conditions

Use a named host profile with documented CPU, memory, kernel, storage, and Rust toolchain. Record ambient load before the run. Do not present a shared GitHub Actions runner as target-host evidence.

The benchmark uses the real cognitive SQLite owner and product retrieval path. Its default workload performs 256 governed mutations using the same 16 entity keys and 128 relations. These produce 4,096 entity revision occurrences and 32,768 relation revision occurrences, while canonical projection identity deduplicates them into 16 nodes and 128 edges with 36,864 combined node/edge supports. The legacy receipt fields `logicalNodes` and `logicalEdges` count revision occurrences; `canonicalNodeCount`, `canonicalEdgeCount` and `canonicalSupportCount` report canonical graph size. This is a support-growth probe, not evidence that a 4,096-node/32,768-edge canonical graph has been exercised.

The probe measures ordinary product retrieval (including preparation of the transaction-local index), concurrent readers plus a writer, and reopen. `boundedQueryWork.implementation = full_scan_reference_v2` identifies separate reference-kernel work counters; these counters do not measure indexed product-query visits. The receipt also reports p50/p95/p99 latency, DB/WAL bytes, current and peak RSS, Linux CPU ticks and contention distributions.

## Exact-source invocation

From a clean checkout at the candidate commit:

```bash
source "$HOME/.cargo/env" 2>/dev/null || true
SHA="$(git rev-parse HEAD)"
python3 scripts/hepta-knowledge-graph-target-measure.py \
  --expected-sha "$SHA" \
  --host-profile-id '<stable-host-profile-id>' \
  --storage-identity '<stable-storage-profile-id>' \
  --target-dir /tmp/hepta-knowledge-graph-target \
  --output /tmp/knowledge-graph-target-host.json \
  --raw-output /tmp/knowledge-graph-target-host.log
```

Install the repository's pinned `just` and `cargo-nextest` tools first. The harness uses `just test` with an exact ignored-test filter and fails when no test is selected. It rejects a dirty worktree or mismatched SHA before and after measurement, and validates the structured `hepta.knowledge-graph-perf-library.v2` receipt and actual workload counts before writing the target-host evidence file.

`storageIdentity` is a reviewed profile label supplied by the operator. The evidence also records the benchmark temporary-directory path and observed filesystem device number. Those observations do not independently attest storage hardware; verify that `TMPDIR` selects the reviewed storage before running the probe.

## Interpretation

- Compare exact-source and deterministic synthetic-merge correctness before using the timing result.
- Treat latency numbers as host-specific observations, not universal thresholds.
- The selected runtime writer remains complete-generation rebuild unless an independently checked localized writer preserves semantic equivalence and demonstrates a material target-host benefit.
- Retain the JSON evidence and raw log with the pull-request qualification record; do not rewrite module acceptance state from the benchmark alone.

The default-branch-only `.github/workflows/hepta-knowledge-graph-target-host.yml` evaluates a committed `hepta.knowledge-graph-budget.v1` profile under `qualification/knowledge-graph/budgets`. Its required host identity, complete fixture minima and latency/memory/storage limits must match the observed evidence. No reviewed target-host budget is committed at this candidate; target-host qualification remains open until an actual profile and matching execution evidence exist. A passing evaluation remains measurement evidence and grants no independent acceptance, activation or release.
