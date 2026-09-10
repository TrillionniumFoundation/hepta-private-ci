# learning.artifacts: implementation design

Parent: `docs/modules/learning.artifacts/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: create-only storage, complete V2 manifest, replayable withdrawal state, head anti-rollback, lifecycle validation, withdrawal-bound admission and predecessor-bound lifecycle journal source candidate implemented; exact-head and ordered-base synthetic-merge CI determine source qualification. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md` and `../../../docs/engineering/MODULE_ENGINEERING_STANDARD.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-learning-artifacts`.
Packages: `ART-1-LEARNING-ARTIFACT-REGISTRY`, `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`.

Concrete mappings are recorded in `../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Stable V1 registry and create-only storage APIs remain available; no operation grants selection or activation authority.

## 2. Public operations and contract details

The closed-world surface includes create/read payload and registry snapshot operations, `load_pinned_candidate`, complete V2 manifest validation, withdrawal append/admission, registry-head validation, lifecycle-transition validation, and the additive operations:

- `admit_manifest_at_withdrawal_head_v3`;
- `verify_artifact_admission_v3`;
- `validate_artifact_publication_v3`;
- `ArtifactLifecycleJournalV2::append`;
- `ArtifactLifecycleJournalV2::from_snapshot`.

Candidate registration is not selection. A successful read is not execution. V3 admission retains the exact withdrawal head used during validation, and publication validation rejects the receipt whenever that head has advanced. The lifecycle journal binds every accepted transition to the previous journal head, authenticated actor evidence supplied by the host, an allowed role, the prior artifact state and an immutable event identity. Its receipt is always `AuthorityPosture::DENY_ALL`.

## 3. State records and transaction design

The module owns create-only `learning_artifact_registry` and `operator_sensor_core_registry`. `LearningArtifactManifestV2` binds payload digest/length, every source dataset, complete lineage, predecessors, rollback predecessor, training code, runtime, device, objective, schema, normalization, compatibility, producer and expiry.

`DatasetWithdrawalRegistry` is append-only, digest chained and exactly replayable. It persists typed tombstones when hosted by a durable adapter and blocks future manifests that reference a withdrawn dataset. Exact notice retry is idempotent; changed semantics under a reused notice identity conflict.

`WithdrawalBoundArtifactAdmissionV3` binds the normalized manifest digest, observed withdrawal head and admission time. The product publisher must validate it while holding the same exclusive writer fence used to append the manifest. A check followed by an unfenced publish remains invalid; V3 supplies the expected-head contract but does not pretend to provision the physical lock.

`ArtifactLifecycleJournalV2` stores an ordered record containing sequence, predecessor head, event digest, chain digest, producer identity, actor evidence and the full lifecycle event. It maintains per-artifact state and an event-identity digest index. Reused event identity with changed semantics conflicts; exact replay is idempotent; stale head, stale state, expired actor evidence, role mismatch and snapshot drift fail closed. `from_snapshot` reconstructs the journal by replaying every record through the same validation path and comparing every reconstructed record and final head.

`RegistryHeadWitnessV1` detects generation, authority-epoch and predecessor rollback after the host has authenticated the witness. The pure validator does not verify a cryptographic signature. Likewise, `LifecycleActorEvidenceV2` is a typed post-authentication input; the source module does not claim to verify an external signature or provision the actor credential.

## 4. Deterministic algorithm and scheduling

Validate size, lineage, compatibility and expiry; read the current withdrawal head; require it to equal the caller's expected head; validate the manifest against the withdrawal set; create immutable bytes; synchronize; revalidate the admission against the still-current withdrawal head under the writer fence; append the registry event against an exact predecessor; publish the snapshot; obtain an independently authenticated head witness; then acknowledge.

Payload and registry publication are a bounded saga. Bytes synchronized without a registry event are an orphan candidate, never selected state. New processes load an exact selected tuple against both current registry and withdrawal heads. Restore and rollback overlay current revocations and withdrawals before exposing bytes.

Lifecycle remains `proposed -> trained -> evaluated -> shadow -> canary -> operator_accepted -> selected -> retired`, with quarantine and revocation edges. Each journal append first checks the expected chain head, then actor freshness and actor/event binding, then the stable transition validator, current per-artifact state and role-specific edge. Only after all checks pass does it calculate and publish the next chain digest. The producer cannot issue its own evaluation, acceptance, selection, quarantine or revocation.

## 5. Capacity and performance profile

Payload size follows the native create-only profile. V2 permits at most 64 source datasets, 1,024 lineage digests and 64 predecessor IDs per manifest; withdrawal and lifecycle record counts are bounded. The lifecycle journal is capped at 1,000,000 records and uses bounded ordered maps for state and event identity. Measure payload sync, containing-directory sync, withdrawal lookup, V3 admission/revalidation, lifecycle append and snapshot replay, registry publication, witness publication, cold read/hash, reopen, backup replay and orphan reconciliation.

Source ceilings are not target-host measurements. Large lineage proofs require indexed traversal and complete eligibility evidence.

## 6. Concrete verification cases

- ART-01: create-only identity drift conflicts and exact retry is idempotent.
- ART-02: payload sync before registry publication leaves an orphan, not selection.
- ART-03: corrupt, incomplete or mixed-generation bytes and manifests fail closed.
- ART-04: rollback to a revoked, withdrawn or incompatible predecessor fails under the current frontier.
- ART-05: admission binds the exact withdrawal head and a concurrent withdrawal invalidates publication.
- ART-06: lifecycle publication is expected-head- and prior-state-bound, actor-role-gated, exact-retry idempotent and exactly replayable from an immutable snapshot.

Every case maps to concrete Rust tests in `../../lane-e/TEST_TRACEABILITY.json`. Passing a same-process fixture is not deployment evidence.

## 7. Integration, rollback and capability ceiling

A product transaction must hold one writer fence across V3 publication validation and manifest append, then persist the resulting registry head. Lifecycle publication must bind the same product operation to an exact journal predecessor and durably publish the new head before acknowledging it. Rollback is a new authorized transition to a complete compatible predecessor under current withdrawal and revocation state. Backup markers cannot reactivate a revoked artifact.

Immediate revocation and stop remain effective. Preserve all external gates; the artifact owner cannot select, load, activate, promote or release itself. The lifecycle journal records a host-authenticated observation and remains deny-all; it does not mint the external authority represented by a selector, operator, quarantine, revocation or retirement role.

## 8. Native closure and remaining evidence

Repository-controlled coverage now includes all stable storage operations, complete V2 provenance, replayable withdrawal semantics, anti-rollback validation, lifecycle transition rules, withdrawal-race rejection, predecessor-bound role-gated lifecycle journaling and exact snapshot reconstruction. `../../../scripts/hepta-lane-e-closure.py` verifies every public symbol, crate export, attributed test and cross-crate link; CI repeats all checks on exact head and ordered merge.

The repository cannot self-provision a trusted filesystem namespace, signature key, newest-head distribution service or target-host directory durability; cannot produce external-cache or physical-erasure evidence; and cannot issue independent selection, product-process loading, canary, operator acceptance, promotion or release. Those exact-candidate gates remain external.
