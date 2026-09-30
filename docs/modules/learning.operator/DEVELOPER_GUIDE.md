# `learning.operator` developer guide

Canonical admission semantics are in [ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).
[STATUS.json](STATUS.json) distinguishes implemented components, the generic
shadow coordinator, default runtime composition and external acceptance.

## Default qualification path

1. Replay the authoritative `learning.ledger` and freeze an owner-issued
   `DatasetSnapshotReceiptV3` with the exact source set, authority and expiry.
2. Construct `LearningEvidenceVerifierV1` from host-owned trust configuration.
   Candidate inputs do not choose signer keys, roles, scope or authority epoch.
3. Derive `TrainingProfileV1` or `WorldModelProfileV1` from semantic values. Their
   profile/runtime identities are computed internally; do not accept an unrelated
   caller-supplied digest as evidence of the profile.
4. Bind exact row semantics to independent `Observer` attestations and prepare
   `TabularTrainingRequestV1` or `WorldModelTrainingRequestV1`.
5. Issue the opaque capability through `issue_tabular_final_use_capability_v1`
   or `issue_world_model_final_use_capability_v1`. Bind the current durable owner,
   fence, issuance witness, exclusive deadline and shared work controls.
6. Consume it once through `fit_tabular_final_use_v1` or
   `fit_world_model_final_use_v1`. Revalidation before and after fitting is part
   of the operation; it must not be removed to save time.
7. Freeze independent evaluation data and evaluate the exact immutable candidate
   under the preregistered plan. Obtain a separately authenticated selection.
8. Persist the independently selected candidate create-only through the existing
   artifact owner, binding its payload and complete `TabularPayloadPinV2`.
9. Load in a fresh process and observe the candidate through a read-only host.
   `LoadedTabularOperatorV2` validates immutable payload/pin identity; selection,
   current owner state, revocations, clock and stop state require host checks at
   final use. An opaque selected wrapper is not a live owner witness.
10. Restore the exact immutable predecessor and its original complete pin after
    shadow qualification; never retrain or rewrite it during rollback.

The generic `coordinate_learning_operator_shadow_v1` enforces stage ordering
when a host supplies its ports. Its current tests use fixture ports; real owner
adapters and a default runtime caller remain repository integration work. Signed
component E2E exercises the ledger/evaluator/selector/ranker separately.

Direct V3 verify/fit primitives and structural V1/V2 fitters are available only
under `qualification-unverified-input`, in `compatibility`. They are diagnostic
and migration surfaces, not the default capability path. Existing V1 payload
pins and immutable predictors remain exported for named owner-bound adapters;
they do not establish current selection or runtime authority.

Canonical JSON adapters remain separate work. Native profile names do not imply
wire parity with registered protocols. Existing correctly pinned `HEPTTB01`
payloads can be read, while new V2 source commitments require new independent
admission; there is no implicit digest-version downgrade.

## Local checks

Run the Python checks from the repository root, and use the repository `just`
recipe for routine Rust tests:

```bash
python3 scripts/hepta-lane-e-closure.py self-test
python3 scripts/hepta-lane-e-closure.py verify
python3 scripts/hepta-learning-operator-contract.py verify
just test -p codex-hepta-bellman-operator --locked
just test -p codex-hepta-agentd --lib -E 'test(cognitive_ranker::evaluated_tests)'
just test -p codex-hepta-agentd --lib -E 'test(learning_operator_coordinator::tests)'
```

Exact-source CI independently records documentation, API consumer checks,
compilation, tests, mutation, coverage, resource regression and static quality.
`hepta-implementation-maps.py verify` additionally requires the retained source
observations to exist in local Git history. Missing historical objects or stale
observations are diagnostics, not current execution evidence. The authoritative
qualification script is an exact committed-candidate workflow; inspect every
stage receipt and any skip instead of treating command presence as a pass.

## Error semantics

Use `ClassifyOperatorAdmissionFailure::disposition`; do not parse display strings.
Correct request-local failures, re-admit stale evidence against current owners,
reject invalid candidates, abstain on unsupported cells, and stop the consumer on
owner, clock or authority failure. Reopening failure of the exact predecessor is
terminal.

## Ownership boundaries

`learning.operator` constructs deterministic qualification candidates. The
ledger, artifact registry, evaluator, selector, activation policy, production
writer and rollback authority remain with their existing owners. Repository
success does not issue scientific acceptance or production activation.
