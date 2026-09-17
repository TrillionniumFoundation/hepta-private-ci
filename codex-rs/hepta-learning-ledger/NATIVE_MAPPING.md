# `learning.ledger` native implementation mapping

This file maps the stable module guide and implementation dossier to concrete
Rust symbols. It does not grant a production writer, authenticate a real
credential issuer, prove organizational independence, establish physical
unlearning, or prove future outcomes.

## Compatibility and state ownership

The existing V1 `LearningLedger` and durable event/chain encoding remains
readable. The additive V2 causal layer represents facts that V1 cannot safely
compress into a plain identity or opaque support digest. No automatic V1-to-V2
reinterpretation is permitted.

Owned logical domains remain:

- causal decision and episode facts;
- independently observed outcome facts;
- conserved credit facts;
- correction and revocation lineage;
- immutable dataset-freeze receipts.

The pure core has no ambient I/O. Raw `DurableLedger` and `SegmentedLedger`
instances remain maintenance/recovery surfaces over host-supplied file
capabilities. Product-facing source composition should use
`WitnessedLearningLedger` through the sealed `AcknowledgedLearningJournal`
port so a durable journal mutation is not acknowledged before its independent
witness frontier is synchronized.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| append a validated V1 event | `LearningLedger::append` | `src/ledger.rs` | retained |
| durable append and anchored reopen | `DurableLedger`, `LedgerAnchor`, `LedgerRecovery` | `src/durable.rs` | retained |
| segmented durable append/rotation | `SegmentedLedger` | `src/segments.rs` | retained |
| atomic durable event batch | `DurableLedger::append_batch`, `SegmentedLedger::append_batch` | `src/durable.rs`, `src/segments.rs` | implemented |
| independent acknowledgement witness | `LedgerWitnessStore` | `src/witness.rs` | implemented |
| witness-gated consumer journal | `WitnessedLearningLedger`, `AcknowledgedLearningJournal` | `src/acknowledged.rs` | implemented |
| map a deny-all intuition decision | `prepare_shadow_decision`, `append_shadow_decision` | `src/shadow.rs` | implemented |
| authenticate generator/observer separation | `verify_independent_roles` | `src/causal_v2.rs` | implemented |
| cryptographically admit signed evidence | `LearningEvidenceVerifierV1`, `verify_signed_role_separation` | `src/signed_evidence.rs` | implemented |
| validate delayed/corrected outcome | `validate_authenticated_outcome` | `src/causal_v2.rs` | implemented |
| prove generator-relative candidate completeness | `validate_candidate_set_completeness` | `src/causal_v2.rs` | implemented |
| finalize conserved credit | `finalize_credit_batch` | `src/causal_v2.rs` | implemented |
| commit conserved credit to witnessed durable history | `append_conserved_credit_batch_v1` | `src/credit_commit.rs` | implemented |
| freeze caller-described immutable dataset | `freeze_dataset` | `src/causal_v2.rs` | retained compatibility surface |
| self-verify a complete dataset receipt | `freeze_dataset_receipt_v3`, `verify_dataset_snapshot_receipt_v3` | `src/dataset_receipt_v3.rs` | implemented |
| derive dataset membership from replayed ledger | `freeze_dataset_from_ledger_v3` | `src/dataset_from_ledger.rs` | implemented |

The V2 structural identity check compares principal ID, credential-chain digest
and signing-key digest and validates authority epoch and expiry. Actual external
evidence admission is performed by `LearningEvidenceVerifierV1`, which validates
host-owned trust context, Ed25519 signatures, role assignment, validity windows,
payload binding and signer revocation. The host remains responsible for supplying
and rotating the current trust snapshot; source code cannot self-certify the
production trust-root distribution.

`OutcomeWatermarkV1` distinguishes pending, censored and terminal observations.
Terminal records require an observed value and finalization time; censored
records require a censoring reason and carry no invented value. Corrections bind
a predecessor.

`CreditAllocationBatchV1` is the semantic publication unit for causal credit.
`finalize_credit_batch` sorts/deduplicates allocations and requires
`sum(allocations) + residual == terminal outcome` exactly in raw Q32 units.
`append_conserved_credit_batch_v1` additionally derives the terminal outcome from
the current acknowledged ledger snapshot, binds each V1 `CreditAssignment` to
the V2 batch digest, commits the complete allocation set through one atomic
durable batch and advances the independent witness before returning success.

`freeze_dataset_from_ledger_v3` is the strict V1-compatible freeze path. It
replays the supplied authoritative snapshot through `LearningLedger`, derives
the actual ledger head, logical frontier, objective membership, active lineage,
relevant revocation cut and pending count, and then emits a self-verifying V3
receipt. It does not trust a caller-supplied source-record set. The V1 ledger has
no censored-outcome representation, so this compatibility path never invents a
censored count; full censoring semantics remain a V2/external-evidence concern.

## Acknowledgement and recovery rules

`LedgerWitnessStore` is append-only and monotonic. Each witness transition binds
its predecessor and successor anchors and is synchronized before success.
`WitnessedLearningLedger::attach` refuses to promote a non-empty journal from an
empty witness. A valid witnessed prefix may reconcile a longer canonical journal
suffix after lost acknowledgement, but a mismatched prefix fails closed.

The witness file being a separate capability is necessary but not sufficient for
operational independence. A production host must place and administer the witness
outside the failure/rollback domain of the protected ledger, including directory
durability, ACL/credential separation, backup isolation and restore policy.

## Host and caller obligations

A production integration receipt must name all of the following:

1. the product process and exact callsite invoking each operation;
2. the current credential/trust-root source and verifier generation;
3. the exclusive physical writer fence and durable ledger identity;
4. the independently administered witness identity and durability boundary;
5. the source of independent terminal observations;
6. the correction/revocation and outcome-watermark sources used for dataset freeze;
7. target-host latency, storage-growth, disk-full, crash/reopen and restore measurements;
8. the exact commit, tree, binary and configuration generation.

A shadow/test caller is not a production caller. A separate file in the same
rollback or administrative domain is not, by itself, proof of independent
witnessing. A different `StableId` without authenticated credential, key and
controller separation is not proof of independent observation.

## Failure and retry rules

- semantic identity reuse with changed content conflicts;
- missing/stale authentication fails before a causal receipt is emitted;
- acknowledgement loss retries the original identity and semantic digest;
- pending or censored outcomes never become zero reward;
- a failed anchored reopen never silently retries unanchored;
- a witnessed writer never acknowledges journal state ahead of its witness;
- atomic batches validate and fit before bytes are written, then synchronize the complete suffix before publishing in-memory state;
- durable credit derives the terminal outcome from acknowledged ledger state rather than trusting the submitted batch;
- strict dataset freeze derives membership from replayed ledger state rather than a caller-supplied digest list;
- logical revocation excludes active lineage but does not claim physical erasure, backup purge or model-weight unlearning;
- every exported V2/V3 receipt remains deny-all and cannot select or activate an artifact.

## Qualification mapping

Focused tests live in the owner crate, including:

- `src/durable_tests.rs`;
- `src/segments_tests.rs`;
- `src/causal_v2_tests.rs`;
- `src/signed_evidence_tests.rs`;
- `src/witness.rs` test module;
- `src/acknowledged.rs` test module;
- `src/credit_commit.rs` test module;
- `src/dataset_from_ledger.rs` test module;
- `src/shadow_tests.rs`.

Cross-crate composition remains exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
CI jobs and externally governed acceptance gates remain registered under
`qualification/lane-e/` and `docs/lane-e/`. Passing source tests is not proof of
a live production caller, physical durability on a target host, independent
acceptance, canary promotion or release.
