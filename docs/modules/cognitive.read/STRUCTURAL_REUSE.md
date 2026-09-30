# Request-local immutable structural reuse

This technical supplement preserves the single-owner and final-use boundaries
in TECHNICAL.md. It describes direct source implementation, not deployment
acceptance. All activation and release claims remain false pending evidence.

## Types and lifetime

`PreparedReadSnapshotV1<'snapshot>` borrows one immutable CognitiveSnapshot and
builds its validated current-head index once. The constructor calls the existing
whole-snapshot integrity and terminal-tombstone checks. It does not own a store,
principal, grant, revocation cache, clock, lease or background worker. An active
borrow prevents changing the snapshot bytes, digest or generation in safe Rust.

The one-shot `read_ids_v1` and prepared `read_ids` methods share request validation,
exact-ID lookup, field projection, construction preflight and canonical encoding.
Every call repeats ID/field/budget checks and requires the bound snapshot digest.
Results remain all-or-error and DENY_ALL. V1 digest domains and golden vectors
are unchanged. Preparation is not source authentication or current authorization.

Agentd's private `OwnerCutReadView` accepts only the already acquired
DurableCognitiveSnapshot. It retains that exact cut borrow rather than pairing
an index with caller-supplied scope metadata. One normal read request reuses it
for admission and the final selected projection. It is not placed in process
state, a shared cache, a persistent record or a cross-request handle.

The final-use request still reacquires the current owner cut, compares bindings,
constructs a fresh view and repeats record/retrieval/ranker checks. No publication
view crosses that boundary. The final check is an observation, not a lease that
prevents later owner writes.

## Verification

`prepared_tests.rs` covers field-set and permutation equality with one-shot reads,
IDs beyond the legacy prefix, explicit missing IDs, total-byte boundaries,
repeated request rejection, generation mismatch and corruption outside selected
IDs. The compile-fail example documents the borrow restriction; the crate has
`doctest=false`, so that example is not claimed as an executed test.

Normal Agentd, memory, infer-core, native-worker and cognitive_product_e2e tests
must run on the exact source and synthetic merge. A unit test or source audit is
not a replacement for fresh-context acceptance and stale/revoked-context rejection
at the physical TurnStart boundary.

## Measurements

The prepared benchmark compares two complete one-shot projections with one
preparation plus two projections. Preparation is included in the comparison;
prepare-only and warm projection-only distributions are labeled separately.
Order alternates to reduce systematic warm-cache bias. Every case first checks
complete result equality. Workloads vary total revision rows (128/4096/16384),
revision depth (1/8) and requested IDs (1/up to 512), with citations present.

Each case records 32 empirical samples. Process high-water RSS is a whole-process
Linux observation, not a per-case allocation measure. These in-memory measurements
do not establish SQLite latency, CPU attribution, cold-reopen performance, model
latency or target-host acceptance. Those require additional owner/host evidence.

## Qualification V2

The read-only qualifier executes the same mandatory suites for source and merge.
Its V2 receipt requires the expected command set, command/log/exit records,
nonempty nextest execution summaries and valid workload measurements. Partial
successful command sets cannot issue passed=true. Failed gates remain in the
bundle, and failure exits nonzero. V1 receipts remain historical evidence; they
are not upgraded or rebound to a new candidate.

The workflow has read-only repository permission and does not repair, commit,
delete or push candidate source. Implementation-map refresh is an ordinary
reviewed documentation commit after source authoring, never a qualification step.
