# kernel.evidence technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `kernel.evidence`

**Owner:** `qualification-plane`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.9-EXTERNAL-GATES`

This stable document is the implementation guide for `kernel.evidence`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Preserve exact-candidate evidence and integrity without converting qualification into promotion authority.

The primary owner `qualification-plane` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `qualification`, kind `evidence`, state model `stateful` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-evidence`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-evidence`

Non-authoritative implementation evidence roots:

- `codex-rs/hepta-evidence`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-evidence/src/provider_effect_store.rs](../../../codex-rs/hepta-evidence/src/provider_effect_store.rs); observed identifiers include `StoredProviderEffect`, `append_provider_effect_intent`, `dispatch_provider_effect_qualification`, `append_provider_effect_ack`, `mark_provider_effect_indeterminate`, `reconcile_provider_effect_lookup`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/kernel.evidence.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.evidence.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`

Authoritative write domains:

- `qualification_evidence`

Explicitly denied capabilities:

- `runtime_effect`
- `promotion_authority`
- `self_issued_independent_review`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `append-only receipt store`
- `integrity verifier`
- `query projection`
- `retention and export boundary`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::qualification_evidenceV1`
- `ModulePort::kernel.evidence::control.engineering`
- `ModulePort::kernel.evidence::control.runtime`
- `ModulePort::kernel.evidence::learning.eval`
- `ModulePort::kernel.evidence::learning.operator`
- `ModulePort::kernel.evidence::learning.plasticity`

Consumed contracts:

- `DomainRead::automation_occurrenceV1`
- `DomainRead::automation_scheduleV1`
- `DomainRead::browser_profile_stateV1`
- `DomainRead::compact_checkpointV1`
- `DomainRead::global_state_snapshotV1`
- `DomainRead::integration_decisionV1`
- `DomainRead::matrix_dispatch_ledgerV1`
- `DomainRead::matrix_ingress_projectionV1`
- `DomainRead::optimization_decisionV1`
- `DomainRead::plasticity_proposal_registryV1`
- `DomainRead::secret_leaseV1`
- `DomainRead::secret_metadataV1`
- `DomainRead::work_assignment_projectionV1`
- `EvaluationReceiptV1`
- `LocalModelRuntimeReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::platform.types::kernel.evidence`
- `OutboxReceiptV1`
- `ReconciliationReceiptV1`
- `UnlearningComplianceReceiptV1`

Critical protocol schemas:

- `EvaluationReceiptV1`
- `LocalModelRuntimeReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `UnlearningComplianceReceiptV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `qualification_evidence`

Read-only data dependencies:

None.

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/kernel.evidence.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.evidence.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/kernel.evidence.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.evidence.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.evidence.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-evidence/src/provider_effect_store.rs](../../../codex-rs/hepta-evidence/src/provider_effect_store.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Operate through the existing evidence store and its migrations. Keep candidate, issuer and terminal-observer identities separate; query integrity before admitting restored evidence. Qualification dispatch and stored caller observations must not be exposed as a production issuer or remote terminal oracle.

Current operating and state-format references:

- [codex-rs/hepta-evidence/src/provider_effect_store.rs](../../../codex-rs/hepta-evidence/src/provider_effect_store.rs).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-evidence/src/authbus_outbox_issuer_tests.rs](../../../codex-rs/hepta-evidence/src/authbus_outbox_issuer_tests.rs); named case: `current_issuer_scan_cannot_be_starved_by_older_epochs_or_other_issuers`.
- [codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs](../../../codex-rs/hepta-evidence/src/authbus_outbox_quarantine_tests.rs); named case: `quarantine_requires_current_fence_and_survives_reopen_without_acknowledgement`.

In `codex-rs`, run `just test -p codex-hepta-evidence`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.evidence.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.9-EXTERNAL-GATES`

The bootstrap package is `P0.9-EXTERNAL-GATES`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `kernel.evidence`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `P0.9-EXTERNAL-GATES`

- State: `blocked_external`; priority: `0`; parallel class: `external_independent`.
- Owner/deputy: `qualification-plane` / `security-authority`.
- Allowed write paths:
None.
- Development predecessors:
- `P0.8D-VERTICAL-SLICE`
- Activation predecessors:
- `P0.8D-VERTICAL-SLICE`
- Required deliverables:
- `repository_ruleset`
- `independent_exact_candidate_review`
- `real_model_provider_corpus`
- `physical_platform`
- `operator_acceptance`
- `trust_root_ceremony`
- `promotion`
- `release`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `kernel.evidence` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `DomainRead::qualification_evidenceV1`
- `IndependentDecisionReceiptV1`
- `ModulePort::kernel.evidence::control.engineering`
- `ModulePort::kernel.evidence::control.runtime`
- `ModulePort::kernel.evidence::learning.eval`
- `ModulePort::kernel.evidence::learning.operator`
- `ModulePort::kernel.evidence::learning.plasticity`

**Consumed contracts:**
- `AlgorithmFaultReceiptV1`
- `CandidateEvaluationReceiptV1`
- `ConformanceReceiptV1`
- `DomainRead::automation_occurrenceV1`
- `DomainRead::automation_scheduleV1`
- `DomainRead::browser_profile_stateV1`
- `DomainRead::compact_checkpointV1`
- `DomainRead::global_state_snapshotV1`
- `DomainRead::integration_decisionV1`
- `DomainRead::matrix_dispatch_ledgerV1`
- `DomainRead::matrix_ingress_projectionV1`
- `DomainRead::optimization_decisionV1`
- `DomainRead::plasticity_proposal_registryV1`
- `DomainRead::secret_leaseV1`
- `DomainRead::secret_metadataV1`
- `DomainRead::work_assignment_projectionV1`
- `EvaluationReceiptV1`
- `LocalModelRuntimeReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::platform.types::kernel.evidence`
- `OutboxReceiptV1`
- `ReconciliationReceiptV1`
- `UnlearningComplianceReceiptV1`

**Typed protocols:**
- `AlgorithmFaultReceiptV1`
- `CandidateEvaluationReceiptV1`
- `ConformanceReceiptV1`
- `EvaluationReceiptV1`
- `IndependentDecisionReceiptV1`
- `LocalModelRuntimeReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `UnlearningComplianceReceiptV1`

**Owned data domains:**
- `independent_decision_receipt_v1`
- `qualification_evidence`

**Read data domains:**
- `algorithm_fault_receipt_v1`
- `candidate_evaluation_receipt_v1`
- `conformance_receipt_v1`

**Work packages:**
- `P0.9-EXTERNAL-GATES`

**Owned threats:**
- None.

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `kernel.evidence` to primary lane `LANE-A-FOUNDATION`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)
- [`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- `AssimilationQualificationReceiptV1`
- `CanonicalSourceReceiptV1`
- `EvaluatorIndependenceReceiptV1`

Consumed readiness protocols:

- `ActuatorReconciliationReceiptV1`
- `AssimilationProposalV1`
- `BranchPurposeManifestV1`
- `CapabilityBoundaryV1`
- `EmergencyStopReceiptV1`
- `ExternalSystemManifestV1`
- `IntegrationCheckpointV1`
- `MigrationPlanV1`
- `ObjectiveSourceEnvelopeV1`
- `RealTimeLoopProfileV1`
- `RollbackPointV1`
- `SandboxExecutionReceiptV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-3-STATE-MIGRATION-QUALIFICATION`
- `EMB-3-HIL-SIM-TO-REAL-QUALIFICATION`
