# learning.artifacts: implementation design

Parent: `docs/modules/learning.artifacts/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: create-only storage, complete V2 manifest, domain-bound V3 admission, persistent dataset withdrawal, durable lifecycle/withdrawal replay, publication crash classification and governed iteration source candidate implemented; current exact-head and synthetic-merge CI determine source qualification, while product loading and independent selection remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-artifacts`.
Packages: `ART-1-LEARNING-ARTIFACT-REGISTRY`, `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve the stable V1 registry and create-only storage APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

Stable compatibility operations remain `write_candidate_payload`, `write_registry_snapshot`, `write_registry_head_witness`, `read_registry_head_witness` and `load_pinned_candidate`. New hosts should prefer `prepare_candidate_payload_v1`, `prepare_registry_snapshot_v1` and `prepare_registry_head_witness_v1` before creating final paths, followed by the corresponding `write_prepared_*` operation.

Closure operations include `validate_artifact_manifest_v2`, `DatasetWithdrawalRegistry::append`, `withdrawal_head_digest_v3`, `admit_manifest_at_withdrawal_head_v3`, `ArtifactLifecycleJournalV2::append/from_snapshot`, `prepare_artifact_publication_transaction_v1`, `classify_artifact_publication_recovery_v1`, and create-only read/write adapters for withdrawal/lifecycle snapshots. `IterationCandidateV1` and `IterationLedgerV1` provide bounded authority-free iteration state/evidence.

Candidate registration is not selection. A successful read, admission, lifecycle transition, publication receipt or iteration transition is not execution/activation authority. The supervisor or separately authorized selector consumes independent selection evidence; the artifact owner never installs itself.

## 3. State records and transaction design

Own create-only `learning_artifact_registry` and `operator_sensor_core_registry`. The stable V1 registry/payload encoding remain readable. `LearningArtifactManifestV2` binds payload digest/length, all source datasets, complete lineage, multiple predecessors, rollback predecessor, training code, runtime, device, objective, schema, normalization, compatibility, producer, creation time and expiry.

`DatasetWithdrawalRegistry` is an append-only digest chain that persists tombstones and blocks future manifests referencing withdrawn datasets. V3 admission additionally binds `WithdrawalAuthorityDomainV1 { registry_id, scope_digest, authority_id }`; the admitted frontier is a domain-separated digest of that domain and the raw withdrawal head. Identical raw heads in distinct scopes are not interchangeable.

`ArtifactLifecycleJournalV2` is predecessor-bound and role-aware. Historical replay validates actor evidence at immutable event time rather than restart time, so credential expiry cannot make valid stored history unrecoverable. New mutation still requires currently valid actor evidence.

`HEPTAW01` withdrawal and `HEPTAL02` lifecycle snapshots are create-only, bounded and independently receipted. The V1 artifact registry remains `HEPTAR01`, with `HEPTAH01` for independently validated current-head distribution.

`ArtifactPublicationTransactionV1` is the hard host commit tuple, not a claim of cross-file atomicity. It binds exact V2 admission, withdrawal domain/head, V1 predecessor/candidate registry heads, the V1/V2 common-field bridge and next authenticated head witness. Crash classification accepts only exact predecessor as `NotCommitted` or exact candidate generation as `Committed`; any unrelated head conflicts.

## 4. Deterministic algorithm and scheduling

Under one authenticated host writer fence: validate V2 manifest and scoped withdrawal frontier; prepare bytes before final-path creation; construct an exact V1 successor registry with a currently eligible V1 bridge for the V2 artifact; validate the next head witness; prepare `ArtifactPublicationTransactionV1`; sync payload/snapshot; durably publish the authenticated current-head witness; acknowledge only after the witness is durable.

The compatibility one-shot storage APIs remain available, but deterministic validation can occur after a capability has created its final path and may therefore leave a zero-length orphan. Prepare-before-create avoids those predictable orphans. I/O failure after creation remains indeterminate and host-reconciled.

New runs load an exact selected tuple against the current head and withdrawal frontier; old runs retain frozen snapshots. Restore/rollback overlays current revocations and withdrawals before exposure. The lifecycle evidence machine remains `proposed -> trained -> evaluated -> shadow -> canary -> operator_accepted -> selected -> retired`, with bounded quarantine/revocation edges and role separation.

## 5. Capacity and performance profile

Artifact, withdrawal and lifecycle owner histories share the code-enforced durable-record cap `4096`. Canonical artifact/control snapshots are bounded by `8 MiB`; candidate payloads by `64 MiB`. V2 source datasets are bounded to 64, lineage digests to 1024 and predecessor IDs to 64. Iteration candidate/file/diff/parallel-sandbox and ledger-event bounds are encoded in `iteration.rs` and `iteration_ledger.rs`.

The owner rejects mutation before accepting state its canonical durable format cannot represent. Measure put/fsync, containing-directory synchronization, witness publication, cold read/hash, registry/control reopen, withdrawal lookup, revoke propagation, backup replay, recovery conflict and orphan reconciliation. Source limits are not target-host measurements.

## 6. Concrete verification cases

- ART-01: create-only ID reuse with different bytes conflicts; identical semantic retry is idempotent.
- ART-02: crash before authenticated current-head publication classifies `NotCommitted`; crash after exact candidate-head publication classifies `Committed`.
- ART-03: corrupt/incomplete/mixed-generation payload or control snapshot is refused on reopen.
- ART-04: rollback to a revoked/incompatible predecessor fails even if an old backup once marked it selected.
- ART-05: equal raw withdrawal heads from different registry/scope/authority domains are not interchangeable.
- ART-06: lifecycle history written while actor evidence was valid reopens after that credential expires, while a new write with the expired credential is rejected.
- ART-07: a publication candidate that registers and then revokes/quarantines the admitted artifact is not a valid publication bridge.
- ART-08: rooted create-only placement rejects lexical parent escape and symlinked-parent escape; prepare-before-create creates no final path on deterministic validation failure.

Cross-crate mappings remain in `../../lane-e/TEST_TRACEABILITY.json`; inline native tests additionally cover V3 admission, lifecycle journal, control storage, publication recovery and iteration bookkeeping. Test identities are not execution receipts.

## 7. Integration, rollback and capability ceiling

C1 proves durable round-trip, independent decision, new-process changed behavior and exact compatible rollback separately. Passing a same-process fixture is not production deployment. Deletion may require full retraining or revocation when selective unlearning is unsupported.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

The current source mapping is enumerated in `../../../docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json` and `../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md`.

- **Registry/payload:** V1 append-only registry, prepare-before-create payload/snapshot/witness APIs, create-only final writes, current-head witness readback and exact pinned loading.
- **Withdrawal/admission:** persistent withdrawal chain plus V3 registry/scope/authority domain separation and exact-frontier admission.
- **Lifecycle:** predecessor-bound role-aware journal; replay uses historical event time while current append uses current credential validity.
- **Durable control state:** create-only `HEPTAW01` withdrawal and `HEPTAL02` lifecycle snapshots round-trip through real files with independent receipts.
- **Publication:** `ArtifactPublicationTransactionV1` validates the exact successor prefix/bridge/current eligibility and next witness; recovery is explicit `NotCommitted` / `Committed` / conflict.
- **Iteration:** bounded `IterationCandidateV1` transition model and `IterationLedgerV1` external-evidence ledger remain deny-all.
- **Capacity/path hardening:** owner histories share the 4096 durable cap; `CreateOnlyArtifactFile::create_in` rejects absolute/parent/symlink-parent escape while documenting the remaining hostile-rename host boundary.
- **Admin/service:** `inspect_artifact_owner_status_v1` exposes read-only heads, bounded counts and remaining durable capacity with `AuthorityPosture::DENY_ALL`; it cannot discover newest files, mutate state, delete orphans, select, activate, promote or release.
- **Source tests:** registry, storage/budget/lock, pinned, revocation, closure V2 plus inline admission V3, lifecycle, control-storage, publication and iteration tests.

**Remaining boundary:** product caller and production writer are still not composed. The host owns trusted newest-head discovery, external signature/authentication, target-filesystem directory durability/openat-style hostile-race protection, backup non-resurrection, independently selected process loading, admin orchestration and release gates.

## 9. Native closure and remaining evidence

Repository-controlled source coverage is checked by `../../../scripts/hepta-lane-e-closure.py`; exact-head and actual-base synthetic-merge execution are defined in `.github/workflows/hepta-lane-e-gap-closure.yml`. The workflow compiles all targets, runs owner/cross-crate tests, strict Clippy and rustfmt. Push events use `github.event.before` as their synthetic-merge base with a zero-SHA initial-push fallback; pull requests use the PR base SHA.

The repository can prove source-owned persistence/replay and deterministic publication recovery, but it cannot self-provision a trusted filesystem namespace/signing key/newest-head distribution service, prove target-filesystem directory durability or hostile rename races on every target, produce physical-erasure evidence, or issue independent selection, product process loading, canary, operator acceptance, promotion or release. Those exact-candidate and external gates remain separate.
