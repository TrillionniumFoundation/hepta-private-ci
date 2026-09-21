# Kernel operations durable store V1

## Scope

`DurableOperationStore` is the kernel.operations-owned SQLite persistence
boundary for canonical operation identity, immutable transition history and
cross-owner outbox lease state. It complements, rather than replaces, the
in-memory `OperationLedger` and `Outbox` reference models.

The store grants no authority, authenticates no caller and dispatches no
external effect. Product adapters must authenticate separately and consume the
non-serializable final-use token owned by `kernel.authority` immediately
before the real owner/effect boundary.

## Database lineage

The physical lineage is `hepta_operations_1.sqlite`, created beneath the
configured kernel owner root with the repository's durable SQLite connection
profile. Migration `0001_durable_operations.sql` owns four tables:

- `operation_records`: current operation projection;
- `operation_events`: immutable transition history;
- `operation_outbox`: current leased outbox projection;
- `operation_outbox_events`: immutable outbox history.

Event tables reject UPDATE and DELETE. Reopen checks SQLite integrity and
foreign keys, the exact SQLx migration ledger, projection-to-current-event
binding, complete event counts through the current revision, and the immutable
event triggers.

## Operation state machine

The durable transition chain is:

`pending -> authorized -> dispatched -> indeterminate? -> applied | not_applied | quarantined`.

Exact replay of an already committed transition is idempotent only when the
bound digest/generation tuple is identical. Reusing one operation ID with a
different payload or owner generation conflicts. Terminal observation is
accepted only from the operation's current owner generation.

An outbox acknowledgement never makes the operation terminal. Terminality
requires an independently supplied reconciliation outcome and outcome digest.

## Outbox lease

Each outbox row references an existing operation and binds destination and
payload digest. A claim binds owner ID, owner generation and an expiry no more
than 300 seconds in the future. A live claim fences other owners; only after
expiry may another owner/generation take over. Acknowledgement must come from
the live claim owner and is idempotent only for the exact acknowledgement
digest.

## Transaction model

Every mutation begins with `BEGIN IMMEDIATE`, updates the current projection
and appends the matching immutable event in one transaction. The implementation
is bounded to 16,384 current operation rows and 16,384 current outbox rows.

## Qualification boundary

Source tests cover crash/reopen through indeterminate and terminal
reconciliation, multi-handle operation identity conflict, live-lease fencing
and expired takeover, acknowledgement-not-terminal behavior, and corruption
rejection when the current projection no longer matches immutable history.

This is repository source implementation evidence only. It does not prove a
named product caller, final-use-authorized real dispatch, selected-host
performance, external rollback protection, independent acceptance, activation
or release.
