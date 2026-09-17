# `kernel.operations` current implementation

## Current executable contract

`codex-rs/hepta-operations` now contains two deliberately separate surfaces:

1. `OperationLedger` and `Outbox` remain bounded in-memory reference models used
   as deterministic transition oracles.
2. `DurableOperationStore` is the SQLite-backed authoritative implementation for
   operation intent, the local cross-owner outbox, claim fencing, crash/reopen
   recovery and terminal reconciliation.

`DurableOperationStore::prepare_intent` writes the scoped operation record and
its outbox row under one `BEGIN IMMEDIATE` transaction. The database uses WAL,
`FULL` synchronous durability, foreign keys, checked migrations and open-time
`quick_check`/foreign-key validation. Semantic identity binds scope, operation,
predecessor, destination and final payload digest. Exact replay is idempotent;
identity reuse with changed semantics conflicts.

A claim stores a monotonically increasing fence, attempt count, worker identity,
owner generation and lease deadline. An expired lease may be taken over only if
the effect boundary was not entered. Once dispatch is durably marked, lease
loss/reopen is converted to `Indeterminate` and cannot be blindly requeued.
Transport acknowledgement is ordinary evidence, not terminal success.

`DurableDispatcher` claims a real `kernel.authority` `SignedFinalUseGrant`
immediately before adapter entry and executes the adapter through
`FinalUseAuthority::with_verified_use`. A successful transport acknowledgement
still settles as `Indeterminate`; only a generation-fenced trusted terminal
observer may settle `Applied`, `NotApplied` or `Quarantined`.

Destination deduplication is not written by this module. The exported
`DESTINATION_DEDUPE_SCHEMA_V1`, `reserve_destination_effect` and
`finish_destination_effect` helpers are designed to run inside the destination
owner's own SQLite transaction, so dedupe and the destination domain mutation
commit or roll back together.

## Public symbols and source bindings

- durable owner/store and state: `src/durable.rs` — `DurableOperationStore`,
  `DurableIntent`, `OperationIdentity`, `DispatchLease`, durable state/status,
  recovery and metrics types;
- authority-bound dispatch/reconciliation: `src/dispatcher.rs` —
  `DurableDispatcher`, `DispatchEnvelope`, `DispatchResult`,
  `DestinationEffectAdapter`;
- destination-owned dedupe transaction helpers: `src/destination_dedupe.rs`;
- durable schema: `migrations/0001_durable_operations.sql`;
- deterministic reference oracle: `src/model.rs`, `src/ledger.rs`,
  `src/outbox.rs`.

The reference-only `ReferenceAuthorityWitness` remains intentionally separate
and is never a production credential.

## Durability and activation

Durability is implemented as an owned SQLite WAL database with
`synchronous=FULL`. Operation intent and local outbox publication share one
transaction. Store open verifies integrity, applies checksum-tracked SQLx
migrations and recovers expired claims. Pre-dispatch abandoned claims become
eligible again; post-dispatch abandoned claims become indeterminate and require
reconciliation.

The source implementation is **not automatically product-activated**. A named
host must choose the store path, supply the current authority owner, bind an
actual destination adapter/observer and include the destination dedupe schema in
the destination owner's migration. No current documentation grants operator
acceptance, canary, promotion or release.

## Target-only design

The repository still needs product-specific composition and external evidence:

- a named production caller and host lifecycle for `DurableOperationStore`;
- the destination owner's actual domain mutation composed with the exported
  dedupe helper in one destination transaction;
- target-host power-loss, disk-full and filesystem-corruption qualification;
- a host-owned background scheduler/reconciler for destinations that need one;
- an async final-use authority boundary before an adapter may hold authority
  across arbitrary asynchronous work.

Those are composition/qualification/activation items, not missing semantics in
the durable source owner.

## Known limits and non-claims

SQLite durability is local-host durability; it is not an external monotonic
anti-rollback oracle. A restored database image can only be rejected when the
host supplies an independent rollback/checkpoint signal. `SystemTime` supplies
local scheduling time and is not a trusted distributed time service.

The durable dispatcher intentionally supports a synchronous final-use adapter
entry because the current `kernel.authority` API keeps the revocation fence
while `with_verified_use` executes. Network clients that require asynchronous
work must provide a synchronous effect-entry wrapper or extend and separately
qualify the authority contract; this module does not weaken that fence.

Outbox terminal pruning never deletes the operation ledger identity, preventing
GC from making a completed operation look new. Compensation remains a new,
separately authorized operation; reconciliation never invents a successful
external effect.

## Verification

Reference-model tests continue to cover zero/invalid digests, capacity,
idempotent replay, payload/operation drift, witness expiry, generation fencing,
transport acknowledgement separation and indeterminate reconciliation.

Durable tests additionally cover:

- injected outbox insertion failure proving ledger/outbox co-commit rollback;
- exact replay and conflicting semantic identity;
- pre-dispatch lease expiry and higher-generation takeover;
- close/reopen after dispatch forcing indeterminate rather than resend;
- acknowledgement loss followed by authoritative terminal reconciliation;
- independent SQLite handles contending on the same operation identity;
- destination dedupe committed in the destination transaction;
- terminal-outbox GC without operation resurrection;
- corrupt database reopen failing closed;
- a real `FinalUseAuthority` token consumed at the dispatcher effect boundary.

The module is qualified by `scripts/run_lane_a_native_qualification.sh`, which
runs package tests and strict Clippy for the Lane A packages on the exact
candidate.

## Integration prerequisites

Before production activation, the selected host must bind an exact durable store
path, current `FinalUseAuthority`, destination adapter, destination transaction
and terminal observer. The product candidate must run the durable transition
suite plus target-host crash/power-loss, disk-full, corruption, migration,
multi-writer and claim-takeover qualification. Activation remains separate from
source implementation and cannot be inferred from a passing library test.
