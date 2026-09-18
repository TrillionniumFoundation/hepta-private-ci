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

The [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.artifacts.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.artifacts.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.artifacts.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.artifacts.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

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

- [codex-rs/hepta-learning-artifacts/STORAGE.md](../../../codex-rs/hepta-learning-artifacts/STORAGE.md).
- [codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md](../../../codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md).
- [codex-rs/hepta-learning-artifacts/PINNED_LOAD.md](../../../codex-rs/hepta-learning-artifacts/PINNED_LOAD.md).
- [codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md](../../../codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/closure_v2_tests.rs); named case: `art_01_manifest_v2_normalizes_complete_lineage`.
- [codex-rs/hepta-learning-artifacts/src/dataset_revocation_tests.rs](../../../codex-rs/hepta-learning-artifacts/src/dataset_revocation_tests.rs); named case: `batch_revokes_direct_targets_and_blocks_descendants_without_mutating_input`.

In `codex-rs`, run `just test -p codex-hepta-learning-artifacts`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.artifacts.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

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


## 18. Current native closure, durability and host boundary

The module-specific source closure represented by
`docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json` now includes the
stable V1 registry/storage surface plus the additive V2/V3 admission,
withdrawal, lifecycle and governed-iteration surfaces. The map's `sourceBase`
remains the repository-wide implementation-map generation identity shared by
all module maps; its `implementationHead` records the newer
`learning.artifacts` source closure reviewed by this guide.

### 18.1 Bounded durable histories

All crate-owned append-only histories that are expected to round-trip through
the create-only snapshot formats use the shared
`MAX_DURABLE_HISTORY_RECORDS = 4096` ceiling. The stable V1 artifact registry,
the scoped dataset-withdrawal registry and the lifecycle journal must reject a
new append before they can enter a state that the bounded durable formats cannot
represent. The byte ceiling remains independently enforced by each format.

The stable artifact snapshot remains `HEPTAR01`. Additive create-only sidecar
formats provide durable semantic replay for the other authoritative histories:

- `HEPTAW01` persists one scoped `DatasetWithdrawalRegistry`, including its
  registry identity, scope digest, exact notice sequence and head;
- `HEPTAL02` persists `ArtifactLifecycleJournalV2`, including predecessor
  head, actor evidence and the complete lifecycle event for every record.

Readers require an independently retained receipt, verify bounded exact bytes,
replay the source semantics and reject non-canonical re-encoding.

### 18.2 Historical lifecycle recovery

A lifecycle actor must be currently valid when creating a new mutation.
Historical snapshot replay is different: each persisted record is revalidated
at its immutable `event.occurred_at` time. Therefore a credential that was
valid when an event was accepted may later expire without making the immutable
history unrecoverable. Reopening after expiry must succeed; attempting a new
append with the expired credential must still fail.

### 18.3 Scoped withdrawal authority

V3 withdrawal-aware admission requires a
`WithdrawalRegistryBindingV1 { registry_id, scope_digest }`. The binding is
domain-separated into its own digest and is carried by the withdrawal snapshot
and `WithdrawalBoundArtifactAdmissionV3`. The V3 admission digest binds the
complete V2 manifest digest, withdrawal registry binding, exact withdrawal head
and admission time.

Two registries with an identical event head are not interchangeable when their
registry identity or scope differs. Legacy unscoped withdrawal registries remain
usable for the V2 source API, but they cannot issue a V3 publication admission.

### 18.4 V3 admission to durable registry publication

`prepare_artifact_publication_v3` and
`revalidate_artifact_publication_v3` define the crate-side transaction
contract. Preparation returns `PreparedArtifactPublicationV3`, which deliberately
does not expose the staged registry or durable snapshot binding. Preparation binds:

1. the V3 admission digest;
2. withdrawal registry/scope binding and exact withdrawal head;
3. the expected stable V1 registry predecessor head;
4. the exact V1 register-event digest;
5. the resulting stable registry head.

The resulting transaction digest is the required binding for the create-only
registry snapshot. Immediately before publication, while holding the host
writer fence, the host consumes the prepared value through
`revalidate_artifact_publication_v3`. A changed registry head or withdrawal
frontier fails closed. Only the returned `RevalidatedArtifactPublicationV3`
exposes the staged registry and snapshot binding, so the safe API cannot publish
a prepared-but-not-revalidated registry snapshot.

The stable V1 durable registry has one predecessor slot and one `support_digest`
slot. A V2 manifest with multiple predecessors is therefore refused instead of
silently discarding lineage. A dataset-derived V2 manifest is losslessly bridged
only when it references exactly one source dataset; that dataset digest remains
the V1 `support_digest`, preserving the existing `prepare_dataset_revocation`
lookup semantics. Dataset-independent artifacts use the complete validated V2
manifest digest as their V1 support commitment. Multi-dataset V2 publication is
refused by the stable V1 bridge until a versioned durable format can represent
all source datasets explicitly. A future multi-predecessor or multi-dataset
encoding requires a new versioned format rather than an in-place reinterpretation.

Cross-file durability remains a bounded saga, not a claimed filesystem
transaction: payload synchronization, registry snapshot creation and current
head-witness publication are distinct durable effects. The externally visible
commit point is the host's authenticated publication of the exact registry
snapshot/current-head witness pair. Crash recovery reconciles by transaction
digest, exact predecessor and independently retained receipts.

### 18.5 Iteration and iteration-ledger contracts

`iteration.rs` owns bounded iteration-envelope and candidate transition
semantics only. `iteration_ledger.rs` records bounded externally supplied
evidence and rebuilds candidate state exclusively by replaying that evidence.
Neither surface executes a sandbox, evaluates code, chooses a winner, merges a
candidate, promotes it or releases it. Evidence requiring independence rejects
the generator identity where the state transition requires a separate actor.

### 18.6 Host-owned obligations and non-claims

The source crate now owns the deterministic validation, create-only bytes,
semantic replay and digest-bound publication contracts described above. The
product host still owns all capabilities that require an authenticated or
platform-specific environment:

- newest/current snapshot and witness discovery;
- signature verification, key distribution and principal authentication;
- writer fencing and serialized publication;
- trusted ancestor-directory traversal, namespace containment and
  containing-directory synchronization;
- encryption, quota, retention, backup deletion and physically deleting a
  proven orphan;
- target-filesystem locking/power-loss qualification;
- independently authorized selection, process loading, canary, promotion and
  release.

An empty or partial file left after a failed create-only write is never silently
reused. `inspect_orphan_candidate` can hash and classify a caller-opened file
against a bounded set of independently retained digests under a shared lock; it
does not delete the file and does not turn absence from that digest set into
deletion authority. Cleanup is a separately fenced host operation that must
first prove the path/identity is not referenced by any current or retained
historical receipt.

`inspect_artifact_admin_state` is the crate's read-only operational surface for
already-supplied registry, withdrawal and lifecycle objects. It reports chain
heads, record counts, direct artifact states and eligibility counts and always
returns `AuthorityPosture::DENY_ALL`. It neither discovers the latest state nor
mutates, selects, activates, promotes or releases an artifact.

### 18.7 Qualification

`.github/workflows/hepta-lane-e-gap-closure.yml` qualifies the exact PR source
and an ordered-parent synthetic merge. Pull requests use the PR base SHA; push
qualification uses `github.event.before`, with the all-zero initial-push value
falling back to the source commit's parent. Compilation, owner tests,
cross-crate closure, strict Clippy, rustfmt and clean-tree checks must all be
green before this source closure is treated as repository-qualified.

These source changes do not change the capability ceiling: product execution,
independent acceptance, activation and release remain separate evidence gates.
