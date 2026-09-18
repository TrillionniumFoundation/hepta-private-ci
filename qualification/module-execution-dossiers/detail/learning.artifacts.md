# learning.artifacts: implementation design

Parent: `docs/modules/learning.artifacts/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: create-only storage, complete V2 manifest, scoped persistent dataset withdrawal, digest-bound V3 publication staging, durable withdrawal/lifecycle sidecars, head anti-rollback and governed iteration/lifecycle source candidates implemented; current exact-head and synthetic-merge CI determine source qualification, while product loading and independent selection remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-artifacts`.
Packages: `ART-1-LEARNING-ARTIFACT-REGISTRY`, `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve the stable V1 registry and create-only storage APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`write_candidate_payload(file, registry, artifact, bytes) -> Digest32`; `inspect_orphan_candidate(file, retained_digests) -> OrphanInspection`; `write_registry_snapshot(file, registry, binding) -> RegistrySnapshotReceipt`; `write_registry_head_witness(file, witness, requirement, binding) -> RegistryHeadWitnessReceipt`; `read_registry_head_witness(file, receipt, requirement) -> RegistryHeadWitnessV1`; `load_pinned_candidate(snapshot, payload, pin) -> LoadedPinnedCandidate`; `validate_artifact_manifest_v2(manifest, now) -> ValidatedArtifactManifestV2`; `DatasetWithdrawalRegistry::new_scoped(binding)`; `DatasetWithdrawalRegistry::append(notice) -> DatasetWithdrawalReceiptV1`; `DatasetWithdrawalRegistry::admit_manifest(manifest, now) -> ValidatedArtifactManifestV2`; `admit_manifest_at_withdrawal_head_v3(...) -> WithdrawalBoundArtifactAdmissionV3`; `prepare_artifact_publication_v3(...) -> PreparedArtifactPublicationV3`; `revalidate_artifact_publication_v3(...) -> RevalidatedArtifactPublicationV3` (the revalidated token alone exposes durable snapshot state/binding); `write/read_withdrawal_registry_snapshot`; `ArtifactLifecycleJournalV2::append/from_snapshot`; `write/read_lifecycle_journal_snapshot`; `validate_registry_head_witness(witness, requirement) -> RegistryHeadReceiptV1`; `validate_iteration_transition` and `IterationLedgerV1::transition`; `inspect_artifact_admin_state(registry, withdrawal, lifecycle) -> ArtifactAdminSnapshotV1`.

Candidate registration is not selection. A successful read is not execution or activation. The supervisor or separately authorized selector consumes independent selection evidence; the artifact owner never installs itself.

## 3. State records and transaction design

Own create-only `learning_artifact_registry` and `operator_sensor_core_registry`. The stable V1 registry and payload encoding remain readable. `LearningArtifactManifestV2` explicitly binds payload digest/length, every source dataset, complete lineage, multiple predecessors, rollback predecessor, training code, runtime, device, objective class, schema, normalization, compatibility, producer, creation time and expiry.

`DatasetWithdrawalRegistry` is a separate append-only digest chain. V3 admission requires a `WithdrawalRegistryBindingV1` containing a registry identity and scope digest, so another registry with an equal head cannot be substituted. `HEPTAW01` create-only snapshots persist that binding and exact history. The registry blocks every future manifest that references a withdrawn dataset, closing the gap left by a snapshot-local invalidation batch. Exact notice retries are idempotent; changed semantics under a reused notice ID conflict.

`RegistryHeadWitnessV1` binds registry identity, generation, predecessor head, authority epoch, signer, signing key and validity window. Generation rollback, authority-epoch rollback, predecessor mismatch and expiry fail. A product host must authenticate the witness signature before constructing the typed value.

## 4. Deterministic algorithm and scheduling

Validate scope, size and complete lineage; check the scoped persistent withdrawal frontier; create immutable bytes with conflict-on-different-content identity; synchronize; issue a V3 admission at the exact withdrawal head; stage a canonical V1 registry event against the exact predecessor; bind admission, withdrawal scope/head, event and resulting registry head into the publication transaction digest; revalidate both mutable frontiers under the host writer fence; publish the registry snapshot using the transaction digest as its binding; obtain an independently authenticated head witness; and acknowledge only after the witness is durable.

New runs load an exact selected tuple against the current head and withdrawal frontier; the old run retains its snapshot. Restore and rollback always overlay current revocations and withdrawals before exposing artifacts. Payload and registry publication form a bounded saga: bytes synchronized without a registry event are an orphan candidate, never selected state.

The lifecycle evidence state machine is `proposed -> trained -> evaluated -> shadow -> canary -> operator_accepted -> selected -> retired`, with bounded quarantine and revocation edges. A producer cannot issue its own evaluation, acceptance, selection, quarantine or revocation decision, and mandatory states cannot be skipped. `HEPTAL02` snapshots reopen by replaying historical actor evidence at each event occurrence time; credential expiry after a valid historical write cannot make the journal unrecoverable, while the same expired credential still cannot authorize a new write.

## 5. Capacity and performance profile

Payload bytes remain bounded by the native create-only storage profile. V2 source datasets are bounded to 64, lineage digests to 1024 and predecessor IDs to 64 per manifest. All crate-owned durable append-only histories reject growth beyond the shared 4096-record snapshot ceiling. Large lineage graphs use indexed traversal and reject incomplete eligibility proofs.

Measure put/fsync, containing-directory synchronization, witness publication, cold read/hash, registry reopen, withdrawal lookup, revoke propagation, backup replay and orphan reconciliation. Source limits are not target-host measurements.

## 6. Concrete verification cases

- ART-01: create-only ID reuse with different bytes conflicts; identical retry is idempotent.
- ART-02: crash after bytes sync but before publication yields an orphan candidate, not selected state; transaction-bound snapshot reopen and lexical create-only leaf containment are regression-mapped.
- ART-03: corrupt/incomplete/mixed-generation durable state is refused by a new loading process; withdrawal and lifecycle sidecars prove exact reopen, including historical actor expiry.
- ART-04: rollback/admission under a revoked, withdrawn, incompatible or cross-scope frontier fails safely; the V1 bridge preserves single-dataset revocation lookup and rejects lossy multi-dataset/multi-predecessor projection.

Every case is mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`. Additional V2 tests cover complete manifest normalization, persistent withdrawal replay, anti-rollback witnesses and lifecycle self-decision/state-skip rejection.

## 7. Integration, rollback and capability ceiling

C1 proves durable round-trip, independent decision, new-process changed behavior and exact compatible rollback separately. Passing a same-process fixture is not production deployment. Deletion may require full retraining or revocation when selective unlearning is unsupported.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

`RevalidatingCandidate::with_current` guards cached consumption with a monotonic current registry prefix and exact lineage eligibility. Any failed refresh closes the consumer. Tests cover revocation, old-backup resurrection, longer forks, changed scope and corrupted views; authenticated current-view discovery remains a host responsibility.

- **Implemented entrypoints:** `load_pinned_candidate` in [codex-rs/hepta-learning-artifacts/src/pinned.rs](../../../codex-rs/hepta-learning-artifacts/src/pinned.rs); create-only payload/registry/head-witness APIs plus `CreateOnlyArtifactFile::create_in_directory` in [codex-rs/hepta-learning-artifacts/src/storage.rs](../../../codex-rs/hepta-learning-artifacts/src/storage.rs); scoped withdrawal-aware V3 admission in [codex-rs/hepta-learning-artifacts/src/admission_v3.rs](../../../codex-rs/hepta-learning-artifacts/src/admission_v3.rs); digest-bound staging/revalidation in [codex-rs/hepta-learning-artifacts/src/publication.rs](../../../codex-rs/hepta-learning-artifacts/src/publication.rs); create-only withdrawal/lifecycle sidecars in [codex-rs/hepta-learning-artifacts/src/aux_storage.rs](../../../codex-rs/hepta-learning-artifacts/src/aux_storage.rs); read-only orphan inspection in `storage.rs`; DENY_ALL operational state inspection in `admin.rs`; lifecycle journal and governed iteration/iteration-ledger APIs in their native modules.
- **State and recovery:** Create-only file payloads and registry snapshots preserve exact manifest/digest identity. Withdrawal and lifecycle sidecars carry independent receipts and semantic replay; historical lifecycle credentials are evaluated at event time. Pinned loading checks the full supplied manifest before bytes return; none of these readers can make an old supplied head current.
- **Source tests:** [codex-rs/hepta-learning-artifacts/src/pinned_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/pinned_tests.rs), [codex-rs/hepta-learning-artifacts/src/storage_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/storage_tests.rs), [codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs), plus unit tests in `admission_v3.rs`, `lifecycle_journal.rs`, `publication.rs`, `aux_storage.rs`, `iteration.rs` and `iteration_ledger.rs`. Lane E traceability maps the new durability regressions into ART-02/03/04. These are test identities until exact-head CI executes them.
- **Implementation and operating references:** [codex-rs/hepta-learning-artifacts/STORAGE.md](../../../codex-rs/hepta-learning-artifacts/STORAGE.md), [codex-rs/hepta-learning-artifacts/PINNED_LOAD.md](../../../codex-rs/hepta-learning-artifacts/PINNED_LOAD.md).
- **Remaining work:** Supply trusted latest-head discovery/signature distribution, product-host writer composition, trusted ancestor-directory containment and containing-directory durability, and independently selected product loading. The stable V1 publication bridge deliberately rejects V2 multi-predecessor and multi-dataset manifests rather than dropping semantics; complete support for those shapes requires a versioned durable V2+ registry format. The native channel validates an independently authenticated witness and current requirement but does not discover the newest file or grant selection/activation.

## 9. Native closure and remaining evidence

Repository-controlled source coverage is checked by `../../../scripts/hepta-lane-e-closure.py`; exact-head and ordered-parent synthetic-merge execution are defined in `.github/workflows/hepta-lane-e-gap-closure.yml`. The workflow compiles all targets, runs owner and cross-crate tests, strict Clippy and rustfmt.

The repository cannot self-provision a trusted filesystem namespace, signing key or newest-head distribution service; cannot prove containing-directory durability on every target; cannot produce external-cache or physical-erasure evidence; and cannot issue independent selection, product process loading, canary, operator acceptance, promotion or release. Those exact-candidate gates remain external.
