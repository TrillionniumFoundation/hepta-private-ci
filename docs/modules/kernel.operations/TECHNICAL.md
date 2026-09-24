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

Declared exclusive contract root:

- `codex-rs/hepta-operations`

Durable implementation/evidence roots used by the current candidate:

- `codex-rs/hepta-operations`
- `codex-rs/hepta-memory`
- `codex-rs/hepta-agentd`
- `codex-rs/hepta-automation` (current-main consumer evidence)

The exclusive root owns canonical `OperationIntentV1`, deterministic in-memory reference oracles and a standalone `DurableOperationStore` used only for durability/fault-matrix qualification. The named Agentd product path deliberately reuses the existing CognitiveStore SQLite owner through `ProductionDurableWriter`. These two persistence surfaces never co-own or dual-write one logical operation: standalone-store records have an explicit qualification/migration role, while product callers must enter the CognitiveStore-backed owner.

### Current claim levels

| Claim | Current candidate |
| --- | --- |
| target architecture | specified |
| reference oracle | implemented |
| standalone durable qualification store | implemented; not an Agentd product owner |
| CognitiveStore product source implementation | implemented candidate |
| final-use CognitiveStore destination and immutable terminal proof | implemented candidate |
| second current-main OperationIntentV1 consumer | implemented in automation.taskflow |
| Agentd final-use host primitive | source-composed |
| Agentd daemon lifecycle composition | source-composed through explicit host injection |
| external authority/grant enrollment | not activated; no default authority is manufactured |
| exact-head / synthetic-merge execution | pending current candidate CI |
| independent acceptance / release | false |

Canonical exact source identity is recorded by `IMPLEMENTATION_MAP.json` with `sourceIdentityPolicy=path_blob_manifest_v1`. The verifier resolves every mapped path through `git rev-parse HEAD:<path>`; a tracked map therefore does not need to contain its own future HEAD/tree hash.

The 16,384-record limits belong to the in-memory reference oracle. Durable configured limits and fail-before-mutation checks live in the CognitiveStore owner. Long-lived segment/checkpoint compaction remains a separate gap.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`

Authoritative write domains:

- `operation_ledger`
- `cross_owner_outbox`

Explicitly denied capabilities:

- `domain_schema_ownership`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation. One logical operation selects exactly one source persistence owner; no compatibility adapter may mirror it into both `DurableOperationStore` and CognitiveStore.

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

### Neural Circuit intent boundary (integration target)

A circuit edge or learned route is not operation authority. The evolved TaskFlow
owner commits its effect-relevant choice/outbox first, then the existing operation
and destination owners validate final payload, identity, grant and predecessor.
Cancellation, feedback re-entry or policy replacement must not reset logical effect
identity. Unknown outcomes remain open until owner reconciliation; a late child
effect survives parent cancellation. No cross-owner SQL transaction is implied.
See the [circuit execution contract](../automation.taskflow/TECHNICAL.md#44-durable-choice-checkpoint-and-effect-ordering).
This requirement adds no native operation or accepted wire field by itself.

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

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative/rebuildable domains:

- `cross_owner_outbox`
- `operation_ledger`

The Agentd product operation surface is stored inside the existing CognitiveStore SQLite owner. Migration `0011_kernel_operations.sql` installs the immutable operation semantic binding; migration `0012_kernel_operation_dispatch_claims.sql` installs per-operation durable dispatch-claim lineage; migration `0016_kernel_operation_destination_terminal.sql` installs immutable destination-owned terminal proofs. The separate `hepta-operations` SQLite schema is retained only for standalone durability qualification and migration compatibility and opens through the repository SQLite shim.

`ProductionDurableWriter::prepare_operation` binds the complete `OperationIntentV1` to one event/outbox identity and commits the source-owned rows atomically. Exact semantic replay is idempotent; changed subject, destination, payload, scope, policy generation or predecessor conflicts.

Dispatch claims carry bounded attempt, generation/fence, lease expiry and next-eligible state. The destination remains the only writer of its domain fact. The source cannot infer destination success from transport acknowledgement.

The first concrete destination, `CognitiveSourceOutboxTarget`, reconstructs the full intent and verifies predecessor/CAS inside destination-owned `BEGIN IMMEDIATE`. A deterministic mismatch commits an immutable `NotApplied` proof in the same target transaction; successful application commits an immutable `Applied` proof with the domain write. Mere absence of a domain row or proof remains `Indeterminate` and can never terminalize a still-running dispatch.

Migrations are checksum/lineage verified on open. SQLite must be WAL with `synchronous=FULL`. Deterministic storage exhaustion and transaction fault tests prove source operation/event/outbox rollback to the last committed cut. Physical power-loss claims require target-host evidence.

Append-only local history is not deleted in place. Long-lived retention requires explicit segment/checkpoint compaction with anti-resurrection evidence.

## 7. Runtime, concurrency and transaction model

The source prepare transaction linearizes operation/event/outbox identity. A bounded dispatch lease may be renewed/taken over only while the effect boundary has not been crossed. Before target entry the writer persists a one-shot ambiguous-effect fence; after that point restart/reopen must reconcile rather than resend.

`ProductionDispatchRequest` carries subject, destination, payload digest, scope digest, policy generation, full `OperationIntentV1` semantic digest and optional expected predecessor. `ProductionFinalUseOutboxDispatcher` consumes final-use authority with `with_verified_use_async`, so the active-effect fence spans the target future through completion or cancellation. Revocation that linearizes before entry yields zero target entries; revocation racing an entered effect reports `DispatchInProgress` until that effect leaves the boundary.

`AgentdProductionWriterHost` is final-use-only and supports stable destination registration plus bounded observer-only reconciliation. It requires externally supplied authority/grants; default daemon startup does not synthesize them.

Ordinary mutation uses targeted current-row checks. Full append-only chain verification is reserved for open/reopen/recovery/audit boundaries, avoiding an O(n) full scan on each mutation.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Crash before source commit leaves no dispatch identity. Crash after source commit reopens the exact queued identity. Once target entry may have occurred, the durable state remains indeterminate until an independent destination observer reads an immutable operation-bound proof of `Applied`, `NotApplied` or `Quarantined`; missing proof is an indeterminate continuation, never negative evidence.

Stale claimants, stale generations, changed semantic digests and changed predecessor expectations fail closed. In the standalone qualification store, owner handoff and synchronous effect entry linearize under one `BEGIN IMMEDIATE` transaction: a newer generation that wins first keeps the old callback count at zero; an effect that wins first is classified before handoff proceeds. The product async path uses the final-use active-effect fence and destination proof protocol instead of treating future construction as effect entry.

Source qualification includes transaction fault cuts, deterministic `SQLITE_FULL`, corruption/tamper checks, reopen, claim takeover and lost-ack reconciliation. These are not physical power-loss certification; target-host filesystem/storage/controller evidence remains external.

Compensation is always a new authorized operation. Rollback cannot rewrite an already observed external effect.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `blind_retry_after_unknown_effect`
- `cross_owner_direct_write`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The durable source ceiling is distinct from the 16,384-record reference-oracle ceiling. Capacity checks reject before visible mutation. The pilot target remains pending intents <= 100000 per configured shard and reconciliation batches <= 256.

Hot-path work is bounded to current occurrence/claim rows plus the owning SQLite transaction. Full historical verification runs at open/reopen/recovery/audit. Benchmark commit/fsync latency, claim age, reconciliation backlog, SQLite write amplification and reopen verification cost on the selected host.

Long-lived append-only history still requires segment/checkpoint compaction before production-scale retention can be claimed.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Operation state, dispatch claim and destination terminal observation are separate facts. Queue acceptance/transport acknowledgement never reports terminal success.

The host observes at minimum queued age, active claim lease/attempt, indeterminate backlog, stale-claim rejection, destination-observer availability and reconciliation outcome. `AgentdProductionWriterHost::reconcile` is observer-only and bounded; it never invokes target dispatch.

Current operating/state-format references include:

- `codex-rs/hepta-operations/src/model.rs`
- `codex-rs/hepta-memory/migrations/0011_kernel_operations.sql`
- `codex-rs/hepta-memory/migrations/0012_kernel_operation_dispatch_claims.sql`
- `codex-rs/hepta-memory/migrations/0016_kernel_operation_destination_terminal.sql`
- `codex-rs/hepta-memory/src/operation_claims.rs`
- `codex-rs/hepta-memory/src/production_writer.rs`
- `codex-rs/hepta-memory/src/production_cognitive_source_target.rs`

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Focused source tests cover:

- `OperationIntentV1` semantic digest and reference ledger/outbox parity;
- operation/event/outbox atomic rollback at every injected source prepare cut;
- fail-before-mutation capacity boundaries;
- deterministic `SQLITE_FULL` rollback and clean reopen;
- durable claim attempt/expiry/renewal/takeover semantics;
- complete destination semantic reconstruction;
- predecessor mismatch -> transactionally persisted deterministic `NotApplied` proof;
- missing destination proof remains indeterminate and cannot race a late commit into false rejection;
- final-use mismatch/revocation before target entry yields zero target entries;
- revocation during an entered asynchronous effect returns `DispatchInProgress` until completion/cancellation;
- target commit + lost acknowledgement -> indeterminate -> observer-only reconcile;
- standalone generation handoff before entry yields zero callback executions.

Run the applicable Rust package tests, strict lint, exact-head qualification and deterministic synthetic-merge qualification. Test names in source are not pass receipts. Any PR-head movement invalidates prior exact-candidate evidence.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain failure, compilation, independent-evidence and target-host obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `P0.7B-B2-TOOL-NET-FS`
- `P0.7D-FAULT-MATRIX`

The bootstrap package is `P0.7D-FAULT-MATRIX`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. `DurableOperationIntentV1` is the standalone-store record shape and has no implicit product conversion. Migration into the product owner must replay one canonical `OperationIntentV1` through `ProductionDurableWriter` under a new, explicit migration operation; direct row copying or dual writing is forbidden. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

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

This receipt is source-navigation evidence for the current durable candidate; runtime activation and release remain separate.

| Operation | Native symbol | Source path | Evidence |
|---|---|---|---|
| canonical intent | `OperationIntentV1` | `codex-rs/hepta-operations/src/model.rs` | semantic-field binding tests |
| standalone qualification owner | `DurableOperationStore` | `codex-rs/hepta-operations/src/durable_store.rs` | generation/effect-entry, crash and SQLite fault tests; not a product caller |
| durable prepare | `ProductionDurableWriter::prepare_operation` | `codex-rs/hepta-memory/src/production_writer.rs` | atomic prepare/fault tests |
| durable claim | `operation_claims::claim/renew` | `codex-rs/hepta-memory/src/operation_claims.rs` | attempt/lease/backoff tests |
| final-use dispatch | `ProductionFinalUseOutboxDispatcher::dispatch` | `codex-rs/hepta-memory/src/production_writer.rs` | final-use tests |
| destination CAS/proof/observer | `CognitiveSourceOutboxTarget` | `codex-rs/hepta-memory/src/production_cognitive_source_target.rs` | predecessor, absence/late-commit and lost-ack tests |
| Agentd host primitive | `AgentdProductionWriterHost` | `codex-rs/hepta-agentd/src/production_writer_host.rs` | explicit final-use/grant composition |
| Agentd runtime composition | `AgentdConfig::with_production_operations` + `runtime::run` | `codex-rs/hepta-agentd/src/config.rs`, `runtime.rs` | lifecycle task cleanup/fail-closed default |
| second current-main consumer | `AutomationStore::dispatch_authorized_effect` | `codex-rs/hepta-automation/src/authorized_effect.rs` | automation authorized-effect tests |
| reference ledger | `OperationLedger` | `codex-rs/hepta-operations/src/ledger.rs` | reference oracle |
| reference outbox | `Outbox` | `codex-rs/hepta-operations/src/outbox.rs` | reference oracle |

- Exact mapped source identity is verified through `path_blob_manifest_v1`.
- `productionImplementation=true` means repository source implementation exists; it does not mean product execution, activation, acceptance or release.
- Remaining repository gates are current exact-head/synthetic-merge success, remaining destination adapters and long-lived segment/checkpoint compaction. External production authority/grant enrollment remains an activation gate and is not manufactured by Agentd.
