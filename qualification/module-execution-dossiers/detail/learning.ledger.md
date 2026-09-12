# learning.ledger: implementation design

Parent: `docs/modules/learning.ledger/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: additive native source implementation candidate; current exact-head and synthetic-merge CI determine source qualification, while product composition and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-ledger`.
Packages: `LRN-0-CAUSAL-LEARNING-CONTRACTS`, `LRN-1-DURABLE-EPISODE-LEDGER`.

Operation signatures below are design contracts. Concrete source mappings are now recorded in `../../../codex-rs/hepta-learning-ledger/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`append_decision(run_snapshot, legal_set, assignment, expected_anchor) -> DecisionCommit`; `append_outcome(decision, authenticated_observer, watermark) -> OutcomeCommit`; `append_correction_or_revoke(source, cutoff) -> LineageCommit`; `freeze_dataset(plan, eligible_frontier) -> DatasetSnapshotV2`. Use the existing `DurableLedger`, native admission and anchored recovery surfaces; do not create a parallel product ledger.

The stable V1 event and durable encoding remains readable. The additive V2 source exposes `verify_independent_roles`, `validate_authenticated_outcome`, `validate_candidate_set_completeness`, `finalize_credit_batch` and `freeze_dataset`. V1 records are not automatically relabelled V2 and a plain `StableId` is not an authenticated principal.

## 3. State records and transaction design

Own `learning_episode_ledger`, `learning_credit_ledger` and `learning_unlearning_lineage`. Decision rows bind principal/episode/boundary, objective/artifact/model/body, full generator-relative legal candidates, chosen action, propensity and delivery. Outcome rows bind independent observer, exact action, reward units, delay/watermark and correction predecessor. Credit rows conserve terminal outcome; lineage rows track source-to-dataset-to-artifact revocation. Large payloads remain outside general receipts.

`AuthenticatedPrincipalV1` binds principal, credential chain, signing key, scope, authority epoch and validity window. Generator and observer independence requires all three identity classes to differ. `OutcomeWatermarkV1` distinguishes pending, censored and terminal state. `CreditAllocationBatchV1` is finalized only when allocations plus residual equal the terminal outcome exactly. `DatasetSnapshotV2` binds ledger head, eligible frontier, outcome watermark, correction cut, revocation cut, inclusion policy and canonical source record set.

## 4. Deterministic algorithm and scheduling

Host authenticates observer, scope and handles; validate and prepare; predecessor CAS; encode canonical frame; sync; publish core state; persist an independent acknowledgement witness; then acknowledge externally. A retry after sync must use the original identity, predecessor and digest. Failed anchored recovery cannot retry unanchored. Unknown outcome stays pending or censored, never zero reward. Physical erasure and model unlearning are distinct from logical exclusion.

The native V2 validators are pure and deny-all. They validate already authenticated receipt fields but do not verify signatures or provision a trust root. The product host must perform that work before constructing the typed values.

## 5. Capacity and performance profile

Pilot candidate count is at most 128. The stable durable core bounds total records and encoded frames; the product profile retains the stricter applicable row, segment and dataset limits. Rotation is a separately tested migration. Measure sync, reopened-history validation, correction/revocation traversal, storage growth and pending watermark age.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition.

## 6. Concrete verification cases

- LEDGER-01: acknowledgement loss reconciles the committed event from its original identity and anchor.
- LEDGER-02: truncating acknowledged history fails anchored recovery.
- LEDGER-03: generator posing as an independent observer is rejected by real host authentication, not string comparison.
- LEDGER-04: delayed/corrected outcomes and revoked ancestry change dataset eligibility without rewriting history.

Every case is mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`. A passing source test is not a production deployment, live observer or future-calendar receipt.

## 7. Integration, rollback and capability ceiling

Compose native `DurableLedger`, dataset and artifact consumers in C1. Future-time labels generated inside one fixture do not qualify longitudinal efficacy. Rollback restores compatible formats and current revoke cutoffs; it never drops a durable acknowledgement frontier.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `DurableLedger` in [codex-rs/hepta-learning-ledger/src/durable.rs](../../../codex-rs/hepta-learning-ledger/src/durable.rs); `LearningEvidenceVerifierV1` in [codex-rs/hepta-learning-ledger/src/signed_evidence.rs](../../../codex-rs/hepta-learning-ledger/src/signed_evidence.rs). Anchored file ledger and additional signed evidence admission implemented.
- **State and recovery:** DurableLedger owns HEPTLR01 framed, checksum/chain-bound append storage over a host-authorized locked File; sync precedes in-memory commit. Anchored recovery requires an independently retained LedgerAnchor. Signed evidence verification is a separate API from pure typed V2 validators.
- **Source tests:** [codex-rs/hepta-learning-ledger/src/durable_tests.rs](../../../codex-rs/hepta-learning-ledger/src/durable_tests.rs), [codex-rs/hepta-learning-ledger/src/signed_evidence_tests.rs](../../../codex-rs/hepta-learning-ledger/src/signed_evidence_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-learning-ledger/DURABLE.md](../../../codex-rs/hepta-learning-ledger/DURABLE.md), [codex-rs/hepta-learning-ledger/INSPECTION.md](../../../codex-rs/hepta-learning-ledger/INSPECTION.md).
- **Remaining work:** Supply current trusted signer/witness distribution, durable directory ownership and product causal consumers. Logical revocation leaves audit bytes and does not establish physical erasure, independent scientific truth or long-term efficacy.

## 9. Native closure and remaining evidence

Repository-controlled implementation coverage is verified by `../../../scripts/hepta-lane-e-closure.py` and `.github/workflows/hepta-lane-e-gap-closure.yml`. The workflow compiles and tests the owner crates, executes a cross-crate causal chain, applies strict Clippy/rustfmt and repeats the source checks on an ordered-parent synthetic merge.

The repository cannot self-issue the remaining product evidence: a named production caller, current credential/signature verification, exclusive physical writer and directory durability, live independent outcomes, target-host measurements, independent semantic acceptance, canary, selection, promotion or release. Those gates remain open until their responsible external owners issue immutable receipts for the exact candidate.
