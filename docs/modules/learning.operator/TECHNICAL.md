# learning.operator technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `learning.operator`

**Owner:** `learning-platform`

**Deputy:** `qualification-plane`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `HBO-0-BELLMAN-OPERATOR-CONTRACTS`

This stable document is the implementation guide for `learning.operator`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Train bounded Bellman/operator candidates in qualification space without online production mutation.

The primary owner `learning-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `qualification-plane` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `qualification`, kind `trainer`, state model `stateful_shadow` and architecture role `slow_learner` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-bellman-operator`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-bellman-operator`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `learning.operator`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `learning.ledger`
- `learning.artifacts`
- `kernel.evidence`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `online_current_artifact_mutation`
- `production_write`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `dataset snapshot loader`
- `feature and target builder`
- `bounded trainer`
- `evaluation hook`
- `artifact emitter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `BellmanOperatorArtifactV1`
- `RegularityProfileV1`

Consumed contracts:

- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `DomainRead::qualification_evidenceV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `ModulePort::kernel.evidence::learning.operator`
- `ModulePort::learning.artifacts::learning.operator`
- `ModulePort::learning.ledger::learning.operator`
- `ModulePort::platform.types::learning.operator`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`

Critical protocol schemas:

- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `RegularityProfileV1`

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

The [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.operator.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.operator.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/learning.operator.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.operator.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `Bellman_error_amplification`
- `off_policy_residual_blowup`
- `replay_contamination`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.operator.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-bellman-operator/src/lib.rs](../../../codex-rs/hepta-bellman-operator/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Offline/reference learning library. Bind immutable dataset/sensor profiles and emit candidates through the artifact owner. Distinguish the deterministic reference, simplest-sufficient learner and action-conditioned world model; synthetic trajectories cannot supply independent production outcome evidence.

Current operating and state-format references:

- [codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md](../../../codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-bellman-operator/src/learned_tests.rs](../../../codex-rs/hepta-bellman-operator/src/learned_tests.rs); named case: `op_05_tabular_operator_fits_complete_grid_deterministically`.
- [codex-rs/hepta-bellman-operator/src/lib_tests.rs](../../../codex-rs/hepta-bellman-operator/src/lib_tests.rs); named case: `deterministic_and_canonical`.

In `codex-rs`, run `just test -p codex-hepta-bellman-operator`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/learning.operator.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- `BIO-2-REPLAY-CONSOLIDATION`
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR`

The bootstrap package is `HBO-0-BELLMAN-OPERATOR-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `learning.operator`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `HBO-0-BELLMAN-OPERATOR-CONTRACTS`

- State: `planned`; priority: `2`; parallel class: `contract_first_parallel`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-bellman-operator/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `PIM-0-PROMPT-INTERVENTION-CONTRACTS`
- Activation predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
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

#### `HBO-2-BELLMAN-OPERATOR-SHADOW`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-bellman-operator/**`
- Development predecessors:
- `HBO-1-OPERATOR-SENSOR-CORE`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- Activation predecessors:
- `HBO-1-OPERATOR-SENSOR-CORE`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
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

#### `BIO-2-REPLAY-CONSOLIDATION`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-bellman-operator/**`
- `qa/learning/replay/**`
- Development predecessors:
- `BIO-1-ELIGIBILITY-HOMEOSTASIS`
- `LONG-2-RETENTION-FORGETTING`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `HBO-1-OPERATOR-SENSOR-CORE`
- Activation predecessors:
- `BIO-1-ELIGIBILITY-HOMEOSTASIS`
- `LONG-2-RETENTION-FORGETTING`
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
- `verified_episode_replay`
- `fast_slow_memory_separation`
- `replay_ablation`
- `deletion_eligibility`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

#### `BIO-3-WORLD-MODEL-PREDICTION-ERROR`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `learning-platform` / `qualification-plane`.
- Allowed write paths:
- `codex-rs/hepta-bellman-operator/**`
- `qa/learning/world-model/**`
- Development predecessors:
- `BIO-2-REPLAY-CONSOLIDATION`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `HBO-1-OPERATOR-SENSOR-CORE`
- Activation predecessors:
- `BIO-2-REPLAY-CONSOLIDATION`
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
- `state_action_prediction`
- `reward_and_risk_prediction`
- `prediction_error_modulation`
- `dreamed_and_real_trajectory_separation`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `learning.operator` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `BellmanOperatorArtifactV1`

**Consumed contracts:**
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
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `ModulePort::kernel.evidence::learning.operator`
- `ModulePort::learning.artifacts::learning.operator`
- `ModulePort::learning.ledger::learning.operator`
- `ModulePort::platform.types::learning.operator`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`

**Typed protocols:**
- `CandidateSetCompletenessReceiptV1`
- `CreditAssignmentReceiptV1`
- `DatasetSnapshotV1`
- `GoldenFixtureManifestV1`
- `LearningDecisionV1`
- `LearningEpisodeV1`
- `OperatorApplicabilityCertificateV1`
- `OperatorSensorCoreManifestV1`
- `OutcomeReceiptV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RegularityProfileV1`
- `SupportAuditReceiptV1`

**Owned data domains:**
- None.

**Read data domains:**
- `candidate_set_completeness_receipt_v1`
- `golden_fixture_manifest_v1`
- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `operator_applicability_certificate_v1`
- `operator_sensor_core_manifest_v1`
- `operator_sensor_core_registry`
- `outcome_watermark_v1`
- `qualification_evidence`
- `random_stream_manifest_v1`
- `regularity_profile_v1`
- `support_audit_receipt_v1`

**Work packages:**
- `BIO-2-REPLAY-CONSOLIDATION`
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`

**Owned threats:**
- `Bellman_error_amplification`
- `off_policy_residual_blowup`
- `replay_contamination`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `learning.operator` to primary lane `LANE-E-LEARNING`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-LRN`](../../readiness/LEARNING_EVALUATION_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `learning.operator` is implemented by work package `HBO-0-BELLMAN-OPERATOR-CONTRACTS` in:

- `codex-rs/hepta-bellman-operator`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
