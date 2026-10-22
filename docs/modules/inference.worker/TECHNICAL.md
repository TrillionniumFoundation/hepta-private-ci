# inference.worker technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

The native App Server worker now calls the same durable control owner for explicit local-slot admission, persisted dispatch identity, cancellation intent and actual observed settlement. Optional observed tokens remain unknown when absent; restarting a possibly dispatched request never replays it. This does not close economic quota, local weights/device or trusted post-crash provider-reconciliation gaps. The [native host guide](../../readiness/LANE_B_NATIVE_HOST.md#durable-inference-journal) specifies journal limits, CLI requirements and recovery semantics.

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `inference.worker`

**Owner:** `inference-platform`

**Deputy:** `security-authority`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `INFER-V4-T4`

This stable document is the implementation guide for `inference.worker`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Execute a granted inference request in an isolated worker without minting authority or mutating fleet state.

The primary owner `inference-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `adapter`, kind `worker`, state model `ephemeral_isolated` and architecture role `checked_adapter` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-infer-worker-host`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-infer-worker-host`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate and are covered by the dedicated closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification. This status does not activate `inference.worker`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `inference.control`
- `kernel.authority`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `grant_issuance`
- `fleet_mutation`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `bounded ingress`
- `isolated execution cell`
- `resource guard`
- `terminal receipt reporter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

None.

Consumed contracts:

- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::inference_receiptV1`
- `DomainRead::inference_requestV1`
- `DomainRead::inference_reservationV1`
- `ModulePort::inference.control::inference.worker`
- `ModulePort::kernel.authority::inference.worker`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

- `authority_lease`
- `capability_revocation`
- `inference_receipt`
- `inference_request`
- `inference_reservation`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.worker.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/inference.worker.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

The existing `model_worker::InferenceWorker` component retains the original request
slot and model handle when token or neuron-feature execution returns a driver
error or an unobserved terminal state. Its typed unresolved lifecycle refuses
further execution and unloading of that model with the existing `ActiveRequests`
error; duplicate request identities retain `RequestCapacity`. Only an observed
terminal result releases the request slot. Failed unloading retains and freezes
the same handle; a retry must release its original load attempt, and only
confirmed resource release removes it. This component adds no durable journal or
terminal reconciler. Dropping or restarting the owner does not prove resource
release. These safeguards are prerequisites within existing `P0.8C-RESOURCE-BUDGETS`
and `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`; the hosted App Server path, real local
neural backend, aggregate memory accounting and three-round model acceptance
remain separately qualified boundaries.

`load_model` now requires an explicit lifetime byte reservation. Before driver
dispatch the existing model table retains the complete manifest/grant binding,
worker generation, monotonic attempt sequence and original budget. Checked sums
cannot exceed the original grant; lower observations never shrink reservations.
Driver errors and `Unknown` preserve the attempt and block new load/run dispatch.
Only matching original-attempt observations advance it: `NoEffect` can clear an
attempt before ownership, while an owned resource requires `Released`. Cleanup
also latches every matching `Owned` observation, including malformed or
foreign opaque identifiers: later `NoEffect` cannot release its reservation.
Only the original attempt selects cleanup; these identifiers grant no authority.
Rejected loads stay in cleanup and cannot become ready through reconciliation. Cleanup
uses the original attempt, never an opaque handle from malformed/foreign output.
`reconcile_load` only observes unresolved loads; it cannot reconcile an execution
or unload. Expired admission grants still permit original-owner observation and
cleanup, without admitting new work. Physical budget enforcement and real local
driver consumption remain unqualified; fault-driver resource-table tests do not
constitute RSS measurements or neural-backend acceptance.

Hosted output observation retains per-item text within one bound turn, including
the interrupt grace period. Completed message bytes replace that item's partial
deltas; identical completions deduplicate, conflicting completions and later
deltas refuse. The aggregate text limit remains 1 MiB, with at most 1,024 message
identities of at most 128 bytes each. Thread, turn and original App Server
transport bindings remain mandatory. Text completion grants no terminal status,
FinalUse authority or success; those still require the existing terminal witness
and current owner checks. A `NotLoaded` turn must contain no items. `Summary`
preserves the actual stream bytes without supplying missing message text. `Full`
replaces output atomically in its complete message order only after checking
identity uniqueness, retention of every observed message, completed-byte
consistency and the aggregate limit. Partial output is rendered in item order
before any return or owner-loss settlement, including without a terminal event.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-infer-worker-host/src/lib.rs](../../../codex-rs/hepta-infer-worker-host/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Build hepta-infer-worker and explicitly select --profile native-app-server. Supply the owning Agentd socket, Agent ID/generation, exact configured model, private journal and stable request ID as documented. Hosted execution uses the owning App Server; it does not establish local model weights, device grants or GPU isolation.

Current operating and state-format references:

- [docs/readiness/LANE_B_NATIVE_HOST.md](../../readiness/LANE_B_NATIVE_HOST.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-infer-worker-host/src/lib_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/lib_tests.rs); named case: `terminal_success_requires_exact_authority_binding`.
- [codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs); named case: `loads_runs_and_unloads_exact_model_tuple`.

In `codex-rs`, build the actual helper executable with
`cargo build --locked -p codex-cli --bin codex`, then run
`just test --locked -p codex-hepta-infer-worker-host`. The cross-crate Agentd
test host receives explicit runtime paths from the repository binary resolver;
the Bazel unit-test launcher supplies the same CLI through its runfiles mapping.
The test harness executable is not a substitute for that CLI. These commands are
test invocations, not stored results. Inspect the exact-candidate output for
passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/inference.worker.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `INFER-V4-T4`
- `INFER-V4-T5`
- `MEM-READ-1-SNAPSHOT-PORT` (co-owned cognitive final-use revalidation)
- `NEU-1-LOCAL-MODEL-BAKEOFF`

The bootstrap package is `INFER-V4-T4`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `inference.worker`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `INFER-V4-T4`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `inference-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-infer-worker-host/**`
- Development predecessors:
- `INFER-V4-T1`
- Activation predecessors:
- `INFER-V4-T3`
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

#### `INFER-V4-T5`

- State: `planned`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `inference-platform` / `security-authority`.
- Allowed write paths:
- `codex-rs/hepta-infer-worker-host/**`
- Development predecessors:
- `INFER-V4-T4`
- Activation predecessors:
- `INFER-V4-T4`
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

#### `NEU-1-LOCAL-MODEL-BAKEOFF`

- State: `planned`; priority: `2`; parallel class: `external_evidence_coordinated`.
- Owner/deputy: `learning-platform` / `inference-platform`.
- Allowed write paths:
- `codex-rs/hepta-neuron/**`
- `codex-rs/hepta-infer-worker-host/**`
- Development predecessors:
- `BIO-0-NEURON-INTUITION-CONTRACTS`
- `INFER-V4-T5`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `INFER-V4-T4`
- Activation predecessors:
- `INFER-V4-T5`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `BIO-0-NEURON-INTUITION-CONTRACTS`
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

The canonical readiness overlay binds `inference.worker` to primary lane `LANE-B-RUNTIME`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- `SensorCalibrationManifestV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `inference.worker` is implemented by work package `INFER-V4-T4` in:

- `codex-rs/hepta-infer-worker-host`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
