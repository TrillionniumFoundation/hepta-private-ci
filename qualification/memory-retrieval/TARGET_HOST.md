# memory.retrieval target-host qualification

This profile is an execution recipe, not a stored performance result. A valid
performance receipt binds the exact Git source/tree, target host identity,
kernel/CPU/memory profile, Rust compiler, release flags, fixture size, command
bytes, observation time and the captured stdout/stderr plus GNU `time` output.

The normal source/merge CI must be green before measurements are interpreted.
Do not convert CI duration, simulator timing or a different host population into
a target-host claim.

## 1. Owner SQLite / source-revalidation probe

From `codex-rs` on the named target host:

```sh
/usr/bin/time -v \
  cargo test --release --locked -p codex-hepta-memory \
  target_host_owner_retrieval_reports_latency_percentiles \
  -- --ignored --nocapture --test-threads=1
```

The ignored fixture creates 1,024 verified owner memories and executes 200
iterations of the real SQLite `observe_memory_retrieval` plus batch source
revalidation. It prints one
`hepta.memory-retrieval.target-host.v1` JSON line containing owner-retrieval
and revalidation p50/p95/p99 microseconds. GNU `time -v` supplies process CPU
and maximum resident-set observations for the same command.

The fixture exercises a large store relative to the current per-channel
32-candidate owner limits; it does not assert full-store recall.

## 2. HNMF candidate-ceiling probe

```sh
/usr/bin/time -v \
  cargo test --release --locked -p codex-hepta-memory-retrieval \
  target_host_hnmf_reports_latency_percentiles_at_candidate_ceiling \
  -- --ignored --nocapture --test-threads=1
```

The fixture executes 100 deterministic HNMF recalls with 512 candidate events,
512 engram nodes, associative recurrence, the product four-step ceiling and a
16-result retrieval profile. It prints p50/p95/p99 microseconds plus the final
engram resource receipt. This is a source-level HNMF probe; it is not a
substitute for the SQLite/Agentd end-to-end observation above or future
4096-node/32768-synapse stress profiles.

## 3. Functional qualification matrix

The ordinary package tests cover:

- RET-01 generator/channel permutation invariance and canonical union;
- RET-02 contradiction-driven abstention and OOD/coverage failures;
- RET-03 exact owner revision/source revalidation and stale/revoked omission;
- RET-04 plain/no-intervention, lexical-only, no-recurrence and no-inhibition
  ablation fixtures;
- channel saturation, total 512-candidate ingress, 16-result output, 4096-node,
  32768-synapse, four-step and 64-active-per-population hard bounds;
- recomputed-digest structural receipt forgeries;
- policy/generator completeness mismatch and cross-generation rebinding;
- durable enumerated/legal/selected/final-delivered assignment persistence.

These fixtures establish deterministic correctness and separable interventions.
They do not establish real-world recall quality or learned-policy uplift.

## 4. Evidence that remains independent

A performance receipt records measurements; it does not select, accept, promote
or release the candidate. Real recall-quality and causal-utility claims require
an independently labeled/evaluated query set and independently observed
downstream outcomes. If the optional learned ranker changes ordering, its policy
identity and propensity must be logged independently of the deterministic HNMF
propensity.

Vector, causal, procedural and contradiction-support channels require their
actual owner implementations and currentness receipts before an enabled policy
can be called complete. Operator acceptance, canary, promotion and release
remain separately governed.
