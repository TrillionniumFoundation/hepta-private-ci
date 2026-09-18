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
| bind withdrawal registry namespace | `DatasetWithdrawalRegistry::new_scoped`, `DatasetWithdrawalDomainV1::binding_digest` | `src/closure_v2.rs` | implemented |
| bind V3 admission to withdrawal domain + head | `admit_manifest_at_withdrawal_head_v3`, `validate_artifact_publication_v3` | `src/admission_v3.rs` | implemented |
| append/replay lifecycle journal | `ArtifactLifecycleJournalV2::append`, `ArtifactLifecycleJournalV2::from_snapshot` | `src/lifecycle_journal.rs` | implemented |
| persist/reopen withdrawal frontier | `write_dataset_withdrawal_snapshot`, `read_dataset_withdrawal_snapshot` | `src/storage.rs` | implemented |
| persist/reopen lifecycle journal | `write_lifecycle_journal_snapshot`, `read_lifecycle_journal_snapshot` | `src/storage.rs` | implemented |
| project V3 admission into V1 registry event | `artifact_registry_event_for_admission_v3` | `src/publication.rs` | implemented |
| prepare/recover publication transaction | `prepare_artifact_publication_v1`, `recover_artifact_publication_v1` | `src/publication.rs` | implemented |
| governed iteration transition | `validate_iteration_transition` | `src/iteration.rs` | implemented |
| governed iteration evidence ledger | `IterationLedgerV1::append_candidate`, `IterationLedgerV1::transition`, `IterationLedgerV1::from_snapshot` | `src/iteration_ledger.rs` | implemented |
| contained create/orphan reconciliation | `CreateOnlyArtifactFile::create_in`, `remove_zero_length_orphan_in` | `src/storage.rs` | implemented |

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
snapshot. A production V3 registry is scoped by `DatasetWithdrawalDomainV1`;
the domain digest participates in the chain and admission receipt, so identical
heads from different registry/scope/authority domains are not interchangeable.
It closes the snapshot-local invalidation gap by rejecting every later manifest
that references a previously withdrawn dataset. Exact notice retries
are idempotent; changed semantics under a reused notice ID conflict.

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

## Publication saga and host obligations

The product host must bind one durable saga:

1. reserve a create-only artifact identity;
2. write, synchronize and verify payload bytes;
3. check the current withdrawal registry;
4. append a manifest event against an exact predecessor head;
5. durably publish the registry snapshot;
6. publish an independently authenticated head witness;
7. acknowledge the producer only after the witness is durable.

The host also owns trusted directory traversal, containing-directory durability,
latest witness discovery, writer fencing, orphan collection, retention, backup
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
- `src/storage_tests.rs` and storage budget tests;
- `src/pinned_tests.rs`;
- `src/dataset_revocation_tests.rs`;
- `src/closure_v2_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.


## Current source blockers

Source implementation does not close every qualification boundary. Historical
lifecycle replay is now separated from current mutation authorization: restart
validates recorded actor evidence against the event-time credential window, while
a new append still requires current authorization. Product composition must still
supply the authenticated writer fence, current-witness service, parent-directory
durability and target-OS containment/power-loss qualification. These remain
explicit boundaries rather than inferred runtime authority.
