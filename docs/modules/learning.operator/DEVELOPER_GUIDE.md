# `learning.operator` developer guide

## Production qualification sequence

The production path is deliberately narrower than the compatibility API:

1. Replay the authoritative `learning.ledger` and freeze a `DatasetSnapshotReceiptV3`.
2. Rebind the receipt to that replay with `verify_dataset_snapshot_receipt_against_ledger_v3`.
3. Construct `LearningEvidenceVerifierV1` exclusively from host-owned trust configuration. Candidate input may not choose keys, roles, scope, objective, or authority epoch.
4. Canonically encode every training row, including row identity, sensor/state, action, target/outcome, next-state semantics, and source evidence digest.
5. Require an Ed25519 `Observer` attestation over those exact canonical bytes.
6. Call `verify_tabular_operator_plan_v3` or `verify_world_model_dataset_v3`. Only the resulting opaque value may reach the V3 fit API.
7. Persist create-only payload bytes and a host-selected complete payload pin.
8. Independently evaluate and select the exact immutable artifact.
9. Load in a fresh process through the evaluated, read-only consumer path. Keep authority deny-all during shadow operation.
10. Roll back by reopening an immutable predecessor and its original pin; never retrain or rewrite it.

V2 dataset wrappers and V1 payload pins are compatibility surfaces. They do not independently establish production admission.

## Local checks

```bash
python3 scripts/hepta-lane-e-closure.py self-test
python3 scripts/hepta-lane-e-closure.py verify
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-bellman-operator --locked
cargo clippy --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-bellman-operator --all-targets --locked -- -D warnings
```

## Error semantics

A receipt, ledger-head, trust-epoch, signature, row-payload, registry-head, runtime-profile, schema, or immutable-identity mismatch is a global admission failure. Unsupported prediction cells abstain. No production adapter may silently repair or quarantine a semantically changed row and continue training.

## Ownership boundaries

`learning.operator` constructs deterministic qualification candidates. It does not own the ledger, artifact registry, evaluator, selector, activation policy, production writer, or rollback authority. Those owners must issue independently verifiable inputs; passing caller-authored digests is not a substitute.
