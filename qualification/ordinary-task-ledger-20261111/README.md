# Ordinary task ledger producer: candidate scope

Status: implementation candidate; native formatting, compilation, caller verification
and tests have not been run for this delta. The twelve new test methods are
component fixtures. Ordinary complete loops, positive adoption, ordinary
NoUpdate/rollback and independent-C qualification remain **0**.

## Fixed source and integration

The source reads use `9bfdef05995409a2257e3c8bd16b967fe6d013e4`.
The separate control-completion change was subsequently published as
`3c8dabe46598599e91b2b8b80081e09069ff9426`; this delta does not replace its
control/client/Feature files or QA changes. Its CALLERS base is Git blob
`e062ce0d0d1779b842a9cd3b42965574e4a56723`. The semantic CALLERS delta adds
actual callers and new boundaries without resetting another candidate's guards.

## Actual product entry and ordinary task result

An embedded host calls `AgentdConfig::with_q24_learning_task_profile` with
the existing real `CircuitQ24TaskProfileV1` and
`OriginalCellQ24TaskLedgerInputsV1`. The factory uses the ordinary Q24 channel
and installs its original source through a concrete invocation wrapper. The
returned `AgentdQ24LearningTaskRuntimeV1` contains the original task runtime and
a retained `Arc<OriginalCellQ24TaskLedgerProducerV1>`.

The original authenticated ObjectiveStart still reaches
`execute_circuit_task_record`. The wrapper's `publish_result` only publishes
the original source result. The separate learning observation invokes the
producer through the installed provider after that real publication. It can
finish the original Generator journal and Ledger; it cannot dispatch a task.

A successful task with no independent Terminal Outcome stays a successful,
readable task. Learning is Pending. Commit uncertainty and refused learning
evidence are reported as learning state; they do not invent an Outcome or a
new task attempt. The original producer's public readback exposes the exact
durable status or original error.

## Capabilities and business data the host must supply

- The existing published task, actual native model, Cell/source files and
  witnesses, routes, fence and original clock required by the ordinary Q24
  profile. A task/source descriptor alone is insufficient.
- The original `Arc<Mutex<LedgerWriter>>`, independently retained witness and
  activated trust for the same objective, plus the Generator's enrolled signer,
  actual key and separate once-only journal/witness.
- The original expected Observer enrollment, business episode/outcome IDs,
  finite-generator metadata, unit and delay profiles, and bounded signing
  window. The producer receives no Observer private key.
- An actually observed `AuthenticatedOutcomeV1` and its original Observer
  signature for `submit_original_terminal_outcome`. Success text, a Cell
  prediction, a trace or an ACK cannot supply a target value. The original
  Ledger checks current Observer permission, full role independence and time.
- The original Evaluator key, trust, journal and witness for Dataset freeze.
  Freeze authorization is distinct from independent B evaluation.
- The existing Root scoped enrollment/consumer handoff and original E/D,
  trainer, independent evaluation, Model, policy and publication owners for the
  later ordinary learning startup. This code does not create these authorities.

No original deployment/business Outcome, independent B holdout, independent C
controller or real daemon/Root restart was supplied by these component fixtures.

## Once-only history and delayed feedback

The Generator signs the exact real Cell/source projection after its original
claim becomes durable. Pending never signs again. The retained envelope binds
the original Ledger predecessor and signed payload. The Outcome journal
retains the independent caller's exact original signature before append.

An exact active record covered by the original witness is historical evidence.
Its saved signature is checked at its original issue time; current original
enrollment/revocation and immutable trust/source bindings are still checked.
No historical verification result is exported as new authority. A fresh
Outcome consumes the current Observer window without demanding that an
already witnessed Generator signature still be unexpired.

A record not yet covered by its witness must use the original Ledger append
path with its unchanged signature at the current time. A one-record witness
lag permits only the original Ledger's exact idempotent replay. An expired
unappended or unwitnessed signature is refused, never renewed or backdated.
Readback and Ready require a fully witnessed cut.

`LedgerWriter::validate_observed_outcome` is a read-only extraction of the
original append checks. The actual append repeats the same checks. It creates
no evidence token, wire profile or owner substitute.

## Actual readiness and startup recovery

Only the producer can construct `OriginalCellQ24TaskLearningReadyV1`.
It binds the complete original RunStart, including authentication, the original
source publication and committed trace, accepted Decision/Outcome records, and
the exact witnessed Ledger cut. The enqueue path rechecks those facts.

The original delivery registry now carries its explicit source profile through
startup recovery. `HostStageOwners` and `OriginalObjective` retain their
existing selected-owner contracts. Actual Root Q24 assembly selects
`OriginalQ24`; an absent producer is Pending/OwnerUnavailable, never a
fallback to either older profile. The plain source explicitly reports
NonLearning. The source run ID alone cannot construct Ready.

`ObjectiveRuntimeHost::reconcile_learning_outbox` reads the original RunStart
and committed trace, invokes the same installed readiness provider, and enqueues
only the appropriate original completion pointer. It never calls ObjectiveStart
or inference. This is the explicit startup/reconciliation continuation after a
late business Outcome; the initial Pending return does not already enqueue.

## Freeze, materialize, and scoped startup

`prepare_learning` has a concrete body: require the original completed ledger
state; capture the actual Dataset and retained task capabilities; create or
recover the supplied original Evaluator freeze owner; authorize and materialize
through the existing HQ24T002 path; revalidate the original source. The actual
batch then determines SGD(batch), the frozen scope and the existing Prepared
input to scoped Root startup. No placeholder optimizer digest, scope rewrite,
legacy HQ24T001 downgrade, or replacement owner is used.

Its `Recover` mode is explicitly for the same current cut. Historical recovery
uses `recover_learning` with the retained original `CellQ24FrozenDatasetV1`,
empty initial checkpoint and frozen scope, plus the current original source,
Ledger, Evaluator journal/witness and signing configuration. It restores the
retained prefix, calls the original freeze owner's readback only, compares the
saved signature exactly, and invokes `CellQ24PreparedLearningV1::recover`.
It never authorizes a new freeze or renews its window. Unrelated later appends
can preserve the old cut; changed receipts, initial/scope, authorization or
current withdrawal still refuse. Current original Evaluator authorization
checks remain required by that existing owner.

A later actual Feature C task can be installed with the same explicit learning
profile. The existing `original_dataset_task` feedback capability can also
supply compatible retained history. Its next independent business Outcome and
new freeze/Root inputs remain mandatory; different runs alone do not prove an
independent original consumer.

## Component test intent

The twelve new methods cover successful task/Pending learning separation and real
startup reconcile; wrong labels, units, support, roles, keys and source withdrawal;
full-authentication Ready binding and missing-installed-producer refusal; delayed witnessed signatures; retained Outcome
ACK loss; expired unappended evidence; original Pending reopen; a real readonly
witness write failure followed by exact replay; expired unwitnessed Outcome; and
canonical Outcome truncation/trailing/unknown-tag rejection; and exact retained
Dataset recovery after an explicitly synthetic unrelated Ledger append, with
changed receipt, initial, signature, Create-mode and source-withdrawal negatives. The witness failure
uses an actual original file descriptor and original recovery APIs, with no
production fault-injection or permission-bypass hook.

Test keys, CURRENT custody and stage profiles are explicit fixtures. Static
method counts and syntax/marker checks are not executed native results.
