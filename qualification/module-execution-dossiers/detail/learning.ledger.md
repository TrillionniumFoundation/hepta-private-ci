# learning.ledger: implementation design

Parent: `docs/modules/learning.ledger/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: additive native source implementation candidate; current exact-head and ordered-base synthetic-merge CI determine source qualification, while product composition and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md` and `../../../docs/engineering/MODULE_ENGINEERING_STANDARD.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-learning-ledger`.
Packages: `LRN-0-CAUSAL-LEARNING-CONTRACTS`, `LRN-1-DURABLE-EPISODE-LEDGER`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-learning-ledger/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Stable V1 formats remain readable; no operation creates another authority or execution spine.

## 2. Public operations and contract details

The closed-world native surface is:

- `verify_independent_roles`;
- `validate_authenticated_outcome`;
- `validate_candidate_set_completeness`;
- `finalize_credit_batch`;
- `freeze_dataset`;
- `append_shadow_decision`;
- `freeze_dataset_receipt_v3`;
- `verify_dataset_snapshot_receipt_v3`.

Product-level `append_decision`, `append_outcome` and correction/revocation flows compose these validators with the existing `DurableLedger`; they are not parallel stores. A stable V1 event is never automatically relabelled V2 or V3, and a plain `StableId` is not an authenticated principal.

`DatasetSnapshotV2` remains source compatible. `DatasetSnapshotReceiptV3` is the required cross-module form because it retains producer identity, correction cut, revocation cut and inclusion policy alongside the V2 snapshot. A consumer can independently reconstruct the exact V2 digest preimage and reject any semantic-field drift.

## 3. State records and transaction design

The module owns `learning_episode_ledger`, `learning_credit_ledger` and `learning_unlearning_lineage`. Decision rows bind principal, episode, objective, model, artifact, the complete generator-relative legal set, selected action, propensity and delivery. Outcome rows bind an independently authenticated observer, exact action, reward units, delay/watermark and correction predecessor. Credit rows conserve terminal outcome exactly. Lineage rows track source-to-dataset-to-artifact correction and revocation.

`AuthenticatedPrincipalV1` is a typed result consumed after host authentication. The pure crate validates bound fields, authority epoch and validity windows but does not provision a trust root or verify an external signature. Product adapters must obtain the value from a current cryptographic verifier rather than deserialize it directly from an untrusted caller.

Generator, observer and allocator independence is a product admission requirement. Principal, credential-chain and signing-key identities must differ. `OutcomeWatermarkV1` distinguishes pending, censored and terminal state. Missing outcomes never become zero reward. `CreditAllocationBatchV1` publishes only when allocations plus residual equal the terminal outcome exactly.

## 4. Deterministic algorithm and scheduling

Authenticate the caller and observer; validate complete candidates and bounded inputs; prepare against an exact predecessor; encode a canonical frame; synchronize; publish core state; persist an independent acknowledgement witness; then acknowledge externally. Retry after synchronization uses the original identity, predecessor and semantic digest. Failed anchored recovery never retries unanchored.

Dataset freeze sorts and deduplicates source record digests and binds the exact ledger head, eligible frontier, outcome watermark, correction cut, revocation cut and inclusion policy. V3 verification replays that canonical preimage from the retained fields. Logical exclusion, model unlearning and physical erasure remain separate operations.

## 5. Capacity and performance profile

Pilot candidate count is at most 128; credit allocation count is at most 256; dataset source records are at most 1,000,000. Existing durable row, frame and segment bounds remain authoritative where stricter. Measure synchronization, reopened-history validation, acknowledgement recovery, correction/revocation traversal, V3 digest verification, storage growth and pending-watermark age.

Source ceilings are enforced limits, not target-host measurements. Rotation and migration require separately qualified profiles.

## 6. Concrete verification cases

- LEDGER-01: acknowledgement loss reconciles the committed event from its original identity and anchor.
- LEDGER-02: truncating acknowledged history fails anchored recovery.
- LEDGER-03: generator/observer identity collision is rejected across principal, credential and signing key.
- LEDGER-04: delayed/corrected outcomes and revoked ancestry alter dataset eligibility without rewriting history.
- LEDGER-05: a self-verifying dataset receipt recomputes exactly and rejects correction, revocation, policy or source-record drift.

Every case maps to concrete Rust tests in `../../lane-e/TEST_TRACEABILITY.json`. A passing source test is not a production deployment, live observer or future-calendar receipt.

## 7. Integration, rollback and capability ceiling

Product composition must pass `DatasetSnapshotReceiptV3`, not a detached digest, into operator and artifact adapters. Rollback restores compatible formats and current revoke cutoffs and never drops a durable acknowledgement frontier. Immediate revocation and stop remain effective across frozen snapshots.

Use all dossier receipt fields. Preserve every applicable external gate; no generator self-acceptance, self-merge, self-selection or self-release is authorized.

## 8. Native closure and remaining evidence

Repository-controlled coverage is verified by `../../../scripts/hepta-lane-e-closure.py` and `.github/workflows/hepta-lane-e-gap-closure.yml`. CI compiles and tests owner crates and the cross-crate consumer, applies strict Clippy/rustfmt, and repeats checks on an ordered merge against the immutable pull-request base.

The repository cannot self-issue a named production caller, current credential/signature verification, exclusive physical writer, directory durability, live independent outcomes, target-host measurements, independent semantic acceptance, canary, selection, promotion or release. Those exact-candidate gates remain open for their external owners.
