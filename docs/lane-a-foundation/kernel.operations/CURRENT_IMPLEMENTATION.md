# kernel.operations current implementation

## Current executable contract

`codex-rs/hepta-operations` currently provides an **in-memory deterministic
reference model**. `OperationLedger` models `Pending -> Authorized ->
Dispatched -> Indeterminate/terminal` transitions, exact operation/payload
identity, monotonic revisions and generation-fenced terminal observation.
`Outbox` models enqueue, generation-fenced claim and idempotent acknowledgement.
Zero dispatch, uncertainty and terminal-evidence digests reject before state
mutation.

This model is useful as an oracle for a later durable backend. It is not itself
a durable operation ledger or a production reconciliation service.

## Target-only design

The target design is a transactional durable ledger/outbox with atomic local
intent publication, destination deduplication, bounded attempts, crash/reopen
recovery, current-fence reconciliation and migration/rollback support. None of
those durability properties may be inferred from cloning or reopening the
in-memory Rust value in a unit test.

## Known limits and non-claims

There is no database, append-only file, fsync, interprocess lock, lease expiry,
background dispatcher, terminal observer registry or production caller in this
crate. Process exit loses the model state. Compensation is not rollback; it
must be a new authorized operation in a future product composition.

## Verification

Native tests cover dispatch not being terminal success, indeterminate recovery,
payload-drift conflict, stale generations, expired witnesses, revision
exhaustion and zero evidence digests. A durable implementation must run the
same transition suite plus crash, corruption, migration and multi-writer tests.
