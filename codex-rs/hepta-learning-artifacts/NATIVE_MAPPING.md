# `learning.artifacts` native implementation mapping

This file maps immutable artifact storage, lineage, withdrawal and lifecycle
design to concrete Rust symbols. Candidate storage and evaluation eligibility
are not selection, activation, promotion or release.

## Compatibility and state ownership

The existing V1 `ArtifactRegistry`, create-only payload files, registry
snapshots and pinned loader remain unchanged. The additive V2 layer makes
provenance and control evidence explicit without reinterpreting historical V1
manifests.

Owned logical domains are:

- immutable candidate bytes and byte identity;
- append-only artifact registry and lineage;
- persistent dataset-withdrawal facts;
- registry-head witness validation;
- artifact lifecycle evidence.

The source modules do not own a signing key, selection route, production process
or filesystem namespace. Those capabilities remain host-owned.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| register/quarantine/revoke V1 candidate | `ArtifactRegistry::append` | `src/registry.rs` | retained |
| create immutable payload/snapshot | `CreateOnlyArtifactFile`, `write_candidate_payload`, `write_registry_snapshot` | `src/storage.rs` | retained |
| distribute and reload current head witness | `write_registry_head_witness`, `read_registry_head_witness` | `src/storage.rs` | implemented |
| read exact pinned candidate | `load_pinned_candidate` | `src/pinned.rs` | retained |
| prepare snapshot-local dataset revocation | `prepare_dataset_revocation` | `src/dataset_revocation.rs` | retained |
| validate complete V2 manifest | `validate_artifact_manifest_v2` | `src/closure_v2.rs` | implemented |
| persist dataset withdrawal frontier | `DatasetWithdrawalRegistry::append` | `src/closure_v2.rs` | implemented |
| deny future admission from withdrawn dataset | `DatasetWithdrawalRegistry::admit_manifest` | `src/closure_v2.rs` | implemented |
| validate latest-head/anti-rollback evidence | `validate_registry_head_witness` | `src/closure_v2.rs` | implemented |
| validate lifecycle transition | `validate_artifact_lifecycle_transition` | `src/closure_v2.rs` | implemented |
| bind withdrawal authority domain/head | `WithdrawalAuthorityDomainV1`, `withdrawal_authority_domain_digest_v1`, `withdrawal_head_digest_v3` | `src/admission_v3.rs` | implemented |
| admit against exact scoped withdrawal frontier | `admit_manifest_at_withdrawal_head_v3` | `src/admission_v3.rs` | implemented |
| append/replay lifecycle journal | `ArtifactLifecycleJournalV2::append`, `from_snapshot` | `src/lifecycle_journal.rs` | implemented |
| persist withdrawal/lifecycle control snapshots | `write_*_snapshot`, `read_*_snapshot`, domain-aware withdrawal wrappers | `src/control_storage.rs` | implemented |
| bind V2 admission to durable V1 publication | `prepare_artifact_publication_transaction_v1` | `src/publication.rs` | implemented |
| classify publication crash recovery | `classify_artifact_publication_recovery_v1` | `src/publication.rs` | implemented |
| govern bounded iteration candidate state | `IterationCandidateV1::transition` | `src/iteration.rs` | implemented |
| record/replay iteration evidence | `IterationLedgerV1::transition`, `from_snapshot` | `src/iteration_ledger.rs` | implemented |
| prepare durable writes before final path creation | `prepare_registry_snapshot_v1`, `prepare_candidate_payload_v1`, `prepare_registry_head_witness_v1` | `src/storage.rs` | implemented |
| root create-only paths under host namespace | `CreateOnlyArtifactFile::create_in` | `src/storage.rs` | implemented |
| inspect bounded owner service status | `inspect_artifact_owner_status_v1` | `src/service.rs` | implemented |
| inspect/cleanup proven storage orphan | `ArtifactStorageAdminV1::{inspect,cleanup_zero_length_orphan}` | `src/storage_hygiene.rs` | implemented |

`LearningArtifactManifestV2` explicitly binds:

- every source dataset digest;
- additional lineage evidence digests;
- multiple predecessor IDs and an optional rollback predecessor;
- payload digest and exact byte count;
- training code, runtime tuple and device profile;
- objective class, schema, normalization and compatibility profiles;
- producer identity, creation time and expiry.

Dataset-derived and dataset-independent artifacts are different provenance
modes. A dataset-derived manifest without a source dataset, or a
dataset-independent manifest containing one, fails.

`DatasetWithdrawalRegistry` is append-only, digest-chained and replayable from a
snapshot. It closes the snapshot-local invalidation gap by rejecting every later
manifest that references a previously withdrawn dataset. Exact notice retries
are idempotent; changed semantics under a reused notice ID conflict.
V3 admission never binds only the raw head: `WithdrawalAuthorityDomainV1`
domain-separates the registry identity, host-authenticated scope digest,
withdrawal authority and nonzero authority epoch before the raw frontier is admitted.

`RegistryHeadWitnessV1` binds registry identity, generation, predecessor head,
authority epoch, signer and expiry. Validation rejects generation rollback,
epoch rollback, predecessor mismatch and expired evidence. It validates the
bound fields but does not verify a cryptographic signature; the host must do
that before constructing the witness.

## Lifecycle ownership

The V2 evidence state machine is:

```text
proposed -> trained -> evaluated -> shadow -> canary
         -> operator_accepted -> selected -> retired
eligible states -> revoked
bounded early states -> quarantined
```

A producer may report training completion but cannot issue its own evaluation,
acceptance, selection, quarantine or revocation decision. State skips reject.
The selector and route owner remain separate external authorities.

## Lifecycle and control-state durability

Historical lifecycle recovery validates actor evidence at the immutable event
`occurred_at`; process restart time is not allowed to invalidate an event that
was valid when appended. New mutations still require credentials valid at the
current append time.

`control_storage.rs` persists canonical create-only `HEPTAW01` withdrawal and
`HEPTAL02` lifecycle snapshots with independent receipts. Its domain-aware
withdrawal wrappers derive the binding from registry/scope/authority/epoch and
reject cross-domain reopen. The native owner can therefore prove real-file persist/reopen/replay without claiming latest-generation
discovery, directory durability or production placement.

## Publication saga and host obligations

The product host must bind one durable saga:

1. reserve a create-only artifact identity;
2. write, synchronize and verify payload bytes;
3. check the exact domain-separated withdrawal registry frontier;
4. construct the V1 successor registry and common-field bridge for the admitted V2 manifest;
5. validate `ArtifactPublicationTransactionV1` against exact predecessor/candidate heads and the next head witness while holding the host writer fence;
6. durably publish payload and registry snapshot;
7. publish an independently authenticated head witness;
8. acknowledge the producer only after the witness is durable.

After a crash, `classify_artifact_publication_recovery_v1` accepts only the
authenticated predecessor head as `NotCommitted` or the exact candidate head
at the transaction generation as `Committed`; any other head is a conflict.

The host also owns trusted directory traversal, containing-directory durability,
latest witness discovery, writer fencing, retention, backup
restore and actual process loading. The native head-witness file now provides a
bounded create-only distribution channel with independent receipt and
requirement revalidation; it does not discover the latest file or prove that a
self-consistent stale snapshot is current.

Rollback requires a current authorized transition to a complete compatible
predecessor under the latest withdrawal and revocation frontier. An old backup
marker cannot reactivate a revoked candidate.

## Qualification mapping

Focused tests live in:

- `src/registry_tests.rs`;
- `src/storage_tests.rs` and storage budget/lock tests;
- `src/pinned_tests.rs`;
- `src/dataset_revocation_tests.rs`;
- `src/closure_v2_tests.rs`;
- inline tests in `src/admission_v3.rs`, `src/lifecycle_journal.rs`,
  `src/control_storage.rs`, `src/publication.rs`, `src/storage_hygiene.rs`,
  `src/iteration.rs` and `src/iteration_ledger.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.
