# learning.artifacts: implementation design

Parent: `docs/modules/learning.artifacts/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: create-only storage, complete V2 manifest, persistent dataset withdrawal, head anti-rollback and lifecycle source candidate implemented; current exact-head and synthetic-merge CI determine source qualification, while product loading and independent selection remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-artifacts`.
Packages: `ART-1-LEARNING-ARTIFACT-REGISTRY`, `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve the stable V1 registry and create-only storage APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`write_candidate_payload(file, registry, artifact, bytes) -> Digest32`; `write_registry_snapshot(file, registry, binding) -> RegistrySnapshotReceipt`; `load_pinned_candidate(snapshot, payload, pin) -> LoadedPinnedCandidate`; `validate_artifact_manifest_v2(manifest, now) -> ValidatedArtifactManifestV2`; `DatasetWithdrawalRegistry::append(notice) -> DatasetWithdrawalReceiptV1`; `DatasetWithdrawalRegistry::admit_manifest(manifest, now) -> ValidatedArtifactManifestV2`; `validate_registry_head_witness(witness, requirement) -> RegistryHeadReceiptV1`; `validate_artifact_lifecycle_transition(producer, event) -> Digest32`.

Candidate registration is not selection. A successful read is not execution or activation. The supervisor or separately authorized selector consumes independent selection evidence; the artifact owner never installs itself.

## 3. State records and transaction design

Own create-only `learning_artifact_registry` and `operator_sensor_core_registry`. The stable V1 registry and payload encoding remain readable. `LearningArtifactManifestV2` explicitly binds payload digest/length, every source dataset, complete lineage, multiple predecessors, rollback predecessor, training code, runtime, device, objective class, schema, normalization, compatibility, producer, creation time and expiry.

`DatasetWithdrawalRegistry` is a separate append-only digest chain. It persists dataset tombstones and blocks every future manifest that references a withdrawn dataset, closing the gap left by a snapshot-local invalidation batch. Exact notice retries are idempotent; changed semantics under a reused notice ID conflict.

`RegistryHeadWitnessV1` binds registry identity, generation, predecessor head, authority epoch, signer, signing key and validity window. Generation rollback, authority-epoch rollback, predecessor mismatch and expiry fail. A product host must authenticate the witness signature before constructing the typed value.

## 4. Deterministic algorithm and scheduling

Validate scope, size and complete lineage; check the persistent withdrawal frontier; create immutable bytes with conflict-on-different-content identity; synchronize; append a canonical registry event against an exact predecessor; publish the registry snapshot; obtain an independently authenticated head witness; and acknowledge only after the witness is durable.

New runs load an exact selected tuple against the current head and withdrawal frontier; the old run retains its snapshot. Restore and rollback always overlay current revocations and withdrawals before exposing artifacts. Payload and registry publication form a bounded saga: bytes synchronized without a registry event are an orphan candidate, never selected state.

The lifecycle evidence state machine is `proposed -> trained -> evaluated -> shadow -> canary -> operator_accepted -> selected -> retired`, with bounded quarantine and revocation edges. A producer cannot issue its own evaluation, acceptance, selection, quarantine or revocation decision, and mandatory states cannot be skipped.

## 5. Capacity and performance profile

Payload bytes remain bounded by the native create-only storage profile. V2 source datasets are bounded to 64, lineage digests to 1024 and predecessor IDs to 64 per manifest. Persistent withdrawal and registry record counts are bounded. Large lineage graphs use indexed traversal and reject incomplete eligibility proofs.

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

- **Implemented entrypoints:** `load_pinned_candidate` in [codex-rs/hepta-learning-artifacts/src/pinned.rs](../../../codex-rs/hepta-learning-artifacts/src/pinned.rs); `write_candidate_payload` in [codex-rs/hepta-learning-artifacts/src/storage.rs](../../../codex-rs/hepta-learning-artifacts/src/storage.rs); `admit_manifest_at_withdrawal_head_v3` in [codex-rs/hepta-learning-artifacts/src/admission_v3.rs](../../../codex-rs/hepta-learning-artifacts/src/admission_v3.rs). Create-only payload storage, pinned loading and withdrawal-aware admission implemented.
- **State and recovery:** Create-only file payloads and registry snapshots preserve exact manifest/digest identity. Pinned loading checks the full supplied manifest before bytes return; withdrawal/lifecycle journals retain their own bounded lineage and cannot make an old supplied head current.
- **Source tests:** [codex-rs/hepta-learning-artifacts/src/pinned_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/pinned_tests.rs), [codex-rs/hepta-learning-artifacts/src/storage_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/storage_tests.rs), [codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-learning-artifacts/STORAGE.md](../../../codex-rs/hepta-learning-artifacts/STORAGE.md), [codex-rs/hepta-learning-artifacts/PINNED_LOAD.md](../../../codex-rs/hepta-learning-artifacts/PINNED_LOAD.md).
- **Remaining work:** Supply authenticated latest-head/withdrawal distribution, namespace and directory durability, and independently selected product loading; a successful read is not selection or activation.

## 9. Native closure and remaining evidence

Repository-controlled source coverage is checked by `../../../scripts/hepta-lane-e-closure.py`; exact-head and ordered-parent synthetic-merge execution are defined in `.github/workflows/hepta-lane-e-gap-closure.yml`. The workflow compiles all targets, runs owner and cross-crate tests, strict Clippy and rustfmt.

The repository cannot self-provision a trusted filesystem namespace, signing key or newest-head distribution service; cannot prove containing-directory durability on every target; cannot produce external-cache or physical-erasure evidence; and cannot issue independent selection, product process loading, canary, operator acceptance, promotion or release. Those exact-candidate gates remain external.
