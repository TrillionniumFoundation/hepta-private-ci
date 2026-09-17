# `learning.artifacts` native implementation mapping

This file maps the current immutable artifact, withdrawal, lifecycle, publication,
iteration and storage-hardening design to concrete Rust symbols. None of these
symbols grants selection, activation, promotion or release authority.

## State ownership and compatibility

The stable V1 `ArtifactRegistry` remains the durable artifact-registry projection.
The additive V2/V3 layers preserve compatibility while making complete provenance,
withdrawal frontier/domain and publication evidence independently inspectable.

Owned logical domains are:

- immutable candidate bytes and byte identity;
- append-only artifact registry and lineage;
- persistent dataset-withdrawal facts;
- artifact lifecycle evidence;
- bounded governed-iteration bookkeeping;
- create-only durable state receipts;
- fail-closed publication-generation commitment.

The crate does not own signing keys, a production selector, a process deployment
route or the product's authenticated current-generation pointer.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| register/quarantine/revoke V1 candidate | `ArtifactRegistry::append` | `src/registry.rs` | implemented |
| replay exact V1 registry snapshot | `ArtifactRegistry::from_snapshot` | `src/registry.rs` | implemented |
| create immutable payload/snapshot | `CreateOnlyArtifactFile`, `write_candidate_payload`, `write_registry_snapshot` | `src/storage.rs` | implemented |
| distribute/reload current head witness | `write_registry_head_witness`, `read_registry_head_witness` | `src/storage.rs` | implemented |
| read exact pinned candidate | `load_pinned_candidate` | `src/pinned.rs` | implemented |
| prepare existing-artifact dataset revocation | `prepare_dataset_revocation` | `src/dataset_revocation.rs` | implemented |
| validate complete V2 manifest | `validate_artifact_manifest_v2` | `src/closure_v2.rs` | implemented |
| append/replay dataset withdrawal frontier | `DatasetWithdrawalRegistry::append`, `DatasetWithdrawalRegistry::from_snapshot` | `src/closure_v2.rs` | implemented |
| validate registry head/anti-rollback evidence | `validate_registry_head_witness` | `src/closure_v2.rs` | implemented |
| bind V3 admission to withdrawal domain + head | `admit_manifest_at_withdrawal_head_v3`, `validate_artifact_publication_v3` | `src/admission_v3.rs` | implemented |
| append/replay lifecycle journal | `ArtifactLifecycleJournalV2::append`, `ArtifactLifecycleJournalV2::from_snapshot` | `src/lifecycle_journal.rs` | implemented |
| persist/reopen withdrawal authority | `write_withdrawal_registry_snapshot`, `read_withdrawal_registry_snapshot` | `src/durable_authority.rs` | implemented |
| persist/reopen lifecycle authority | `write_lifecycle_journal_snapshot`, `read_lifecycle_journal_snapshot` | `src/durable_authority.rs` | implemented |
| bind V2 admission to exact durable generation | `prepare_artifact_publication_v1`, `ArtifactPublicationTransactionV1::seal` | `src/publication.rs` | implemented |
| verify sealed publication commitment | `verify_artifact_publication_commit_v1` | `src/publication.rs` | implemented |
| validate bounded iteration transition | `validate_iteration_transition` | `src/iteration.rs` | implemented |
| record/replay external iteration evidence | `IterationLedgerV1` | `src/iteration_ledger.rs` | implemented |
| root-confined storage administration | `ArtifactStorageAdminV1` | `src/storage_hygiene.rs` | implemented |

## V2/V3 artifact and withdrawal binding

`LearningArtifactManifestV2` explicitly binds all source dataset digests, lineage
evidence, predecessor/rollback identities, payload digest/size, training code,
runtime/device tuple, objective/schema/normalization/compatibility profiles,
producer identity and validity window.

`DatasetWithdrawalRegistry` is append-only, digest-chained and replayable. It is
the persistent tombstone authority used to reject future manifests referencing a
withdrawn dataset.

`WithdrawalAuthorityDomainV1` adds explicit registry, scope, authority identity and
authority epoch. `WithdrawalBoundArtifactAdmissionV3` hashes that domain together
with the exact current withdrawal head and validated V2 manifest. Equal frontier
digests from different authority domains are not interchangeable.

## Lifecycle ownership and historical replay

The lifecycle state machine is externally governed. Actor roles constrain which
state transitions may be recorded; the producer cannot self-issue independent
evaluation/selection/revocation decisions.

Fresh append checks actor validity at the current `now`. Snapshot/durable recovery
checks an immutable historical record at `event.occurred_at`. Thus a credential
that expires later blocks new mutation but does not make previously valid history
unrecoverable.

## Durable authority files

`durable_authority.rs` provides create-only, bounded files and independent receipts
for withdrawal (`HPTWDR01`) and lifecycle (`HPTLCJ02`) state. Readback checks exact
file digest/length and replays the semantic state before accepting the expected
head.

These files are immutable generation components; their existence is not current
publication authority.

## Publication contract and host obligations

`prepare_artifact_publication_v1` joins:

- current V3 admission;
- the compatible/eligible V1 registry projection;
- exact registry snapshot head/count/binding;
- exact withdrawal domain/head/count;
- exact lifecycle binding/head/count;
- publication scope, generation and predecessor publication digest.

`ArtifactPublicationTransactionV1` accepts exact durable receipts for the V1
registry, withdrawal registry and lifecycle journal. It cannot seal until all three
are durable. `ArtifactPublicationCommitV1` then binds their file digests and semantic
heads into one commit digest.

The product host must persist/fsync that commit and only afterward atomically
change its independently authenticated current-generation pointer. The host also
owns writer fencing, parent-directory durability and crash reconciliation.

## Governed iteration

`IterationEnvelopeV1` imposes explicit budgets for files, diff bytes, candidates
and parallel sandboxes. `IterationCandidateV1` records exact rollback/diff/test
identities. `IterationLedgerV1` records typed evidence and rejects generator-owned
evidence for independently governed stages. Snapshot state is reconstructed only
by replaying evidence events.

The ledger does not execute a sandbox or grant the decision represented by a
recorded `Selected`, `Promoted` or `Released` state.

## Storage hygiene

`ArtifactStorageAdminV1` enrolls a canonical root, rejects absolute/parent/path-
prefix escape, canonicalizes the existing parent and requires it to remain under
the enrolled root.

Orphan cleanup is deliberately narrow: only regular, non-symlink, zero-length
files may be removed, followed by parent-directory sync. The host must still
protect enrolled ancestors from concurrent hostile replacement.

## Qualification mapping

Focused coverage exists in the source modules plus the existing registry/storage,
pinned-load, closure V2 and dataset-revocation test suites. Key new cases include:

- `art_05_cross_domain_zero_head_is_rejected`;
- `art_06_historical_replay_survives_actor_expiry_but_new_append_does_not`;
- `art_07_withdrawal_registry_durable_roundtrip_rebuilds_exact_head`;
- `art_07_lifecycle_durable_roundtrip_survives_actor_expiry`;
- `art_08_publication_transaction_is_unsealable_after_partial_durability`;
- `art_08_publication_commit_binds_all_durable_receipts`;
- `art_09_storage_admin_rejects_parent_escape`;
- `art_09_storage_admin_removes_only_zero_length_orphan`.

Cross-crate composition remains exercised by `hepta-shadow-qualification`. Exact
candidate compilation/tests, strict lint, formatting and actual-base synthetic
merge are still required before source closure is claimed.
