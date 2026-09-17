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

`authorize_dispatch` consumes a real `kernel.authority` `SignedFinalUseGrant`
and persists a `dispatching` write-ahead state before the adapter entry.
`AuthorizedDispatch::enter` consumes the non-serializable `VerifiedUseToken`
through `FinalUseAuthority::with_verified_use` immediately around the effect
entry. Transport dispatch and acknowledgement remain distinct from terminal
effect observation. Missing acknowledgement moves the source operation to
`indeterminate`; `observe_terminal` requires a current-generation observer and
an evidence digest before settlement.

## Public symbols and source bindings

Durable implementation:

- `OperationIntentV1`, durable state/receipt/error types: `src/durable_model.rs`;
- `DurableOperationStore`, claim/lease/dispatch/reconcile/metrics/GC:
  `src/durable_store.rs`;
- `DurableDispatcher`: `src/dispatcher.rs`;
- `DestinationDedupeStore`: `src/destination_dedupe.rs`;
- source schema: `migrations/0001_durable_operations.sql`;
- destination-owner schema reference:
  `destination_migrations/0001_operation_dedupe.sql`.

Reference oracle:

- `OperationLedger`: `src/ledger.rs`;
- `Outbox`: `src/outbox.rs`;
- reference state/witness types: `src/model.rs`.

## Durability and activation

The durable owner uses SQLite WAL mode, `synchronous=FULL`, foreign keys and a
bounded busy timeout. Store open runs `PRAGMA quick_check`, the checksum-bound
SQLx migration lineage, required-table verification and foreign-key validation
before recovery. Unknown, incomplete or checksum-drifted migration state fails
closed.

`DestinationDedupeStore` supplies the destination half of the protocol. In
product composition the destination owner installs the exact dedupe schema in
its own database lineage and calls `from_migrated_pool`. `begin_apply` holds the
destination write transaction open so owner-domain SQL and the immutable dedupe
receipt commit atomically. The standalone destination database is
qualification-only and is not a new authoritative cross-owner store.

Terminal source rows can be compacted only after writing an immutable semantic
tombstone in the same transaction. Tombstones prevent an old operation identity
from being resurrected after pruning or backup restoration.

Source durability is implemented in this candidate; product activation is not.
No named production caller, selected target host, operator acceptance, canary,
promotion or release is claimed by source presence.

## Target-only design

The remaining target-only capabilities are product composition rather than a
second durability implementation: a named product caller, installation of the
destination dedupe table in each selected destination owner's own migration
lineage, a continuously hosted reconciler backed by a trusted terminal observer,
and selected-host measurements/qualification including real power-loss and
disk-exhaustion behavior.

A product adapter must continue consuming a fresh final-use authority token at
the effect boundary. Destination dedupe must remain destination-owned; source
outbox acknowledgement alone never proves terminal effect success.

## Known limits and non-claims

The in-memory reference witness remains test-only and must never be treated as a
production credential. The durable SQLite owner is not a distributed
anti-rollback oracle and does not manufacture trusted time. Clock rollback
against active durable state fails closed, but trusted-time provisioning remains
a host concern.

A `NotDispatched` classification is eligible for automatic requeue only when the
adapter can prove callback entry produced no downstream effect. Unknown effect,
acknowledgement loss, or crash after durable dispatch admission becomes
`indeterminate`. Compensation is a new authorized operation, never implicit
rollback.

The destination standalone store demonstrates the transaction protocol but may
not replace an owner's real durable domain transaction. Qualification fixtures,
source tests and documentation grant no runtime, operator, promotion or release
authority.

## Verification

Focused durable tests cover atomic prepare/reopen, exact concurrent prepare,
payload conflict, lease takeover, stale fencing, crash/reopen after dispatch
admission, acknowledgement loss, explicit not-dispatched retry, terminal
reconciliation, migration-checksum drift, database corruption and tombstone
anti-resurrection. Destination tests prove that a domain mutation and dedupe
receipt share one transaction and roll back together.

The retained reference tests continue to exercise deterministic transition
parity, idempotent replay, generation fencing and the distinction between
transport dispatch and terminal success.

These test sources are not a claim that an exact GitHub candidate passed until
the applicable Lane A source-head and synthetic-merge workflows reach terminal
success.

## Integration prerequisites

Before activation, at least one named destination owner must install the dedupe
schema in its own migration lineage, a named product caller must construct and
persist `OperationIntentV1`, the host must supply current final-use grants, and a
trusted terminal observer must settle unknown effects. The selected host must
also provide commit/fsync, backlog, contention, power-loss and real
disk-exhaustion qualification evidence.

Activation, operator acceptance, canary, promotion and release remain separate
gates even after all source-level tests pass.
