# Evaluated shadow consumer

`run_evaluated_shadow_v1` is an opt-in library composition entry. It verifies the
single `DatasetSnapshotReceiptV3` manifest against the complete evaluation
snapshot-ID set, invokes E's signed V2 evaluation, and requires eligibility
before invoking any F port. The same registered evaluator must additionally
sign `evaluated_candidate_signing_payload_v1`: the complete E request commitment,
actual candidate byte digest/length and artifact generation. The bytes must match
the F snapshot's model-artifact digest. These bounded opaque bytes need not be a
model; their meaning and evaluation provenance remain the signer's responsibility.

The host supplies the first seven `LaneFShadowPortsV1` methods. Its intuition
result must match a recomputed `decide_calibrated_v2` receipt and disposition for
the supplied typed request. The generic eight-port API and its simulation tests
remain available. This wrapper does not enroll a production host or implement
neural input, prompt, context, model invocation or external dispatch adapters.

## Authenticated ledger admission

The eighth method is implemented here, bypassing the host's `record_learning`.
It no longer receives a raw `DurableLearningJournal` or constructs a weak V1
`LedgerEvent::Decision`. The caller supplies one `LedgerWriter`, which owns the
durable backend, the activated signer distribution and an independently durable
acknowledgement witness.

Before any host port is invoked, the evaluated-shadow adapter deterministically
builds `ProductionDecisionV2` from the coherent run snapshot and the recomputed
calibrated decision. The candidate set is augmented with the reserved explicit
`abstain` and `shadow:slow-path` choices, canonicalized, and bound into a
`CandidateSetCompletenessReceiptV1` with `omitted_count_bound == 0`. The
registered generator must sign the exact bytes returned by
`decision_signing_payload_v2`. The writer verifies that evidence against its
activated trust distribution before committing an
`AuthenticatedDecisionRecordV2`.

`LearningRecorded` carries the actual committed chain digest only after both
the ledger frame and the independent witness frontier have been synced. If the
ledger commit succeeds but witness persistence is indeterminate, the writer
returns `IndeterminateAfterLedgerCommit`; callers must recover and reconcile
rather than retry with a new identity. Abstain and slow-path decisions are
recorded without context/dispatch calls. No Outcome or Credit is synthesized. A
terminal host failure appends nothing.

The source retains `LearningLedger`, `DurableLedger`,
`SegmentedLedger`, and the sealed `DurableLearningJournal` compatibility port
for V1 history, focused persistence tests and migration tooling. They are not the
product-facing admission surface. New composed callers use `LedgerWriter` so
signed V2 admission, credit conservation, correction lineage and witness
requirements cannot be skipped through the same owned handle.

## Retry, recovery and rotation

The run ID is the durable record ID. Retries retain the original expected ledger
predecessor, episode, decision input and artifact/evaluation bindings. Exact
retries are idempotent, including after anchored reopen; changed input under one
record ID conflicts. Host ports may run again during retry and must remain free
of external effects.

For a single-file backend, `LedgerWriter` requires a separately retained
`LedgerWitnessStore` bound to the same store identity. Recovery first validates
the durable ledger against the acknowledged anchor, independently recovers the
witness and then reconstructs the writer. A complete ledger record may lead its
witness by at most one record only for lost-acknowledgement reconciliation of
that exact event.

For a segmented backend, rotation is performed through
`LedgerWriter::rotate_segment`; the writer advances the independent witness to
the new segment topology before reporting the rotation. The host still owns
trusted file opening, directory publication/synchronization, encryption,
isolation and physical-storage qualification. The witness is a minimum durable
frontier, not a backup or a replacement for directory durability.

## Capability boundary

Hosts must supply a current `LearningTrustDistributionV1` from their authority
source, activate it monotonically with `activate_learning_trust`, authenticate
raw data and calibration/OOD measurements, supply correctly generated assignment
draws, persist frozen plans before collecting holdouts, and durably prevent
holdout reuse. The activated distribution binds generation, effective time,
scope, objective, authority epoch, signer keys, controller identities and roles.

A self-verifying dataset manifest is not proof of raw observations. Signed
metrics authenticate their attester, not statistical validity. This path grants
no selection, activation, promotion or release authority and demonstrates no
long-term learning or quality improvement.

`just test --offline -p codex-hepta-intelligence` includes real-file append,
witnessed reopen/replay, segmented rotation/recovery, capacity/corruption,
signed-input substitution, upstream failure, abstention and slow-path checks.
Test signatures and metrics are synthetic qualification inputs, not measured
learning results.
