# Learning evaluation admission after consolidation

The restored Lane E source includes strict learned-operator fitting, immutable
dataset/admission receipts, and replayable final-holdout/lifecycle journals. The
journals implement semantic replay and expected-head checks; the host still owns
exclusive writing, fsync, crash recovery and a trusted persisted head. Their
existence is not evidence of a running long-term learner.

## Authenticated evidence boundary

`AuthenticatedPrincipalV1::validate`, the legacy evaluator and the V1/V2 dataset
receipt APIs validate supplied structure and digests. They do not authenticate an
external caller or prove that an estimate was produced by an independent actor.
They remain available for trusted in-process composition and compatibility.

Qualification-scoped external evaluation uses `decide_with_signed_evidence_v1`
or `decide_with_signed_evidence_v2`. A `SystemLongitudinal` request now requires
`decide_with_signed_longitudinal_evidence_v3`: signed window names alone are
insufficient. V1/V2 authenticate the submitted bytes, then reject that stronger
claim with `MissingLongitudinalTiming`. The host constructs `LearningEvidenceVerifierV1`
from its authority store and distributes the resulting trust digest to signers.
Never construct that verifier from the same remote request being evaluated.

1. Register scoped Ed25519 public keys, role assignments, controlling authorities,
   credential lifetimes, objective and authority epoch in host-owned trust state.
2. Persist the frozen evaluation plan before accessing its holdout. The generator
   signs the frozen plan digest. Claimed signature timestamps do not prove the
   order of observations; the host's durable registration establishes that order.
3. The independent evaluator signs the exact `evaluation_signing_payload_v1/v2`
   bytes. These bind the entire supplied bundle and V2 metric-role contract.
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
registry/journal's responsibility. This does not replace AuthBus execution replay
protection or authorize effects.

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
holdout authority. Its actual caller supplies an authorized regular `File`, a
nonzero scope binding and an independently retained `HoldoutAnchorV1`. `create`
is explicit initialization; `recover` never recreates or trims a damaged file.
The adapter takes an exclusive file lock, replays bounded frames and checks the
acknowledged chain prefix. `consume` checks the expected anchor, validates the
next semantic state, writes and synchronizes bytes, then publishes memory state.
An uncertain write poisons the handle. Exact retries do not append duplicates.

Host-owned format `HEPTHO01` is distinct from cross-owner protocols: an eight-byte
magic, 32-byte binding and 32-byte header checksum precede length-prefixed sealed
plan payloads and their checksums. Integers are big-endian, IDs are bounded ASCII,
frames are at most 2,048 bytes, files at most 16 MiB and journals at most 8,192
records. Unknown/truncated/corrupt bytes reject. No implicit migration is allowed.

Before releasing confirmatory labels or acknowledging consumption externally,
the host must durably retain the returned anchor independently of this journal.
A backup cannot manufacture its own expected anchor. The host still owns current
trust/revocation distribution, directory durability, retention and the production
scheduler. Locks exclude cooperating writers, not hostile filesystem mutation.
Tests in `src/durable_holdout_tests.rs` cover a different loading process,
idempotent retries, acknowledged-history truncation, corruption, writer collision
and write uncertainty. They are not production-caller or future-window receipts.

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
checks still run. The host must authenticate durable preregistration and the
observer's actual collection/clock provenance; signatures alone do not prove the
calendar elapsed or that measurements are honest. Native virtual-clock tests are
explicitly **not** future-calendar efficacy evidence. No capability level changes.
