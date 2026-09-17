# `kernel.operations` current implementation

## Current executable contract

`codex-rs/hepta-operations` now contains two deliberately separate surfaces:

1. `OperationLedger` / `Outbox`, the bounded in-memory reference oracle retained for deterministic transition parity; and
2. `DurableOperationStore`, the SQLite-backed authoritative owner for durable operation intent, transactional local outbox publication, fenced claims, destination deduplication and terminal reconciliation.

`PrepareOperationIntent` binds scope, operation identity, predecessor digest, final payload digest and destination into one canonical semantic digest. `prepare_intent` persists the scoped ledger row and local cross-owner outbox row in one `BEGIN IMMEDIATE` transaction. Exact semantic replay is idempotent; reuse of the scoped operation identity with changed semantics conflicts.

`DurableDispatcher` claims bounded ready work with a generation/fence lease. Before an effect adapter enters its synchronous boundary it consumes the real non-serializable final-use token owned by `kernel.authority`; the store records the conservative `Dispatched` state before adapter entry. Transport acknowledgement updates the outbox only and never invents terminal success. Unknown delivery becomes `Indeterminate` and requires destination observation/reconciliation.

Destination deduplication is durable and keyed by destination plus operation identity. An exact destination outcome replay is idempotent; semantic/outcome/evidence drift conflicts. Source settlement is generation-fenced and accepts only a matching destination receipt for a `Dispatched` or `Indeterminate` operation.

## Public symbols and source bindings

Reference oracle:

- `OperationKey`, `OperationState`, `OperationRecord`, `ReconciliationOutcome`, `ReferenceAuthorityWitness`: `src/model.rs`;
- `OperationLedger`, `MAX_MODEL_OPERATION_RECORDS`: `src/ledger.rs`;
- `Outbox`, `OutboxIntent`, `OutboxState`, `MAX_MODEL_OUTBOX_RECORDS`: `src/outbox.rs`.

Durable owner:

- `PrepareOperationIntent`, `DurableOperationRecord`, `DurableOperationState`, `DurableOutboxStatus`, `DispatchLease`, `DestinationReceipt`: `src/durable/model.rs`;
- `DurableOperationStore`: `src/durable/store.rs`;
- `DurableDispatcher`, `DispatchBoundaryResult`: `src/durable/dispatcher.rs`;
- destination dedupe and reconciliation: `src/durable/reconcile.rs`;
- schema: `migrations/0001_operation_store.sql`.

The named product storage composition point is `codex-rs/hepta-agentd/src/main.rs` through `AgentdOperationsHost`. Opening the store does not grant an external effect capability.

## Durability and activation

The durable store uses the repository SQLite durability shim: WAL, `synchronous=FULL`, foreign keys, bounded busy timeout and pooled access. SQLx migration checksums, `PRAGMA quick_check`, `foreign_key_check`, required table/index/trigger validation and an immutable schema-version row fail store open closed on incompatible/corrupt structure.

Operation intent and local outbox publication are atomic. Claims carry owner generation, monotonically increasing fence, bounded attempt count and lease expiry. An expired claim can be taken over by a non-stale generation; the previous lease can no longer renew/retry/ack. Reopen preserves operations, outbox state, fences, acknowledgements and destination receipts.

Agentd source composition opens the durable owner store for the lifetime of the daemon generation. External effect dispatch remains explicitly gated on a real signed `kernel.authority` final-use grant and an adapter call. Independent target-host qualification, operator acceptance, canary, promotion and release are not granted by source composition.

## Target-only design

Remaining target-bound capabilities are not source omissions in the durable ledger/outbox core. They require destination or deployment ownership:

- concrete effect adapters and authoritative terminal observers for every registered destination port;
- target-host power-loss/fsync, storage-device and filesystem qualification;
- independently governed operator acceptance, canary, promotion and release;
- deployment-specific alert thresholds and retention periods;
- stronger external rollback/clock guarantees where a target profile requires them.

## Known limits and non-claims

The reference oracle remains process-local and is not a durability boundary. `ReferenceAuthorityWitness` remains deterministic test evidence, not authentication.

SQLite `FULL` plus WAL defines the repository durability implementation; it is not by itself evidence about a particular physical disk, hypervisor, network filesystem or power-loss domain. An Agentd store open is composition, not permission to dispatch. `DurableDispatcher::dispatch_authorized` requires the real final-use authority path and still distinguishes transport acknowledgement from independently observed terminal effect.

Destination dedupe prevents semantic replay for destinations that use this durable receipt store. A destination implemented outside this store must provide an equivalent durable idempotency boundary and authoritative observer before activation.

Compensation remains a newly authorized operation; terminal history is never rewritten to pretend rollback occurred.

## Verification

Reference-model tests remain in `ledger_tests.rs` and `outbox_tests.rs`.

Durable focused tests cover atomic ledger/outbox rollback on forced write failure, reopen persistence, semantic replay conflict, lease expiry and higher-generation takeover, stale-fence rejection, transport acknowledgement non-terminality, explicit indeterminate reconciliation, destination dedupe conflict, real final-use authority binding, schema-object corruption fail-closed behavior, metrics and bounded terminal retention. Dispatcher tests cover bounded claim batches and real final-use gated adapter entry.

These are source test identities. Exact-candidate workflow success is a separate receipt and must be inspected for this branch/merge candidate before claiming qualification.

## Integration prerequisites

Each production effect destination must bind an adapter that consumes the final-use token at its actual effect boundary and a terminal observer/dedupe authority that can prove `Applied`, `NotApplied` or `Quarantined`. Unknown effects remain unresolved and are never blindly retried.

Activation additionally requires exact-head and merge-candidate native qualification, target-host crash/power-loss/storage tests, current revocation handling, operational thresholds, independent semantic review and the repository's separate acceptance/promotion/release gates.
