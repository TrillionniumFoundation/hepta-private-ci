# Learning evaluation admission after consolidation

The restored Lane E source includes strict learned-operator fitting, immutable
dataset/admission receipts, replayable final-holdout/lifecycle journals, an
independently anchored holdout-owner contract and signed longitudinal admission.
Their existence is not evidence of a running long-term learner. Repository-
controlled qualification status is owned by
`../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`; this document cannot
upgrade product execution, future-calendar evidence, acceptance or release.

## Authenticated evidence boundary

`AuthenticatedPrincipalV1::validate`, the legacy evaluator and the V1/V2 dataset
receipt APIs validate supplied structure and digests. They do not authenticate an
external caller or prove that an estimate was produced by an independent actor.
They remain available for trusted in-process composition and compatibility.

Qualification-scoped external evaluation uses `decide_with_signed_evidence_v1`
or `decide_with_signed_evidence_v2`. A `SystemLongitudinal` request requires an
observed-time admission path: V3 validates signed observed windows and independent
observer identity, while V4 additionally binds external preregistration,
collection and trusted-clock provenance. V1/V2 authenticate the submitted bytes,
then reject the stronger longitudinal claim with `MissingLongitudinalTiming`.
The host constructs `LearningEvidenceVerifierV1` from its authority store and
distributes the resulting trust digest to signers. Never construct that verifier
from the same remote request being evaluated.

1. Register scoped Ed25519 public keys, role assignments, controlling authorities,
   credential lifetimes, objective and authority epoch in host-owned trust state.
2. Persist the frozen evaluation plan before accessing its holdout. The generator
   signs the frozen plan digest. Claimed signature timestamps do not prove the
   order of observations; the host's durable preregistration receipt establishes
   that order.
3. The independent evaluator signs the exact request payload for the applicable
   V1/V2/V3/V4 surface. These bind the entire supplied bundle and, where
   applicable, the metric-role, observed-time and external-provenance contracts.
4. Admission verifies the actual payload digest and signature, issuer assignment,
   role, scope, objective, epoch, lifetime and revocation, and rejects shared
   principal/key/credential/controller identities. A private verified type is
   produced only by this verifier. Rotate/revoke by replacing trusted state and
   reverify outstanding evidence; cached objects do not consult live revocations.
5. Run the existing frozen-plan, holdout, lineage, interval and claim checks.
   Preserve both the decision and its authentication/trust digests for audit.
   All resulting decisions retain `DENY_ALL` authority.

A signature proves an authorized key attested the bytes. It does not establish
unbiased measurement, honest controller registration, actual organizational
independence, valid confidence coverage or future learning gains. Data collection,
estimation and selection/promotion authorization remain separate host duties.
Exact signed-request replay is read-only evaluation; one-use holdouts remain the
registry/journal/owner's responsibility. This does not replace AuthBus execution
replay protection or authorize effects.

## Preregistered metric roles

`freeze_cross_fold_plan_v2` assigns every metric exactly one role and requires at
least one primary objective. Directions, absolute bounds, roles and nonnegative
margins enter the sealed plan/metric digests before holdout consumption:

- `PrimarySuperiority`: conservative direction-adjusted improvement must strictly
  exceed the registered minimum improvement.
- `NonInferiority`: improvement may equal minus the maximum permitted regression.
- `AbsoluteConstraint`: the registered bound alone gates this metric. For a
  maximize metric it is a lower bound; for minimize it is an upper bound.

Existing absolute bounds apply to all roles. The V2 evaluator verifies the same
plan and metric contract; changing roles/margins or reinterpreting V2 with the
legacy all-superiority evaluator fails. Zero-event safety can remain at zero
while a primary utility improves. Simultaneous coverage and estimator validity
remain obligations of the supplied confidence evidence.

## Temporal claim limits

Current temporal fitting and per-fold lineage require distinct training and
holdout principals. This estimates generalization to previously unseen subjects;
it does not test whether the same subject improves through its own history.
The existing `SystemLongitudinal` requirements (multiple snapshots and future
windows, retention and unlearning receipts) are structural gates, not observed
long-term gains. No new learning level or benchmark gain is claimed here.

An individual-longitudinal protocol needs a separately registered estimand:
fixed subjects/cohort and baseline history; forward-only time splits permitting
shared subjects while excluding future decision/outcome/episode leakage;
policy/objective snapshots; dependency-aware subject or episode clusters (or
justified temporal blocks for one subject); independently measured future outcomes;
retention and unlearning after updates; and holdouts inaccessible to the learner.
Do not weaken the current cross-subject isolation to imitate this experiment.

## Capacity failure atomicity

`FinalHoldoutJournalV1::with_record_limit` exposes a host admission budget bounded
by the existing one-million-record ceiling. Capacity and sequence checks precede
registry mutation. Full journals still permit exact retries; a failed new request
changes neither journal nor registry digest. Snapshots keep their existing wire
shape. Hosts retaining a lower limit reopen through
`from_snapshot_with_record_limit`; the legacy constructor uses the original cap.

## Durable final-holdout owner adapter

`DurableFinalHoldoutJournalV1` wraps the existing semantic journal, not another
holdout authority. Its caller supplies an authorized regular `File`, a nonzero
scope binding and an independently retained minimum `HoldoutAnchorV1`. `create`
is explicit initialization; `recover` never recreates or trims a damaged file.
The journal takes an exclusive file lock, replays bounded frames and checks the
acknowledged chain prefix. `consume` checks the expected anchor, validates the
next semantic state, writes and synchronizes bytes, then publishes memory state.
An uncertain write poisons the handle. Exact retries do not append duplicates.

Host-owned format `HEPTHO01` is distinct from cross-owner protocols: an eight-byte
magic, 32-byte binding and 32-byte header checksum precede length-prefixed sealed
plan payloads and their checksums. Integers are big-endian, IDs are bounded ASCII,
frames are at most 2,048 bytes, files at most 16 MiB and journals at most 8,192
records. Unknown/truncated/corrupt bytes reject. No implicit migration is allowed.

For qualification-scoped product composition, use
`DurableFinalHoldoutOwnerV1<S: HoldoutAnchorStoreV1>` rather than treating the raw
journal as sufficient evidence of exclusivity. The owner requires the host's
independent anchor store to expose durable compare-and-store semantics. Before a
new holdout-use receipt is returned, the journal has been synced and the external
anchor must advance from the expected value to the replayed head. If the anchor
commit is unavailable, conflicting or indeterminate, the owner fences itself;
the caller must reopen through recovery before any confirmatory label is exposed.
Recovery can fast-forward an independently acknowledged prefix after replay but
refuses to adopt a nonempty journal when no independent anchor exists.

This protocol closes the repository-side acknowledgement window; it still does
not prove that a concrete anchor implementation is independently administered,
authenticated, durably replicated or current. Product qualification must name and
verify that store, its namespace, writer/CAS policy, directory durability and
recovery procedure. Locks exclude cooperating writers, not hostile filesystem
mutation. Tests cover process reopen, idempotent retry, old-backup/truncation,
corruption, lock collision, uncertain journal writes, uncertain external-anchor
commits, fencing and prefix recovery. They are not production-caller or future-
window receipts.

## Observed-time longitudinal admission

V3 binds `ObservedFutureWindowV1` records to the frozen plan, objective, dataset,
snapshot IDs, exact window set, observed source cuts and a host-preregistered
minimum window duration. Time values use **Unix microseconds throughout the
selected trust profile**, including signer lifetimes and the caller's current
time. The frozen time must equal the generator's signed plan timestamp. Windows
must follow freezing, not overlap, have nonzero observed counts and distinct
source cuts, and end before the observer's signed observation and trusted current
time. The final holdout window must be among those observed windows.

The independent observer signs `future_window_signing_payload_v1`. The evaluator
signs `longitudinal_evaluation_signing_payload_v3`, including the time evidence,
observer signature and minimum duration; a changed policy requires new evidence.
Existing trust, role separation, support, intervals, retention and unlearning
checks still run.

For qualification-grade external longitudinal admission, V4 adds
`LongitudinalEvidenceProvenanceV1`. It requires three distinct nonzero digests:

- `preregistration_receipt_digest`: durable host evidence that the frozen plan was
  registered before confirmatory observations became available;
- `collection_receipt_digest`: authenticated provenance for the independent live
  outcome collection/source cut;
- `clock_attestation_digest`: an independently checkable trusted-current-time
  attestation used by the host.

`future_window_signing_payload_v2` binds the V3 observed-time bytes and all three
provenance references for the observer. The evaluator signs
`longitudinal_evaluation_signing_payload_v4`, which also includes the observer's
signed evidence. `decide_with_signed_longitudinal_evidence_v4` verifies generator,
evaluator and observer role separation, validates the observed window bounds and
includes the provenance bytes in the final authentication digest. Reusing one
digest for multiple provenance classes or supplying a zero reference rejects.

V4 deliberately carries references, not a repository-owned claim that those
external systems are truthful. Exact-candidate qualification must independently
resolve/authenticate those receipts and establish that the calendar actually
elapsed, collection was live and the clock/currentness source was trustworthy.
Native virtual-clock and generated-timestamp tests are explicitly **not** future-
calendar efficacy evidence. No capability level changes merely because V4 source
validation succeeds.

## Exact-head evidence retention

`.github/workflows/hepta-lane-e-gap-closure.yml` binds execution to the exact
candidate source SHA, runs closed-world/status validation, all-target compilation,
owner regression tests, cross-crate and cross-language tests, strict per-crate
Clippy and formatting/clean-worktree checks. Only after the complete exact-head
job succeeds does it upload a retained `lane-e-exact-head` receipt. The ordered-
parent synthetic-merge job likewise uploads a separate receipt only after the
merge tree compiles, tests and remains byte/index stable.

The receipts bind source/base/merge identities as applicable and the git blob
identities of the Lane-E implementation matrix, test traceability registry and
learning.eval status guard. They explicitly state that product execution,
future-calendar evidence, independent acceptance and release are not proved.
Thus a green source receipt cannot be reinterpreted as an external capability
acceptance artifact.
