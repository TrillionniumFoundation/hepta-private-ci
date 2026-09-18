# `kernel.operations` current implementation

## Claim boundary

The module now has two deliberately separate native surfaces:

1. `OperationLedger` / `Outbox`: bounded in-memory deterministic reference
   models used as semantic oracles.
2. `DurableOperationStore`: a SQLite-backed production-oriented native
   ledger/outbox implementation.

This source implementation does **not** by itself establish a production caller,
a deployed target host, independent acceptance, activation, promotion or
release. Those remain separate evidence gates.

## Reference executable contract

The reference model covers pending, authorized, dispatched, indeterminate and
terminal states; exact operation/payload identity; monotonic revisions;
generation-fenced terminal observation; and a bounded in-memory outbox.

All evidence digests required by reference transitions are nonzero. Exact
command replay is idempotent; identity reuse with changed semantics conflicts.
The `ReferenceAuthorityWitness` remains deterministic test evidence only. It is
not authentication and must never be accepted by a production effect adapter.

## Durable native contract

`DurableOperationStore` owns `hepta_operations_1.sqlite` and opens it through
the shared FULL-synchronous WAL SQLite shim. Its migration creates
`operation_ledger` and `cross_owner_outbox`.

The durable implementation provides:

- one atomic `BEGIN IMMEDIATE` prepare transaction that inserts the operation
  ledger row and the source outbox row together;
- a stable semantic operation digest binding source owner, scope, payload,
  destination and optional predecessor;
- bounded active-operation capacity, claim batch, attempts and lease duration;
- lease expiry, takeover, renewal and monotonically increasing writer fences;
- owner-generation plus authority-epoch handoff;
- a durable dispatch-start marker before an effect may cross the boundary;
- no blind retry once dispatch may have happened;
- transport acknowledgement that remains distinct from terminal effect
  observation;
- explicit indeterminate state and current-generation/current-epoch terminal
  reconciliation;
- terminal outbox compaction that retains the authoritative ledger identity and
  therefore cannot resurrect an operation;
- schema-object, quick-check and foreign-key validation on open;
- a helper that consumes `kernel.authority`'s non-serializable final-use token
  immediately around one synchronous checked effect closure.

The complete storage and recovery contract is
[`DURABLE_STORE_V1.md`](DURABLE_STORE_V1.md).

## Public symbols and source bindings

Reference surface:

- `OperationKey`, `OperationState`, `OperationRecord`,
  `ReconciliationOutcome`, `ReferenceAuthorityWitness`: `src/model.rs`;
- `OperationLedger`, `MAX_MODEL_OPERATION_RECORDS`: `src/ledger.rs`;
- `Outbox`, `OutboxIntent`, `OutboxState`,
  `MAX_MODEL_OUTBOX_RECORDS`: `src/outbox.rs`.

Durable surface:

- `PreparedIntent`, `DurableOperationStore`, `DurableOperationRecord`,
  `DispatchLease`, `DispatchEnvelope`, `EffectObservation`:
  `src/durable.rs`;
- physical schema and guards: `migrations/0001_operations.sql`;
- stable errors: `src/error.rs`.

## Durability and recovery

Durability is implemented for the local operation ledger/outbox database in
this candidate source. Persistence is not inferred from cloning a reference
model.

A committed prepare survives reopen. An expired pre-dispatch lease can be
taken over with a newer fence. A process exit after the durable dispatch-start
marker reopens as non-dispatchable; recovery must reconcile instead of
resending.

The V1 store keeps authoritative operation identities after terminal outbox
retention. Destructive long-term ledger archival requires a separately
versioned anti-resurrection policy.

## Final-use authority

The reference witness remains non-authoritative.

The durable dispatch helper derives an attempt-specific `FinalUseBinding`
covering destination, scope, final payload and the operation/fence/attempt
identity. It consumes `VerifiedUseToken` at the synchronous effect boundary.

The operation store does not mint authority. Owner handoff requires a newer
authority epoch, and the external authority owner must publish that epoch
before the new writer may dispatch.

## Destination semantics

Destination deduplication remains destination-owned. The source ledger cannot
claim physical exactly-once semantics for another owner's store.

Native tests include a durable qualification-only filesystem destination to
exercise source dispatch, final-use authority and destination semantic dedupe.
It is not a product caller or production destination.

A production composition must bind one named destination owner, its atomic
dedupe/apply transaction and its trusted terminal observer.

## Verification

Reference tests:

- `src/ledger_tests.rs`;
- `src/outbox_tests.rs`.

Durable tests:

- `src/durable_tests.rs`;
- atomic prepare rollback under injected second-write failure;
- close/reopen idempotency and payload drift conflict;
- expired-lease takeover and stale-token fencing;
- owner handoff and no-blind-retry behavior;
- acknowledgement versus terminal observation;
- terminal retention without resurrection;
- missing schema guard failure on reopen;
- actual child-process exit after dispatch-start commit;
- final-use authority at the qualification effect boundary.

Test source identity is not an execution receipt. Exact-head and deterministic
synthetic-merge CI must pass for the exact candidate before repository
qualification claims are advanced.

## Remaining integration work

The remaining repository-controlled integration work is narrower than before
but still material:

- bind `DurableOperationStore` to a named authenticated product caller;
- bind a real destination owner's dedupe/apply transaction and terminal
  observer;
- supply target-host disk-full/I/O/backup-restore measurements and fault
  receipts;
- independently review cross-owner semantics and the selected composition.

No production binary should treat the reference `OperationLedger` or
`Outbox` as persistence or authority boundaries.
