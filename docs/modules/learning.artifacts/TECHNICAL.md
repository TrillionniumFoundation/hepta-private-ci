# learning.artifacts technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.artifacts`

**Owner:** `learning-platform`

**Deputy:** `durability-kernel`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `ART-1-LEARNING-ARTIFACT-REGISTRY`

This stable document is the implementation guide for `learning.artifacts`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own immutable create-only learning artifacts, sensor cores, lineage and rollback predecessors.

The primary owner `learning-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `durability-kernel` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `store`, state model `stateful_create_only` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-learning-artifacts`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-learning-artifacts`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `learning.artifacts`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

### 2.1 Current native source surface

The current source is materially beyond the original V1 bootstrap while preserving the V1 registry and payload formats as compatibility surfaces. The crate now contains:

- `registry.rs` and `storage.rs`: append-only V1 registry, create-only payload/snapshot/head-witness storage, bounded reads, and contained prevalidated writes beneath a host-designated trusted root;
- `closure_v2.rs`: complete `LearningArtifactManifestV2`, scoped dataset-withdrawal registry, registry-head requirements, and lifecycle transition validation;
- `admission_v3.rs`: withdrawal-head admission that is additionally bound to `authority_domain_id + registry_id + scope_id`; unscoped registries fail closed for V3 admission;
- `publication.rs`: crash-recoverable host publication transaction contract that binds the complete V2 admission to the exact V1 compatibility-registry snapshot and independently validated current-head witness before acknowledgement, revalidates the current scoped withdrawal frontier during durable publication, and exposes a deny-all read-only status projection;
- `lifecycle_journal.rs`: predecessor-bound lifecycle journal whose historical replay validates actor evidence at the event occurrence time rather than at process-recovery time;
- `durable_snapshots.rs`: create-only, canonical, receipt-bound durable snapshots for scoped withdrawal state and lifecycle state;
- `pinned.rs` and `dataset_revocation.rs`: exact pinned loading, current-view revalidation, and snapshot-local revocation preparation;
- `iteration.rs` and `iteration_ledger.rs`: bounded authority-free iteration envelopes, candidates, externally evidenced transitions, and replayable iteration bookkeeping. These records do not run sandboxes or grant selection, promotion, merge or release authority.
- `owner_host.rs` and `owner_service.rs`: the named fenced product writer, signed writer-lease validation, signed CURRENT chain discovery, durable publication recovery, old-backup/authority-epoch rollback rejection, and opaque `VerifiedCurrentRegistryViewV1` issuance for final-use readers.
- `selection.rs`: an independent selector trust domain bound to the exact artifact-owner trust snapshot; selector keys must not collide with writer/head authority keys, signed selection binds CURRENT + complete V1 manifest/payload identity, and verified selection yields DENY_ALL load eligibility rather than activation authority.

The shared durable state ceiling is `MAX_DURABLE_ARTIFACT_RECORDS = 4096`. This deliberately aligns accepted artifact-registry, withdrawal and lifecycle record counts with the supported bounded snapshot formats so an in-memory state cannot cross a record-count threshold that the crate refuses to persist.

Source implementation is therefore not equivalent to product activation. The crate now has a named source-composed owner service with an exclusive OS writer fence, signed writer/head authentication and bounded local CURRENT discovery. The exact candidate remains qualification-dependent; trusted deployment namespace/parent-directory durability, external CURRENT distribution transport, live selector trust enrollment/private keys, independent canary/operator acceptance/promotion/release and target-host power-loss evidence remain host/external responsibilities.

### Owner-backed selected payload and restart descriptor

`LearningArtifactOwnerHost::read_current_selected_payload` obtains the live signed
CURRENT from the existing fenced owner, independently verifies selection, then
resolves exact registered bytes. `read_current_selected_manifest` additionally
returns the full validated metadata from the live selected owner entry.
A cloned `ArtifactRegistry` or old signed view cannot replace that owner read. Selection remains DENY_ALL load eligibility, not
activation, promotion, training permission or effect authority.

The V1 compatibility index's `support_digest` is the complete V2 manifest digest,
not a single dataset digest. The owner persists that manifest's existing canonical
binary encoding in `transactions/<manifest-digest>.manifest-v2` before publication
checkpoint acknowledgement. No manifest or registry digest format changes.
Selected loading verifies canonical form, every V1 projection field, full lineage
and the original V2 validity window. Manifest reads are bounded to 64 KiB; collection
lengths are checked before allocation. Missing, truncated or mismatched metadata
cannot be reconstructed from an otherwise valid model payload or old selection.
An old publication may retain its exact metadata through `resume_publication`
only with the complete transaction snapshot matching its durable checkpoint and
current writer authorization. Recovery never synthesizes missing lineage.

`persist_selected_descriptor` stores the canonical signed selection in
`transactions/<digest>.selection`; `read_selected_descriptor` verifies its bounded
encoding, content identity and current selection on every restore. The descriptor
limit is 16 KiB. Truncated records, trailing data, oversized identities, missing
payloads and currentness failures are errors, not fallback or bootstrap signals.
The consuming native composition retains the descriptor digest and independently
retained CURRENT floor. Reopening after publication uses
`open_with_required_current_head`; a self-consistent old backup is not a new floor.

`publish_revocation` requires the live writer lease, exact next signed CURRENT,
predecessor and authority epoch. It durably stages the immutable revoked registry
and transition receipt before publishing that signed head. An exact retry is
idempotent; conflicting heads are rejected. Local snapshot presence alone does
not commit a transition. New file acknowledgements also flush their containing
directory; unsupported directory flushing fails closed. Deployment must already
provide a durable, trusted owner-root namespace. This change is tested on Linux,
not a new claim of Windows/macOS power-loss qualification.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `kernel.operations`

Authoritative write domains:

- `learning_artifact_registry`
- `operator_sensor_core_registry`

Explicitly denied capabilities:

- `self_promotion`
- `mutable_artifact_bytes`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `schema and migration owner`
- `transactional writer`
- `snapshot read port`
- `integrity and lineage verifier`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Persist immutable base/organ/cell parameter bundles with complete tensor inventories and compatibility/deletion lineage. Preserve scalar ParameterProposalV2 semantics; larger updates require a versioned artifact-reference adapter. Reference-aware GC must retain shared bases still in use; the registry neither trains nor selects its own artifacts.

Bind circuit routing/termination policy to compatible cell, definition and state versions. TaskFlow continues to own immutable operational definitions; artifact storage is not a second body/run registry. See the
[Neural Circuit execution contract](../automation.taskflow/TECHNICAL.md#41-neural-circuit-target-and-legacy-boundary).

Required targeted tests: base replacement, adapter shape/order mismatch, revoked source reload, optimizer lineage and shared-reference GC.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

### Capacity, depth and learning evidence target

Retain capacity, parameter-field and adaptation profiles under existing manifests. Bind tensor sharing, probe/anchor/coordinate epochs, optimizer lineage, representation precision and compatibility. Factor norms are not effective-operator distance; field projections do not replace original artifacts.

Detailed conditions are in [Cell expressivity](../../learning/NEURAL_BIOMIMICRY_SPEC.md)
and [learning experiments](../../learning/CAUSAL_LONGITUDINAL_SPEC.md). This is a
planned integration requirement, not a change to source or product status.

### Shared-experience and isolated-Agent integration target

Retain permitted-source and derived-consumer scope through datasets, optimizers, adapters, normalizers, distillation and descendants. Revocation withdraws affected bundles; unsupported unlearning requires truthful quarantine/retrain. Shared metadata/hash equality does not authorize cross-scope access.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::learning_artifact_registryV1`
- `DomainRead::operator_sensor_core_registryV1`
- `LearningArtifactManifestV1`
- `ModulePort::learning.artifacts::intuition.policy`
- `ModulePort::learning.artifacts::learning.eval`
- `ModulePort::learning.artifacts::learning.operator`
- `ModulePort::learning.artifacts::learning.plasticity`
- `ModulePort::learning.artifacts::neuron.runtime`
- `ModulePort::learning.artifacts::prompt.optimizer`
- `ModulePort::learning.artifacts::utility.ndu`
- `OperatorSensorCoreManifestV1`

Consumed contracts:

- `BellmanOperatorArtifactV1`
- `DatasetSnapshotV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `EvaluationReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::kernel.operations::learning.artifacts`
- `ModulePort::platform.types::learning.artifacts`
- `PlasticityProposalV1`
- `RegularityProfileV1`
- `UnlearningComplianceReceiptV1`

Critical protocol schemas:

- `DatasetSnapshotV1`
- `EvaluationReceiptV1`
- `LearningArtifactManifestV1`
- `LongitudinalEvaluationReceiptV1`
- `OperatorSensorCoreManifestV1`
- `RegularityProfileV1`
- `UnlearningComplianceReceiptV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains remain:

- `learning_artifact_registry`
- `operator_sensor_core_registry`

Read-only dependencies remain `cross_owner_outbox` and `operation_ledger`.

`operator_sensor_core_registry` is physically owned by the same immutable writer as `learning_artifact_registry`: sensor cores are first-class `ArtifactKind::SensorCore` records in `ArtifactRegistry`. `project_operator_sensor_core_registry_v1` is only the typed read view over that history, bound to the exact source registry head; it is not a second journal or writer. Revocation and quarantine therefore propagate without cross-store reconciliation.

The stable V1 `ArtifactRegistry` is an append-only compatibility registry with canonical create-only snapshots. A V1 `ArtifactManifest` intentionally remains readable, but it cannot represent every V2 field: V2 supports multiple source datasets, multiple lineage digests and multiple predecessors. The implementation therefore does **not** flatten the complete V2 closure into one V1 predecessor or support field.

The complete V2 authority-free admission is retained by `WithdrawalBoundArtifactAdmissionV3`. A publication transaction stores that complete admission as the authoritative sidecar while verifying that the final V1 compatibility-registry record agrees on the fields V1 can faithfully represent: artifact identity, kind, generation, payload digest, producer, compatibility digest and exact byte length.

Dataset withdrawal is a separate append-only digest chain. New V3 admission requires a `DatasetWithdrawalScopeV1` binding `authority_domain_id`, `registry_id` and `scope_id`. The scope participates in the scoped genesis/head derivation and the V3 admission digest, so an equal-looking event history in another namespace cannot satisfy the current admission.

Withdrawal and lifecycle state both have canonical create-only durable snapshot adapters with independently retained receipts binding namespace/scope, chain head, file digest, record count and encoded byte count. Recovery rebuilds the semantic state and rejects non-canonical bytes, digest mismatch, scope mismatch, record-count mismatch or chain mismatch.

Historical lifecycle replay validates actor evidence at `event.occurred_at`. Recovery time is not reused as mutation authorization time: an actor credential that expired after a valid historical append does not make the journal unrecoverable, while a new mutation after expiry still fails.

All artifact-registry, withdrawal and lifecycle state machines share `MAX_DURABLE_ARTIFACT_RECORDS = 4096`. This is a source-enforced capacity invariant, not a target-host throughput claim.

Historical V1 snapshots remain interpretable. New V2/V3/scoped records are additive surfaces; they do not reinterpret an old V1 file as carrying fields it never encoded. Any future schema migration must preserve this distinction and provide checksum-bound deterministic replay.

## 7. Runtime, concurrency and transaction model

Artifact publication is an ordered durability protocol, not an assumed multi-file filesystem transaction.

`ArtifactPublicationTransactionV1` enforces:

`Prepared -> PayloadDurable -> RegistryDurable -> WitnessDurable -> Acknowledged`.

Preparation validates the current scoped withdrawal registry and binds the exact predecessor registry head. `PayloadDurable` requires the exact V2 payload digest and byte count. `RegistryDurable` requires a durable registry receipt whose current last record extends the expected predecessor and matches every V2 field representable by V1; it also revalidates the live scoped withdrawal frontier. `WitnessDurable` requires an independently validated head witness for that exact registry head and predecessor and revalidates the withdrawal frontier again. Final acknowledgement revalidates the current withdrawal frontier once more, so a withdrawal arriving during crash recovery or publication cannot be hidden by an older admission. Acknowledgement before witness durability is rejected.

The transaction exposes a digest-bound snapshot and replay constructor. Crash tests recover after prepared, payload-durable and registry-durable boundaries and prove that a partial publication cannot be relabelled acknowledged. The host that composes this contract must persist the returned transaction snapshot in its fenced transaction store before treating a phase as durable; a host that does not persist/replay the contract is outside this source qualification boundary.

Create-only file writers hold an exclusive advisory file lock through the empty-file check, write and `sync_all`. Readers hold shared locks for bounded reads. The crate does not own the global writer lease, product process, newest-head service or parent-directory fsync. Those are host-owned boundaries and must serialize publication, current-head discovery and final route changes.

Iteration bookkeeping is separately bounded and authority-free. `IterationLedgerV1` can record typed externally produced evidence and replay candidate state, but it does not execute a sandbox, evaluate code, select a candidate, merge source or release an artifact.

## 8. Failure semantics, recovery and rollback

The module fails closed on digest mismatch, scope mismatch, predecessor mismatch, stale withdrawal head, invalid lifecycle transition, expired mutation credentials, invalid current-head witness, non-canonical durable bytes, capacity exhaustion and publication phase skips.

The contained high-level storage APIs validate snapshot/witness/payload semantics **before** creating the final path, avoiding zero-length files for ordinary validation failures. A write or `sync_all` failure after final-path creation remains `Indeterminate`; the host must reconcile that path and may not infer success or reuse its identity.

`CreateOnlyArtifactFile::create_beneath_trusted_root` rejects absolute paths, `..`, non-normal components and symlink ancestors under the canonical trusted root. This is lexical and ordinary symlink containment, not an `openat2` substitute. Because the crate forbids unsafe code and the standard library does not expose a directory-handle no-follow transaction, the host must prevent concurrent hostile replacement of trusted ancestors and must fsync the containing directory when the target platform requires it.

Withdrawal recovery requires the same scope digest. Lifecycle recovery replays historical actor evidence at occurrence time. Publication recovery preserves the last durable phase and never upgrades an unknown/partial effect into success. Restoring an older registry, withdrawal snapshot or route marker cannot override a current independently authenticated head or current revocation/withdrawal frontier.

Rollback is a new authorized transition to an exact compatible predecessor. It is never implicit reuse of an expired grant, stale backup, old witness or previously selected state.

## 9. Security, privacy and threat controls

Owned threat entries:

- `artifact_lineage_break`
- `current_run_artifact_swap`
- `operator_sensor_clustering`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

Source-enforced ceilings relevant to this module include:

- candidate payload: 64 MiB;
- canonical V1 registry snapshot: 8 MiB;
- artifact-registry / withdrawal / lifecycle durable record ceiling: 4,096 records;
- V2 source datasets per manifest: 64;
- V2 lineage digests per manifest: 1,024;
- V2 predecessor IDs per manifest: 64;
- iteration candidates: 32;
- iteration files per candidate envelope: 100;
- iteration semantic diff budget: 1 MiB;
- parallel iteration sandboxes named by an envelope: 8;
- iteration ledger events: 384.

These bounds are safety/resource limits, not benchmark claims. Measure payload write + fsync, snapshot encode/write/reopen, withdrawal and lifecycle replay, current-head witness publication, pinned cold read/hash, current-view revalidation, crash recovery, parent-directory synchronization and orphan reconciliation on the selected target host.

The V1 compatibility registry remains intentionally bounded. A product that needs a larger history must introduce a new durable format or compaction/checkpoint design; it must not silently raise the in-memory limit beyond what the supported durable representation can carry.

## 11. Observability and operations

Operate create-only artifact storage under one writer owner, with independently retained receipts and current revocation/withdrawal/head witnesses. Do not derive an expected receipt from the file currently under inspection.

For safer filesystem integration prefer the contained prevalidated writers:

- `write_candidate_payload_beneath`;
- `write_registry_snapshot_beneath`;
- `write_registry_head_witness_beneath`;
- `write_dataset_withdrawal_snapshot_beneath`;
- `write_artifact_lifecycle_snapshot_beneath`.

The lower-level `CreateOnlyArtifactFile` APIs remain for compatibility and capability-based composition. A host using them must reconcile empty files caused by creating a capability before later semantic validation.

The crate deliberately exposes no mutable “admin override”, force-select, force-promote or force-repair API. `ArtifactPublicationTransactionV1::status` provides a deny-all read-only service/admin projection containing operation, phase, admission/withdrawal bindings, registry head, witness, acknowledgement time and transaction state digest. Repair still requires a separately authenticated/fenced host operation. This keeps operational tooling from becoming an undeclared authority bypass.

Current operating and state-format references:

- [codex-rs/hepta-learning-artifacts/STORAGE.md](../../../codex-rs/hepta-learning-artifacts/STORAGE.md);
- [codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md](../../../codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md);
- [codex-rs/hepta-learning-artifacts/PINNED_LOAD.md](../../../codex-rs/hepta-learning-artifacts/PINNED_LOAD.md);
- [codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md](../../../codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md);
- [codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md](../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md).

Target-host alerting should distinguish rejected input, capacity exhaustion, busy lock, stale/scope-mismatched evidence, corrupt durable bytes and indeterminate I/O. Concrete thresholds require the selected deployment profile.

## 12. Verification and qualification

Focused native coverage includes:

- V2 manifest normalization and lineage rejection in `closure_v2_tests.rs`;
- persistent withdrawal replay and future-admission denial;
- scoped V3 admission, including unscoped fail-closed and cross-scope publication rejection;
- lifecycle transition separation plus historical replay after actor credential expiry;
- create-only storage, lock/read budgets, path escape and symlink-ancestor rejection;
- validation-before-create proof that a rejected payload does not leave a final-path orphan;
- canonical durable withdrawal and lifecycle snapshot round trips with digest/scope checks;
- publication phase ordering, crash snapshot replay and V1/V2 projection mismatch rejection;
- exact pinned load/current-view revalidation and dataset revocation propagation;
- bounded iteration and iteration-ledger transition/replay tests.

The Lane E workflow executes locked all-target compilation, owner tests, cross-crate causal closure, the Rust↔Python wire-fault test, strict Clippy, rustfmt and an ordered-parent synthetic merge. The synthetic merge uses the pull-request base on PR events and `github.event.before` on normal pushes; initial pushes with a zero predecessor do not pretend to have a valid merge base.

A green workflow is execution evidence for its exact commit only. It is not product activation, operator acceptance, selection, promotion or release. The repository cannot self-produce external filesystem trust, newest-head distribution, signing-key authentication or production route evidence.

## 13. Implementation sequence and work packages

The `State:` values inside the execution envelopes below are canonical planning metadata imported from the global work-package plan; they are not a live substitute for the source status in sections 2.1 and 12. A package may still display `planned` here while its source candidate exists and awaits exact-commit qualification or external activation evidence.

Applicable work packages:

- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `HBO-1-OPERATOR-SENSOR-CORE`

The bootstrap package is `ART-1-LEARNING-ARTIFACT-REGISTRY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `learning.artifacts`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `ART-1-LEARNING-ARTIFACT-REGISTRY`

- State: `source_implemented`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-learning-artifacts/**`
- `codex-rs/hepta-shadow-qualification/tests/durable_learning_roundtrip.rs`
- Development predecessors:
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `MEM-1-STORE`
- Activation predecessors:
- `MEM-1-STORE`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`

- State: `source_implemented`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-learning-artifacts/**`
- `qa/learning/reload-rollback/**`
- Development predecessors:
- `LRN-2-CAUSAL-EVALUATION`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- Activation predecessors:
- `LRN-2-CAUSAL-EVALUATION`
- `HBO-1-OPERATOR-SENSOR-CORE`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- `current_snapshot_immutable`
- `signed_next_snapshot`
- `exact_reload`
- `rollback_predecessor`
- `crash_reopen`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `HBO-1-OPERATOR-SENSOR-CORE`

- State: `source_implemented`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-learning-artifacts/**`
- `codex-rs/hepta-bellman-operator/**`
- Development predecessors:
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- Activation predecessors:
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `learning.artifacts` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::operator_sensor_core_registryV1`
- `LearningArtifactManifestV1`
- `ModulePort::learning.artifacts::intuition.policy`
- `ModulePort::learning.artifacts::learning.eval`
- `ModulePort::learning.artifacts::learning.operator`
- `ModulePort::learning.artifacts::learning.plasticity`
- `ModulePort::learning.artifacts::neuron.runtime`
- `ModulePort::learning.artifacts::prompt.optimizer`
- `ModulePort::learning.artifacts::utility.ndu`
- `OperatorSensorCoreManifestV1`

**Consumed contracts:**
- `AlgorithmFaultReceiptV1`
- `BellmanOperatorArtifactV1`
- `CandidateEvaluationReceiptV1`
- `ConformanceReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `EvaluationReceiptV1`
- `IndependentDecisionReceiptV1`
- `IterationCandidateV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::kernel.operations::learning.artifacts`
- `ModulePort::platform.types::learning.artifacts`
- `NduCoefficientManifestV1`
- `NduWellPosednessCertificateV1`
- `OperatorApplicabilityCertificateV1`
- `PlasticityProposalV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`
- `TopologyProposalV1`
- `UnlearningComplianceReceiptV1`

**Typed protocols:**
- `AlgorithmFaultReceiptV1`
- `CandidateEvaluationReceiptV1`
- `ConformanceReceiptV1`
- `DatasetSnapshotV1`
- `EvaluationReceiptV1`
- `IndependentDecisionReceiptV1`
- `IterationCandidateV1`
- `LearningArtifactManifestV1`
- `LongitudinalEvaluationReceiptV1`
- `NduCoefficientManifestV1`
- `NduWellPosednessCertificateV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `PlasticityProposalV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`
- `TopologyProposalV1`
- `UnlearningComplianceReceiptV1`

**Owned data domains:**
- `learning_artifact_registry`
- `operator_sensor_core_manifest_v1`
- `operator_sensor_core_registry`

**Read data domains:**
- `algorithm_fault_receipt_v1`
- `candidate_evaluation_receipt_v1`
- `conformance_receipt_v1`
- `cross_owner_outbox`
- `independent_decision_receipt_v1`
- `iteration_candidate_v1`
- `ndu_coefficient_manifest_v1`
- `ndu_well_posedness_certificate_v1`
- `operation_ledger`
- `operator_applicability_certificate_v1`
- `plasticity_proposal_v1`
- `regularity_profile_v1`
- `support_audit_receipt_v1`
- `topology_proposal_v1`

**Work packages:**
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `HBO-1-OPERATOR-SENSOR-CORE`

**Owned threats:**
- `artifact_lineage_break`
- `current_run_artifact_swap`
- `operator_sensor_clustering`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.artifacts` to primary lane `LANE-E-LEARNING`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-NEU`](../../readiness/NEURON_RUNTIME_EXECUTION.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)
- [`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md)

Owned readiness protocols:

- `CandidateLineageV1`

Consumed readiness protocols:

- `EvaluationPlanV1`
- `NduConvergenceCertificateV1`
- `RetentionSliceReceiptV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.artifacts` is implemented by work package `ART-1-LEARNING-ARTIFACT-REGISTRY` in:

- `codex-rs/hepta-learning-artifacts`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
