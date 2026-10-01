# memory.retrieval target-host qualification

This profile is an execution recipe, not a stored performance result. A valid
performance receipt binds the exact Git source/tree, target host identity,
kernel/CPU/memory profile, Rust compiler, release flags, fixture size, command
bytes, observation time and the captured stdout/stderr plus GNU `time` output.

The normal source/merge CI must be green before measurements are interpreted.
Do not convert CI duration, simulator timing or a different host population into
a target-host claim.

## Qualification-host evidence collector

`.github/workflows/hepta-memory-retrieval-qualification-host.yml` executes all four
release-mode probes on an exact PR/source SHA, records the source tree and runner
identity, captures kernel/CPU/memory/Rust toolchain facts, preserves raw stdout/
stderr plus GNU `/usr/bin/time -v` output, and uploads the complete record as a
30-day workflow artifact. The repository's `just test`/nextest runner explicitly
fails if a probe or regression filter selects zero tests; removed/renamed tests
cannot silently create successful qualification evidence. Native, learning-ledger
retrieval and SQLite adapter/revalidation regression logs are retained alongside
the measurements. A separate debug-profile job retains the exact-source Agentd
context/delivery regression log and host identity. A GitHub-hosted run is useful reproducible
qualification-host evidence; it is **not** the approved named production target
host and cannot satisfy target-host acceptance by relabeling the runner.

The same commands must be repeated on the approved named target host after the
source/merge gates are green. That target-host receipt must preserve the same
identity and raw-measurement fields before any performance claim advances.

## 1. Owner SQLite / source-revalidation probe

From the repository root on the named target host:

```sh
/usr/bin/time -v \
  just test --release --locked -p codex-hepta-memory \
  --run-ignored ignored-only --no-tests fail --no-capture \
  -E 'test(target_host_owner_retrieval_reports_latency_percentiles)'
```

The ignored fixture creates 1,024 verified owner memories and executes 200
iterations of the real SQLite `observe_memory_retrieval` plus batch source
revalidation. It prints one
`hepta.memory-retrieval.target-host.v1` JSON line containing owner-retrieval
and revalidation p50/p95/p99 microseconds. GNU `time -v` supplies process CPU
and maximum resident-set observations for the same command.

The fixture exercises a large store relative to the current seven per-channel
32-candidate owner limits (maximum 224 raw owner events before union); it does
not assert full-store recall.

## 2. HNMF candidate-ceiling probe

```sh
/usr/bin/time -v \
  just test --release --locked -p codex-hepta-memory-retrieval \
  --run-ignored ignored-only --no-tests fail --no-capture \
  -E 'test(target_host_hnmf_reports_latency_percentiles_at_candidate_ceiling)'
```

The fixture executes 100 deterministic HNMF recalls with 512 candidate events,
512 engram nodes, associative recurrence, the product four-step ceiling and a
16-result retrieval profile. It prints p50/p95/p99 microseconds plus the final
engram resource receipt. This is a source-level HNMF probe; it is not a
substitute for the SQLite/Agentd end-to-end observation above.

## 3. HNMF structural-ceiling probe

```sh
/usr/bin/time -v \
  just test --release --locked -p codex-hepta-memory-retrieval \
  --run-ignored ignored-only --no-tests fail --no-capture \
  -E 'test(target_host_hnmf_validates_full_structural_ceiling)'
```

This fixture constructs and validates the exact 4,096-node / 32,768-synapse
structural ceiling, then executes 50 recalls with 512 candidates and four settling
steps. It checks 4,096 expanded nodes and 131,072 synapse traversals and prints
recall p50/p95/p99 plus construction and validation microseconds. GNU `time -v`
supplies CPU and RSS/peak-memory observations for the same process. This fixture
does not establish an approved latency target for all possible support densities,
population mixes or target hosts.

## 4. HNMF outside-support working-set probe

```sh
/usr/bin/time -v \
  just test --release --locked -p codex-hepta-memory-retrieval \
  --run-ignored ignored-only --no-tests fail --no-capture \
  -E 'test(target_host_hnmf_ranking_reports_outside_support_latency)'
```

This fixture has two current candidates, 448 active nodes and 512 exact supports
per node (229,376 support events). Most supports are outside the current cut.
Twenty samples independently measure deterministic candidate ranking and full
receipt validation, with selection parity and successful validation checked for
every sample. The two JSON phases are `hnmf-ranking-outside-support` and
`hnmf-receipt-validation-outside-support`. They isolate temporary-index overhead;
they do not measure settling, SQLite I/O or end-to-end Agentd latency.

## 5. Functional qualification matrix

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

## 6. Evidence that remains independent

A performance receipt records measurements; it does not select, accept, promote
or release the candidate. Real recall-quality and causal-utility claims require
an independently labeled/evaluated query set and independently observed
downstream outcomes. If the optional learned ranker changes ordering, its policy
identity and propensity must be logged independently of the deterministic HNMF
propensity.

The typed causal, procedural and contradiction-support channels are supplied by
the durable SQLite KG projection under reserved semantic relation values and are
kept separate from generic graph evidence. Vector still requires a real current
encoder/vector-index owner and currentness receipt before that policy channel can
be enabled. Operator acceptance, canary, promotion and release
remain separately governed.
