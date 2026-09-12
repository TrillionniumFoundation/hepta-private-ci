# utility.ndu technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `utility.ndu`

**Owner:** `intelligence-platform`

**Deputy:** `learning-platform`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `NDU-0-PREFERENCE-UTILITY-CONTRACTS`

This stable document is the implementation guide for `utility.ndu`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Maintain bounded preference and recursive-utility projections for system, domain, agent and episode subjects.

The primary owner `intelligence-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `learning-platform` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `preference_utility_runtime`, state model `stateful_projection` and architecture role `preference_utility_controller` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-ndu`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-ndu`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `utility.ndu`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `cognitive.read`
- `learning.ledger`
- `learning.artifacts`

Authoritative write domains:

- `ndu_preference_projection`
- `ndu_utility_projection`

Explicitly denied capabilities:

- `hard_constraint_mutation`
- `authority_issuance`
- `physical_effect`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `preference-state reader`
- `bounded state updater`
- `recursive utility evaluator`
- `boundary-condition cache`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `ModulePort::utility.ndu::control.runtime`
- `ModulePort::utility.ndu::intelligence.control`
- `ModulePort::utility.ndu::intuition.policy`
- `ModulePort::utility.ndu::prompt.optimizer`
- `NduBoundaryConditionV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`

Consumed contracts:

- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `ModulePort::cognitive.read::utility.ndu`
- `ModulePort::learning.artifacts::utility.ndu`
- `ModulePort::learning.ledger::utility.ndu`
- `ModulePort::platform.types::utility.ndu`
- `NduBoundaryConditionV1`
- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Critical protocol schemas:

- `NduBoundaryConditionV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `ndu_preference_projection`
- `ndu_utility_projection`

Read-only data dependencies:

- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `operator_sensor_core_registry`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/utility.ndu.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/utility.ndu.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/utility.ndu.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/utility.ndu.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `parent_child_NDU_oscillation`
- `preference_state_goal_drift`
- `recursive_utility_instability`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/utility.ndu.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-ndu/src/lib.rs](../../../codex-rs/hepta-ndu/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Embed the deterministic evaluator under a frozen objective and versioned policy. The actual request-local context planner is described in the native host guide; it does not activate global adaptive reconfiguration. Projection journals are bounded owner-local references and must not be substituted for an independently selected production writer.

Current operating and state-format references:

- [docs/readiness/NDU_SYSTEM_EXECUTION.md](../../readiness/NDU_SYSTEM_EXECUTION.md).
- [codex-rs/hepta-ndu/RECURSIVE_UTILITY.md](../../../codex-rs/hepta-ndu/RECURSIVE_UTILITY.md).
- [codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md](../../../codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-ndu/src/covariance_tests.rs](../../../codex-rs/hepta-ndu/src/covariance_tests.rs); named case: `scaled_covariance_recovers_three_instead_of_six_and_converts_microseconds`.
- [codex-rs/hepta-ndu/src/evaluator_tests.rs](../../../codex-rs/hepta-ndu/src/evaluator_tests.rs); named case: `hard_violation_is_filtered_before_utility`.

In `codex-rs`, run `just test -p codex-hepta-ndu`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/utility.ndu.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `NDU-2-AGENT-DOMAIN-HIERARCHY`

The bootstrap package is `NDU-0-PREFERENCE-UTILITY-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `utility.ndu`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `NDU-0-PREFERENCE-UTILITY-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `intelligence-platform` / `learning-platform`.
- Allowed write paths:
- `codex-rs/hepta-ndu/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- Activation predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
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

#### `NDU-1-DETERMINISTIC-UTILITY-BASELINE`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `learning-platform`.
- Allowed write paths:
- `codex-rs/hepta-ndu/**`
- Development predecessors:
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `OBJ-1-OBJECTIVE-COMPILER`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- Activation predecessors:
- `OBJ-1-OBJECTIVE-COMPILER`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
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

#### `NDU-2-AGENT-DOMAIN-HIERARCHY`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `learning-platform`.
- Allowed write paths:
- `codex-rs/hepta-ndu/**`
- `codex-rs/hepta-control-plane/**`
- Development predecessors:
- `LONG-1-TEMPORAL-HOLDOUT`
- `RCP-1-RUNTIME-CONTROL-PLANE`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- Activation predecessors:
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `RCP-1-RUNTIME-CONTROL-PLANE`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
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
- `system_domain_agent_episode_only`
- `boundary_condition_receipts`
- `resource_conservation`
- `weak_coupling_stability`
- `no_central_hot_path_rpc`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

<!-- BEGIN GENERATED EXACT REGISTRY PROJECTION -->
### Exact closed-world registry projection

This generated projection binds `utility.ndu` to the current canonical contract, protocol, data, delivery and threat registries. The registries remain authoritative; this block is a digest-checked documentation projection.

**Produced contracts:**
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `ModulePort::utility.ndu::control.runtime`
- `ModulePort::utility.ndu::intelligence.control`
- `ModulePort::utility.ndu::intuition.policy`
- `ModulePort::utility.ndu::prompt.optimizer`
- `NduBoundaryConditionV1`
- `NduCoefficientManifestV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`

**Consumed contracts:**
- `DomainRead::learning_artifact_registryV1`
- `DomainRead::learning_credit_ledgerV1`
- `DomainRead::learning_episode_ledgerV1`
- `DomainRead::learning_unlearning_lineageV1`
- `DomainRead::operator_sensor_core_registryV1`
- `GoldenFixtureManifestV1`
- `ModulePort::cognitive.read::utility.ndu`
- `ModulePort::learning.artifacts::utility.ndu`
- `ModulePort::learning.ledger::utility.ndu`
- `ModulePort::platform.types::utility.ndu`
- `NduBoundaryConditionV1`
- `NduWellPosednessCertificateV1`
- `ObjectiveFunctionV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RunStartSnapshotV1`

**Typed protocols:**
- `GoldenFixtureManifestV1`
- `NduBoundaryConditionV1`
- `NduCoefficientManifestV1`
- `NduPreferenceStateV1`
- `NduSummaryReceiptV1`
- `NduUpdateReceiptV1`
- `NduWellPosednessCertificateV1`
- `ObjectiveFunctionV1`
- `OutcomeWatermarkV1`
- `RandomStreamManifestV1`
- `RunStartSnapshotV1`

**Owned data domains:**
- `ndu_coefficient_manifest_v1`
- `ndu_preference_projection`
- `ndu_update_receipt_v1`
- `ndu_utility_projection`

**Read data domains:**
- `golden_fixture_manifest_v1`
- `learning_artifact_registry`
- `learning_credit_ledger`
- `learning_episode_ledger`
- `learning_unlearning_lineage`
- `ndu_well_posedness_certificate_v1`
- `operator_sensor_core_registry`
- `outcome_watermark_v1`
- `random_stream_manifest_v1`

**Work packages:**
- `NDU-0-PREFERENCE-UTILITY-CONTRACTS`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- `NDU-2-AGENT-DOMAIN-HIERARCHY`

**Owned threats:**
- `parent_child_NDU_oscillation`
- `preference_state_goal_drift`
- `recursive_utility_instability`

<!-- END GENERATED EXACT REGISTRY PROJECTION -->

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `utility.ndu` to primary lane `LANE-D-OBJECTIVE-VALUE`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-NDU`](../../readiness/NDU_SYSTEM_EXECUTION.md)

Owned readiness protocols:

- `NduIterationReceiptV1`
- `UtilityContributionV1`

Consumed readiness protocols:

- `NduConvergenceCertificateV1`
- `ObjectiveCompileReceiptV1`
- `ObjectiveConstraintSetV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `utility.ndu` is implemented by work package `NDU-0-PREFERENCE-UTILITY-CONTRACTS` in:

- `codex-rs/hepta-ndu`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
