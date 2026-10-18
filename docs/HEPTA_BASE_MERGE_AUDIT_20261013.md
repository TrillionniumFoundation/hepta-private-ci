# Hepta PR #1468: frozen base reconciliation audit

This is an **audit, not an approved merge**. It captures a GitHub three-way
comparison on 2026-10-13 and must be refreshed if either ref advances.

| Ref                                                                     | SHA                                        |
| ----------------------------------------------------------------------- | ------------------------------------------ |
| Merge base                                                              | `7b4055812cf3373528aa2577a7846482e7a5f694` |
| Advanced target branch (`codex/hepta-bounded-inference-scale-20261009`) | `d66045cac5941ac5db73b78e7c7c516dd0310c55` |
| Audited PR head before this audit                                       | `da795caad26bab9391e5009ed19ac17722eed98e` |

At this snapshot, GitHub reported `mergeable=false`,
`mergeable_state=dirty`: the target had **41** commits since the
merge base, while the PR had **740**. Target-side changes affect 38 paths.
There are 14 paths changed on both sides; nine contain divergent
overlapping edits. Do not treat an old green canary or a signed fixture
digest as acceptance of this unmerged tree.

## No-change/identical overlap (do not discard either branch)

These overlapping paths have either independent edit regions or exactly
matching changed regions. Preserve both changes and check the resulting
imports or public APIs after the merge:

- `codex-rs/hepta-agentd/src/lib.rs`
- `codex-rs/hepta-automation/src/migration_convergence_tests.rs` (identical changes)
- `codex-rs/hepta-evidence/src/metrics_group_commit.rs`
- `codex-rs/hepta-fleet/src/authority_port.rs` (identical changes)
- `codex-rs/hepta-neuron/src/lib.rs`

All 24 target-only changed paths must also be carried forward unchanged,
unless an independently reviewed replacement with equivalent tests exists.

## Semantic conflict queue (nine paths; manual resolution mandatory)

| Path                                                  | Target-branch capability to retain                                                          | PR capability to retain                                                         |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `hepta-agentd/src/neuron_runtime.rs`                  | Durable effect-intent prepare/resolve, WAL phase accounting, post-effect NDU frontier check | Signed Final-use claim binding and expiry/revocation guard                      |
| `hepta-neuron/src/runtime.rs`                         | Guarded post-effect checkpoint publication                                                  | Production signed Final-use entry and non-public legacy deterministic tick      |
| `hepta-infer-core/src/microbatch.rs`                  | BTreeSet ticket ordering, O(log n) lane removal, per-Scope invalidation index               | Model-compatible physical batch affinity, rotating fairness, bounded coalescing |
| `hepta-infer-core/src/microbatch_tests.rs`            | Ticket/order/rollover and indexed invalidation tests                                        | Cross-Scope physical-batch fairness and bound tests                             |
| `hepta-infer-worker-host/src/batched_neuron.rs`       | Native execution and durable/metric observation enhancements                                | Per-item signed authorization, actual shared-feature batch, error propagation   |
| `hepta-infer-worker-host/src/batched_neuron_tests.rs` | New native/metrics replay and observability regressions                                     | Independent per-request proofs and real backend batch count regressions         |
| `hepta-infer-worker-host/src/model_worker.rs`         | Writer/native worker execution and telemetry changes                                        | Signed worker lifecycle/batching and generation gates                           |
| `hepta-evidence/src/metrics_group_commit_tests.rs`    | WAL/NDU/Final-use phase durable replay tests                                                | Exact committed counters and unsynced-loss-window tests                         |
| `hepta-evidence/src/metrics_sink_tests.rs`            | Durable WAL and protected signed phase sink tests                                           | Flush barriers, exact batch counts and abrupt-exit tests                        |

The original three-way comparison had identical insertions in
`hepta-automation/src/migration_convergence_tests.rs` and
`hepta-fleet/src/authority_port.rs`. That does not prove the combined
runtime is correct. Conflicting data structures and receipt transitions
are **not** safe to resolve via a blanket `ours` or `theirs` merge
strategy.

### Resolution order

1. **Neuron admission and effect intent:** merge `hepta-neuron`
   and `hepta-agentd` first. Preserve both independent signed NDU
   Final-use and crash-recoverable Prepare/Resolve with no effect replay.
   Verify expiring authority before and after guarded checkpoint writes.
2. **Scheduler:** combine ticket-based Scope indexing with model-compatible
   physical affinity and bounded fair polling. No cross-Scope authority,
   cache generation or quota may be inferred from physical batch affinity.
3. **Worker and telemetry:** combine true one-call native backend batch,
   per-item original Final-use, WAL group commit and signed metrics.
   Missing telemetry must fail closed before declaring production-ready.
4. **Tests:** carry forward both suites; test stale/wrong generation,
   duplicate effect, lost ACK, parent/child crash, NDU expiry, native
   batch one-call, resource counters and cross-Scope fairness.
5. **Only then** construct a two-parent merge, verify its exact tree and
   repeat Rustfmt, Rust tests/Clippy, Bazel Linux/macOS/Windows and
   `cargo-deny` on the resulting commit. Merge-base/current-base and
   GitHub prospective merge SHA must be checked afresh.

## Separate blocking CI defects

The last fully logged source-head build examined was commit
`0430ad22e56bd48daca486a299a936e224b7931c`.
It compiled much of the native suite but failed at
`hepta-intelligence-eval/src/cell_split_lifecycle_tests.rs` with
Rust E0624 for two private methods. The _later_ PR source has
`pub(crate)` methods, so this specific error was already repaired
before the current audit; **no subsequent complete native validation
has been observed**.

Bazel strict Clippy also denied `expect()` usage in the original
Supervisor-checkpoint integrity test. Source commit
`da795caad26bab9391e5009ed19ac17722eed98e` contains its
Result-propagation fix. This still needs an actual current-head check.

`cargo-deny` remains red on a 0.18.0 Matrix SDK graph:
`RUSTSEC-2026-0318` for `matrix-sdk-crypto` (patched at >=0.19.0)
and `RUSTSEC-2026-0319` for the unmaintained `anymap2`, plus
`RUSTSEC-2024-0449` for `unsafe-libyaml`. Migrating Matrix SDK
requires replacing/revalidating the existing vendored
`matrix-sdk-sqlite-0.18.0` / libsqlite3-sys compatibility patch and
regenerating Cargo.lock with a real toolchain. **Do not add advisory
ignores or manually fake a resolved Cargo.lock.**

## Production and operational decision

The PR remains Draft. No Cell Split can be promoted or physically
executed based on a source-only four-owner transcript, static Observer
join, a locally signed minimum store, or a dirty prospective merge.
Independent authenticated monotonic custody, NDU/Selector Final-use,
current owner readbacks, target-host power-loss recovery and the
64/256/1024/4096 Cell metrics matrix remain external acceptance gates.
