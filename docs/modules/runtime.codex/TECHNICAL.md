# runtime.codex technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `runtime.codex`

**Owner:** `codex-integration`

**Deputy:** `agent-runtime`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.7B-B1B-MODEL-BOUNDARY`

This stable document is the implementation guide for `runtime.codex`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Integrate Hepta contracts with the sole Codex thread, turn, model and tool execution spine.

The primary owner `codex-integration` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `agent-runtime` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `execution`, kind `adapter`, state model `stateful` and architecture role `execution_plant` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/codex-app-server`
- `codex-rs/hepta-codex-adapter`

Existing declared roots at this exact source snapshot:

- `codex-rs/codex-app-server`
- `codex-rs/hepta-codex-adapter`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source is [codex-rs/hepta-codex-adapter/src/lib.rs](../../../codex-rs/hepta-codex-adapter/src/lib.rs); the current boundary includes `CodexOperationIntent`, `AppServerRequestBinding`, `TerminalOutcome`, `CodexAdapterReceipt`, typed terminal/rejection adapters, and durable thread-read reconciliation. The named product caller is [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs); final-use authority is obtained through [codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs](../../../codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs); the production CLI composition root is [codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs](../../../codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs); and durable request/reconciliation ownership is in [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs). This is repository-controlled source composition, not proof of target-host provider execution, independent acceptance, activation, promotion, or release. Read the [fault matrix](FAULT_MATRIX.md) and [current native implementation](../../../qualification/module-execution-dossiers/detail/runtime.codex.md#8-current-native-implementation) together.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.wire`
- `kernel.authority`

Authoritative write domains:

- `thread_session`

Explicitly denied capabilities:

- `hepta_domain_implementation_dependency`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `contract translator`
- `authority verifier`
- `checked effect boundary`
- `terminal observation mapper`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::thread_sessionV1`
- `ModulePort::runtime.codex::automation.taskflow`
- `ModulePort::runtime.codex::runtime.agentd`
- `PromptDeliveryObservationV1`

Consumed contracts:

- `CodexContextAttachmentV1`
- `ContextCompilationReceiptV1`
- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `ModulePort::kernel.authority::runtime.codex`
- `ModulePort::platform.wire::runtime.codex`
- `VerifiedUseTokenWitnessV1`

Critical protocol schemas:

- `ContextCompilationReceiptV1`
- `PromptDeliveryObservationV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `thread_session`

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/runtime.codex.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.codex.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/runtime.codex.md#8-current-native-implementation) and the explicit [runtime.codex fault matrix](FAULT_MATRIX.md). Completed, failed and interrupted terminal outcomes stay distinct; only explicit pre-admission overload is retry-safe; unknown acknowledgement, transport loss and process-loss ambiguity are reconcile-only and never justify blind replay. The durable native journal and thread-read reconciler are repository source mechanisms, but they do not substitute for target-host provider evidence or an external policy for unresolved indeterminate effects.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.codex.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-codex-adapter/src/lib.rs](../../../codex-rs/hepta-codex-adapter/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

The deployed execution spine is the existing codex-app-server package under codex-rs/app-server. codex-rs/codex-app-server is a source alias, not another binary. Use its registered thread/turn APIs and observe exact admission; hepta-codex-adapter alone neither starts a model nor proves a tool effect.

The named Hepta native inference caller is deliberately **model-only**: the App Server tool planner returns an empty router for the `hepta-infer-worker` client identity before MCP, connector, extension, dynamic-tool or core-tool planning. That deny-only identity can remove capability but never grant it. Any future external tool effect must enter a separately authorized effect-owner path with its own final-use grant, durable operation identity and terminal observer; the `dispatch_tool` source mapping to codex-core is navigation/delegation evidence only and is not proof of an authorized tool effect.

`IMPLEMENTATION_MAP.sourceBase` is historical provenance only. Exact candidate identity is derived from the checked-out Git candidate by `scripts/hepta-lane-b-truth.py verify`, which emits `exactHead` and `exactTree`; the map records this verifier-derived provenance contract instead of attempting to hard-code its own self-referential commit/tree.

Current operating and state-format references:

- [codex-rs/app-server/README.md](../../../codex-rs/app-server/README.md).
- [docs/readiness/LANE_B_RUNTIME_COMPOSITION.md](../../readiness/LANE_B_RUNTIME_COMPOSITION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-codex-adapter/src/lib_tests.rs](../../../codex-rs/hepta-codex-adapter/src/lib_tests.rs): terminal status separation, exact thread/turn/transport correlation, overload classification, and thread-read recovery conflicts.
- [codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs](../../../codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs): absolute deadline binding, stable request identity, and late terminal evidence.
- [codex-rs/hepta-infer-core/src/native_control_tests.rs](../../../codex-rs/hepta-infer-core/src/native_control_tests.rs): durable write-ahead, slot retention, pre-effect abort proof, no-replay, and legacy journal safety.
- [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs): named caller terminal/cancellation/deadline/owner semantics.
- [codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs): reopen/no-replay and explicit pre-start rejection.
- [codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs): signed exact-binding grant, denial, peer identity, and revocation rollback.
- [codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs): launches the real Agentd/App Server product process, drives the named runtime.codex caller through a signed final-use grant into a mock Responses transport, and proves one physical provider request plus a durable terminal correlation receipt.

In `codex-rs`, run `just test -p codex-hepta-codex-adapter`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.codex.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.7B-B1B-MODEL-BOUNDARY`

The bootstrap package is `P0.7B-B1B-MODEL-BOUNDARY`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `runtime.codex`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `P0.7B-B1B-MODEL-BOUNDARY`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `codex-integration` / `agent-runtime`.
- Allowed write paths:
- `codex-rs/hepta-codex-adapter/**`
- `codex-rs/codex-app-server/**`
- Development predecessors:
- `P0.7B-B0-VERIFIED-USE`
- Activation predecessors:
- `P0.7B-B1A-PROVIDER-BOUNDARY`
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

The canonical readiness overlay binds `runtime.codex` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `runtime.codex` is implemented by work package `P0.7B-B1B-MODEL-BOUNDARY` in:

- `codex-rs/codex-app-server`
- `codex-rs/hepta-codex-adapter`

The designated source gate is `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. A workflow definition or prior run is not a pass receipt for this candidate; exact-head and merge-candidate evidence must match the reviewed head. This source evidence grants no deployment or release authority. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
