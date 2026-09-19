# `learning.ledger` native implementation mapping

This file maps the stable module guide and implementation dossier to concrete
Rust symbols. It does not grant a production writer, authenticate a real
credential issuer or prove future outcomes.

## Compatibility and state ownership

The existing V1 `LearningLedger` and `DurableLedger` event tags 0-3 and their
chain encoding remain unchanged and readable. This convergence adds durable tags
4-6 for authenticated outcomes, conserved credit batches and explicit unlearning
lineage. New binaries read old histories; old binaries are not claimed to read a
history after a new event kind has been appended. No automatic V1-to-V2
reinterpretation is permitted.

Owned logical domains remain:

- causal decision and episode facts;
- independently observed outcome facts;
- conserved credit facts;
- correction and revocation lineage;
- immutable dataset-freeze receipts.

The pure core has no ambient I/O. `DurableLedger` writes only through a
host-supplied file capability and the host remains responsible for trusted path
opening, directory durability, writer fencing and publication of an independent
anchor.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| append a validated V1 event | `LearningLedger::append` | `src/ledger.rs` | retained |
| durable append and anchored reopen | `DurableLedger`, `LedgerAnchor`, `LedgerRecovery` | `src/durable.rs` | retained |
| map a deny-all intuition decision | `prepare_shadow_decision`, `append_shadow_decision` | `src/shadow.rs` | implemented |
| authenticate generator/observer separation | `verify_independent_roles` | `src/causal_v2.rs` | implemented |
| validate delayed/corrected outcome | `validate_authenticated_outcome` | `src/causal_v2.rs` | implemented |
| prove generator-relative candidate completeness | `validate_candidate_set_completeness` | `src/causal_v2.rs` | implemented |
| finalize conserved credit | `finalize_credit_batch` | `src/causal_v2.rs` | implemented |
| freeze immutable dataset | `freeze_dataset` | `src/causal_v2.rs` | implemented |
| production signed + anchored admission | `ProductionLedgerWriter` | `src/production.rs` | implemented, not product-composed |
| current trust refresh + anti-rollback | `LearningEvidenceTrustProviderV1`, `LearningEvidenceTrustSnapshotV1` | `src/signed_evidence.rs`, `src/production.rs` | implemented, host provider not product-bound |
| pinned-root signer distribution | `verify_learning_trust_manifest`, `RootedLearningEvidenceTrustProviderV1::rotate` | `src/trust_root.rs` | implemented, production root key/distribution external |
| durable authenticated/corrected outcome | `LedgerEvent::AuthenticatedOutcome` | `src/model.rs`, `src/ledger.rs`, `src/durable_codec.rs` | implemented |
| durable atomic conserved credit batch | `LedgerEvent::CreditBatch` | `src/model.rs`, `src/ledger.rs`, `src/durable_codec.rs` | implemented |
| correction graph head/fork/cycle prevention | `LearningLedger::validate_authenticated_outcome` | `src/ledger.rs` | implemented |
| derive dataset from current ledger | `ProductionLedgerWriter::freeze_dataset_from_ledger` | `src/production.rs` | implemented |
| explicit source-to-derived unlearning lineage | `LedgerEvent::UnlearningLineage` | `src/unlearning.rs`, `src/ledger.rs` | implemented |
| independent acknowledgement witness | `DurableAnchorWitness` | `src/witness.rs` | implemented |
| canonical registry protocol adapters | `OutcomeReceiptV1`, `CreditAssignmentReceiptV1`, `DatasetSnapshotV1`, `LearningDecisionV1`, `LearningEpisodeV1` | `src/protocol.rs` | implemented |
| verifiable long-history index checkpoint | `LedgerIndexCheckpointV1` | `src/index_checkpoint.rs` | implemented |
| deterministic recovery-work accounting | `LedgerRecoveryWorkV1`, `measure_ledger_recovery_work` | `src/index_checkpoint.rs` | implemented |

The V2 identity check compares principal ID, credential-chain digest and
signing-key digest, and validates authority epoch and expiry.
`LearningEvidenceVerifierV1` performs Ed25519 admission against a host-owned trust
snapshot. `ProductionLedgerWriter` no longer caches one verifier indefinitely:
it queries `LearningEvidenceTrustProviderV1` before every signed mutation,
validates the snapshot time window and maintains a monotone revision/authority
epoch/trust-digest frontier. Trust rollback or same-revision drift fails closed.
`RootedLearningEvidenceTrustProviderV1` can back that boundary with an
out-of-band pinned Ed25519 root and predecessor-bound signed signer manifests;
remote evidence cannot choose or replace the root. The host still owns the root
private key, durable authority-store publication and controller identity.

`OutcomeWatermarkV1` distinguishes pending, censored and terminal observations.
Terminal records require an observed value and finalization time; censored
records require a censoring reason and carry no invented value. Corrections bind
a predecessor.

`CreditAllocationBatchV1` is the publication unit for causal credit. Allocation
rows are sorted and deduplicated, and `sum(allocations) + residual` must equal
the terminal outcome exactly in raw Q32 units before a receipt is emitted.

`DatasetSnapshotV2` binds the exact ledger head, eligible frontier, outcome
watermark, correction cut, revocation cut, inclusion policy and canonical source
record digest set. It carries pending and censored counts and has `DENY_ALL`
authority.

## Host and caller obligations

A product integration receipt must still name all of the following:

1. the process and callsite invoking each operation;
2. the current credential/trust-root verifier;
3. the exclusive writer fence and durable file/store identity;
4. the source of independent terminal observations;
5. the acknowledgement witness retained outside the ledger file;
6. the revocation and correction frontier used for dataset freeze;
7. target-host latency, storage-growth and crash/reopen measurements;
8. the exact commit, tree, binary and configuration generation.

A test caller or source-path inventory is not a production caller. A different
`StableId` without credential and signing-key separation is not independent.

## Failure and retry rules

- semantic identity reuse with changed content conflicts;
- missing/stale authentication fails before a causal receipt is emitted;
- current trust is reloaded per signed production mutation; revision/epoch rollback and same-revision trust drift reject;
- acknowledgement loss retries the original identity and semantic digest;
- pending or censored outcomes never become zero reward;
- a failed anchored reopen never silently retries unanchored;
- stale correction predecessors, forks and cross-episode correction edges reject;
- conserved credit batches append as one durable event and cannot bypass exact conservation through the production writer;
- dataset source/correction/revocation cuts are derived from the anchored ledger by the production writer rather than caller-supplied;
- dataset source digests are sorted and duplicate source records reject;
- unlearning lineage requires an already-revoked source and one linear head per derived object;
- canonical protocol adapters reject unknown fields and semantically invalid values on both encode and decode;
- recovery-work receipts account exact replayed canonical event bytes without claiming target-host wall-clock latency;
- every exported V2 receipt remains deny-all and cannot select or activate an
  artifact.

## Qualification mapping

Focused tests live in:

- `src/durable_tests.rs`;
- `src/causal_v2_tests.rs`;
- `src/convergence_tests.rs`;
- `src/production_tests.rs`;
- `src/witness_tests.rs`;
- `src/protocol_tests.rs`;
- `src/index_checkpoint_tests.rs`;
- `src/shadow_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.
