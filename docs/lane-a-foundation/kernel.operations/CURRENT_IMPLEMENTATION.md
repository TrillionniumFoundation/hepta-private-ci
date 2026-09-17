# `kernel.operations` current implementation

## Current executable contract

`codex-rs/hepta-operations` now contains two deliberately separate surfaces:

1. the existing bounded in-memory reference model (`OperationLedger` and
   `Outbox`), retained as a deterministic transition oracle; and
2. `DurableOperationStore`, a SQLite/WAL durable owner for the production target
   semantics.

The durable store owns `operation_ledger` and `cross_owner_outbox` in one schema
lineage. `prepare_intent` creates both rows in one `BEGIN IMMEDIATE` transaction,
so a committed operation cannot exist without its source outbox. Operation
identity binds scope, operation ID, predecessor, destination and exact payload
digest. Reusing that identity with different semantics conflicts.

The source outbox has bounded attempts, next-eligible time, worker identity,
lease expiry, owner generation and a monotonically increasing fence. Expired
leases are safe to requeue only while the source operation is still `prepared`.
If dispatch admission may have crossed the effect boundary, recovery changes the
operation to `indeterminate` and does not blindly retry it.

## Final-use authority and effect entry

`authorize_dispatch` consumes a real `kernel.authority` `SignedFinalUseGrant`
and persists a `dispatching` write-ahead state before the adapter entry.
`AuthorizedDispatch::enter` consumes the non-serializable `VerifiedUseToken`
through `FinalUseAuthority::with_verified_use` immediately around the effect
entry. A final-use rejection before callback entry is classified as
not-dispatched; it does not manufacture a remote outcome.

Transport dispatch and acknowledgement remain distinct from terminal effect
observation. Missing acknowledgement moves the source operation to
`indeterminate`. `observe_terminal` requires a current-generation observer and
an evidence digest before it can settle `Applied`, `NotApplied` or
`Quarantined`.

## Destination deduplication

`DestinationDedupeStore` supplies the destination half of the protocol. In
product composition the destination owner installs the exact dedupe schema in
its own database lineage and calls `from_migrated_pool`. `begin_apply` holds the
destination write transaction open so owner-domain SQL and the immutable dedupe
receipt commit atomically. An exact repeated operation returns the stored
receipt; payload drift conflicts.

The standalone destination database exists only for qualification. It is not a
new cross-owner source of truth and must not replace a destination owner's own
transaction boundary.

## Persistence, recovery and retention

The durable owner uses SQLite WAL mode, `synchronous=FULL`, foreign keys and a
bounded busy timeout. Store open runs `PRAGMA quick_check`, the checksum-bound
SQLx migration lineage, required-table verification and foreign-key validation
before recovery. Unknown/incomplete/drifted migration state fails closed.

Terminal source rows can be compacted only after writing an immutable semantic
tombstone in the same transaction. Tombstones prevent an old operation identity
from being resurrected after pruning or backup restoration.

## Public source bindings

Durable implementation:

- `OperationIntentV1`, durable state/receipt/error types: `src/durable_model.rs`;
- `DurableOperationStore`, claim/lease/dispatch/reconcile/metrics/GC:
  `src/durable_store.rs`;
- `DestinationDedupeStore`: `src/destination_dedupe.rs`;
- source schema: `migrations/0001_durable_operations.sql`;
- destination-owner schema reference:
  `destination_migrations/0001_operation_dedupe.sql`.

Reference oracle:

- `OperationLedger`: `src/ledger.rs`;
- `Outbox`: `src/outbox.rs`;
- reference state/witness types: `src/model.rs`.

## Verification in this candidate

Focused durable tests cover atomic prepare/reopen, exact concurrent prepare,
payload conflict, lease takeover, stale fencing, crash/reopen after dispatch
admission, acknowledgement loss, explicit not-dispatched retry, terminal
reconciliation, migration-checksum drift, corruption failure and tombstone
anti-resurrection. Destination tests prove that a domain mutation and dedupe
receipt share one transaction and roll back together.

These test sources are not a claim that an exact GitHub candidate passed until
the applicable Lane A/source workflows reach terminal success.

## Remaining integration boundary

The durable source implementation does **not** by itself activate a product.
A named destination owner must install the dedupe migration in its own lineage,
a named product caller must construct `OperationIntentV1`, and the host must
supply current final-use grants and a trusted terminal observer. Activation,
operator acceptance, canary, promotion and release remain separate gates.

The in-memory reference witness remains test-only and must never be treated as a
production credential. Compensation remains a new authorized operation, never
implicit rollback.
