# `kernel.operations` current implementation

## Current executable contract

The current candidate deliberately has two distinct surfaces.

1. `codex-rs/hepta-operations` remains the bounded in-memory reference oracle for deterministic operation/outbox semantics.
2. The durable production-shaped source path is integrated into the existing CognitiveStore owner in `codex-rs/hepta-memory`: `ProductionDurableWriter` + `LocalLeaseOutbox` atomically bind the complete `OperationIntent`, the local event and the local outbox row in one SQLite `BEGIN IMMEDIATE` transaction.

The durable operation identity binds operation ID, exact payload digest, scope, owner, destination and optional predecessor digest. Exact replay is idempotent only for the same semantic tuple. Changed operation semantics conflict.

Dispatch has two durable stages. `cognitive_operation_dispatch_claims` persists the bounded claim lease, attempt, renewal/takeover and retry eligibility. Immediately before final-use target entry the writer appends the one-shot indeterminate effect-entry marker. Concurrent/reopened dispatchers therefore cannot blindly resend after boundary ambiguity. A terminal predecessor generation may hand an unresolved queued identity to a newer owner without creating a second event/outbox identity.

## Public symbols and source bindings

Reference oracle:

- `OperationIntent`, `OperationKey`, `OperationState`, `OperationRecord`, `ReconciliationOutcome`, `ReferenceAuthorityWitness`: `codex-rs/hepta-operations/src/model.rs`;
- `OperationLedger`: `codex-rs/hepta-operations/src/ledger.rs`;
- `Outbox`: `codex-rs/hepta-operations/src/outbox.rs`.

Durable integrated owner:

- migration/schema: `codex-rs/hepta-memory/migrations/0011_kernel_operations.sql` and `0012_kernel_operation_dispatch_claims.sql`;
- atomic operation/event/outbox publication, reopen verification and generation handoff: `codex-rs/hepta-memory/src/local_lease_outbox.rs`;
- durable claim lease/attempt owner: `codex-rs/hepta-memory/src/operation_claims.rs`;
- production-shaped writer, one-shot effect-entry fence, final-use boundary and reconciliation: `codex-rs/hepta-memory/src/production_writer.rs`;
- CognitiveStore destination adapter and terminal observer: `codex-rs/hepta-memory/src/production_cognitive_source_target.rs`;
- Automation destination-owned dedupe/apply + terminal observer: `codex-rs/hepta-automation/src/operation_destination.rs`;
- named Agentd runtime composition: `codex-rs/hepta-agentd/src/production_writer_host.rs`, `config.rs` and `runtime.rs`; one writer owns a destination-keyed dispatcher registry, rejects duplicate/empty destination registration, requires explicit destination routing when multiple adapters are attached, and reconciles each registered destination through observer-only bounded batches.

## Durability and activation

Durable source implementation is present. The existing CognitiveStore SQLite owner supplies WAL + `synchronous=FULL`, migration lineage verification, schema/integrity verification, single-writer lease fencing and reopen semantics.

`admit_operation` writes the admitted event, local outbox row and `cognitive_operation_ledger` row before one transaction commit. Fault hooks cover failure after the event, after the outbox and after the operation row; every injected failure leaves all three absent.

The production dispatcher first persists a bounded claim lease/attempt. Same-owner replay is idempotent while the lease is live, renewal is explicit, and a strictly newer generation may take over only after expiry/backoff with the attempt budget preserved. It then persists a one-shot effect-entry marker before target entry; from that point a crash reopens as indeterminate and must use observation/reconciliation instead of redispatch. A successor owner can recover an inherited queued identity only after the predecessor fence is durably terminal and reuses the same event/outbox identity.

The real final-use path consumes the non-serializable token owned by `kernel.authority`: `FinalUseAuthority::claim` followed immediately by `with_verified_use(... target.dispatch(...))`. Binding covers subject, destination, scope, exact payload and request/operation digest. A binding failure before adapter entry settles locally without invoking the target.

Two concrete destination slices are source-integrated. `CognitiveSourceOutboxTarget` reconstructs and verifies the full operation semantic digest, enforces predecessor/CAS expectation inside the same `BEGIN IMMEDIATE` destination transaction, and provides destination-owned terminal observation. Automation independently commits task mutation + semantic dedupe receipt in its own transaction and exposes a terminal observer. The lost-ack CognitiveStore test exercises durable prepare → final-use dispatch → destination commit → source indeterminate → destination observation → source reconcile.

This source composition does **not** claim default Agentd activation, target-host qualification, independent acceptance, promotion or release.

## Target-only design

The following remain outside the current executable closure:

- enrolled production authority/grant provisioning for a selected Agentd deployment; the multi-destination runtime path and continuous observer-only reconciler are source-composed but default process-environment startup does not manufacture credentials;
- destination-owned dedupe/apply/terminal-observer adapters for every additional effect destination before that destination is activated;
- bounded physical compaction/checkpoint retention for the append-only local lease/event/outbox audit journals;
- target-host power-loss, filesystem/storage-device and clock/rollback qualification;
- independently governed acceptance, canary, promotion and release.

The 16,384-record limits in `hepta-operations` apply only to the in-memory reference oracle. The integrated SQLite owner rejects before mutation at 100,000 operation/outbox rows and 400,000 event rows per lease; these limits preserve room for multiple lifecycle events per operation.

## Known limits and non-claims

The reference oracle is still not a durability or authority boundary. `ReferenceAuthorityWitness` remains deterministic test/reference evidence only.

The durable owner intentionally preserves the local lease/event/outbox journals as immutable hash-chained evidence. This candidate does not claim physical bounded-history compaction of those journals. Adding retention by deleting rows would break reopen/audit invariants; bounded compaction requires an explicit segment/checkpoint design with anti-resurrection evidence.

SQLite WAL + FULL is a repository durability implementation, not proof of a particular physical power-loss domain. Source qualification includes deterministic `SQLITE_FULL` atomic rollback + reopen and a child-process kill/reopen probe; neither substitutes for target-host physical power-loss evidence.

Compensation is always a new authorized operation. Rollback never rewrites an observed external effect into a fictitious success/failure.

## Verification

Current source test identities include:

- `operation_event_and_outbox_are_one_atomic_transaction_across_every_fault_boundary`;
- `durable_sequence_capacity_rejects_before_mutation_boundary`;
- `sqlite_full_aborts_operation_event_and_outbox_atomically_and_reopens_cleanly`;
- `qualification_durable_writer_crash_reopen_probe` (qualification-only child-process kill/reopen probe);
- `expired_owner_handoff_allows_successor_to_reconcile_indeterminate_without_resend`;
- `crash_after_target_send_reopens_as_indeterminate_and_cannot_redispatch`;
- `concurrent_dispatchers_have_one_durable_claim_and_one_target_call`;
- `final_use_is_consumed_at_target_entry_and_binding_mismatch_never_calls_target`;
- `queued_identity_survives_owner_handoff_and_dispatches_once_under_new_final_use`;
- `real_cognitive_destination_deduplicates_same_operation_and_rejects_payload_drift`;
- `full_durable_final_use_slice_reconciles_lost_ack_from_real_destination`;
- retained reference-oracle tests in `ledger_tests.rs` and `outbox_tests.rs`.

These are source test identities, not a claim that the current candidate CI has passed. Exact-head and deterministic merge-candidate workflow receipts remain separate evidence.

## Integration prerequisites

Before activation, the selected candidate must have current exact-head and merge-candidate native qualification, an enrolled production grant source, a continuously hosted dispatcher/reconciler, real destination observers for the activated effect set, target-host storage/power-loss qualification, operational retention/alert profiles and independent acceptance.

Claim levels for this candidate are therefore:

- `target`: full cross-owner transaction architecture and deployment requirements are specified;
- `reference-implemented`: bounded deterministic `hepta-operations` oracle;
- `production-implemented`: durable SQLite owner, bounded claim lease/attempt state, final-use boundary, CognitiveStore CAS destination and Automation destination are source-implemented;
- `execution-proved`: **pending current exact-candidate CI**;
- `activated/released`: false.
