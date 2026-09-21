# `kernel.operations` current implementation

## Current executable contract

`codex-rs/hepta-operations` now contains two deliberately separate layers:

1. the bounded in-memory `OperationLedger` / `Outbox` reference models used
   as deterministic transition oracles; and
2. the kernel-owned `DurableOperationStore` SQLite implementation for
   crash/reopen-safe operation identity, immutable transition history and
   leased cross-owner outbox state.

Both preserve the rule that transport acknowledgement is not terminal effect
observation. Once dispatch may have crossed an effect boundary, the operation
is either dispatched or indeterminate until a current-generation observer
records `applied`, `not_applied` or `quarantined`.

All transition digests are nonzero. Exact replay is idempotent only for the
same semantic tuple. Reusing one operation ID with another payload or owner
generation conflicts.

The `ReferenceAuthorityWitness` remains test/reference material only. It is
not a cryptographic credential and is not accepted by the durable store as
production authority. A production adapter must consume the
`kernel.authority` final-use token separately at the actual effect boundary.

## Public symbols and source bindings

Reference-model symbols:

- `OperationKey`, `OperationState`, `OperationRecord`,
  `ReconciliationOutcome`, `ReferenceAuthorityWitness`: `src/model.rs`;
- `OperationLedger`, `MAX_MODEL_OPERATION_RECORDS`: `src/ledger.rs`;
- `Outbox`, `OutboxIntent`, `OutboxState`,
  `MAX_MODEL_OUTBOX_RECORDS`: `src/outbox.rs`.

Durable-owner symbols:

- `DurableOperationStore`, `DurableOperationError`,
  `DurableOutboxState`: `src/durable.rs`;
- schema lineage: `migrations/0001_durable_operations.sql`;
- crash/reopen, multi-handle, lease and corruption qualification:
  `src/durable_tests.rs`.

## Durable operation ledger

The physical lineage is `hepta_operations_1.sqlite`. Mutation paths use
`BEGIN IMMEDIATE` and atomically update the current projection plus append its
immutable event.

The durable operation chain is:

`pending -> authorized -> dispatched -> indeterminate? -> applied | not_applied | quarantined`.

Terminal observation is generation fenced. Reopening verifies SQLite
`quick_check`, foreign keys, the exact SQLx migration ledger, projection/event
agreement, complete event counts through the current revision and immutable
event triggers.

## Durable outbox

Every outbox row references an existing durable operation. Claims bind owner
identity, owner generation and a bounded lease expiry. Another owner is rejected
while the lease is live and may take over only after expiry. Acknowledgement is
accepted only from the current claim owner and exact acknowledgement replay is
idempotent.

Outbox acknowledgement does not update the operation to a terminal state.

## Capacity

The current source implementation bounds both durable current-operation rows
and durable current-outbox rows at 16,384. Outbox lease lifetime is bounded to
300 seconds.

## Qualification implemented in source

The durable suite covers:

- dispatch -> indeterminate -> process/store close -> reopen -> independent
  terminal observation -> reopen;
- two opened handles replaying the same operation identity and rejecting changed
  payload reuse;
- live outbox owner fencing, expired lease takeover and stale-owner
  acknowledgement rejection;
- queue acknowledgement remaining non-terminal for the operation;
- reopen rejection after the current operation projection is tampered away from
  its immutable event history.

These are test sources until exact-head and deterministic synthetic-merge jobs
pass for the candidate.

## Remaining product and external gates

The durable kernel owner is not a product mutation gateway. There is still no
named ui.control caller, no durable RBAC/policy decision owner composed here,
no final-use-authorized real Agentd effect dispatch, no independently observed
product terminal adapter and no background product reconciler.

Trusted time / external anti-rollback, target-host capacity and disk-fault
campaigns, independent review, deployment acceptance, activation, promotion and
release also remain separate gates.

The existing in-memory reference models remain useful test oracles but must not
be confused with the SQLite durability owner.
