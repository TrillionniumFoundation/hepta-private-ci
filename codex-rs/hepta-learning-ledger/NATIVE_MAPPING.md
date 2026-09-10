# `learning.ledger` native implementation mapping

This file maps the stable guide and implementation dossier to concrete Rust symbols. It grants no production writer, trust root, live observer, selection or release authority.

## Compatibility and ownership

The V1 `LearningLedger` and `DurableLedger` encoding remains readable. V2 adds causal identity, watermarks, credit conservation and dataset-freeze semantics. V3 wraps the V2 dataset snapshot with every semantic field required to recompute its digest. No historical object is reinterpreted as a newer version.

Owned logical domains remain causal decision/episode facts, independent outcome facts, conserved credit, correction/revocation lineage and immutable dataset-freeze receipts. The host owns trusted path opening, writer fencing, directory durability, signature verification and independent anchors.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| append a validated V1 event | `LearningLedger::append` | `src/ledger.rs` | retained |
| durable append and anchored reopen | `DurableLedger`, `LedgerAnchor`, `LedgerRecovery` | `src/durable.rs` | retained |
| append deny-all shadow decision | `append_shadow_decision` | `src/shadow.rs` | implemented |
| verify generator/observer separation | `verify_independent_roles` | `src/causal_v2.rs` | implemented |
| validate delayed/corrected outcome | `validate_authenticated_outcome` | `src/causal_v2.rs` | implemented |
| validate generator-relative completeness | `validate_candidate_set_completeness` | `src/causal_v2.rs` | implemented |
| finalize conserved credit | `finalize_credit_batch` | `src/causal_v2.rs` | implemented |
| freeze V2 dataset snapshot | `freeze_dataset` | `src/causal_v2.rs` | retained additive surface |
| freeze self-describing snapshot receipt | `freeze_dataset_receipt_v3` | `src/dataset_receipt_v3.rs` | implemented |
| independently recompute snapshot digest | `verify_dataset_snapshot_receipt_v3` | `src/dataset_receipt_v3.rs` | implemented |

`DatasetSnapshotReceiptV3` retains the producer, correction cut, revocation cut and inclusion policy omitted from the compact V2 return type. Verification checks authenticated-principal bounds, deny-all authority, canonical strictly ordered source records and the exact `hepta.learning-ledger.dataset-snapshot.v2` preimage.

## Host obligations

A product integration receipt names the process and callsite, cryptographic credential verifier and trust-root generation, exclusive writer and file/store identity, independent outcome source, acknowledgement witness, correction/revocation frontier, target-host measurements and exact commit/tree/binary/configuration tuple.

`AuthenticatedPrincipalV1` is a preverified host input. Its field validation is not signature verification. A test caller, source path or different string ID is not proof of a production caller or independent principal.

## Failure and retry rules

Semantic identity reuse with changed content conflicts. Missing/stale authentication fails before a receipt. Acknowledgement-loss retry preserves identity, predecessor and semantic digest. Pending or censored outcomes never become zero. Failed anchored reopen never retries unanchored. Dataset source records are canonical and duplicate-free. Every emitted authority posture remains deny-all.

## Qualification mapping

Focused tests live in `src/durable_tests.rs`, `src/causal_v2_tests.rs`, `src/dataset_receipt_v3.rs` and `src/shadow_tests.rs`. Cross-crate composition and API linkage are compiled by `hepta-shadow-qualification`. Exact case and workflow mappings are in `../../qualification/lane-e/TEST_TRACEABILITY.json`.
