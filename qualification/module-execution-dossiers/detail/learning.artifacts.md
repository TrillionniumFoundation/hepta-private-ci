# learning.artifacts: implementation design

Parent: `docs/modules/learning.artifacts/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: create-only storage, complete V2 manifest, scoped persistent dataset withdrawal, V3 withdrawal-bound admission, crash-recoverable publication transaction, durable withdrawal/lifecycle replay, head anti-rollback, lifecycle and governed-iteration source candidates implemented; current exact-head and synthetic-merge CI determine source qualification, while product loading and independent selection remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-artifacts`.
Packages: `ART-1-LEARNING-ARTIFACT-REGISTRY`, `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve the stable V1 registry and create-only storage APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`write_candidate_payload(file, registry, artifact, bytes) -> Digest32`; `write_registry_snapshot(file, registry, binding) -> RegistrySnapshotReceipt`; `write_registry_head_witness(file, witness, requirement, binding) -> RegistryHeadWitnessReceipt`; `read_registry_head_witness(file, receipt, requirement) -> RegistryHeadWitnessV1`; `load_pinned_candidate(snapshot, payload, pin) -> LoadedPinnedCandidate`; `validate_artifact_manifest_v2(manifest, now) -> ValidatedArtifactManifestV2`; `DatasetWithdrawalRegistry::new_scoped(domain)`; `DatasetWithdrawalRegistry::append(notice) -> DatasetWithdrawalReceiptV1`; `admit_manifest_at_withdrawal_head_v3(...)`; `artifact_registry_event_for_admission_v3(...)`; `prepare_artifact_publication_v1(...)`; `recover_artifact_publication_v1(...)`; `write_dataset_withdrawal_snapshot` / `read_dataset_withdrawal_snapshot`; `write_lifecycle_journal_snapshot` / `read_lifecycle_journal_snapshot`; `ArtifactLifecycleJournalV2::append`; `IterationLedgerV1::{append_candidate, transition, from_snapshot}`; `CreateOnlyArtifactFile::create_in`; `remove_zero_length_orphan_in`; `validate_registry_head_witness(witness, requirement) -> RegistryHeadReceiptV1`; `validate_artifact_lifecycle_transition(producer, event) -> Digest32`.

Candidate registration is not selection. A successful read is not execution or activation. The supervisor or separately authorized selector consumes independent selection evidence; the artifact owner never installs itself.

## 3. State records and transaction design

Own create-only `learning_artifact_registry` and `operator_sensor_core_registry`. The stable V1 registry and payload encoding remain readable. `LearningArtifactManifestV2` explicitly binds payload digest/length, every source dataset, complete lineage, multiple predecessors, rollback predecessor, training code, runtime, device, objective class, schema, normalization, compatibility, producer, creation time and expiry.

`DatasetWithdrawalRegistry` is a separate append-only digest chain. Production V3 use is scoped by `DatasetWithdrawalDomainV1`, binding registry identity, host-authenticated scope and authority domain into the chain. It persists dataset tombstones and blocks every future manifest that references a withdrawn dataset, closing the gap left by a snapshot-local invalidation batch. Exact notice retries are idempotent; changed semantics under a reused notice ID conflict. Equal head bytes from a different scope are not publication authority.

`RegistryHeadWitnessV1` binds registry identity, generation, predecessor head, authority epoch, signer, signing key and validity window. Generation rollback, authority-epoch rollback, predecessor mismatch and expiry fail. A product host must authenticate the witness signature before constructing the typed value.

## 4. Deterministic algorithm and scheduling

Validate scope, size and complete lineage; check the scoped persistent withdrawal frontier; create immutable bytes with conflict-on-different-content identity; synchronize; project the admitted V3 manifest into the unique V1 `Register` event; append it against an exact predecessor; verify the append event/sequence/chain receipt; derive the publication-contract binding; publish the registry snapshot with that binding; obtain an independently authenticated head witness whose durable receipt carries the same binding; and acknowledge only after the witness is durable. For a dataset-derived artifact the stable V1 projection accepts exactly one source dataset and preserves that dataset digest as `support_digest`, so later dataset revocation can still discover the published artifact. The V1 event ID remains the exact publication operation ID. Because stable V1 has only one support slot and one runtime predecessor edge, multi-dataset and multi-predecessor V2 manifests fail closed rather than losing revocation or eligibility edges. `ArtifactPublicationTransactionV1` binds the complete V3 admission/frontier and exact V1 append into `snapshot_binding`, represents the durable phases as `Prepared -> SnapshotDurable -> WitnessDurable -> Acknowledged`, and on restart accepts receipts only when an immutable contract (or authenticated deterministic reconstruction) recomputes that exact binding.

New runs load an exact selected tuple against the current head and withdrawal frontier; the old run retains its snapshot. Restore and rollback always overlay current revocations and withdrawals before exposing artifacts. Payload and registry publication form a bounded saga: bytes synchronized without a registry event are an orphan candidate, never selected state.

The lifecycle evidence state machine is `proposed -> trained -> evaluated -> shadow -> canary -> operator_accepted -> selected -> retired`, with bounded quarantine and revocation edges. A producer cannot issue its own evaluation, acceptance, selection, quarantine or revocation decision, and mandatory states cannot be skipped.

## 5. Capacity and performance profile

Payload bytes remain bounded by the native create-only storage profile. V2 source datasets are bounded to 64, lineage digests to 1024 and predecessor IDs to 64 per manifest. Artifact, withdrawal and lifecycle owner histories share the supported 4096-record durable ceiling, preventing accepted in-memory state from exceeding the canonical snapshot writer solely by record count. Large lineage graphs use indexed traversal and reject incomplete eligibility proofs.

Measure put/fsync, containing-directory synchronization, witness publication, cold read/hash, registry reopen, withdrawal lookup, revoke propagation, backup replay and orphan reconciliation. Source limits are not target-host measurements.

## 6. Concrete verification cases

- ART-01: create-only ID reuse with different bytes conflicts; identical retry is idempotent.
- ART-02: crash after bytes sync but before registry publication yields an orphan candidate, not a selected artifact.
- ART-03: corrupt/incomplete/mixed-generation payload is refused by a new loading process.
- ART-04: rollback to a revoked or incompatible predecessor fails safely even if an old backup once marked it selected.

Every case is mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`. Additional V2 tests cover complete manifest normalization, persistent withdrawal replay, anti-rollback witnesses and lifecycle self-decision/state-skip rejection.

## 7. Integration, rollback and capability ceiling

C1 proves durable round-trip, independent decision, new-process changed behavior and exact compatible rollback separately. Passing a same-process fixture is not production deployment. Deletion may require full retraining or revocation when selective unlearning is unsupported.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

`RevalidatingCandidate::with_current` guards cached consumption with a monotonic current registry prefix and exact lineage eligibility. Any failed refresh closes the consumer. Tests cover revocation, old-backup resurrection, longer forks, changed scope and corrupted views; authenticated current-view discovery remains a host responsibility.

- **Implemented entrypoints:** `load_pinned_candidate` in [codex-rs/hepta-learning-artifacts/src/pinned.rs](../../../codex-rs/hepta-learning-artifacts/src/pinned.rs); registry, withdrawal and lifecycle durable adapters plus contained create/orphan reconciliation in [codex-rs/hepta-learning-artifacts/src/storage.rs](../../../codex-rs/hepta-learning-artifacts/src/storage.rs); scoped withdrawal and manifest/lifecycle validation in [codex-rs/hepta-learning-artifacts/src/closure_v2.rs](../../../codex-rs/hepta-learning-artifacts/src/closure_v2.rs); domain/head-bound admission in [codex-rs/hepta-learning-artifacts/src/admission_v3.rs](../../../codex-rs/hepta-learning-artifacts/src/admission_v3.rs); exact V3-to-V1 registry projection and crash recovery in [codex-rs/hepta-learning-artifacts/src/publication.rs](../../../codex-rs/hepta-learning-artifacts/src/publication.rs); governed iteration in `src/iteration.rs` and `src/iteration_ledger.rs`.
- **State and recovery:** Create-only file payloads and registry snapshots preserve exact manifest/digest identity. Withdrawal and lifecycle snapshots have crate-native create-only writers, independent receipts, bounded reopen, semantic replay and canonical re-encoding. Pinned loading checks the full supplied manifest before bytes return; none of these stores can make an old supplied head current.
- **Source tests:** [codex-rs/hepta-learning-artifacts/src/pinned_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/pinned_tests.rs), [codex-rs/hepta-learning-artifacts/src/storage_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/storage_tests.rs), [codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-learning-artifacts/STORAGE.md](../../../codex-rs/hepta-learning-artifacts/STORAGE.md), [codex-rs/hepta-learning-artifacts/PINNED_LOAD.md](../../../codex-rs/hepta-learning-artifacts/PINNED_LOAD.md).
- **Remaining work:** Supply authenticated product-host composition, trusted latest-head discovery, writer fencing, withdrawal-frontier distribution, directory-handle/containing-directory durability, target-filesystem power-loss qualification and independently selected product loading. Historical lifecycle replay is source-closed by validating the recorded actor/event-time binding during restart while reserving current-time credential checks for new mutations. The native channel validates an independently authenticated witness and current requirement but does not discover the newest file or grant selection/activation.

## 9. Native closure and remaining evidence

Repository-controlled source coverage is checked by `../../../scripts/hepta-lane-e-closure.py`; exact-head and ordered-parent synthetic-merge execution are defined in `.github/workflows/hepta-lane-e-gap-closure.yml`. The workflow compiles all targets, runs owner and cross-crate tests, strict Clippy and rustfmt.

The repository cannot self-provision a trusted filesystem namespace, signing key or newest-head distribution service; cannot prove containing-directory durability on every target; cannot produce external-cache or physical-erasure evidence; and cannot issue independent selection, product process loading, canary, operator acceptance, promotion or release. Those exact-candidate gates remain external.
