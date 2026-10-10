# Evaluated shadow consumer

`run_evaluated_shadow_v1` is an opt-in library composition entry. It verifies a sealed `ProductQualificationReceiptV1`, requires its trust digest to equal the current host verifier, binds the single `DatasetSnapshotReceiptV3` to the receipt's exact dataset/objective/snapshot set, and requires product eligibility before invoking any F port. It does not call the low-level V2 evaluator. The same registered evaluator must additionally sign `evaluated_candidate_signing_payload_v2`, which binds the terminal product qualification evidence/publication, actual candidate byte digest/length and artifact generation. The bytes must match the F snapshot's model-artifact digest.

The host supplies the first seven `LaneFShadowPortsV1` methods. Its intuition
result must match a recomputed `decide_calibrated_v2` receipt and disposition for
the supplied typed request. The generic eight-port API and its simulation tests
remain available. This wrapper does not enroll a production host or implement
neural input, prompt, context, model invocation or external dispatch adapters.

The eighth method is implemented here, bypassing the host's `record_learning`.
It appends exactly one `LedgerEvent::Decision` through the supplied
sealed `DurableLearningJournal` port; both `DurableLedger` and `SegmentedLedger`
preserve the same event identity. `LearningRecorded` carries the actual committed
chain digest.
Abstain and slow-path decisions are recorded without context/dispatch calls.
No Outcome or Credit is synthesized. A terminal host failure appends nothing;
append failure returns an error. Fsync is blocking, not preemptively bounded by
the advisory stage time budget.

The run ID is the durable record ID. Retries retain the original expected ledger
predecessor, episode, decision input and artifact/evaluation bindings. Exact
retries are idempotent, including after anchored reopen; changed input under one
record ID conflicts. Host ports may run again during retry and must remain free
of external effects. The host retains the ledger anchor outside the journal and
reconciles any indeterminate I/O before retrying. A segmented host additionally
retains the segment/seal checkpoint and publishes directory entries durably, as
specified in [the existing ledger guide](../hepta-learning-ledger/DURABLE.md).
The adapter does not create files or rotate them implicitly on capacity errors.

Hosts must supply current trusted keys/controller mappings, revocation and time;
authenticate raw data, candidate completeness and calibration/OOD measurements;
supply a correctly generated assignment draw; supply a `ProductQualificationReceiptV1` from the canonical product runner, whose holdout/evidence publication occurred before this adapter is entered. A self-verifying
dataset manifest is not proof of raw observations. Signed metrics authenticate
their attester, not statistical validity. This path grants no selection,
activation, promotion or release authority and demonstrates no long-term learning
or quality improvement.

`just test --offline -p codex-hepta-intelligence` includes real-file append,
reopen/replay, capacity/corruption, signed-input substitution, upstream failure,
abstention and slow-path checks. Test signatures and metrics are synthetic
qualification inputs, not measured learning results.

The durable Decision port now consumes the canonical `LedgerWriter`, requires a separately signed `ProductionDecisionV2` from the qualified generator, and acknowledges only after the independent witness advances. The terminal `ProductQualificationReceiptV1` remains the runtime admission source.
