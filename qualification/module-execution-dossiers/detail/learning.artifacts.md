# learning.artifacts: implementation design

Parent: `docs/modules/learning.artifacts/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-artifacts`.
Packages: `ART-1-LEARNING-ARTIFACT-REGISTRY`, `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`put_candidate(bytes, manifest, create_only_key) -> ArtifactReference`; `append_registry_event(artifact, lifecycle_event, evidence) -> RegistryCommit`; `resolve_eligible(reference, current_revocations, compatibility) -> ReadHandle`; `read_for_next_snapshot(selected_reference, supervisor_evidence) -> ImmutableArtifact`. Candidate registration is not selection; the supervisor consumes independent selection and the artifact owner never installs itself.

## 3. State records and transaction design

Own create-only learning_artifact_registry and operator_sensor_core_registry. Manifest fields bind byte digest/length, code, dataset/source lineage, model/runtime/device/profile, objective class, schema/config/body compatibility, expiry and rollback predecessor. Registry lifecycle and revocation are append-only. Store bytes durably before publishing their registry reference; reconcile interrupted byte/registry publication through the existing transaction/outbox design.

## 4. Deterministic algorithm and scheduling

Validate scope, size and complete lineage; create immutable bytes with conflict-on-different-content identity; sync; append a canonical registry snapshot/event; obtain independent evidence; resolve only a currently eligible complete artifact. New run loads an exact selected tuple; the old run retains its snapshot. Restore and rollback always overlay current revocations before exposing artifacts.

## 5. Capacity and performance profile

Artifact byte size, concurrent uploads and retained versions are package profile bounds; pilot manifest <=256 KiB with <=1024 lineage references per bounded publication. Large lineage graphs use bounded indexed traversal and reject incomplete eligibility proofs. Measure put/fsync, cold read/hash, registry reopen and revoke propagation.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- ART-01: create-only ID reuse with different bytes conflicts; identical retry is idempotent.
- ART-02: crash after bytes sync but before registry publication yields an orphan candidate, not a selected artifact.
- ART-03: corrupt/incomplete/mixed-generation payload is refused by a new loading process.
- ART-04: rollback to a revoked or incompatible predecessor fails safely even if an old backup once marked it selected.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

C1 proves durable round-trip, independent decision, new-process changed behavior and exact compatible rollback separately. Passing a same-process fixture is not production deployment. Deletion may require full retraining or revocation when selective unlearning is unsupported.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
