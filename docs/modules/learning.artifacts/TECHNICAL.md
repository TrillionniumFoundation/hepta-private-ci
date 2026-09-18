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

Declared exclusive target root: `codex-rs/hepta-learning-artifacts`. The root is present; there are no missing declared or non-authoritative evidence roots.

The current native source candidate contains the stable V1 immutable registry/create-only storage, V2 manifest and withdrawal closure, V3 domain-bound admission, a predecessor-bound lifecycle journal, durable lifecycle/withdrawal control snapshots, a host publication transaction contract with crash classification, pinned loading, governed iteration records and an append-only iteration evidence ledger. The current source-to-symbol inventory is [`IMPLEMENTATION_MAP.json`](./IMPLEMENTATION_MAP.json).

`existing_bound` is a source-location fact, not a qualification result. The current candidate must pass closed-world inventory, focused/package tests, all-target compilation, strict lint, exact-head execution and actual-base synthetic-merge execution before the source-completion claim changes. Source presence does not activate the module, create a production caller/writer, grant effect authority, issue independent acceptance, select/promote a candidate or authorize release.

The implementation map retains the repository-wide canonical `sourceBase` shared by all module maps. Candidate-specific branch/PR/commit evidence is carried separately by `implementationReceipt`; changing only this module's shared `sourceBase` would intentionally fail the closed-world map verifier.

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

Current native components:

- `registry.rs`: V1 append-only `ArtifactRegistry`, lineage eligibility and idempotent event identity.
- `storage.rs`: create-only payload/snapshot/head-witness I/O, prepare-before-create APIs, bounded reload and rooted path containment.
- `storage_hygiene.rs`: enrolled-root inspection and conservative zero-length orphan cleanup; no recursive or non-empty deletion.
- `pinned.rs`: exact candidate loading from an independently retained registry receipt.
- `closure_v2.rs`: `LearningArtifactManifestV2`, persistent dataset-withdrawal frontier, anti-rollback head witness and lifecycle transition primitives.
- `admission_v3.rs`: admission bound to the exact withdrawal head and explicit `registry_id + scope_digest + authority_id + authority_epoch` domain identity.
- `lifecycle_journal.rs`: predecessor-bound lifecycle journal with actor/role evidence and historical-recovery semantics.
- `control_storage.rs`: canonical create-only persistence/reopen for withdrawal and lifecycle snapshots.
- `publication.rs`: hard host publication contract binding V2 admission to a durable V1 successor registry and authenticated head witness, plus deterministic crash classification.
- `dataset_revocation.rs`: snapshot-local preparation of V1 revocation events for directly dataset-bound artifacts.
- `iteration.rs` and `iteration_ledger.rs`: bounded authority-free self-iteration state and append-only external-evidence bookkeeping.
- `limits.rs`: one durable record/snapshot capacity contract shared by memory owners and persistence adapters.
- `service.rs`: read-only owner health/reconciliation status exposing heads, bounded counts and remaining capacity with deny-all authority.

Ingress validates identity, version, size, scope, predecessor/frontier and digest before mutation. State transition is separated from external authority: typed actor/evidence values are supplied only after host authentication, and returned authority posture remains deny-all. This crate owns no signing key, product route, deployment selector or release decision.

Configuration affecting authority, schema, compatibility, model identity, objective semantics or resource policy creates a new revision/generation. Hidden mutable singletons, unbounded queues, implicit store fallback and silent old-snapshot fallback are prohibited.

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

Owned authoritative or rebuildable domains are `learning_artifact_registry` and `operator_sensor_core_registry`; `cross_owner_outbox` and `operation_ledger` remain read-only dependencies.

The stable V1 `ArtifactRegistry` is the canonical durable registry surface. Its `HEPTAR01` snapshot binds host scope, full event history, chain head, file digest, record count and byte count. `HEPTAH01` distributes a separately validated current-head witness; an old self-consistent snapshot never proves currentness.

The V2/V3 surfaces are additive rather than an in-place reinterpretation of V1 history:

- `LearningArtifactManifestV2` binds complete dataset/provenance, predecessor, payload, training/runtime/device/objective/schema/normalization/compatibility and time facts.
- `DatasetWithdrawalRegistry` persists the dataset tombstone frontier and denies future dataset-derived admission.
- V3 admission domain-separates that frontier with `registry_id`, `scope_digest`, `authority_id` and nonzero `authority_epoch`; equal raw heads across scopes or authority epochs are not interchangeable.
- `ArtifactLifecycleJournalV2` persists predecessor-bound lifecycle evidence.
- `ArtifactPublicationTransactionV1` binds V2 admission/withdrawal state to the exact V1 predecessor registry, candidate registry and authenticated head witness. The V1 register event is the compatibility bridge and must match common artifact identity/content fields.

`control_storage.rs` adds canonical `HEPTAW01` withdrawal and `HEPTAL02` lifecycle snapshots with independent receipts and byte-for-byte reopen verification. Domain-aware withdrawal helpers derive the snapshot binding from the exact `WithdrawalAuthorityDomainV1`, so a snapshot cannot be reopened under a different scope, authority or authority epoch. This proves durable replay of the state models; newest-generation discovery and external witness publication remain host responsibilities.

All owner-side append paths share `MAX_DURABLE_ARTIFACT_RECORDS = 4096`; memory owners may not accept state that canonical durable formats cannot persist. The artifact/control snapshot byte ceiling is `8 MiB`. Stable V1 encodings remain readable; additive formats have distinct magic/domain tags. Future format migrations must be deterministic, checksum-bound and leave a recoverable predecessor.

## 7. Runtime, concurrency and transaction model

One authenticated host writer fence owns publication ordering. The required model is a bounded saga, not a claim of multi-file filesystem atomicity:

1. validate the V2 manifest and exact scoped withdrawal frontier;
2. prepare payload/snapshot bytes before creating final paths when validation can be completed in memory;
3. construct a V1 successor registry whose prefix is the exact current registry and whose V1 register event matches common V2 artifact fields;
4. build/validate the next `RegistryHeadWitnessV1` against the exact predecessor head;
5. call `prepare_artifact_publication_transaction_v1` while holding the writer fence; it rechecks withdrawal domain/head, successor relation, manifest bridge and witness;
6. durably write/sync payload and snapshot, then durably publish the independently authenticated current-head witness;
7. acknowledge the producer/source only after current-head publication is durable.

Two synced files are not a distributed transaction. The hard transaction contract is the immutable tuple bound by `ArtifactPublicationTransactionV1`, which makes recovery deterministic without inventing a stronger storage primitive. A host may use a stronger external atomic store only if it preserves the same predecessor, withdrawal, manifest and witness invariants.

V3 admission becomes stale when either the scoped withdrawal head or domain identity changes. `IterationLedgerV1` records externally supplied evidence/transitions but does not run sandboxes, choose candidates, select, promote or release them.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the owner boundary.

## 8. Failure semantics, recovery and rollback

Historical replay and current mutation deliberately use different time semantics. A lifecycle event valid when written remains recoverable after its actor credential expires: snapshot replay validates actor binding at immutable `event.occurred_at`. A new append still validates credential freshness at caller-supplied current `now`. Restart time must not retroactively invalidate valid history.

After an interrupted publication, authenticate the current head and call `classify_artifact_publication_recovery_v1`:

- exact predecessor head with an older generation => `NotCommitted`; candidate files may be orphans and remain unselected;
- exact candidate head with the transaction generation => `Committed`;
- unrelated head or inconsistent generation => hard conflict requiring external reconciliation.

The module never guesses commit state from payload/snapshot files and never rolls back automatically. An old registry/head pair cannot resurrect a withdrawn dataset, revoked ancestor or superseded generation.

Prefer `prepare_registry_snapshot_v1`, `prepare_registry_head_witness_v1` and `prepare_candidate_payload_v1` before final path creation. Predictable semantic rejection then creates no zero-length final-path orphan. Failures after create/write/sync begins remain `Indeterminate`; the host reconciles the exact target/digest. `ArtifactStorageAdminV1` may remove only a proven zero-length regular-file orphan below its enrolled canonical root; non-empty files, directories, symlinks and special files are fail-closed.

Newest-head discovery, directory fsync, product-store reconciliation, backup non-resurrection and external acknowledgement remain host obligations. [Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threats: `artifact_lineage_break`, `current_run_artifact_swap`, and `operator_sensor_clustering`.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Withdrawal admission is namespace/epoch-bound: `registry_id`, `scope_digest`, `authority_id`, nonzero `authority_epoch` and the raw withdrawal chain head are domain-separated before admission is minted. A head from another scope cannot satisfy the receipt even when both raw chains are empty or byte-identical.

`CreateOnlyArtifactFile::create_in` rejects absolute paths, parent traversal and symlinked ancestor escapes after canonicalizing the host-selected root and parent. This is cooperative safe-Rust containment, not proof against a hostile process racing ancestor rename/replacement; target-host openat-style or equivalent guarantees remain a qualification obligation.

Opaque prepared capabilities redact payload bytes from `Debug`. Typed actor evidence does not itself verify a cryptographic signature; the host authenticates it before construction. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts.

Negative tests cover stale/revoked grants, historical replay, withdrawal-domain crossing, payload drift, path escape/symlinks, oversize input, lineage violations, producer self-decision and crash recovery. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

Current code-enforced durable pilot ceilings:

- artifact/withdrawal/lifecycle durable records: `4096`;
- canonical artifact/control snapshot bytes: `8 MiB`;
- candidate payload bytes: `64 MiB`;
- V2 source datasets: `64`; lineage digests: `1024`; predecessor IDs: `64`;
- governed iteration candidates: `32`; files: `100`; diff budget: `1 MiB`; parallel sandboxes: `8`;
- iteration ledger events: `384`.

Snapshot creation/replay is O(history) within the pilot cap and is not a high-frequency journal or hard-real-time controller. Hosts may impose stricter quotas but must not silently widen these limits. Capacity failure occurs before accepting an owner mutation that cannot be represented durably.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define target-host measurement and overload obligations.

## 11. Observability and operations

Operate create-only storage under one owner fence with a current scoped withdrawal frontier and authenticated registry-head witness. Prefer prepare-before-create so deterministic validation fails before a final path exists. For host-selected rooted placement, use `CreateOnlyArtifactFile::create_in`. For explicit orphan reconciliation, enroll the same canonical root with `ArtifactStorageAdminV1`; cleanup is limited to zero-length regular files and syncs the containing directory after removal. Directory durability and hostile-filesystem races still require target qualification.

Durable state formats are:

- `HEPTAR01`: stable artifact registry snapshot;
- `HEPTAH01`: current registry-head witness distribution record;
- `HEPTAW01`: dataset-withdrawal snapshot;
- `HEPTAL02`: lifecycle journal snapshot.

Every durable reader requires an independently retained receipt and exact bounds; re-encoding must match byte-for-byte. Restore must re-establish the current external witness/frontier before any candidate is eligible.

Current references:

- [`STORAGE.md`](../../../codex-rs/hepta-learning-artifacts/STORAGE.md)
- [`READ_BOUNDARY.md`](../../../codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md)
- [`PINNED_LOAD.md`](../../../codex-rs/hepta-learning-artifacts/PINNED_LOAD.md)
- [`DATASET_REVOCATION.md`](../../../codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md)
- [`NATIVE_MAPPING.md`](../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md)

Metrics should distinguish validation rejection, capacity, stale frontier/domain, head mismatch, lock contention, indeterminate I/O, orphan reconciliation, replay corruption and recovery conflict. Concrete alert thresholds remain target-host configuration.

## 12. Verification and qualification

Focused source tests include:

- `registry_tests.rs`: event identity, lineage, eligibility and durable-capacity semantics.
- `storage_tests.rs`, `storage_lock_tests.rs`, `storage_budget_tests.rs`: create-only behavior, bounded reopen, prepared writes, rooted containment, locking and budgets.
- `closure_v2_tests.rs`: V2 manifest, withdrawal and head-witness contracts.
- inline `admission_v3.rs` tests: exact scoped withdrawal head, cross-domain rejection and authority-epoch rotation rejection.
- inline `lifecycle_journal.rs` tests: predecessor/state/role checks and historical replay after credential expiry.
- inline `control_storage.rs` tests: real-file withdrawal/lifecycle persistence, domain/authority-epoch binding and post-expiry reopen.
- inline `storage_hygiene.rs` tests: parent-escape rejection plus zero-length-only orphan cleanup.
- inline `publication.rs` tests: V2-to-V1 publication tuple and crash-before/crash-after current-head classification.
- `dataset_revocation_tests.rs`: direct/descendant invalidation and persistence.
- inline `iteration.rs` / `iteration_ledger.rs` tests: bounded transitions, independent evidence and exact replay.

Focused command: `just test -p codex-hepta-learning-artifacts` from `codex-rs`. Lane E additionally requires locked all-target compilation, strict Clippy with `-D warnings`, formatting/clean-tree checks, cross-crate causal closure and cross-language fault closure.

`.github/workflows/hepta-lane-e-gap-closure.yml` must pass both exact source and actual-base synthetic-merge jobs. Its synthetic merge has a valid base for pull requests and pushes: PR base SHA for `pull_request`, `github.event.before` for `push`, with initial-push zero-SHA fallback.

A command or test source is not a pass receipt. Only the current candidate's completed CI results count as qualification evidence.

## 13. Implementation sequence and work packages

Applicable work packages are `ART-1-LEARNING-ARTIFACT-REGISTRY`, `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK` and `HBO-1-OPERATOR-SENSOR-CORE`.

The current native source candidate implements repository-controlled slices for immutable registry/storage, V2/V3 admission closure, withdrawal/lifecycle durable replay, publication crash classification and governed iteration bookkeeping. This source status is deliberately separate from the canonical work-package delivery state rendered below: those envelopes may remain `planned` until required evidence, composition and activation predecessors are satisfied.

Repository-controlled source closure requires the declared root, current implementation map, package tests, all-target compilation, strict lint, clean tracked state, exact-head execution and actual-base synthetic-merge execution. Product composition, target-host qualification, independent review, activation and release remain later gates.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, a current implementation map and closed-world validation. Source completion requires the native root plus a green exact-candidate and merge-candidate evidence set. Product composition requires a named authenticated caller and owner-store integration. Target-host qualification separately proves filesystem/directory durability and race behavior. Independent acceptance, selection, promotion and release remain externally governed.

Current claim boundary:

- native source mapping: implemented for registry, V2/V3 admission, lifecycle, withdrawal, publication recovery, storage and iteration;
- product caller: not composed;
- production writer: not established;
- exact-head / actual-base merge qualification: must be green for the current PR head before source completion is claimed;
- activation / independent acceptance / release: not claimed.

The canonical work-package envelopes below are registry projections. A `planned` delivery-state label is not evidence that source files are absent, and source presence does not itself advance canonical delivery state.

For `learning.artifacts`, this document grants no runtime, production, model, provider, tool, network, filesystem credential, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `ART-1-LEARNING-ARTIFACT-REGISTRY`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
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

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
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

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
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

The bounded native implementation root is `codex-rs/hepta-learning-artifacts`. The current candidate includes stable V1 registry/storage compatibility plus additive V2/V3 admission, scoped withdrawal, lifecycle journal, durable control snapshots, publication recovery and governed iteration surfaces described above.

Candidate qualification is provided by repository workflows rather than by this prose. `.github/workflows/hepta-lane-e-gap-closure.yml` exercises the Lane E exact-source and synthetic-merge path; consolidated source checks continue to enforce wider repository inventory/compilation/lint/cleanliness obligations. Only completed current-head evidence may be used as a pass receipt.

This source receipt grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
