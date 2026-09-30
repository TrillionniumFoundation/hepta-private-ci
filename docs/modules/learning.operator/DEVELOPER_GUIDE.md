
# `learning.operator` developer guide

Canonical state and recovery semantics are in
[ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).

## Production qualification sequence

1. Replay the authoritative `learning.ledger` and freeze a
   `DatasetSnapshotReceiptV3`.
2. Rebind the receipt to that replay with
   `verify_dataset_snapshot_receipt_against_ledger_v3`.
3. Construct `LearningEvidenceVerifierV1` only from host-owned trust
   configuration. Candidate input may not choose keys, roles, scope,
   objective, or authority epoch.
4. Canonically encode every training row, including row identity,
   state/sensor, action, target/outcome, next-state semantics, and
   source evidence digest.
5. Require an independent Ed25519 `Observer` attestation over those
   exact canonical bytes.
6. Call `verify_tabular_operator_plan_v3` or
   `verify_world_model_dataset_v3`. Only the opaque V3 result may reach
   the corresponding V3 fit API.
7. Revalidate current owner state immediately before fitting. Do not
   remove this second check to save time.
8. Persist create-only payload bytes and a host-selected complete
   `TabularPayloadPinV2`.
9. Independently evaluate and select the exact immutable artifact.
10. Load in a fresh process through `LoadedTabularOperatorV2` and the
    evaluated read-only Agentd consumer. Keep authority deny-all.
11. Roll back by reopening an immutable predecessor and original pin;
    never retrain or rewrite it.

V2 dataset wrappers and V1 payload pins are compatibility surfaces.
They establish structural validity only, not current owner-bound
production admission.

## Local checks

```bash
python3 scripts/hepta-lane-e-closure.py self-test
python3 scripts/hepta-lane-e-closure.py verify
python3 scripts/hepta-implementation-maps.py verify
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-bellman-operator --locked
cargo clippy --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-bellman-operator \
  -p codex-hepta-intelligence-eval \
  -p codex-hepta-learning-ledger \
  --all-targets --locked --no-deps -- -D warnings
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd --lib cognitive_ranker::evaluated_tests \
  -- --nocapture
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-bellman-operator \
  full_v3_qualification_path_profile --locked -- --ignored --nocapture
```

Exact-source CI executes every gate independently and publishes an
explicit pass/fail/timeout record. A failed lint gate does not silently
skip the executable tests.

## Error semantics

Use `ClassifyOperatorAdmissionFailure::disposition`; do not parse error
display strings. Request-local failures are corrected, stale evidence
is re-admitted against current owners, candidate-global failures reject
the candidate, unsupported cells abstain, and owner/clock/authority
failures stop the consumer.

## Ownership boundaries

`learning.operator` constructs deterministic qualification candidates.
It does not own the ledger, artifact registry, evaluator, selector,
activation policy, production writer, or rollback authority.
