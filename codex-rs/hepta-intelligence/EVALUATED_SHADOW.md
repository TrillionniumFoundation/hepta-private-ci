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

The eighth method is implemented here, bypassing the host's `record_learning`.
It appends exactly one `LedgerEvent::Decision` through the supplied
`DurableLedger`; `LearningRecorded` carries the actual committed chain digest.
Abstain and slow-path decisions are recorded without context/dispatch calls.
No Outcome or Credit is synthesized. A terminal host failure appends nothing;
append failure returns an error. Fsync is blocking, not preemptively bounded by
the advisory stage time budget.

The run ID is the durable record ID. Retries retain the original expected ledger
predecessor, episode, decision input and artifact/evaluation bindings. Exact
retries are idempotent, including after anchored reopen; changed input under one
record ID conflicts. Host ports may run again during retry and must remain free
of external effects. The host retains the ledger anchor outside the journal and
reconciles any indeterminate I/O before retrying.

Hosts must supply current trusted keys/controller mappings, revocation and time;
authenticate raw data, candidate completeness and calibration/OOD measurements;
supply a correctly generated assignment draw; persist frozen plans
before collecting holdouts; and durably prevent holdout reuse. A self-verifying
dataset manifest is not proof of raw observations. Signed metrics authenticate
their attester, not statistical validity. This path grants no selection,
activation, promotion or release authority and demonstrates no long-term learning
or quality improvement.

`just test --offline -p codex-hepta-intelligence` includes real-file append,
reopen/replay, capacity/corruption, signed-input substitution, upstream failure,
abstention and slow-path checks. Test signatures and metrics are synthetic
qualification inputs, not measured learning results.
