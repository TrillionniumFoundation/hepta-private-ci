# kernel.operations durable store V1

## Status and claim boundary

This document describes the native durable backend implemented by
`codex-rs/hepta-operations/src/durable.rs` and
`codex-rs/hepta-operations/migrations/0001_operations.sql`.

Claim levels are intentionally separate:

| Level | Current claim |
| --- | --- |
| target design | specified |
| deterministic reference semantics | implemented |
| durable native source | implemented in this candidate |
| product caller composition | not claimed by this document |
| exact-head execution | requires current CI receipt |
| synthetic-merge execution | requires current CI receipt |
| independent acceptance | not claimed |
| activation / promotion / release | not claimed |

The older `OperationLedger` and `Outbox` remain bounded in-memory semantic
oracles. They are not silently redefined as persistent objects.

## Physical owner and database

The durable store is `DurableOperationStore`. It owns one SQLite lineage,
`hepta_operations_1.sqlite`, opened through the repository's shared
`codex_state::SqliteConfig::open_durable_evidence_pool` connection shim. That
shim uses SQLite WAL, `synchronous=FULL`, foreign-key enforcement and a bounded
busy timeout.

The operations module owns two authoritative tables in this lineage:

- `operation_ledger`: retained authoritative operation identity and outcome;
- `cross_owner_outbox`: source-side dispatch scheduling and lease state.

The database is not another destination owner. A destination owns its own
deduplication/apply transaction.

## Semantic identity

`PreparedIntent` binds:

- operation ID;
- source owner ID;
- scope digest;
- exact final payload digest;
- destination ID;
- optional expected-predecessor digest.

The domain-separated semantic digest excludes owner generation and authority
epoch. Those fields are runtime fences and may advance during a handoff without
changing the identity of the underlying operation.

Reusing an operation ID with a different semantic digest is a conflict. Exact
replay returns the retained operation and never resurrects a pruned terminal
outbox row.

## Atomic prepare transaction

`prepare_intent` receives the exact bounded payload bytes together with the
semantic intent. It rejects an empty/oversize payload or any byte sequence whose
SHA-256 does not equal `payload_digest` before mutation. The source outbox
persists those exact bytes (maximum 1 MiB), so a restarted dispatcher does not
depend on caller memory or payload reconstruction.

`prepare_intent` executes under one `BEGIN IMMEDIATE` transaction:

1. validate every semantic digest, bounded identity and exact payload binding;
2. check an existing operation for exact semantic replay or conflict;
3. enforce the bounded active-operation ceiling;
4. insert `operation_ledger`;
5. insert the matching `cross_owner_outbox` row;
6. commit once.

There is no committed state in which the operation exists without the initial
outbox row or the initial outbox row exists without its ledger parent.

An injected failure during the second insert must roll back both rows.

## Lease, attempts and fencing

Only a `pending` operation can be claimed for dispatch. A claim reloads the exact persisted payload bytes, verifies their stored digest,
and carries those bytes in the in-process `DispatchLease`. A claim records:

- worker ID;
- lease expiry;
- monotonically increasing integer fence;
- bounded attempt number.

Lease duration is `1..=60_000` ms. Claim batch size is at most 256 and attempts
are capped at 16. An expired `leased` row can be taken over under a strictly
newer fence. Renewal also increments the fence, making the previous token stale.

A stale lease cannot renew, release, mark dispatch, acknowledge or settle a
newer ownership attempt.

Before the effect boundary a caller may release only a still-`pending` lease.
After dispatch start, retry is deliberately not available.

## Durable no-blind-retry boundary

`record_dispatch_started` persists the operation as `dispatched` before the
external effect callback may run. This creates a conservative recovery rule:

- before that commit, the lease can be released or expire and be taken over;
- after that commit, the operation is never returned to the dispatch queue;
- a crash after the commit is recovered by terminal observation or
  `indeterminate` reconciliation, not by resend.

An exact replay of `record_dispatch_started` is observation-only and returns
`AlreadyStarted`. `dispatch_once` converts that condition to
`DispatchAlreadyStarted` and does not invoke the effect again.

## Final-use authority at the effect boundary

`DispatchEnvelope::final_use_binding` binds:

- source owner as subject;
- exact destination;
- exact payload digest;
- exact scope digest;
- an attempt digest containing semantic operation identity, owner generation,
  authority epoch, outbox fence and attempt number.

`execute_with_final_use` obtains the non-serializable
`kernel.authority::VerifiedUseToken` and immediately calls
`FinalUseAuthority::with_verified_use` around one synchronous effect closure.
This is the only helper in this module that treats a final-use token as effect
admission.

The durable dispatch marker is intentionally committed before final-use claim.
If authority fails after that marker, the operation remains conservatively
`dispatched`; recovery must observe `NotApplied` or quarantine it. This
ordering can create extra reconciliation but cannot make an unknown external
effect safe to resend.

Async providers must retain the same rule in their checked adapter: final-use
authority is revalidated immediately at the actual provider/consumer boundary.
The synchronous helper does not claim to make an arbitrary async network call
atomic with SQLite or with the authority store.

## Acknowledgement versus terminality

A transport acknowledgement is ordinary evidence. It is stored separately from
the terminal effect observation and never changes `dispatched` or
`indeterminate` into success.

Exact acknowledgement replay is idempotent; a changed digest conflicts.

Terminal states are:

- `applied`;
- `not_applied`;
- `quarantined`.

Only `observe_terminal` may settle a dispatched/indeterminate operation, and
it requires the current owner generation and current authority epoch.

## Owner handoff

`handoff_owner` requires:

- exact current owner generation;
- a strictly greater new owner generation;
- a strictly greater authority epoch.

It increments the writer/outbox fence and invalidates every old lease.

A pending operation is requeued for the new owner. A dispatched operation is
converted to `indeterminate`, never requeued. An already-indeterminate
operation remains indeterminate.

The authority owner must publish the new epoch before the new writer is allowed
to enter an effect boundary. The operations store does not mint that authority.

## Destination deduplication

The source ledger does not pretend that source idempotency proves destination
exactly-once behavior. A destination must deduplicate by the operation semantic
identity in its own authoritative transaction before applying the effect.

The native tests include a qualification-only durable filesystem destination to
exercise final-use admission and destination idempotency. That fixture is not a
product destination and does not establish product composition.

A production composition must supply a named destination owner and independently
prove:

1. duplicate delivery with the same semantic identity is observation-only;
2. semantic drift under an existing identity conflicts;
3. destination apply and destination dedupe receipt are atomic;
4. acknowledgement loss cannot duplicate the terminal effect;
5. reconciliation reads destination-owned evidence rather than guessing from
   transport state.

## Recovery and corruption policy

Open performs:

1. SQLite `PRAGMA quick_check`;
2. the checksum-bound SQLx migration ledger;
3. required schema-object checks;
4. foreign-key verification.

Missing safety triggers or foreign-key corruption fail closed.

Crash/reopen qualification covers the no-blind-retry boundary with an actual
child-process exit. Additional target-host evidence is still required for
disk-full, I/O errors, backup/restore and platform-specific filesystem behavior.

## Retention and non-resurrection

Active operation and active outbox rows cannot be deleted by schema trigger.

Terminal outbox rows are bounded by age and retained-count maintenance. The
authoritative `operation_ledger` identity is not pruned by that maintenance.
Therefore replay after outbox compaction returns the retained terminal operation
and cannot create a new outbox delivery for the same semantic operation.

Long-term ledger archival or destructive retention requires a separately
versioned policy with an anti-resurrection tombstone/identity mechanism; V1 does
not silently delete authoritative operation identities.

## Capacity

V1 native ceilings:

- active operations: 100,000;
- exact durable payload: 1,048,576 bytes;
- claim batch: 256;
- delivery attempts: 16;
- lease duration: 60 seconds;
- retained terminal outbox rows: 16,384;
- terminal outbox age target: seven days.

These are enforced native bounds, not throughput measurements. Host latency,
fsync cost, contention and backlog SLOs require target-host measurement.

## Required qualification matrix

The native source must pass, at minimum:

- prepare failure between ledger and outbox inserts leaves neither row;
- payload/digest drift rejects before mutation;
- exact payload bytes survive close/reopen and are restored by claim;
- exact prepare replay survives close/reopen;
- semantic drift conflicts;
- two handles cannot hold the same live lease;
- expired lease takeover increments the fence;
- renewal invalidates the old token;
- pending owner handoff fences the old worker and requeues once;
- dispatched owner handoff becomes indeterminate and cannot resend;
- acknowledgement does not imply terminal success;
- terminal replay is exact-tuple idempotent;
- terminal outbox compaction cannot resurrect an operation;
- missing required schema guard fails closed on reopen;
- actual process exit after dispatch-start commit reopens as non-dispatchable and can be moved to indeterminate by the current owner without reconstructing the lost lease;
- final-use authority is consumed at the checked effect boundary;
- destination duplicate apply is idempotent under the same semantic identity.

Passing repository tests does not self-certify independent acceptance,
activation, promotion or release.
