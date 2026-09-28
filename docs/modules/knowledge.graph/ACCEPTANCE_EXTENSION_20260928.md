# knowledge.graph acceptance extension — 2026-09-28

This candidate extends the existing sealed indexed-query implementation and
exact-candidate workflow. It does not replace the runtime writer, create another
fact store or grant production acceptance.

## Public query verification

`codex-rs/hepta-kg/tests/query_acceptance.rs` adds five public-API tests. The
reference/indexed equivalence test exercises 768 combinations of seed subsets,
structural and temporal cuts, relation filters and output limits. Full result
objects are compared, including request/result digests and exact omitted counts.
Input permutations, self-loops, duplicate support identity with payload drift,
exact work-budget exhaustion, simultaneous node/edge withdrawal, retained
dangling-edge rejection and mismatched source-cut digests are covered.

The actual indexed type is `VerifiedKnowledgeGenerationV2` in `indexed_query.rs`.
It owns a validated immutable generation and derived adjacency/node indexes.
Product `RetrievalGeneration` caches that view and compact support identities
inside one owner's SQLite transaction. Raw `query_relations` remains the checked
reference path. The indexed path's default ceiling is 1,000,000 support inspections
plus copies; validation/index construction are separate costs. No constant-time
or allocation-byte bound is implied by the output edge count.

Budget exhaustion is an error, never a truncated successful result. Consequently
a successful empty result is distinguishable from an exhausted request, and no
caller receives an inexact omitted count. The explicit lower-budget API cannot
raise the library ceiling. Trusted code that needs broader work must use a
different, named operation instead of silently treating the external entry point
as unbounded.

## Publish, crash, recovery and retry evidence

The durable owner suite names the lost-acknowledgement replay, competing-head
rollback and publication-failure rollback tests. The ignored destructive test
`qualification_kg_projection_crash_windows_restore_exact_predecessor` launches a
child process, waits at both `before_semantic_receipt` and
`after_semantic_receipt_before_current_pointer`, force-kills the child and reopens
the same store. Each reopen must contain the exact predecessor and pass SQLite
integrity checking. Zero-test, skipped or build-only output is rejected.

The exact-candidate runner records these contracts separately from ordinary
source checks. Missing `protoc`, a failed native build, an unobserved named test,
or an absent destructive receipt fails the lane. `protoc --version` is therefore
an explicit prerequisite rather than an ambient runner assumption.

## Long-history concurrency and deletion

`cognitive_kg_benchmark_tests::history::qualification_kg_history_reopen_no_resurrection`
is the exact ignored test name. Each of the default 128 corrections now overlaps
one product retrieval. A concurrent reader may observe the complete predecessor
or successor, never an unrelated revision. Its memory revision and KG generation
binding must agree for this single-memory fixture. At history checkpoints, after
writer completion and reopen, the latest revision must be retrieved. Final
tombstoning is checked over three reopens, and an attempted correction cannot
resurrect it.

Receipts add `concurrentReads`, `concurrentReaderNs`, `concurrentRoundNs` p50/p95/p99
and an explicit `correctionTimingScope`. `correctionNs` measures the correction
future itself; reader latency and the complete concurrent round are measured
separately. None of these is relabeled as isolated SQLite transaction time.

## Operation measurement and evidence contract

`codex-rs/hepta-kg/tests/operation_measurement.rs` records the current public
operation boundaries: input clone, combined build/validate/seal, verified-view
construction, repeated hot query and publication-receipt construction. It does
not pretend that the public combined builder exposes internal timings that it
does not expose. The native SQLite measurement separately records durable
mutation, query, reopen, writer, reader and complete contention-round
distributions.

Every exact candidate lane writes
`hepta.knowledge-graph-delivery-evidence.v1`. Each contract row binds:

```
contract → implementation symbol → named test → tested commit/tree
         → runner environment → evidence file → remaining open reason
```

The artifact keeps source checks, native compilation, actual scenario execution,
target-host qualification, independent acceptance, activation and release as
separate states. Hosted lanes may prove only the first three.

## Storage, evidence and remaining acceptance

`revision_facts_v1` is compact persistent representation, not incremental runtime
recalculation. Complete bounded rebuild remains selected. Current active graph
size and retained history growth must both be qualified before changing it.

The existing exact-source/fixed-base workflow, source-object map binding, native
execution inventory audit and independent acceptance gates remain required.
These added tests are definitions, not successful execution receipts. A hosted
runner is not automatically the operator's production CPU/storage profile.
No source-implementation, product-execution, target-host acceptance, activation or
release flag is advanced by this extension.
