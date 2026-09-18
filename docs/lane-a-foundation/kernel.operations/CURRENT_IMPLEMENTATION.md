# `kernel.operations` current implementation

## Current executable contract

The crate now has two explicitly separated executable surfaces.

The legacy `OperationLedger` and `Outbox` remain bounded in-memory
deterministic reference models. They exercise state-machine semantics but do not
provide persistence or production authority.

`DurableOperationStore` is the repository-owned persistent implementation. It
owns `hepta_operations_1.sqlite`, opened through the shared FULL-synchronous
WAL SQLite shim, and atomically co-commits `operation_ledger` with
`cross_owner_outbox` during prepare. It implements bounded expiring claim
leases, monotonically increasing fences, bounded attempts, owner-generation plus
authority-epoch handoff, exact bounded payload persistence/recovery, a durable
dispatch-start/no-blind-retry boundary, transport acknowledgement distinct from
terminal observation, indeterminate
reconciliation, and bounded terminal-outbox retention without removing the
authoritative operation identity.

Exact semantic replay is idempotent. Reusing an operation identity with changed
owner/scope/payload/destination/predecessor semantics conflicts.

## Public symbols and source bindings

Reference surface:

- `OperationKey`, `OperationState`, `OperationRecord`,
  `ReconciliationOutcome`, `ReferenceAuthorityWitness`: `src/model.rs`;
- `OperationLedger`, `MAX_MODEL_OPERATION_RECORDS`: `src/ledger.rs`;
- `Outbox`, `OutboxIntent`, `OutboxState`,
  `MAX_MODEL_OUTBOX_RECORDS`: `src/outbox.rs`.

Durable surface:

- `PreparedIntent`, `DurableOperationStore`, `DurableOperationRecord`,
  `DispatchLease`, `DispatchEnvelope`, `EffectObservation`:
  `src/durable.rs`;
- physical schema/guards: `migrations/0001_operations.sql`;
- errors shared by the reference and durable surfaces: `src/error.rs`.

## Durability and activation

Local ledger/outbox durability is implemented in source in this candidate.
Prepare runs under one `BEGIN IMMEDIATE` transaction; a second-write failure
rolls back the first write. Open verifies SQLite quick-check, foreign keys,
migration state and required safety schema objects.

A committed pre-dispatch lease can expire and be taken over under a newer fence.
A committed dispatch-start state is never requeued after crash/reopen. A newer
owner must reconcile it, and dispatched handoff becomes `indeterminate`.

Activation is **not** implied. The implementation map still records no named
product caller and no independently accepted production composition. Exact-head
and synthetic-merge CI are separate execution evidence.

## Target-only design

The remaining target composition is a named authenticated product caller plus a
real destination owner's atomic semantic-dedupe/apply transaction and trusted
terminal observer. Target-host disk-full, backup/restore, performance,
independent acceptance, canary, promotion and release remain outside what
source presence can prove.

The detailed current storage/transaction contract is
[`DURABLE_STORE_V1.md`](DURABLE_STORE_V1.md).

## Known limits and non-claims

`ReferenceAuthorityWitness` remains test/reference evidence only. It is not a
cryptographic credential and must never be accepted by a production effect
adapter.

The durable dispatch path binds an attempt-specific `FinalUseBinding` to exact
destination, scope, payload, owner generation, authority epoch, outbox fence and
attempt. `execute_with_final_use` consumes `kernel.authority`'s
non-serializable `VerifiedUseToken` immediately around one synchronous checked
effect closure. The operation store does not mint authority.

The durable dispatch marker is committed before final-use claim. If authority
then rejects, recovery is conservative: the operation remains dispatched and
must be observed `NotApplied` or quarantined; it is never blindly resent.

Destination deduplication remains destination-owned. The durable filesystem
destination in `durable_tests.rs` is qualification-only and is not a product
destination or product caller.

Terminal source-outbox rows may be compacted, but the authoritative operation
identity is retained. V1 does not implement destructive long-term operation
ledger archival.

Compensation is a new authorized operation, never implicit rollback.

## Verification

Reference tests:

- `src/ledger_tests.rs`: state transitions, replay, witness binding, revision
  exhaustion and terminal reconciliation;
- `src/outbox_tests.rs`: claim/ack generation fencing, replay, digest and
  capacity behavior.

Durable tests:

- atomic prepare rollback under an injected outbox-write failure;
- exact payload/digest binding before mutation and payload recovery from the durable outbox;
- semantic replay/conflict across close/reopen;
- multi-handle live-lease exclusion and expired-lease takeover;
- renewal and owner-handoff stale-fence rejection;
- no blind retry after dispatch start;
- acknowledgement versus terminal observation;
- terminal replay and terminal-outbox retention without resurrection;
- fail-closed reopen when a required schema safety trigger is missing;
- actual child-process exit after the dispatch-start commit;
- final-use authority consumption at a qualification-only durable destination.

Source tests are test identities, not pass receipts. Repository CI must prove the
exact candidate.

## Integration prerequisites

Before product composition may be claimed:

1. bind `DurableOperationStore` to a named authenticated product caller;
2. bind one real destination owner's atomic semantic-dedupe/apply operation;
3. bind a trusted destination-owned terminal observer;
4. preserve `kernel.authority` final-use validation at the real effect
   boundary;
5. retain exact-head and deterministic synthetic-merge receipts;
6. run target-host disk-full/I/O/corruption/backup-restore and performance
   qualification;
7. complete independent semantic/security review and the ordinary activation,
   canary, promotion and release gates.

No production binary may use the reference `OperationLedger` or `Outbox` as a
durability or authority boundary.
