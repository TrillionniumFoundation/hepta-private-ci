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
