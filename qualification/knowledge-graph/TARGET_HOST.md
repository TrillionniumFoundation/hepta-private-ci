# knowledge.graph target-host measurement

This procedure records performance evidence for one exact, clean source commit. It does not grant activation, independent acceptance, promotion, merge, or release authority.

## Required host conditions

Use a named host profile with documented CPU, memory, kernel, storage, and Rust toolchain. Record ambient load before the run. Do not present a shared GitHub Actions runner as target-host evidence.

The benchmark uses the real cognitive SQLite owner and product retrieval path. Its default workload performs 256 governed mutations, producing 4,096 logical nodes and 32,768 logical edges, then measures ordinary retrieval, bounded relation-query work, concurrent readers plus a writer, and reopen. The receipt reports p50/p95/p99 latency, DB/WAL bytes, current and peak RSS, Linux CPU ticks, exact edge/support work counters, and contention distributions.

## Exact-source invocation

From a clean checkout at the candidate commit:

```bash
source "$HOME/.cargo/env" 2>/dev/null || true
SHA="$(git rev-parse HEAD)"
python3 scripts/hepta-knowledge-graph-target-measure.py \
  --expected-sha "$SHA" \
  --host-profile-id '<stable-host-profile-id>' \
  --target-dir /tmp/hepta-knowledge-graph-target \
  --output /tmp/knowledge-graph-target-host.json \
  --raw-output /tmp/knowledge-graph-target-host.log
```

The harness rejects a dirty worktree or mismatched SHA. It validates the structured `hepta.knowledge-graph-perf-library.v2` receipt before writing the target-host evidence file.

## Interpretation

- Compare exact-source and deterministic synthetic-merge correctness before using the timing result.
- Treat latency numbers as host-specific observations, not universal thresholds.
- The selected runtime writer remains complete-generation rebuild unless an independently checked localized writer preserves semantic equivalence and demonstrates a material target-host benefit.
- Retain the JSON evidence and raw log with the pull-request qualification record; do not rewrite module acceptance state from the benchmark alone.
