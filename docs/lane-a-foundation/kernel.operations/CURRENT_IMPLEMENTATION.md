# `kernel.operations` current implementation

## Current executable contract

`codex-rs/hepta-operations` is a bounded **in-memory reference model**, not a
durable operation service. It models pending, authorized, dispatched,
indeterminate and terminal states; exact operation/payload identity; monotonic
revisions; generation-fenced terminal observation; and a bounded in-memory
outbox.

All evidence digests required by transitions are nonzero. Exact command replay
is idempotent; identity reuse with changed semantics conflicts. The
`ReferenceAuthorityWitness` is intentionally not a cryptographic credential and
must never be accepted by a production effect adapter.

## Public symbols and source bindings

- `OperationKey`, `OperationState`, `OperationRecord`,
  `ReconciliationOutcome`, `ReferenceAuthorityWitness`: `src/model.rs`;
- `OperationLedger`, `MAX_MODEL_OPERATION_RECORDS`: `src/ledger.rs`;
- `Outbox`, `OutboxIntent`, `OutboxState`,
  `MAX_MODEL_OUTBOX_RECORDS`: `src/outbox.rs`;
- stable errors: `src/error.rs`.

## Durability and activation

Durability is **not implemented**. Process exit loses every record and claim.
There is no database, journal, fsync, interprocess lock, claim lease, dispatcher
or product caller. The module is inactive.

## Target-only design

The target is a transactional durable ledger/outbox with atomic intent
publication, destination deduplication, bounded claim leases, crash/reopen
takeover, reconciliation, migrations, corruption handling and rollback.

## Known limits and non-claims

Cloning a model is not reopen recovery. An outbox claim has no lease expiry and
cannot be taken over inside this model. Caller-provided reference time and
witnesses are test inputs, not trusted production authority. Compensation is a
new authorized operation, never implicit rollback.

## Verification

The shared model tests cover invalid/zero digests, capacity, idempotent replay,
payload drift, stale generations, expiry, revision exhaustion, dispatch not
being terminal success and indeterminate reconciliation.

## Integration prerequisites

No production binary may use this crate as a durability or authority boundary.
A future backend must execute the same transition suite plus crash, disk-full,
corruption, migration, multi-writer and claim-takeover tests before activation.
