# Kernel operations durable store V1

This document describes the checked-in `DurableOperationStore` implementation.
It is an implementation contract for repository code, not an activation,
operator-acceptance, promotion or release receipt.

## Ownership and files

`kernel.operations` is the sole writer of the local `operation_ledger` and
`cross_owner_outbox` domains. The implementation lives in:

- `codex-rs/hepta-operations/src/durable.rs`;
- `codex-rs/hepta-operations/src/dispatcher.rs`;
- `codex-rs/hepta-operations/src/destination_dedupe.rs`;
- `codex-rs/hepta-operations/migrations/0001_durable_operations.sql`.

`OperationLedger`/`Outbox` remain in-memory transition oracles and are not the
production persistence boundary.

## Durable identity

An operation identity is `(scope_id, operation_id)`. Its semantic digest binds:

1. scope;
2. operation ID;
3. optional predecessor ID;
4. destination ID;
5. final payload digest.

Owner generation and authority epoch are fencing/admission metadata, not effect
semantic identity. Therefore a legitimate higher-generation writer takeover or
fresh authority epoch does not create a second logical effect. Reusing the same
identity with any changed semantic field conflicts.

## Atomic source transaction

`prepare_intent` opens `BEGIN IMMEDIATE` and, before committing, inserts both:

- the authoritative operation row in `operation_ledger`;
- the delivery row in `cross_owner_outbox`.

Neither row is externally visible without the other. The fault test installs a
SQLite trigger that aborts the outbox insert and verifies that the ledger insert
is rolled back as well.

SQLite is opened with WAL, `synchronous=FULL`, foreign keys and a bounded busy
timeout. SQLx migrations are applied before use. Open performs `quick_check`,
database-object checks and `foreign_key_check`; an invalid store fails closed.

## State machines

Operation state:

```text
prepared
   | claim + final-use admission
   v
dispatched --------------------------+
   |                                  |
   | ack lost / unknown / crash       | trusted terminal observation
   v                                  v
indeterminate ----------------> applied | not_applied | quarantined
```

Transport acceptance never implies terminal success.

Outbox state:

```text
queued -> leased -> queued             only when adapter proves NotAttempted
                  -> indeterminate      effect may have crossed boundary
                  -> acknowledged       trusted terminal observation
                  -> quarantined        explicit terminal quarantine
```

A terminal operation identity is retained even if terminal outbox rows are
pruned.

## Lease, fence and owner takeover

Each claim persists:

- `fence`;
- `attempts`;
- `worker_id`;
- `claim_owner_generation`;
- `lease_until_ms`.

Every new claim advances the fence and attempt count. Worker transitions require
the exact live tuple. Stale/expired leases fail closed.

Recovery differentiates two cases:

- expired lease while operation is still `prepared`: no effect boundary was
  durably entered, so the row can return to `queued` and a same/higher owner
  generation can take over;
- expired lease after `dispatched`: the result is unknown, so operation and
  outbox become `indeterminate`. A later worker cannot claim it for resend; a
  terminal observer must reconcile it.

This distinction is the crash/reopen fence against blind retry after an unknown
effect.

## Attempts, scheduling and capacity

V1 bounds are source constants:

- active operation rows: 100,000;
- outbox rows: 100,000;
- claim/list batch: 256;
- attempts: 32;
- one lease: at most 60 seconds;
- explicit NotAttempted retry delay: at most 300 seconds.

`next_eligible_at_ms` drives bounded retry scheduling. Only an adapter result
that explicitly guarantees `NotAttempted` can return a dispatched attempt to
`prepared`/`queued`. Uncertain or transport-accepted results are indeterminate.

## Final-use authority

`DurableDispatcher` consumes the real `kernel.authority` types from
`codex-hepta-contracts`.

For a dispatch it:

1. claims the durable outbox row;
2. derives a `FinalUseBinding` from operation, scope, destination and payload;
3. calls `FinalUseAuthority::claim`, consuming the single-use nonce;
4. binds the current authority epoch in the durable operation;
5. durably marks dispatch started;
6. executes the effect adapter through `FinalUseAuthority::with_verified_use`;
7. records `NotAttempted`, `Indeterminate` or trusted terminal observation.

The current authority API protects a synchronous final-use call. V1 therefore
requires a synchronous final effect-entry adapter. An arbitrary async network
operation may not retain a `VerifiedUseToken` outside that revocation fence.

## Destination-side deduplication

`kernel.operations` does not write another owner's store. Instead it exports a
small destination-owned protocol:

- `DESTINATION_DEDUPE_SCHEMA_V1`;
- `reserve_destination_effect`;
- `finish_destination_effect`.

A destination includes the table in its own migration and invokes both helpers
inside the same write transaction as its domain mutation:

```text
BEGIN destination transaction
  reserve(scope, operation, destination, semantic_digest)
  apply domain mutation
  finish(receipt_digest)
COMMIT
```

Crash/rollback removes both reservation and mutation. Exact replay after a
committed effect returns the retained receipt and performs no second mutation.
Changed semantic identity or changed terminal receipt conflicts.

This is the destination half of at-least-once transport with exactly-once
logical-effect semantics; it does not pretend source and destination share one
distributed ACID transaction.

## Reconciliation

A dispatched or indeterminate operation may become terminal only through
`observe_terminal`/`DurableDispatcher::reconcile` with:

- a nonzero evidence digest;
- a named terminal observer;
- an observer generation not older than the current owner generation;
- an explicit `Applied`, `NotApplied` or `Quarantined` outcome.

Exact terminal replay is idempotent. A conflicting terminal result is rejected.
Compensation is a new operation with fresh authority.

## Retention and metrics

The store reports bounded operational metrics for operation/outbox states and
oldest ready work. Terminal-outbox pruning is age/count bounded and never
deletes the authoritative operation ledger identity, so backup/GC cannot make a
completed operation reusable through normal APIs.

The module does not claim external anti-rollback protection. A restored older
SQLite image requires an independent host checkpoint/rollback witness if the
product needs that property.

## Qualification matrix

Repository tests cover:

- atomic ledger/outbox rollback on injected failure;
- exact replay and semantic drift conflict;
- lease expiry and higher-generation takeover before dispatch;
- reopen after dispatch forcing reconciliation;
- acknowledgement loss;
- two independent SQLite handles contending on one identity;
- destination transaction dedupe and replay;
- retained operation identity after outbox GC;
- corrupt database reopen;
- real signed final-use authority at effect entry.

Product/host qualification must additionally exercise actual process kill or
power interruption, real disk-full/ENOSPC, target-filesystem corruption and the
selected destination/caller. Those observations are not manufactured by this
source document.
