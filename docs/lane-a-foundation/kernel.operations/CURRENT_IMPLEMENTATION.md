# `kernel.operations` current implementation

## Current executable contract

`codex-rs/hepta-operations` now contains two deliberately separate surfaces:

1. the bounded in-memory `OperationLedger`/`Outbox` reference oracle used for
   deterministic state-machine semantics; and
2. `DurableOperationStore`, the SQLite-backed owner of the local operation
   journal and transactional cross-owner outbox.

The durable intent binds scope, operation identity, scope/request/final-payload
digests, destination, predecessor, writer generation and authority epoch. Exact
semantic replay is idempotent; identity reuse with changed semantics conflicts.
`prepare_intent` inserts the operation record and local outbox row in one
`BEGIN IMMEDIATE` transaction.

Pre-dispatch claims are bounded by worker identity, writer generation, monotonic
fence, attempt count and lease deadline. An expired pre-dispatch lease may be
taken over by the same or a higher generation. `arm_dispatch` durably removes
the attempt from the retryable lease set before an external adapter can be
entered. A crash after arming therefore leaves a non-retryable unknown-effect
record that must reconcile instead of being blindly resent.

Transport acknowledgement remains distinct from terminal effect observation.
Only trusted terminal evidence settles an operation as `Applied`, `NotApplied`
or `Quarantined`.

## Public symbols and source bindings

- `DurableOperationStore`: `src/durable_store.rs`;
- durable intent/record/outbox/claim/metric types: `src/durable_model.rs`;
- `EffectAdapter`, `TerminalObserver`, `dispatch_with_final_use`,
  `reconcile_with`: `src/dispatcher.rs`;
- destination-owned transaction helpers `reserve_destination_effect` and
  `record_destination_terminal`: `src/destination_dedupe.rs`;
- durable schema lineage: `migrations/0001_durable_operations.sql`;
- deterministic reference oracle: `src/model.rs`, `src/ledger.rs`,
  `src/outbox.rs`;
- stable errors: `src/error.rs`.

The V1 operating/schema reference is `DURABLE_STORE_V1.md`.

## Durability and activation

The local operation journal and outbox are durably implemented with the shared
SQLite WAL/FULL-synchronous profile. Store open runs quick/integrity checks,
applies the migration lineage and verifies required schema objects. Process
reopen preserves operation/outbox state, leases, fences, acknowledgement state,
terminal state and anti-resurrection tombstones.

Durability does not imply product activation. No named production caller is
claimed by this document. Destination owners must install their own dedupe table
and execute dedupe + domain mutation in one destination-owned transaction. A
trusted terminal observer is also required for each composed destination.

## Target-only design

The remaining target work is product composition rather than a replacement
ledger backend:

- bind a named production caller through a registered `kernel.operations` port;
- install destination-specific dedupe migration/domain-mutation adapters;
- bind a destination-authoritative terminal observer;
- execute target-host crash/disk-full/corruption qualification;
- complete independent acceptance, activation, canary, promotion and release.

## Known limits and non-claims

SQLite durability is local to the selected host and does not provide an external
anti-rollback oracle. Wall-clock lease deadlines assume the host clock does not
move behind a persisted watermark; backward movement is fail-closed where it is
observed. The destination dedupe helpers intentionally do not open or commit
another owner's database; correct exactly-once logical effect semantics require
the destination to put reservation, domain mutation and terminal receipt in the
same transaction.

`ReferenceAuthorityWitness` remains reference-only. The durable dispatcher uses
the real `FinalUseAuthority`/`SignedFinalUseGrant` path and validates the durable
operation's epoch, destination, request, scope and final payload before the
non-serializable token is consumed immediately around adapter entry.

Compensation remains a new authorized operation, never implicit rollback.

## Verification

Reference-model tests continue to cover invalid digests, capacity, exact replay,
payload/operation drift, authority expiry/binding, generation fencing and the
rule that dispatch acknowledgement is not terminal success.

Durable tests additionally cover atomic intent+outbox publication across reopen,
durable semantic conflicts, expired-lease higher-generation takeover, stale
lease rejection, armed-dispatch non-retryability, transport acknowledgement
remaining nonterminal, terminal reopen, tombstone anti-resurrection, concurrent
independent SQLite handles, destination-owned transaction rollback/deduplication
and real final-use token consumption at the dispatch boundary.

These are source tests, not target-host or independent-acceptance receipts.

## Integration prerequisites

Before activation, the selected product caller must bind:

- one configured `DurableOperationStore` owner path;
- current `kernel.authority` final-use state;
- a destination-owned dedupe migration and atomic domain mutation;
- a trusted terminal observer and reconciliation scheduling policy;
- operational thresholds for outbox age, indeterminate backlog and store
  capacity; and
- target-host fault evidence including process kill/reopen, disk exhaustion,
  corruption response and multi-writer fencing.

Repository source completion cannot grant canary, promotion or release.
