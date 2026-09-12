# learning.eval technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.eval`

**Owner:** `learning-platform`

**Deputy:** `qualification-plane`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `LRN-2-CAUSAL-EVALUATION`

This stable document is the implementation guide for `learning.eval`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Perform support-aware causal and longitudinal evaluation independently from the production writer.

The primary owner `learning-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `qualification-plane` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `qualification`, kind `engine`, state model `stateful_shadow` and architecture role `qualification` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-intelligence-eval`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-intelligence-eval`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs); observed identifiers include `TemporalEvaluationPlan`, `TemporalEvaluationReceipt`, `TemporalEvaluationError`, `evaluate_temporal_holdout`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.eval.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `learning.ledger`
- `learning.artifacts`
- `kernel.evidence`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `production_write`
- `production_writer_dependency`
- `self_issued_acceptance`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bounded input stage`
- `deterministic algorithm core`
- `generation publisher`
- `checkpoint and recovery layer`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `EvaluationReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::learning.eval::intelligence.control`
- `ModulePort::learning.eval::learning.plasticity`
- `UnlearningComplianceReceiptV1`

Consumed contracts:

- `BellmanOperatorArtifactV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `LearningArtifactManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LocalModelRuntimeReceiptV1`
- `ModulePort::kernel.evidence::learning.eval`
- `ModulePort::learning.artifacts::learning.eval`
- `ModulePort::learning.ledger::learning.eval`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `PlasticityProposalV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `RegularityProfileV1`
- `TopologyProposalV1`

Critical protocol schemas:

- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `EvaluationReceiptV1`
- `LearningArtifactManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LocalModelRuntimeReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `RegularityProfileV1`
- `TopologyProposalV1`
- `UnlearningComplianceReceiptV1`

### Temporal evaluation digest compatibility

The internal `TemporalEvaluationPlan` composite digest follows the canonical machine-readable profile in `docs/learning/LEARNING_SYSTEM.json` and the normative algorithm text in `docs/learning/CAUSAL_LONGITUDINAL_SPEC.md`. The plan preimage is SHA-256 over the unframed `hepta.ope.temporal-evaluation-plan.v1` domain followed, in order, by the framed evaluation ID, objective digest, every fold field, every OPE field and every confidence field. The stored top-level digest is excluded from its own preimage. The fold, OPE and confidence child plan digests remain independent values; the composite binds them without aliasing them.

Evaluation rejects zero or stale composite plan digests before fitting or estimation. `usize` counts are checked before canonical `u64` big-endian encoding; fixed Q32 values use signed raw `i64` big-endian bytes; IDs use `u32` big-endian UTF-8 byte length followed by exact UTF-8 bytes; digests use raw 32 bytes.

`TemporalEvaluationReceipt.evidence_digest` uses the unframed `hepta.ope.temporal-holdout-pipeline.v2` domain and binds, in order, evaluation ID, composite plan digest, objective digest, fitted model digest, fitted predictions digest and cluster-estimate evidence digest. Version 2 is not wire-compatible with the previous v1 digest preimage: historical v1 evidence stays version-tagged and cannot be reinterpreted as v2. These internal digest profiles do not create a published contract or alter the authority of `EvaluationReceiptV1` and `LongitudinalEvaluationReceiptV1`.

Canonical vector `TEMPORAL-PLAN-DIGEST-GV-001` fixes the complete 293-byte composite preimage and expected digest `dba5b45f87d6a8ef08dccfc9b2108a1456d94b226c3315777c3de2f15f4219b3`; source tests must compare against that hard-coded oracle rather than a value emitted by the implementation under test.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `operator_sensor_core_registry`
- `qualification_evidence`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.eval.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.eval.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `catastrophic_forgetting`
- `deleted_data_resurrection`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Independent evaluation library. Freeze the estimand, split, thresholds, nuisance-model profile and evaluator identity before final outcomes. Persist results through their declared evidence owner. A supported analytic or offline estimate does not create real future calendar windows or authorize selection.

Current operating and state-format references:

- [codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md).
- [codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md](../../../codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md).
- [docs/readiness/LEARNING_EVALUATION_EXECUTION.md](../../readiness/LEARNING_EVALUATION_EXECUTION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-intelligence-eval/src/closure_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/closure_tests.rs); named case: `eval_03_intersects_superiority_safety_retention_and_unlearning`.
- [codex-rs/hepta-intelligence-eval/src/lib_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/lib_tests.rs); named case: `eligible_is_not_promotion`.

In `codex-rs`, run `just test -p codex-hepta-intelligence-eval`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.eval.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `LRN-2-CAUSAL-EVALUATION`
- `LONG-1-TEMPORAL-HOLDOUT`
- `LONG-2-RETENTION-FORGETTING`
- `LONG-3-UNLEARNING-NON-RESURRECTION`

The bootstrap package is `LRN-2-CAUSAL-EVALUATION`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `learning.eval`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `LRN-2-CAUSAL-EVALUATION`

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-intelligence-eval/**`
- `qa/learning/evaluation/**`
- Development predecessors:
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- Activation predecessors:
- `C1-PROMPTED-MEMORY-RETRIEVAL-RANK`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
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
- `support_coverage`
- `ess_ips_snips_dr`
- `cluster_or_bootstrap_ci`
- `candidate_lcb_gt_baseline_ucb`
- `subgroup_and_safety_floor`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `LONG-1-TEMPORAL-HOLDOUT`

- State: `planned`; priority: `2`; parallel class: `external_evidence_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `qa/learning/longitudinal/**`
- Development predecessors:
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- Activation predecessors:
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
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
- `future_time_window`
- `distribution_shift`
- `delayed_outcome_watermark`
- `confidence_bounds`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `LONG-2-RETENTION-FORGETTING`

- State: `planned`; priority: `2`; parallel class: `external_evidence_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `qa/learning/retention/**`
- Development predecessors:
- `LONG-1-TEMPORAL-HOLDOUT`
- Activation predecessors:
- `LONG-1-TEMPORAL-HOLDOUT`
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
- `old_task_holdout`
- `backward_transfer`
- `forgetting_bound`
- `adapter_retirement`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `LONG-3-UNLEARNING-NON-RESURRECTION`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `qa/learning/unlearning/**`
- `codex-rs/hepta-intelligence-eval/**`
- Development predecessors:
- `LONG-2-RETENTION-FORGETTING`
- `LRN-2-CAUSAL-EVALUATION`
- Activation predecessors:
- `LONG-2-RETENTION-FORGETTING`
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
- `lineage_complete`
- `artifact_revocation`
- `backup_restore_non_resurrection`
- `rebuild_excludes_deleted`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `learning.eval` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `AlgorithmFaultReceiptV1`
- `CandidateEvaluationReceiptV1`
- `ConformanceReceiptV1`
- `EvaluationReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `ModulePort::learning.eval::intelligence.control`
- `ModulePort::learning.eval::learning.plasticity`
- `NduWellPosednessCertificateV1`
- `OperatorApplicabilityCertificateV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`
- `UnlearningComplianceReceiptV1`

**Consumed contracts:**
- `BellmanOperatorArtifactV1`
- `CandidateSetCompletenessReceiptV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `GoldenFixtureManifestV1`
- `IterationCandidateV1`
- `IterationEnvelopeV1`
- `LearningArtifactManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LocalModelRuntimeReceiptV1`
- `ModulePort::kernel.evidence::learning.eval`
- `ModulePort::learning.artifacts::learning.eval`
- `ModulePort::learning.ledger::learning.eval`
- `NduCoefficientManifestV1`
- `NduUpdateReceiptV1`
- `NeuronCheckpointV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `OutcomeWatermarkV1`
- `PlasticityProposalV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `RandomStreamManifestV1`
- `TopologyProposalV1`

**Typed protocols:**
- `AlgorithmFaultReceiptV1`
- `CandidateEvaluationReceiptV1`
- `CandidateSetCompletenessReceiptV1`
- `ConformanceReceiptV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `EvaluationReceiptV1`
- `GoldenFixtureManifestV1`
- `IterationCandidateV1`
- `IterationEnvelopeV1`
- `LearningArtifactManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `LocalModelRuntimeReceiptV1`
- `LongitudinalEvaluationReceiptV1`
- `NduCoefficientManifestV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `NeuronCheckpointV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `OutcomeWatermarkV1`
- `PlasticityProposalV1`
- `PromptCandidateSetReceiptV1`
- `PromptDeliveryObservationV1`
- `RandomStreamManifestV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`
- `TopologyProposalV1`
- `UnlearningComplianceReceiptV1`

**Owned data domains:**
- `algorithm_fault_receipt_v1`
- `candidate_evaluation_receipt_v1`
- `conformance_receipt_v1`
- `ndu_well_posedness_certificate_v1`
- `operator_applicability_certificate_v1`
- `regularity_profile_v1`
- `support_audit_receipt_v1`

**Read data domains:**
- `candidate_set_completeness_receipt_v1`
- `golden_fixture_manifest_v1`
- `iteration_candidate_v1`
- `iteration_envelope_v1`
- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `ndu_coefficient_manifest_v1`
- `ndu_update_receipt_v1`
- `neuron_checkpoint_v1`
- `operator_sensor_core_manifest_v1`
- `operator_sensor_core_registry`
- `outcome_watermark_v1`
- `plasticity_proposal_v1`
- `qualification_evidence`
- `random_stream_manifest_v1`
- `topology_proposal_v1`

**Work packages:**
- `LONG-1-TEMPORAL-HOLDOUT`
- `LONG-2-RETENTION-FORGETTING`
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `LRN-2-CAUSAL-EVALUATION`

**Owned threats:**
- `catastrophic_forgetting`
- `deleted_data_resurrection`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.eval` to primary lane `LANE-E-LEARNING`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-NDU`](../../readiness/NDU_SYSTEM_EXECUTION.md)
- [`RDY-NEU`](../../readiness/NEURON_RUNTIME_EXECUTION.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)
- [`RDY-SI`](../../readiness/SELF_ITERATION_EXECUTION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)

Owned readiness protocols:

- `EvaluationPlanV1`
- `NduConvergenceCertificateV1`
- `RetentionSliceReceiptV1`

Consumed readiness protocols:

- `AssimilationProposalV1`
- `CandidateLineageV1`
- `EvaluatorIndependenceReceiptV1`
- `MutationGrammarManifestV1`
- `NduIterationReceiptV1`
- `NeuronRuntimeConfigV1`
- `NeuronTickReceiptV1`
- `SandboxExecutionReceiptV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-3-STATE-MIGRATION-QUALIFICATION`
- `EMB-3-HIL-SIM-TO-REAL-QUALIFICATION`

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.eval` is implemented by work package `LRN-2-CAUSAL-EVALUATION` in:

- `codex-rs/hepta-intelligence-eval`

The source candidate is checked by `.github/workflows/hepta-gap-closure.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
