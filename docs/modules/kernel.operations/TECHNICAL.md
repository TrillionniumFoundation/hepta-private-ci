# kernel.operations technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `kernel.operations`

**Owner:** `durability-kernel`

**Deputy:** `architecture`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.7D-FAULT-MATRIX`

This stable document is the implementation guide for `kernel.operations`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Make cross-owner mutation recoverable through durable intent, outbox, acknowledgement and reconciliation.

The primary owner `durability-kernel` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `architecture` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `kernel`, kind `durability`, state model `stateful` and architecture role `immutable_kernel` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-operations`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-operations`

Source implementation evidence roots:

- `codex-rs/hepta-operations`

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared target root now contains a bounded implementation and focused tests. It does not imply activation, operator acceptance, promotion or release. Source moves must update `MODULES.json`, `SOURCE_BINDINGS.json`, the Cargo/Bazel workspace and this guide in one exact candidate.

### Native source and scope

The current source has two intentionally distinct surfaces. The production-shaped durable source owner is [codex-rs/hepta-operations/src/durable/store.rs](../../../codex-rs/hepta-operations/src/durable/store.rs), with `DurableOperationStore::prepare_intent`, leased `claim_outbox`, durable dispatch transitions and terminal settlement; [durable/dispatcher.rs](../../../codex-rs/hepta-operations/src/durable/dispatcher.rs) owns real final-use gated adapter admission, and [durable/reconcile.rs](../../../codex-rs/hepta-operations/src/durable/reconcile.rs) owns destination receipts and fenced settlement. The bounded [ledger.rs](../../../codex-rs/hepta-operations/src/ledger.rs) / [outbox.rs](../../../codex-rs/hepta-operations/src/outbox.rs) remain deterministic reference oracles rather than the durability boundary. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/kernel.operations.md#8-current-native-implementation) for the exact implemented subset and remaining product activation work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`

Authoritative write domains:

- `operation_ledger`
- `cross_owner_outbox`

Explicitly denied capabilities:

- `domain_schema_ownership`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `operation journal`
- `cross-owner outbox`
- `deduplication index`
- `fenced reconciler`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::kernel.operations::auth.authbus`
- `ModulePort::kernel.operations::automation.taskflow`
- `ModulePort::kernel.operations::channel.matrix`
- `ModulePort::kernel.operations::cognitive.store`
- `ModulePort::kernel.operations::compact.engine`
- `ModulePort::kernel.operations::inference.control`
- `ModulePort::kernel.operations::learning.artifacts`
- `ModulePort::kernel.operations::learning.ledger`
- `ModulePort::kernel.operations::prompt.registry`
- `ModulePort::kernel.operations::runtime.supervisor`
- `OperationIntentV1`
- `OutboxReceiptV1`
- `ReconciliationReceiptV1`

Consumed contracts:

- `ModulePort::platform.types::kernel.operations`
- `VerifiedUseTokenWitnessV1`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

The target wire/JSON contracts must preserve identical semantics and canonical digest scopes when admitted. The current durable native surface is typed Rust plus SQLite records; it does **not** claim that a production JSON codec for every target contract already exists. Native tests cover semantic digest stability, bounds, state/error transitions, migration/integrity behavior, crash/reopen and cross-owner idempotency. Error mapping preserves rejected, unavailable, indeterminate, quarantined and terminal outcomes without converting transport acknowledgement into effect success.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `cross_owner_outbox`
- `operation_ledger`

Read-only data dependencies:

None.

`DurableOperationStore` is the authoritative writer for `operation_ledger` and the source-local `cross_owner_outbox`. `prepare_intent` acquires an immediate SQLite writer transaction and commits both records atomically. Mutations are revision/generation/fence-bound, exact semantic replay is idempotent and reused scoped identities with changed content conflict. Destination domain facts remain owned by their destination modules; `automation.taskflow` is the first concrete destination integration and commits its task row plus immutable operation receipt in one automation-owner transaction.

The operations migrator is deterministic and checksum-bound. Store open verifies migration lineage, quick/foreign-key checks and required tables/indexes/triggers before reads or writes. Migration `0002_retired_identity_tombstones.sql` preserves retired source and generic destination semantic identities so retention cannot resurrect a previously completed effect. The automation owner migration `0004_kernel_operation_dedupe.sql` supplies the same no-replay identity fence around task creation.

Retention removes live terminal rows only after durable tombstone publication in the same transaction. Tombstones are immutable and permanent in the current profile. A rollback across a schema boundary must therefore preserve readable tombstone lineage or fail closed rather than silently re-admit retired work.

## 7. Runtime, concurrency and transaction model

The durable source owner uses the repository SQLite durability shim with WAL + `synchronous=FULL`; logical publication uses `BEGIN IMMEDIATE`. Outbox leases record worker, generation, monotonic fence and expiry; stale lease holders cannot renew/retry/ack a newer claim. Expired pending work may be claimed by a non-stale generation. After an external effect may have crossed, work is never returned to the retry queue: `Dispatched`/`Indeterminate` can settle only from matching destination evidence. A higher generation may atomically adopt such an unresolved operation while recording terminal evidence, while lower generations remain stale. The retained in-memory oracle does not participate in production recovery.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Durable recovery is source-implemented for SQLite reopen, fenced pending-lease takeover, unresolved dispatched/indeterminate owner handoff, indeterminate terminal reconciliation and retention tombstones. Child-process crash fixtures cover pre-dispatch and post-durable-dispatch boundaries; forced write failure proves ledger/outbox co-commit rollback. These source tests still do not replace target-host power-loss/storage qualification or a continuously hosted product reconciler. Unknown effects remain unresolved until destination evidence exists.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `blind_retry_after_unknown_effect`
- `cross_owner_direct_write`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.operations.md) specifies pilot ceilings and measurement obligations. Current durable source enforces bounded claim batches, bounded lease duration, bounded attempts and store record ceilings in `src/durable`; the 16,384-record limits in `ledger.rs`/`outbox.rs` apply only to the reference oracle. Pilot shard ceilings remain design targets until selected-host measurements prove them.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

`DurableOperationStore` exposes durable state and backlog metrics; `DurableDispatcher` separates queue acknowledgement from terminal observation. Agentd currently opens the operations store as a source-composition seam. `automation.taskflow` supplies the first destination-owned apply/dedupe receipt path. Product activation still requires an enrolled grant source, hosted dispatcher/reconciler and operational alert thresholds; opening the store grants no effect authority.

Current operating and state-format references:

- [docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md](../../lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md).
- [codex-rs/hepta-operations/src/durable/store.rs](../../../codex-rs/hepta-operations/src/durable/store.rs).
- [codex-rs/hepta-operations/src/durable/dispatcher.rs](../../../codex-rs/hepta-operations/src/durable/dispatcher.rs).
- [codex-rs/hepta-operations/src/durable/reconcile.rs](../../../codex-rs/hepta-operations/src/durable/reconcile.rs).
- [codex-rs/hepta-automation/src/operation_destination.rs](../../../codex-rs/hepta-automation/src/operation_destination.rs).
- [docs/lane-a-foundation/kernel.operations/REFERENCE_MODEL_V1.md](../../lane-a-foundation/kernel.operations/REFERENCE_MODEL_V1.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-operations/src/durable/tests.rs](../../../codex-rs/hepta-operations/src/durable/tests.rs): atomic publication/reopen, lease fencing/takeover, indeterminate/terminal reconciliation, retention and anti-resurrection.
- [codex-rs/hepta-operations/src/durable/fault_tests.rs](../../../codex-rs/hepta-operations/src/durable/fault_tests.rs): independent handles, forced write failure and real child-process crash boundaries including higher-generation unresolved owner handoff.
- [codex-rs/hepta-operations/src/durable/dispatcher_tests.rs](../../../codex-rs/hepta-operations/src/durable/dispatcher_tests.rs): bounded claims and real final-use gated dispatch.
- [codex-rs/hepta-automation/tests/kernel_operations_destination.rs](../../../codex-rs/hepta-automation/tests/kernel_operations_destination.rs): lost-ack source→automation-owner apply→terminal reconcile, exact replay, payload drift and destination reopen.
- [codex-rs/hepta-operations/src/ledger_tests.rs](../../../codex-rs/hepta-operations/src/ledger_tests.rs) and [outbox_tests.rs](../../../codex-rs/hepta-operations/src/outbox_tests.rs): retained deterministic reference-oracle semantics.

In `codex-rs`, run `just test -p codex-hepta-operations`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/kernel.operations.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.7B-B2-TOOL-NET-FS`
- `P0.7D-FAULT-MATRIX`

The bootstrap package is `P0.7D-FAULT-MATRIX`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `kernel.operations`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `P0.7B-B2-TOOL-NET-FS`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `security-authority` / `kernel-contracts`.
- Allowed write paths:
- `codex-rs/hepta-contracts/**`
- `codex-rs/hepta-operations/**`
- Development predecessors:
- `P0.7B-B0-VERIFIED-USE`
- Activation predecessors:
- `P0.7B-B0-VERIFIED-USE`
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

#### `P0.7D-FAULT-MATRIX`

- State: `source_implemented_execution_pending`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `durability-kernel` / `architecture`.
- Allowed write paths:
- `codex-rs/hepta-operations/**`
- `qa/fault-matrix/**`
- Development predecessors:
- `MEM-1-STORE`
- `MEM-8-PRODUCTION-WRITER`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `PIM-1-PROMPT-FACTOR-REGISTRY`
- `P0.7B-B2-TOOL-NET-FS`
- Activation predecessors:
- `MEM-8-PRODUCTION-WRITER`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `PIM-1-PROMPT-FACTOR-REGISTRY`
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

The canonical readiness overlay binds `kernel.operations` to primary lane `LANE-A-FOUNDATION`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)
- [`RDY-ASM`](../../readiness/EXTERNAL_SYSTEM_ASSIMILATION.md)

Owned readiness protocols:

- `ActuatorReconciliationReceiptV1`
- `MigrationPlanV1`
- `RollbackPointV1`

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

### Readiness implementation work packages

The following additional work packages are source-planning envelopes introduced by the readiness overlay; they do not imply implementation or activation:

- `ASM-2-DEBIAN-BRIDGE-SANDBOX`
- `ASM-3-STATE-MIGRATION-QUALIFICATION`

## 17. Source implementation receipt

This receipt records repository source bindings for the current documentation candidate. It is navigation evidence only; it does not claim product composition, deployment, or external effect authority.

| Operation | Native symbol | Source path | Tests |
|---|---|---|---|
| `prepare_intent` | `DurableOperationStore::prepare_intent` | `codex-rs/hepta-operations/src/durable/store.rs` | `durable/tests.rs`, `durable/fault_tests.rs` |
| `claim_outbox` | `DurableOperationStore::claim_outbox` | `codex-rs/hepta-operations/src/durable/store.rs` | `durable/tests.rs`, `durable/fault_tests.rs` |
| `authorized_dispatch` | `DurableDispatcher::dispatch_authorized` | `codex-rs/hepta-operations/src/durable/dispatcher.rs` | `durable/dispatcher_tests.rs`, automation owner vertical slice |
| `observe_terminal` | `DurableOperationStore::reconcile_destination_receipt` | `codex-rs/hepta-operations/src/durable/reconcile.rs` | `durable/tests.rs`, `durable/fault_tests.rs`, automation owner vertical slice |
| `operationledger` | `OperationLedger` | `codex-rs/hepta-operations/src/ledger.rs` | `ledger_tests.rs` |
| `outbox` | `Outbox` | `codex-rs/hepta-operations/src/outbox.rs` | `outbox_tests.rs` |

- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json`.
- The automation destination-owner slice is source-composed; other registered destination owners still require equivalent dedupe/apply/observer bindings.
- Agentd store-open composition is present, but an enrolled production grant source, hosted dispatch/reconcile loop, exact-candidate qualification, independent acceptance, activation and release remain separate gates.
