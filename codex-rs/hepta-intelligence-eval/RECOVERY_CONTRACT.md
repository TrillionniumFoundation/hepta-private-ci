# Recorded evaluation recovery contract

## Delivery and evidence boundary

PR #1011 (`fix/learning-eval-full-convergence-20260926`) is the canonical delivery
line. PR #1051 remains historical comparison material and must not be treated as
an independent merge route. This contract describes source semantics, not a
passing execution receipt, selected-host qualification, independent acceptance,
activation or release approval.

All recovered records and receipts retain `DENY_ALL`.

## Default API boundary

Default `RecordedProductEvaluationRunnerV1` requires
`DurableProductEvaluationAttemptJournalV1`; the independently anchored wrapper is
the default durable implementation. Raw `ProductEvaluationRunnerV1` and direct
V1/V2 compatibility comparators are unavailable unless the explicit
`trusted-inprocess-eval` feature is enabled.

Signed V2/V3 decision primitives and the raw post-verification publication helper
are crate-internal. Public recovery cannot accept a caller-created decision as a
verification result.

## Persistent attempt lifecycle

The recorded path appends and acknowledges `IntentPersisted` before provider
manifest lookup or final-holdout CAS. The intent binds attempt identity, frozen
plan, actual owner namespace and pre-consumption owner state. An existing attempt
is a recovery case, never permission to re-execute.

The successful chain is:

```text
IntentPersisted
  -> HoldoutConsumed
  -> ComparisonSealed
  -> QualificationArtifactsPersisted
  -> QualificationDecided
  -> PublicationPending
  -> Published
```

`RejectedBeforeHoldout` is permitted only for a known pre-consumption rejection;
`Failed` is permitted only for a known post-consumption evaluation failure.
Unknown owner commits preserve the intent. Comparison sealing is not archive
persistence, decision, publication submission or publication completion.

Intent stores owner namespace and pre-owner state. Later phases bind the consumed
holdout record. `ComparisonSealed` stores execution digest;
`QualificationArtifactsPersisted` stores canonical archive digest;
decided/pending store the exact publication-request digest; published stores the
durable publication digest. Identical replay is idempotent; skipped phases,
changed identities or conflicting terminal state fail closed.

## Lifecycle capacity and unresolved index

The file owner has fixed byte and event ceilings. Before a new intent is admitted,
`AttemptCapacity::project` reserves every remaining success phase. A request that
cannot reserve the complete lifecycle is rejected before the runner contacts the
holdout owner or provider. Already admitted work retains its completion budget.

Legacy histories remain readable and recoverable, but they do not gain unsafe new
admission from pre-reservation state.

The reducer maintains a lexically ordered unresolved-attempt index. It is rebuilt
from canonical history on full replay or checkpoint restoration and updated with
the addressed transition. `pending(after, limit)` walks unresolved identities,
not completed history, and rejects page sizes outside 1..1024. The index is
rebuildable and not authoritative.

## Independent journal anchor

The append format is bounded and checksummed. Full recovery streams frames and
requires the exact independently retained `ProductEvaluationAttemptAnchorV1`
prefix. An older complete backup or valid complete-frame prefix is rejected.
Unanchored recovery is compatibility/source tooling, not the default product
capability.

The anchored wrapper acknowledges only after file sync and independent anchor
CAS. An uncertain anchor write poisons the handle. Recovery may adopt a complete
post-anchor tail only after proving the retained prefix, syncing the recovered
file and advancing the authority to the exact recovered history. It never truncates an uncertain tail or
lowers an anchor.

The anchor authority must be authenticated and outside the journal's rollback and
backup failure domain. Same-directory fixture files are not target-host evidence.

## Independently anchored checkpoints and tail replay

A checkpoint is a canonical serialization of the complete reducer state at one
journal event count and byte frontier. Its record binds:

- journal namespace;
- event count and journal byte frontier;
- rolling journal state digest;
- canonical reducer snapshot digest;
- checkpoint-record digest.

`checkpoint_into` writes a new file, syncs it and advances a domain-separated
checkpoint anchor only after exact bytes are durable. It does not modify or
truncate the journal. The host retains the predecessor until the successor file,
anchor and containing-directory update are durable.

`recover_with_checkpoint` requires the normal journal anchor, the derived
checkpoint anchor, the checkpoint file and original append-only journal. It
verifies checkpoint identity and integrity, rejects a checkpoint newer than the
normal anchor and verifies the original journal prefix through the checkpoint's
exact byte frontier. This bounded streaming pass checks frame checksums, event
count and the same rolling state digest used by ordinary journal replay; an
authentic snapshot cannot authorize a different same-length journal prefix.
Recovery reconstructs histories, capacity reservations and the unresolved index
from the snapshot and replays only later complete frames through the reducer.
The resulting rolling state must encounter the normal retained anchor, and the
file is synced before a recovered frontier can be acknowledged.

Tail-only refers to reducer replay, not journal I/O. Prefix verification reads
and hashes the original prefix in `O(B_prefix)` time with one bounded frame
buffer; with tail validation, journal reads and hashing remain `O(B)` in total.
Checkpoint snapshot loading and restored reducer state require their own bounded
memory. Checkpoint recovery does not provide tail-only reads or erase the
original journal's authority.

Checkpoint substitution, stale journal restore, conflicting tail, truncation or
anchor mismatch fails closed. A checkpoint checksum without an independent anchor
is not trusted evidence.

## Canonical typed qualification archive

Before `QualificationDecided`, the selected-host path creates a versioned
canonical archive from actual typed objects:

- single- or multi-outcome evaluation receipt;
- qualification context;
- signed V2/V3 evidence;
- timing evidence;
- exact plan, holdout, execution, namespace and host bindings.

The archive codec is owned by `learning.eval`; callers do not provide parallel
Debug strings or opaque byte vectors. Encode/decode round trips validate canonical
order, size bounds and exact identity. Persistence is create-only: equal content
is idempotent and changed content under the same attempt conflicts.

Recovery loads the exact archived bytes and re-runs current signature, expiry,
revocation, role separation, objective/scope and V3 timing checks inside the
module. No decoder callback, cached decision or caller-supplied digest is an
authentication result. Only the canonical publication request derived from the
reverified decision may advance the journal.

## Persistent recovery controller

The selected-host controller owns a durable cursor distinct from the attempt
journal. One bounded iteration loads unresolved identities and routes by phase:

- `IntentPersisted`: read the authoritative holdout owner and append only an exact
  already-existing consumption; never call the provider;
- `HoldoutConsumed` or `ComparisonSealed`: preserve evidence and report unresolved
  unless the exact owner-controlled continuation is available;
- `QualificationArtifactsPersisted` or `QualificationDecided`: load the canonical
  archive, reverify current V2/V3 evidence and permit the first publication only
  from the exact prewrite state;
- `PublicationPending`: read the publication store and append `Published` only for
  an exact matching committed record; absence is not permission to write;
- terminal phases: no action.

The cursor advances past unresolved attempts so one permanently unresolved item
cannot starve later identities. The selected host must serialize recovery against
live work for the same attempt and durably retain cursor updates.

## Canonical holdout CAS recovery and cost

The locked-file holdout backend retains one semantic journal during replay.
Before a live CAS append it replays the proposed transition against a cloned
journal and compares the complete canonical result with the supplied record.
Self-consistent metadata digests cannot admit invented journal heads, altered
record fields or histories that disk replay would reconstruct differently.
Only an exact transition is synced and installed in the live cache; rejected
transitions leave both file and cache unchanged. Recovery also syncs the file
before exposing its authoritative state.

For `N` plan records, `F` fence events and `B` file bytes, recovery has worst-case
source cost `O(B + N² + F(N + 1))` and memory `O(B + N)` under the backend's hard
ceilings. It no longer reconstructs every earlier semantic prefix per frame.
The wire-compatible v2 registry still hashes its complete sorted binding table
for each new plan, and snapshots still copy retained records.

The optional `FinalHoldoutCasStoreV1::canonical_journal_cache` preserves a native
journal already produced by canonical replay. Owner recovery uses it only after
normal record validation and complete snapshot equality, then restores the new
owner's record-limit policy. A cache mismatch fails closed. The locked-file
backend supplies this capability, so an in-process takeover of `N` retained
records costs `O(N)` cloning/comparison instead of replaying every prefix again.
A workload with `N` new plans and `F` such cached takeovers remains bounded by
`O(N² + F(N + 1))`, excluding storage synchronization latency.

Stores whose default cache method returns `None` retain strict public snapshot
replay, including recomputation of every historical registry-prefix digest.
Their recovery costs `O(N²)` per call, and repeatedly recovering between new
plans can still produce cubic total work. No public or generic snapshot decoder
accepts caller-supplied registry digests as proof of their earlier prefixes.
These boundaries do not establish linear scaling, a full-capacity service
objective or target-host latency guarantees.

## Holdout and publication reconciliation

Recovery validates complete per-attempt history: identity, sequence, legal phase,
plan/holdout/archive/request binding, predecessor/event digests and latest-pointer
agreement. Individually valid frames from different histories cannot be spliced.
This complements but never replaces the global anti-rollback anchor.

`reconcile_product_attempt_holdout_v1` reads the namespace recorded in intent and
associates only an existing exact plan consumption. It cannot release provider
data, run an estimator, issue holdout CAS or retry evaluation.

`RecordedPublicationSinkV1` persists decided and pending phases before touching
the evidence store. `ReconciledProductQualificationSinkV1` loads before write and
re-reads accepted-or-unknown results. It never turns a pending read returning
absence into a new write.

`reconcile_product_attempt_publication_v1` reads by historical execution identity,
validates the exact request and appends `Published` only for a matching committed
record. These reconciliation functions may mutate the attempt journal but never
issue a publication write.

A crash after `QualificationDecided` but before `PublicationPending` is distinct:
recovery reloads the typed archive, performs current verification and may perform
the first write only for the exact original request. Pending and Published are
rejected by that write path.

## Single- and multi-outcome recovery

Both receipt families use the same typed archive, publication lifecycle and
selected-host controller. `freeze_product_outcome_plan_v1` binds metric/channel
identity, schema, unit, normalization, subgroup, window, provenance commitment,
input digest and candidate/baseline temporal plans.

`evaluate_outcome_comparison` releases one complete channel batch after one
holdout consumption, validates exact payload coverage and computes channels
separately. Partial, relabelled, substituted or duplicate payloads fail closed.
The private one-stream carrier cannot be extracted as a product receipt.

Multi-outcome cold recovery rejects a changed host, namespace, archive family,
execution or publication request, re-verifies current evidence, publishes at most
once and supports read-only reconciliation after acknowledgement loss.

Agentd consumes the sealed outcome receipt only with current owner state and a
signed exact-use payload. These source paths do not authenticate a real
measurement custodian or selected host.

## Statistical reproducibility boundary

`CrossFoldPlanV1::execute_temporal_cross_fit_v1` recomputes every declared fold
from exact supplied lineages and accepts only preregistered model/prediction
digests. It prevents duplicate fold coverage and held-out decision reuse. It does
not rerun a consumed final holdout during recovery.

`SequentialPlan::estimate_cluster_intervals_v1` provides fixed-analysis cluster
bounds for finite-horizon PDIS/DR under a preregistered absolute-return envelope.
Too few clusters and envelope breach remain typed evidence gaps. The result is not
anytime-valid and does not authenticate cluster independence.

## Fault and sustained tests

Process fixtures kill an isolated child around irreversible consumption,
provider-release, computation/sealing, archive/decision, pending-publication and
acknowledgement-loss cuts. Cold-restart fixtures reopen file owners without
retaining pre-crash typed objects, re-verify current evidence and ensure no
provider re-release or duplicate publication.

Checkpoint tests cover exact snapshot/tail restoration, byte substitution and a
checkpoint newer than the normal anchor. Capacity tests cover complete-lifecycle
reservation and indexed unresolved lookup. The sustained source profile creates a
checkpoint 64 attempts before each 128-attempt restart, exercising nonempty tail
replay over 4,096 attempts and 28,672 lifecycle events.

The `learning_eval_storage_profile` binary additionally consumes one distinct
synthetic frozen plan per fence generation within the existing `--fences` budget
(default 512). It reopens the nonempty source history, compacts it, reopens the
compacted history and checks an exact retry cannot add bytes or consume again.
Schema v1 retains its original measurements and adds `planRecords`,
`sourceRecoveryMicros` and `retryPreserved`; `writeMicros` covers plan freezing,
consumption and fence takeover. These same-host fixture measurements exercise
multiple plan histories, not full-capacity or real deployment performance.

These remain source fixtures until one immutable exact tree and its ordered-parent
merge produce passing retained artifacts.

## Remaining obligations

Repository-controlled closure still requires:

1. formatting, compilation, default/compatibility API checks, owner and consumer
   tests, process-fault tests, strict lint, measured coverage, exact-head and
   ordered-parent merge evidence on one final candidate;
2. binding the source facade/controller to an authenticated independently
   administered anchor authority, real provider and publication store on the
   declared topology;
3. near-capacity admission, unresolved backlog, checkpoint rotation, cold startup
   and sustained recovery measurement on that topology.

External gates remain target-host identity, storage linearizability/durability,
real future-calendar outcomes, independent provenance, retention/privacy/
unlearning/power evidence, semantic/operator acceptance, selection, canary,
promotion, activation and release. Source code cannot self-issue them.
