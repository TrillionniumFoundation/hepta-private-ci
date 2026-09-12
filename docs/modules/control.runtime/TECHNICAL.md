# control.runtime technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `control.runtime`

**Owner:** `runtime-control`

**Deputy:** `security-authority`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `RCP-1-RUNTIME-CONTROL-PLANE`

This stable document is the implementation guide for `control.runtime`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Select a feasible bounded global plan from exact snapshots while staying off local hot paths and effect boundaries.

The primary owner `runtime-control` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `control`, kind `optimizer`, state model `stateful_projection` and architecture role `preference_utility_controller` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-control-plane`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-control-plane`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-control-plane/src/organ_runtime.rs](../../../codex-rs/hepta-control-plane/src/organ_runtime.rs); observed identifiers include `OrganHostV1`, `TrustedReadOnlyOrganV1`, `OrganDeliveryV1`, `OrganFaultRecordV1`, `start_all`, `dispatch_once`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/control.runtime.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/control.runtime.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `runtime.fleet`
- `kernel.evidence`
- `utility.ndu`

Authoritative write domains:

- `global_state_snapshot`
- `optimization_decision`

Explicitly denied capabilities:

- `capability_issuance`
- `physical_effect`
- `central_rpc_hot_path`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `snapshot loader`
- `candidate builder`
- `bounded solver`
- `decision receipt emitter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::global_state_snapshotV1`
- `DomainRead::optimization_decisionV1`

Consumed contracts:

- `DomainRead::fleet_allocation_grantV1`
- `DomainRead::ndu_preference_projectionV1`
- `DomainRead::ndu_utility_projectionV1`
- `DomainRead::qualification_evidenceV1`
- `ModulePort::kernel.evidence::control.runtime`
- `ModulePort::runtime.fleet::control.runtime`
- `ModulePort::utility.ndu::control.runtime`
- `NduBoundaryConditionV1`
- `NduSummaryReceiptV1`

Critical protocol schemas:

- `NduBoundaryConditionV1`
- `NduSummaryReceiptV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `global_state_snapshot`
- `optimization_decision`

Read-only data dependencies:

- `fleet_allocation_grant`
- `ndu_preference_projection`
- `ndu_utility_projection`
- `qualification_evidence`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/control.runtime.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/control.runtime.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/control.runtime.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/control.runtime.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `central_RPC_hot_path_dependency`
- `global_optimizer_local_optimum_claim`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/control.runtime.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-control-plane/src/organ_runtime.rs](../../../codex-rs/hepta-control-plane/src/organ_runtime.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Bounded planner and organ-runtime libraries. The real Agentd context caller compares read-context with abstain under measured serialized-byte limits. That local decision is distinct from global adaptive topology/resource reconfiguration; physical execution grants remain separately issued by the owner.

Current operating and state-format references:

- [docs/readiness/CONTROL_RUNTIME_EXECUTION.md](../../readiness/CONTROL_RUNTIME_EXECUTION.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-control-plane/src/embodiment/cart_tests.rs](../../../codex-rs/hepta-control-plane/src/embodiment/cart_tests.rs); named case: `typed_controller_and_plant_replay_the_explicit_euler_q24_golden`.
- [codex-rs/hepta-control-plane/src/embodiment/timing_tests.rs](../../../codex-rs/hepta-control-plane/src/embodiment/timing_tests.rs); named case: `blocking_and_higher_priority_interference_are_included`.

In `codex-rs`, run `just test -p codex-hepta-control-plane`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/control.runtime.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `NDU-2-AGENT-DOMAIN-HIERARCHY`
- `RCP-1-RUNTIME-CONTROL-PLANE`

The bootstrap package is `RCP-1-RUNTIME-CONTROL-PLANE`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `control.runtime`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

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

#### `RCP-1-RUNTIME-CONTROL-PLANE`

- State: `planned`; priority: `2`; parallel class: `contract_first_parallel`.
- Owner/deputy: `runtime-control` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-control-plane/**`
- Development predecessors:
- `DOC-2-DEFAULT-BRANCH-SELECTION`
- `P0.8C-RESOURCE-BUDGETS`
- `NDU-1-DETERMINISTIC-UTILITY-BASELINE`
- Activation predecessors:
- `P0.8C-RESOURCE-BUDGETS`
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
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `control.runtime` to primary lane `LANE-D-OBJECTIVE-VALUE`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-NDU`](../../readiness/NDU_SYSTEM_EXECUTION.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- `RealTimeLoopProfileV1`

Consumed readiness protocols:

- `EmergencyStopReceiptV1`
- `NduConvergenceCertificateV1`
- `NduIterationReceiptV1`
- `ObjectiveConstraintSetV1`
- `SensorCalibrationManifestV1`
- `UtilityContributionV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `EMB-2-REFLEX-MOTOR-ACTUATION`

## 17. Source implementation receipt

The bootstrap source-location obligation for `control.runtime` is implemented by work package `RCP-1-RUNTIME-CONTROL-PLANE` in:

- `codex-rs/hepta-control-plane`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
