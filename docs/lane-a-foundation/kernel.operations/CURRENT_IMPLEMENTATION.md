# `kernel.operations` current implementation

## Current executable contract

The current candidate has three deliberately separated roles across two persistence surfaces:

1. `OperationLedger` and `Outbox` in `codex-rs/hepta-operations` are deterministic bounded in-memory reference oracles.
2. `DurableOperationStore` in the same crate is a standalone durability/fault-matrix qualification owner. It is not an Agentd product owner.
3. The product durable owner reuses the existing per-Agent CognitiveStore SQLite owner in `codex-rs/hepta-memory` through `ProductionDurableWriter`.

One logical operation selects exactly one persistence owner. There is no implicit conversion or dual-write bridge between `DurableOperationIntentV1` and the product path; migration must enter a canonical `OperationIntentV1` as an explicit new migration operation.

The canonical authority-free contract is `OperationIntentV1`. Its semantic digest binds operation id, subject id, destination id, exact payload digest, scope digest, policy generation and optional expected predecessor. Exact semantic replay is idempotent; reusing an operation id with changed semantics conflicts.

## Public symbols and source bindings

### Reference contract and oracle

- `OperationIntentV1`, `OperationKey`, `OperationState`, `OperationRecord`, `ReconciliationOutcome` and `ReferenceAuthorityWitness`: `codex-rs/hepta-operations/src/model.rs`;
- `OperationLedger`: `codex-rs/hepta-operations/src/ledger.rs`;
- `Outbox`: `codex-rs/hepta-operations/src/outbox.rs`.

### Standalone durable qualification owner

- `DurableOperationStore`, its fenced source outbox and synchronous effect-entry qualification: `codex-rs/hepta-operations/src/durable_store.rs`;
- repository SQLite-shim composition: `codex-rs/hepta-operations/src/sqlite.rs`;
- standalone destination dedupe helper: `codex-rs/hepta-operations/src/destination_dedupe.rs`.

This surface exists for recovery, migration and fault qualification. Product Agentd callers do not write it.

### Durable integrated product owner

- immutable operation schema: `codex-rs/hepta-memory/migrations/0011_kernel_operations.sql`;
- durable dispatch-claim schema: `codex-rs/hepta-memory/migrations/0012_kernel_operation_dispatch_claims.sql`;
- immutable destination terminal-proof schema: `codex-rs/hepta-memory/migrations/0016_kernel_operation_destination_terminal.sql`;
- atomic operation/event/outbox publication and journal recovery: `codex-rs/hepta-memory/src/local_lease_outbox.rs`;
- bounded durable claim lease/attempt/backoff/takeover: `codex-rs/hepta-memory/src/operation_claims.rs`;
- production writer and final-use dispatch: `codex-rs/hepta-memory/src/production_writer.rs`;
- destination-owned CognitiveStore apply/observer: `codex-rs/hepta-memory/src/production_cognitive_source_target.rs`;
- Agentd product host: `codex-rs/hepta-agentd/src/production_writer_host.rs`;
- Agentd daemon composition: `codex-rs/hepta-agentd/src/config.rs`, `runtime.rs`, and `state.rs`;
- second producer-owned canonical operation consumer: `codex-rs/hepta-automation/src/authorized_effect.rs` and `effect_dispatch_ledger.rs`.

## Durability and activation

`ProductionDurableWriter::prepare_operation` commits the durable operation identity together with its local event/outbox identity under the CognitiveStore owner transaction. Migration `0011_kernel_operations.sql` installs the immutable operation ledger and migration `0012_kernel_operation_dispatch_claims.sql` installs durable per-operation dispatch claims.

The durable claim path has bounded attempts, lease expiry, renewal, retry eligibility/backoff and higher-generation takeover. A one-shot effect-entry transition is persisted before an external target is entered; once an effect may have crossed the boundary, restart/reopen uses reconciliation instead of blind redispatch.

SQLite is required to be WAL with `synchronous=FULL`. Source tests cover atomic rollback across operation/event/outbox fault cuts, deterministic `SQLITE_FULL`, reopen integrity and pre-mutation capacity rejection. These are source test identities; they are not target-host power-loss evidence.

`ProductionDispatchRequest` carries operation subject, destination, scope digest, policy generation, complete `OperationIntentV1` semantic digest, optional expected predecessor, exact payload digest and operation idempotency identity. `ProductionFinalUseOutboxDispatcher` consumes `kernel.authority` with `with_verified_use_async`; the active-effect fence spans the actual target future instead of only future construction. Revocation before entry yields zero target entries. Revocation after entry reports `DispatchInProgress` until the effect completes or is cancelled. The legacy direct dispatcher is crate-private and is not a product API.

`CognitiveSourceOutboxTarget` reconstructs `OperationIntentV1`, verifies its semantic digest, begins a destination-owned `BEGIN IMMEDIATE` transaction, and checks predecessor/CAS inside that transaction. Success commits an immutable `Applied` proof with the source row; a deterministic mismatch commits an immutable operation-bound `NotApplied` proof. The observer never converts temporary row absence into failure: without a terminal proof it returns `Indeterminate`, so a concurrent late commit cannot be terminalized as rejected. Queue or transport acknowledgement never proves terminal success. Lost acknowledgement is reconciled through the destination-owned proof without redispatch.

Current-main `automation.taskflow` is a second producer-owned `OperationIntentV1` / final-use consumer with its own durable effect-dispatch lineage. It is not folded into the CognitiveStore transaction and does not make `kernel.operations` the owner of Automation facts.

`AgentdProductionWriterHost` is final-use-only. Targets are attached with a `FinalUseAuthority`, and product dispatch requires either an externally supplied signed grant or an `AgentdFinalUseGrantProvider` that receives the exact derived `FinalUseBinding`. The Agentd lifecycle accepts this host through `AgentdConfig::with_production_operations(...)`; when explicitly supplied, runtime construction requires an available CognitiveStore, retains the verified host in `AgentdState`, starts an immediate-then-periodic observer-only reconciler, and cancels that task with the daemon lifetime. Default process-environment startup supplies no production-operation configuration and never synthesizes authority, signing keys or a grant source.

Source composition is implemented; activation remains false until the separately governed authority, host and qualification gates are satisfied.

## Target-only design

The architecture remains a cross-owner saga, not a distributed ACID transaction: source atomic prepare -> durable outbox/claim -> final-use-authorized destination entry -> destination-owned dedupe/CAS/apply -> independent terminal observation -> source settlement.

Before any additional registered effect destination is activated, that destination must supply its own destination-owned dedupe/apply transaction and trusted terminal observer. Long-lived append-only lease/event/outbox history still requires a separately versioned segment/checkpoint compaction protocol with anti-resurrection evidence.

Target-host physical power-loss/storage qualification, independent acceptance, operator acceptance, canary, promotion and release are outside repository source implementation and remain separately governed.

## Known limits and non-claims

The in-memory `OperationLedger` and `Outbox` remain deterministic reference oracles; they are not persistence or authority boundaries. Their 16,384-record ceilings are reference-model limits only.

The durable profile is separately bounded at 100,000 operation/outbox identities per lease/shard and 400,000 event rows. Append paths reject exhaustion before visible mutation. These ceilings are engineering bounds, not proof that the target profile meets latency or storage objectives.

Ordinary admit/outcome mutation uses targeted row/current-state checks after CognitiveStore open has performed integrity verification. Full append-only chain verification remains on open/reopen/recovery/audit and terminal lifecycle boundaries rather than every ordinary mutation. Physical history compaction is not yet implemented; deleting hash-chain rows in place is forbidden because it would destroy reopen/audit lineage.

WAL + `synchronous=FULL`, process-kill/reopen, deterministic `SQLITE_FULL` and corruption tests are repository evidence only. They do not establish behavior for a selected filesystem, storage controller, power-failure domain or hardware host.

Compensation is a new authorized operation. Rollback never rewrites an observed external effect into a fictitious success or failure.

## Verification

Current source test identities cover:

- exact `OperationIntentV1` semantic binding and drift rejection;
- operation/event/outbox atomic rollback across every injected prepare cut;
- capacity rejection before mutation;
- deterministic `SQLITE_FULL` rollback and clean reopen;
- durable claim attempt/expiry/renewal/takeover semantics;
- destination semantic-digest reconstruction;
- predecessor mismatch -> immutable destination-owned `NotApplied` proof;
- target absence without proof remains indeterminate during a late commit;
- final-use binding mismatch or revocation before target entry -> zero target entries;
- revocation during an entered async effect -> `DispatchInProgress` until completion;
- lost acknowledgement -> indeterminate -> observer-only terminal reconciliation;
- concurrent dispatch exclusion and owner-generation handoff, including zero old-generation callback entries when handoff wins first;
- tamper/corruption fail-closed reopening;
- Automation final-use provider-at-most-once and durable recovery;
- Agentd lifecycle composition and reconciler cancellation.

Exact-head and deterministic synthetic-merge execution receipts remain separate evidence and must be current for the final PR head.

## Integration prerequisites

Before source qualification can advance, the exact final candidate must pass the Lane A truth/native suite, package compilation/tests, strict lint, formatting, repository/document/readiness gates and deterministic synthetic-merge qualification.

Before product activation, the selected host must additionally provide an enrolled production authority/grant source, destination adapters for the activated effect set, operational retention/alert policy and target-host crash/power-loss/storage evidence.

Independent semantic acceptance, operator acceptance, canary, promotion and release remain false until their separately governed evidence exists.
