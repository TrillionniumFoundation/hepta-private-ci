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
must never be accepted by a production effect adapter. Its reference digest is
canonically derived from operation identity, final payload digest, authority
generation and expiry. Construction rejects a digest for any other semantic
tuple, and authorization replay revalidates the complete binding and current
expiry before it is treated as idempotent.

Acknowledged outbox state retains both the claiming owner generation and the
acknowledgement digest. A terminal replay is idempotent only for that exact
tuple; a different generation remains stale and a different digest conflicts.

## Public symbols and source bindings

- `OperationKey`, `OperationState`, `OperationRecord`,
  `ReconciliationOutcome`, `ReferenceAuthorityWitness`: `src/model.rs`;
- `OperationLedger`, `MAX_MODEL_OPERATION_RECORDS`: `src/ledger.rs`;
- `Outbox`, `OutboxIntent`, `OutboxState`,
  `MAX_MODEL_OUTBOX_RECORDS`: `src/outbox.rs`;
- stable errors, including reference-witness semantic mismatch:
  `src/error.rs`.

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
cannot be taken over inside this model. Caller-provided reference time is a test
input, not trusted production time. A semantically bound reference digest is
not authentication or a signature. Compensation is a new authorized operation,
never implicit rollback.

The reference ledger does not itself enforce final-use authority at an external
adapter. Product composition must consume the non-serializable token owned by
`kernel.authority` immediately before the effect boundary.

## Verification

The shared model tests cover invalid/zero digests, capacity, idempotent replay,
payload and operation drift, stale/expired reference witnesses, authority
generation and expiry digest binding, stale outbox acknowledgement generations,
changed acknowledgement digests, stale terminal generations, dispatch not being
terminal success and indeterminate reconciliation.

## Integration prerequisites

No production binary may use this crate as a durability or authority boundary.
A future backend must execute the same transition suite plus crash, disk-full,
corruption, migration, multi-writer and claim-takeover tests before activation.
