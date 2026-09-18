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

### 2.1 Current source implementation boundary

The implementation map records code-complete module evidence at
`ab6ca237d427635fc233b187765173bbf56ebd0a`. The v3 `sourceBase` field remains
the repository-wide implementation-map catalog baseline because the verifier
requires every module map to share one source identity; `moduleSourceCommit`
records the newer module-local code snapshot without falsifying that global
catalog invariant.

At this module-local snapshot the source is materially implemented, but not yet
product-composed:

- V1 append-only artifact registry with deterministic replay, eligibility and
  ancestry-based quarantine/revocation.
- create-only registry snapshots, current-head witnesses and candidate payloads.
- V2 complete manifest validation and lineage normalization.
- scoped dataset-withdrawal registry whose event/chain digests bind
  `registry_id + scope_digest + authority_id`.
- V3 admission bound to both the withdrawal registry identity and exact head.
- V2 lifecycle journal with role separation and historical replay semantics:
  historical credentials are checked against event time, while new mutations
  require a credential current at `now`.
- create-only durable withdrawal and lifecycle snapshots with exact receipts and
  canonical replay.
- typed `ArtifactPublicationCommitV1` joining V3 admission, V1 registry,
  withdrawal and lifecycle durable frontiers under one host store binding.
- bounded dataset-revocation preparation.
- governed self-iteration envelope/transition types and append-only
  `IterationLedgerV1` evidence bookkeeping.
- pinned read/revalidation surfaces.
- create-only storage hardening including bounded capacities, empty staging-file
  cleanup and `create_under` containment checks.

The remaining source-to-production boundary is host composition: authenticated
current-pointer publication, race-resistant trusted directory/object-store
capability, directory durability, service identity/signature policy, operator
tooling and product execution evidence.

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

The bounded implementation components are:

- `model.rs` / `registry.rs`: V1 immutable registry, event identity, lineage
  eligibility and replay.
- `storage.rs`: create-only payload/registry/head-witness persistence, bounded
  readers, storage receipts and path/staging hardening.
- `closure_v2.rs`: V2 manifests, scoped dataset withdrawals, registry-head and
  lifecycle transition validation.
- `admission_v3.rs`: withdrawal-registry/head-bound admission and publication
  revalidation.
- `lifecycle_journal.rs`: append-only lifecycle role/state journal with
  separated current authorization and historical replay validation.
- `durable_aux.rs`: create-only withdrawal/lifecycle durable snapshots.
- `publication.rs`: typed publication commit joining all durable frontiers and
  defining the host's single final visibility point.
- `dataset_revocation.rs`: atomic preparation of V1 registry revocations for
  exact dataset support.
- `pinned.rs`: exact pinned candidate load plus fail-closed revalidation.
- `iteration.rs` / `iteration_ledger.rs`: authority-free governed iteration
  states and externally evidenced transition bookkeeping.
- `limits.rs`: shared durable/in-memory capacity contract.

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

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

Owned authoritative or rebuildable domains:

- `learning_artifact_registry`
- `operator_sensor_core_registry`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The V1 registry, scoped withdrawal registry, lifecycle journal and iteration
ledger are independent in-memory state machines. They reject identity conflicts,
stale heads, invalid transitions and capacity overflow before mutation. Current
durable ceilings are intentionally aligned: registry, withdrawal and lifecycle
state each cap at 4096 records so the in-memory state accepted by the crate is
representable by its durable format.

The create-only storage layer uses exclusive advisory locking for writes and
shared advisory locking for bounded reads. Existing final path components are
never reopened for writing. On Unix, an uncommitted empty file remains associated
with its created inode and is removed on capability drop when identity and
zero-length still match; nonempty or interfered files are left for reconciliation.

### 7.1 Historical lifecycle replay

`ArtifactLifecycleJournalV2::append` authorizes a new mutation at the supplied
current `now`. `from_snapshot` instead verifies immutable actor evidence and
requires `event.occurred_at` to lie within the historical credential window.
Reopening after credential expiry therefore succeeds for a previously valid
event, while a new append using the same expired credential fails. Snapshot
events from the future relative to reopen `now` are rejected.

### 7.2 Withdrawal domain separation

`DatasetWithdrawalRegistryBindingV1` binds `registry_id`, `scope_digest` and
`authority_id`. That binding digest is included in withdrawal event/chain
digests and in V3 admission. Equal head bytes in different scopes (including two
empty zero heads) are therefore not interchangeable.

### 7.3 Durable publication transaction

The authoritative protocol is
[`PUBLICATION_TRANSACTION.md`](../../../codex-rs/hepta-learning-artifacts/PUBLICATION_TRANSACTION.md).
Registry, withdrawal and lifecycle snapshots are staged and synced first.
`prepare_artifact_publication_v1` validates their exact receipts, the still
current V3 admission and the corresponding V1/V2 artifact identity, then creates
one deny-all `ArtifactPublicationCommitV1`. The commit marker is also create-only.

All of those objects remain staging until the host performs one fenced atomic
replacement of its authenticated current-publication pointer. The crate does not
claim a cross-filesystem transaction manager. The host must serialize that final
pointer operation and synchronize containing directories/object-store metadata
according to the target platform.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Recovery is receipt-first and fail-closed. Registry, withdrawal, lifecycle and
publication-commit readers require independently retained receipts, bounded byte
counts and exact file digests, then replay the canonical state machine. They do
not repair corrupt state or silently fall back to an older generation.

The publication crash invariant is: before the host current-pointer replacement,
the previous publication remains current even when every new staged object and
commit marker is durable. After pointer replacement, retry/acknowledgement uses
the exact commit digest idempotently. A reader must never select a generation by
directory enumeration or maximum generation number.

Create-only pre-write rejection reaps an empty owned Unix staging inode where
safe. A nonempty/identity-drifted object is intentionally not deleted by the
crate; it is an unreachable orphan until a separately authorized host
reconciler proves it unreferenced. Target-host orphan scanning, retention,
metrics and deletion authorization remain operational responsibilities.

Rollback means following an authenticated predecessor publication/manifest whose
current registry and withdrawal/lifecycle state still permits use. Restoring an
old self-consistent snapshot or commit cannot bypass a newer withdrawal or
revocation witness.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `artifact_lineage_break`
- `current_run_artifact_swap`
- `operator_sensor_clustering`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.artifacts.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-learning-artifacts/src/lib.rs](../../../codex-rs/hepta-learning-artifacts/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Operate create-only candidate storage under one owner, with pinned read bounds and current revocation/head witnesses. Sync bytes before registry publication; incomplete/orphan payloads remain unselected. Reload an exact independently selected compatible tuple; restoring an older registry must not resurrect withdrawn datasets or artifacts.

Current operating and state-format references:

- [codex-rs/hepta-learning-artifacts/PUBLICATION_TRANSACTION.md](../../../codex-rs/hepta-learning-artifacts/PUBLICATION_TRANSACTION.md).
- [codex-rs/hepta-learning-artifacts/STORAGE.md](../../../codex-rs/hepta-learning-artifacts/STORAGE.md).
- [codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md](../../../codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md).
- [codex-rs/hepta-learning-artifacts/PINNED_LOAD.md](../../../codex-rs/hepta-learning-artifacts/PINNED_LOAD.md).
- [codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md](../../../codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-learning-artifacts/src/lifecycle_journal.rs](../../../codex-rs/hepta-learning-artifacts/src/lifecycle_journal.rs): historical snapshot reopen after actor credential expiry, with new append still rejected.
- [codex-rs/hepta-learning-artifacts/src/admission_v3.rs](../../../codex-rs/hepta-learning-artifacts/src/admission_v3.rs): identical withdrawal head in a different scope rejects by binding.
- [codex-rs/hepta-learning-artifacts/src/durable_aux.rs](../../../codex-rs/hepta-learning-artifacts/src/durable_aux.rs): withdrawal/lifecycle durable round trips and post-expiry lifecycle reopen.
- [codex-rs/hepta-learning-artifacts/src/publication.rs](../../../codex-rs/hepta-learning-artifacts/src/publication.rs): all durable frontiers are commit-bound and crash-before-pointer-publish keeps the predecessor current.
- [codex-rs/hepta-learning-artifacts/src/storage_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/storage_tests.rs): create-only conflicts, symlinks, concurrency, staging cleanup and `create_under` containment.
- [codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs): V2 lineage plus withdrawal scope/authority replay.
- [codex-rs/hepta-learning-artifacts/src/dataset_revocation_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/dataset_revocation_tests.rs): atomic multi-target revocation preparation and durable reopen.
- [codex-rs/hepta-learning-artifacts/src/iteration.rs](../../../codex-rs/hepta-learning-artifacts/src/iteration.rs) and [iteration_ledger.rs](../../../codex-rs/hepta-learning-artifacts/src/iteration_ledger.rs): bounded governed iteration transitions and evidence replay.
- [codex-rs/hepta-shadow-qualification/tests/lane_e_api_contract.rs](../../../codex-rs/hepta-shadow-qualification/tests/lane_e_api_contract.rs): cross-crate linkage for registry, withdrawal, lifecycle, durable and publication APIs.

In `codex-rs`, run `just test -p codex-hepta-learning-artifacts`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.artifacts.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `HBO-1-OPERATOR-SENSOR-CORE`

The bootstrap package is `ART-1-LEARNING-ARTIFACT-REGISTRY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

The `State: planned` labels in the generated work-package envelopes below are
canonical program-scheduling fields projected from the registry; they are not a
statement that the module root is empty or that the native surfaces listed in
Section 2.1 are absent. Source implementation, product composition, activation
and release are intentionally tracked as separate facts.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `learning.artifacts`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

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

The bootstrap source-location obligation for `learning.artifacts` is implemented by work package `ART-1-LEARNING-ARTIFACT-REGISTRY` in:

- `codex-rs/hepta-learning-artifacts`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
