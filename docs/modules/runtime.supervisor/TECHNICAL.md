# runtime.supervisor technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `runtime.supervisor`

**Owner:** `runtime-control`

**Deputy:** `fleet-runtime`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.7A-RUNTIME-BOOTSTRAP`

This stable document is the implementation guide for `runtime.supervisor`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Own process and agent lifecycle state while remaining unable to invoke models, tools or secrets.

The primary owner `runtime-control` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `fleet-runtime` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `control`, kind `daemon`, state model `stateful` and architecture role `execution_plant` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-supervisor`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-supervisor`

Non-authoritative implementation evidence roots:

- `codex-rs/hepta-supervisor`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-supervisor/src/supervisor.rs](../../../codex-rs/hepta-supervisor/src/supervisor.rs); observed identifiers include `Supervisor`, `start`, `drain`, `stop`, `kill`, `restart`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `kernel.authority`
- `kernel.operations`

Authoritative write domains:

- `fleet_registry`
- `agent_lifecycle`
- `runtime_instance_projection`
- `release_selection`

Explicitly denied capabilities:

- `model_call`
- `tool_execution`
- `secret_read`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bootstrap and configuration loader`
- `supervision loop`
- `durable state projection`
- `readiness and shutdown controller`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::agent_lifecycleV1`
- `DomainRead::fleet_registryV1`
- `DomainRead::release_selectionV1`
- `DomainRead::runtime_instance_projectionV1`
- `ModulePort::runtime.supervisor::runtime.agentd`
- `ModulePort::runtime.supervisor::runtime.fleet`

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::kernel.authority::runtime.supervisor`
- `ModulePort::kernel.operations::runtime.supervisor`
- `OutboxReceiptV1`
- `ReconciliationReceiptV1`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `agent_lifecycle`
- `fleet_registry`
- `release_selection`
- `runtime_instance_projection`

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`
- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `stale_generation_callback`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-supervisor/src/supervisor.rs](../../../codex-rs/hepta-supervisor/src/supervisor.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Build hepta-supervisord from codex-hepta-supervisor; its native CLI requires --fleet-root with an absolute path. Grant and H7 verifier options are complete trust tuples, not request-supplied switches. The signer binaries require the production-authority build feature; lifecycle startup alone never enrolls effect authority.

Current operating and state-format references:

- [codex-rs/hepta-supervisor/src/main.rs](../../../codex-rs/hepta-supervisor/src/main.rs).
- [codex-rs/hepta-supervisor/EXTERNAL_AUTHORITY_SIGNER.md](../../../codex-rs/hepta-supervisor/EXTERNAL_AUTHORITY_SIGNER.md).
- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-supervisor/src/daemon_platform_tests.rs](../../../codex-rs/hepta-supervisor/src/daemon_platform_tests.rs); named case: `unsupported_host_rejects_daemon_before_accessing_fleet_state`.
- [codex-rs/hepta-supervisor/src/signed_intent_publish_tests.rs](../../../codex-rs/hepta-supervisor/src/signed_intent_publish_tests.rs); named case: `cross_directory_publish_rejects_without_changing_either_file`.

In `codex-rs`, run `just test -p codex-hepta-supervisor`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.7A-RUNTIME-BOOTSTRAP`
- `P0.8B-READINESS`
- `P0.8C-RESOURCE-BUDGETS`

The bootstrap package is `P0.7A-RUNTIME-BOOTSTRAP`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `runtime.supervisor`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `P0.7A-RUNTIME-BOOTSTRAP`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `independent_source_preparation`.
- Owner/deputy: `runtime-control` / `fleet-runtime`.
- Allowed write paths:
- `codex-rs/hepta-supervisor/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- Activation predecessors:
- `DOC-2-DEFAULT-BRANCH-SELECTION`
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

#### `P0.8B-READINESS`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `runtime-control` / `fleet-runtime`.
- Allowed write paths:
- `codex-rs/hepta-supervisor/**`
- `codex-rs/hepta-agentd/**`
- Development predecessors:
- `P0.8A-AST-RATCHET`
- `P0.7A-RUNTIME-BOOTSTRAP`
- Activation predecessors:
- `P0.8A-AST-RATCHET`
- `P0.7A-RUNTIME-BOOTSTRAP`
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

#### `P0.8C-RESOURCE-BUDGETS`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `runtime-control` / `fleet-runtime`.
- Allowed write paths:
- `codex-rs/hepta-supervisor/**`
- `qa/performance/**`
- Development predecessors:
- `P0.8B-READINESS`
- `P0.7A-RUNTIME-BOOTSTRAP`
- Activation predecessors:
- `P0.8B-READINESS`
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

The canonical readiness overlay binds `runtime.supervisor` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `ActuatorReconciliationReceiptV1`
- `AssimilationProposalV1`
- `AssimilationQualificationReceiptV1`
- `BranchPurposeManifestV1`
- `CanonicalSourceReceiptV1`
- `EmergencyStopReceiptV1`
- `ExternalSystemManifestV1`
- `IntegrationCheckpointV1`
- `RealTimeLoopProfileV1`
- `RollbackPointV1`
- `SensorCalibrationManifestV1`
- `ServiceGraphV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-1-DISCOVERY-MANIFEST`
- `ASM-2-DEBIAN-BRIDGE-SANDBOX`
- `EMB-2-REFLEX-MOTOR-ACTUATION`
