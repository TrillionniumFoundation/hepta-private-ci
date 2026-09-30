# Runtime writer selection and long-run qualification

Date: 2026-09-28. Status: complete bounded recalculation remains selected.
This is a selection policy, not a fabricated performance result or release approval.

## Current decision

Retain `refresh_scope_projection_tx` plus complete canonical generation construction
as the durable cognitive mutation algorithm. Retain `apply_incremental_delta` as an
equivalence/reference path; do not promote it merely because the implementation exists.
The storage mode `revision_facts_v1` already avoids persisting a full physical graph
copy per generation. It does not remove full source-cut reconstruction, canonical
recalculation, predecessor validation or publication digest computation.

Indexed verified-generation queries and transaction-local support-index caching are
read-side optimizations. Their successful receipts must equal the scan reference for
admitted requests. A workload budget error is not a partially successful query and
must not be converted into a lower-quality success by an unrecorded fallback.

## Evidence currently required

The exact candidate and deterministic merge against
`a126987b84737dbc2ee2592442a314117bddb4a2` must pass their native profiles. Preserve
per-command logs, exit status, actual test summaries, immutable source/tree identity,
measurement host information and budget-check results. A skipped or absent command,
zero matched exact test, cancelled runner or missing measurement is not success.
Formatting/source binding belongs to preparation commits, never to execution-time
patching of the tested candidate.

The inherited native runner requests the ignored crash-window test and
`cognitive_kg_benchmark_tests::history::qualification_kg_history_reopen_no_resurrection`
explicitly. It also invokes release-mode native measurements and the budget checker
on product/source-head. These must actually execute before their behavior can be
claimed as verified for this continuation.

## Hosted measurement versus deployment target

The inherited `kg-hosted-ci-regression-v1` profile is a deliberately broad hosted-CI
regression ceiling, not a user-facing service-level objective. Its minimum measured
workload includes 256 writes, 20 query samples, five reopens, four contention readers
and ten contention rounds. Current ceiling fields cover mutation/query/reopen p99,
contention writer/reader p99, peak RSS and combined database/WAL bytes. The runner
records machine architecture and logical CPU count; that is not a complete binding
to a deployment CPU model, storage device or filesystem.

A deployment acceptance profile must be selected and retained before measurement,
with CPU/memory limits, storage/filesystem/mount configuration, OS, runtime/toolchain,
release binary identity and workload shape. The intended deployment host and service
budgets were not supplied by this change. Hosted-runner observations cannot be renamed
as deployment qualification, and thresholds must not be relaxed after observing a
failure merely to obtain a green result.

## Long-running workload matrix

Keep current active graph size and retained history size as separate dimensions.
Required host runs vary small/near-capacity active cuts, high support fan-in, repeated
correction and forget operations on existing identities, large revision/generation
history, concurrent readers with a writer, and repeated crash/reopen boundaries.
Measure p50/p95/p99, peak memory, DB/WAL growth, transaction time and contention, not
only final throughput. Reopen and old-snapshot/backup tests must verify that deletion
or revocation cannot resurrect a fact through a projection or cached view.

## Conditions for changing the selected writer

Promoting incremental persistence requires a measured benefit on the fixed host
profile and independent equality against complete recalculation for accepted mutation
traces. Compare canonical source, generation and publication digests, relation/support
identity, query results, correction/forget behavior, rollback and crash recovery.
Include adversarial duplicate identity, shape conflicts, concurrent writes and failed
publication transitions. Preserve complete-rebuild verification and rollback capability.
No numeric speedup, latency success or durable incremental selection is asserted here.

## Claim boundary

`productionImplementation`, `productExecutionProved`, `independentAcceptance`,
`activation` and `release` remain false until their corresponding current evidence and
independent gates are satisfied. No writer-selection document, source-map rebind or
hosted budget check can grant deployment authority by itself.
