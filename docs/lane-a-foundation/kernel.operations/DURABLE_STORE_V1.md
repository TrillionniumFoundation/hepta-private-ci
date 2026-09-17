# kernel.operations durable store V1

## Scope

`DurableOperationStore` is the SQLite-backed owner of the local `operation_ledger`
and `cross_owner_outbox` domains. The older `OperationLedger` and `Outbox` remain
bounded deterministic reference oracles; they are not the persistence boundary.

The durable database is `hepta_operations_1.sqlite`, opened through the shared
`SqliteConfig::open_durable_evidence_pool` profile: WAL journal mode, SQLite
foreign keys, busy timeout, and `synchronous=FULL`. Store open runs
`PRAGMA quick_check`, applies the checksum-tracked `sqlx` migration lineage, then
verifies required tables and foreign-key integrity before serving reads or
writes.

## Atomic intent publication

`prepare_intent` is the sole durable creation path. One `BEGIN IMMEDIATE`
transaction validates semantic identity, predecessor state, capacity and
anti-resurrection tombstones, then inserts both:

- `operation_records(scope_id, operation_id, scope/request/payload digests,
  destination, predecessor, writer generation, authority epoch, revision,
  state, timestamps)`; and
- `cross_owner_outbox(scope_id, operation_id, destination_id, payload_digest,
  fence, claim generation, bounded attempts, next eligible time,
  acknowledgement/reason digests, timestamps)`.

The transaction either commits both identities or neither. Exact semantic replay
is idempotent. Reusing `(scope_id, operation_id)` with changed semantics
conflicts. A terminal identity moved to `operation_tombstones` cannot be
resurrected.

## Claims, fencing and crash recovery

Only a `queued` row or an expired **pre-dispatch** `leased` row may be claimed.
A claim binds worker identity, writer generation, monotonic fence, attempt count
and bounded lease deadline. A stale generation or stale fence cannot renew,
release, arm or settle a newer attempt. A higher generation may take over an
expired pre-dispatch lease and atomically advances the operation writer
generation/revision.

Before an adapter can enter an external effect, `arm_dispatch` atomically moves
the operation to `dispatched` and the outbox out of the retryable lease set into
`indeterminate`. Therefore a crash after arming never turns into an expired lease
that another worker can blindly resend. Reopen observes the same non-retryable
identity and requires reconciliation.

## Authority and dispatch

`dispatch_with_final_use` accepts a real `SignedFinalUseGrant` and
`FinalUseAuthority`. It verifies that the durable operation's authority epoch,
destination, request digest, scope digest and final payload digest equal the
signed `FinalUseBinding`. The authority owner durably consumes the nonce, and
`with_verified_use` rechecks live revocation and expiry immediately around the
adapter callback. `kernel.operations` cannot mint the token.

A transport acknowledgement changes only the outbox acknowledgement state; it
does **not** mark the operation applied. An unknown effect remains dispatched or
indeterminate and is excluded from the retryable outbox query.

## Destination-owned deduplication

Cross-owner exactly-once logical effect semantics require the destination to own
its dedupe fact. `DESTINATION_DEDUPE_SCHEMA_V1`, `reserve_destination_effect`
and `record_destination_terminal` operate on a caller-supplied
`sqlx::Transaction<Sqlite>` only. They never open or commit another owner's
database.

The destination must reserve the semantic identity, perform the domain mutation,
and write the terminal dedupe receipt in the **same destination-owned
transaction**. Rollback removes both the domain mutation and reservation; replay
after commit observes the terminal receipt instead of reapplying the mutation.
Payload drift conflicts.

## Reconciliation and terminality

A trusted destination observer may settle only `dispatched` or `indeterminate`
operations. Terminal outcomes are `Applied`, `NotApplied` or `Quarantined`, are
writer-generation fenced, bind a nonzero evidence digest, and atomically settle
both the operation and its outbox. Exact terminal replay is idempotent;
conflicting terminal evidence is rejected.

Compensation is never implicit rollback. It is a new operation with a new
identity and current authority.

## Capacity, retention and observability

The V1 ceilings are:

- active durable operations: 100,000;
- durable outbox rows: 100,000;
- attempts per outbox identity: 16;
- claim/read batch: 256;
- lease duration: at most 60 seconds.

`metrics` exposes active/terminal operation counts, queued/leased/acknowledged/
indeterminate outbox counts, oldest ready age and tombstone count. Terminal
retention is bounded by age and retained-row policy. Pruning first persists a
semantic tombstone and only then deletes terminal outbox/operation rows in the
same transaction.

## Qualification boundary

Source tests cover atomic publication/reopen, semantic conflict, expired-lease
higher-generation takeover, stale fence rejection, non-retryable armed dispatch,
transport acknowledgement remaining nonterminal, terminal reopen, tombstone
anti-resurrection, independent SQLite handles, destination-transaction rollback
and real final-use token consumption.

These tests establish repository source behavior. Product activation still
requires a named product caller, a destination-owned installed dedupe migration
and domain mutation, a trusted terminal observer, target-host fault evidence and
independent acceptance. Documentation or repository CI does not grant canary,
promotion or release authority.
