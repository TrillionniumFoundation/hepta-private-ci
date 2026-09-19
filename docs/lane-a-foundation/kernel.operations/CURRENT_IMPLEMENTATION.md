# `kernel.operations` current implementation

## Current executable contract

The current candidate deliberately has two distinct surfaces.

1. `codex-rs/hepta-operations` remains the bounded in-memory reference oracle for deterministic operation/outbox semantics.
2. The durable production-shaped source path is integrated into the existing CognitiveStore owner in `codex-rs/hepta-memory`: `ProductionDurableWriter` + `LocalLeaseOutbox` atomically bind the complete `OperationIntent`, the local event and the local outbox row in one SQLite `BEGIN IMMEDIATE` transaction.

The durable operation identity binds operation ID, exact payload digest, scope, owner, destination and optional predecessor digest. Exact replay is idempotent only for the same semantic tuple. Changed operation semantics conflict.

Dispatch is claimed durably before the external boundary. A claim is represented by a durable indeterminate marker under the current generation/fence; concurrent or reopened dispatchers cannot blindly resend it. A terminal predecessor generation may hand an unresolved queued identity to a newer owner without creating a second event/outbox identity.

## Public symbols and source bindings

Reference oracle:

- `OperationIntent`, `OperationKey`, `OperationState`, `OperationRecord`, `ReconciliationOutcome`, `ReferenceAuthorityWitness`: `codex-rs/hepta-operations/src/model.rs`;
- `OperationLedger`: `codex-rs/hepta-operations/src/ledger.rs`;
- `Outbox`: `codex-rs/hepta-operations/src/outbox.rs`.

Durable integrated owner:

- migration/schema: `codex-rs/hepta-memory/migrations/0011_kernel_operations.sql`;
- atomic operation/event/outbox publication, reopen verification and generation handoff: `codex-rs/hepta-memory/src/local_lease_outbox.rs`;
- production-shaped writer, durable pre-dispatch claim, final-use boundary and reconciliation: `codex-rs/hepta-memory/src/production_writer.rs`;
- real CognitiveStore destination adapter and terminal observer: `codex-rs/hepta-memory/src/production_cognitive_source_target.rs`;
- named Agentd host seam: `codex-rs/hepta-agentd/src/production_writer_host.rs`.

## Durability and activation

Durable source implementation is present. The existing CognitiveStore SQLite owner supplies WAL + `synchronous=FULL`, migration lineage verification, schema/integrity verification, single-writer lease fencing and reopen semantics.

`admit_operation` writes the admitted event, local outbox row and `cognitive_operation_ledger` row before one transaction commit. Fault hooks cover failure after the event, after the outbox and after the operation row; every injected failure leaves all three absent.

The production dispatcher persists a one-shot dispatch claim before target entry. From that point a crash reopens as indeterminate and must use status/reconciliation instead of redispatch. A successor owner can recover an inherited queued identity only after the predecessor fence is durably terminal and reuses the same event/outbox identity.

The real final-use path consumes the non-serializable token owned by `kernel.authority`: `FinalUseAuthority::claim` followed immediately by `with_verified_use(... target.dispatch(...))`. Binding covers subject, destination, scope, exact payload and request/operation digest. A binding failure before adapter entry settles locally without invoking the target.

The real destination slice is `CognitiveSourceOutboxTarget`. It applies through the CognitiveStore source ledger, deduplicates exact operation identity, rejects payload drift, and provides a destination-owned terminal observation. The lost-ack test exercises durable prepare → final-use dispatch → destination commit → source indeterminate → destination observation → source reconcile.

This source composition does **not** claim default Agentd activation, target-host qualification, independent acceptance, promotion or release.

## Target-only design

The following remain outside the current executable closure:

- always-on/default Agentd composition with an enrolled production grant source and hosted dispatcher/reconciler;
- equivalent destination-owned dedupe/apply/terminal-observer adapters for every registered effect destination;
- bounded physical compaction/checkpoint retention for the append-only local lease/event/outbox audit journals;
- target-host power-loss, filesystem/storage-device and clock/rollback qualification;
- independently governed acceptance, canary, promotion and release.

The 16,384-record limits in `hepta-operations` apply only to the in-memory reference oracle. The integrated SQLite owner does not inherit that model ceiling.

## Known limits and non-claims

The reference oracle is still not a durability or authority boundary. `ReferenceAuthorityWitness` remains deterministic test/reference evidence only.

The durable owner intentionally preserves the local lease/event/outbox journals as immutable hash-chained evidence. This candidate does not claim physical bounded-history compaction of those journals. Adding retention by deleting rows would break reopen/audit invariants; bounded compaction requires an explicit segment/checkpoint design with anti-resurrection evidence.

SQLite WAL + FULL is a repository durability implementation, not proof of a particular physical power-loss domain. The child-process kill/reopen probe is process-crash evidence and explicitly makes no physical power-loss claim.

Compensation is always a new authorized operation. Rollback never rewrites an observed external effect into a fictitious success/failure.

## Verification

Current source test identities include:

- `operation_event_and_outbox_are_one_atomic_transaction_across_every_fault_boundary`;
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
- `production-implemented`: durable SQLite owner, final-use boundary and one real CognitiveStore destination are source-implemented;
- `execution-proved`: **pending current exact-candidate CI**;
- `activated/released`: false.
