# learning.artifacts: implementation design

Parent: `docs/modules/learning.artifacts/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.

Status: native source candidate implements the immutable V1 registry, complete V2
manifest validation, persistent withdrawal authority, V3 withdrawal-domain/head
binding, lifecycle journal, durable withdrawal/lifecycle snapshots, pinned loading,
publication commit contract, governed iteration ledger and storage hygiene. Current
exact-head plus ordered-parent synthetic-merge CI determine source qualification.
Product writer composition, activation, independent acceptance, promotion and
release remain separate.

## 1. Source and work envelope

Root: `codex-rs/hepta-learning-artifacts`.

Primary work packages:

- `ART-1-LEARNING-ARTIFACT-REGISTRY`;
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`.

Concrete native mappings are maintained in
`../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md` and
`../../../docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json`.

The stable V1 registry remains compatible. V2/V3 and the durable authority/
publication APIs are additive owner-native surfaces. No source in this crate may
be interpreted as deployment, selection or release authority.

## 2. Public closure operations

Key native entrypoints include:

- `ArtifactRegistry::append` / `ArtifactRegistry::from_snapshot`;
- `validate_artifact_manifest_v2`;
- `DatasetWithdrawalRegistry::append` / `from_snapshot`;
- `admit_manifest_at_withdrawal_head_v3`;
- `validate_artifact_publication_v3`;
- `ArtifactLifecycleJournalV2::append` / `from_snapshot`;
- `write_registry_snapshot` / `read_registry_snapshot`;
- `write_withdrawal_registry_snapshot` / `read_withdrawal_registry_snapshot`;
- `write_lifecycle_journal_snapshot` / `read_lifecycle_journal_snapshot`;
- `prepare_artifact_publication_v1`;
- `ArtifactPublicationTransactionV1::seal`;
- `verify_artifact_publication_commit_v1`;
- `load_pinned_candidate`;
- `prepare_dataset_revocation`;
- `IterationLedgerV1`;
- `ArtifactStorageAdminV1`.

All admission/lifecycle/publication receipts are deny-all with respect to runtime,
selection, promotion and release.

## 3. V1 registry and V2 manifest projection

The V1 artifact registry is an immutable append-only event chain. Lineage
eligibility is transitive: quarantine or revocation of an ancestor invalidates a
descendant without rewriting its record.

`LearningArtifactManifestV2` independently binds payload bytes/length, every source
dataset, lineage digests, predecessor/rollback identities, training code, runtime,
device, objective class, schema, normalization, compatibility, producer and
validity window.

The V1 manifest is a stable durable projection and is not a lossless replacement
for V2. Publication planning requires exact equality for fields representable in
both versions and separately binds the V2 admission digest for the richer facts.

## 4. Persistent withdrawal authority and V3 admission

`DatasetWithdrawalRegistry` is an append-only digest chain of source withdrawal
notices. It persists dataset tombstones and blocks future V2 manifests referencing
a withdrawn dataset.

A frontier digest is not a namespace. `WithdrawalAuthorityDomainV1` therefore
binds registry ID, scope digest, authority ID and authority epoch. V3 admission
binds the validated V2 manifest to both the exact current withdrawal head and that
domain digest.

Publication revalidation must observe the same current domain/head. Cross-domain
replay is rejected even when two independent registries share the zero head.

The host authenticates authority signatures/credentials before constructing the
typed domain/notice values.

## 5. Lifecycle state and historical recovery

`ArtifactLifecycleJournalV2` binds expected predecessor head, artifact state,
producer, actor credential evidence, role, event identity and digest chain.
Mandatory progression/role separation prevents producer self-evaluation and other
unsupported state skips.

Fresh mutations require actor evidence valid at current `now`. Historical snapshot
or durable-file reconstruction validates each persisted record at immutable
`event.occurred_at`. Normal later credential expiry therefore cannot make valid
history unrecoverable; the same expired actor still cannot append a new event.

## 6. Durable authority snapshots

The artifact registry uses existing create-only `HEPTAR01` snapshots and independent
`RegistrySnapshotReceipt` values.

Withdrawal and lifecycle state use `durable_authority.rs`:

- `HPTWDR01`: domain-bound withdrawal registry snapshot;
- `HPTLCJ02`: lifecycle journal snapshot.

Both are create-only, file-locked, length/digest checked, bounded to 64 MiB and at
most 1,000,000 records, and semantically replayed before acceptance. The
independently retained `AuthoritySnapshotReceiptV1` binds kind, state binding,
semantic head, complete file digest, record count and length.

A valid file is not proof that it is the current product generation.

## 7. Publication transaction design

`prepare_artifact_publication_v1` binds one exact generation to:

- current V3 admission;
- compatible/eligible V1 artifact projection;
- registry binding/head/count;
- withdrawal domain/head/count;
- lifecycle binding/head/count;
- publication scope, generation and predecessor publication digest.

`ArtifactPublicationTransactionV1` accepts only matching durable receipts for the
registry, withdrawal and lifecycle state files. `seal()` fails while any planned
component is missing. `ArtifactPublicationCommitV1` then binds the plan and all
three file digests/heads/counts/lengths.

This is a fail-closed host contract, not a cross-filesystem atomicity claim. Under
one exclusive product writer fence the host must persist/fsync those files, seal
and persist/fsync the publication commit, and only then atomically change its
independently authenticated current-generation pointer.

A crash before pointer publication can leave orphan immutable files, but cannot
produce a sealed/current partial generation.

## 8. Governed iteration bookkeeping

`IterationEnvelopeV1` binds base commit/tree, objective/grammar and hard budgets for
files, diff bytes, candidate count and parallel sandboxes.

`IterationCandidateV1` records generator, semantic diff, test plan, rollback and
predecessor identity. The monotonic state machine records stages through evaluation,
review and externally governed decision states.

`IterationLedgerV1` stores typed external evidence and rejects generator-owned
evidence at independently governed stages. Evidence IDs are single-use and snapshot
state is reconstructed only by replaying events. The ledger does not execute code,
choose a winner or grant selection/promotion/release authority.

## 9. Storage hygiene and orphan reconciliation

`ArtifactStorageAdminV1` operates only under an enrolled canonical root. It rejects
absolute paths, `.`/`..`, root/prefix components and canonical parent escape.

Cleanup is intentionally conservative: only a regular, non-symlink, zero-length
file can be removed; the parent directory is synced afterward. Non-empty files,
directories, symlinks and special files are never removed by this API.

The host still owns protection against hostile concurrent replacement of enrolled
ancestor directories, filesystem permissions and target-specific durability.

## 10. Dataset revocation

Persistent withdrawal and existing-artifact V1 revocation are complementary.

`DatasetWithdrawalRegistry` denies new V2 admissions. `prepare_dataset_revocation`
stages revoke events on a private V1 registry clone for already registered direct
targets; lineage eligibility propagates ancestor revocation to descendants.

The preparation never mutates the caller's current registry. Product completion
requires the staged state to be included in a fully durable publication generation
before source/outbox acknowledgement.

## 11. Verification cases

Key closure cases include:

- `art_05_cross_domain_zero_head_is_rejected`;
- `art_05_withdrawal_race_invalidates_admission`;
- `art_06_historical_replay_survives_actor_expiry_but_new_append_does_not`;
- `art_07_withdrawal_registry_durable_roundtrip_rebuilds_exact_head`;
- `art_07_lifecycle_durable_roundtrip_survives_actor_expiry`;
- `art_08_publication_transaction_is_unsealable_after_partial_durability`;
- `art_08_publication_commit_binds_all_durable_receipts`;
- `art_09_storage_admin_rejects_parent_escape`;
- `art_09_storage_admin_removes_only_zero_length_orphan`;
- existing registry/storage/pinned/V2/revocation suites;
- iteration/iteration-ledger transition, independence and exact replay tests.

Cross-crate composition remains covered by `hepta-shadow-qualification` Lane E
tests.

## 12. Exact-head and merge qualification

Repository-controlled closure uses `scripts/hepta-lane-e-closure.py` and
`.github/workflows/hepta-lane-e-gap-closure.yml`.

`rust-closure` qualifies the exact source candidate. `synthetic-merge` materializes
an ordered base+PR-source merge and therefore runs only for `pull_request`, where an
exact base SHA exists. A `main` push still runs exact-head closure without trying to
read a nonexistent `pull_request.base.sha`.

The workflow requires closed-world verification, locked all-target compilation,
owner tests, cross-crate/cross-language closure, strict Clippy, rustfmt and clean
source/index state.

## 13. Remaining host/product evidence

Repository source does not establish:

- a named production writer/caller;
- signing-key/credential authentication;
- product writer-fence issuance;
- protected storage namespace credentials;
- durable host publication-commit file/current-pointer service;
- target-filesystem power-loss qualification;
- independent semantic/security acceptance;
- runtime activation, canary, operator acceptance, promotion or release.

The correct current claim is **native source implemented; exact candidate
qualification pending until CI is green; product composition and release remain
external**.
