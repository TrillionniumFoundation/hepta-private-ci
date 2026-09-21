# `kernel.operations` current implementation

## Current executable contract

The current candidate has two deliberately separate surfaces:

1. `codex-rs/hepta-operations` is the deterministic bounded reference oracle.
2. The production-shaped durable owner reuses the existing per-Agent CognitiveStore SQLite owner in `codex-rs/hepta-memory`; it does not create a second operation database or execution spine.

The canonical authority-free contract is `OperationIntentV1`. Its semantic digest binds operation id, subject id, destination id, exact payload digest, scope digest, policy generation and optional expected predecessor. Exact semantic replay is idempotent; reusing an operation id with changed semantics conflicts.

## Durable owner

`ProductionDurableWriter::prepare_operation` commits the durable operation identity together with its local event/outbox identity under the CognitiveStore owner transaction. Migration `0011_kernel_operations.sql` installs the immutable operation ledger and migration `0012_kernel_operation_dispatch_claims.sql` installs durable per-operation dispatch claims.

The durable claim path has bounded attempts, lease expiry, renewal, retry eligibility/backoff and higher-generation takeover. A one-shot effect-entry transition is persisted before an external target is entered; once an effect may have crossed the boundary, restart/reopen uses reconciliation instead of blind redispatch.

SQLite is required to be WAL with `synchronous=FULL`. Source tests cover atomic rollback across operation/event/outbox fault cuts, deterministic `SQLITE_FULL`, reopen integrity and pre-mutation capacity rejection. These are source test identities; they are not target-host power-loss evidence.

## Final-use and cross-owner semantics

`ProductionDispatchRequest` carries the complete durable semantics needed by the destination:

- operation subject;
- destination;
- scope digest;
- policy generation;
- complete `OperationIntentV1` semantic digest;
- optional expected predecessor;
- exact payload digest and operation idempotency identity.

`ProductionFinalUseOutboxDispatcher` consumes `kernel.authority` final-use authority immediately before target entry. The legacy direct dispatcher is crate-private and is not a product API.

`CognitiveSourceOutboxTarget` is the first durable-owner destination slice. It reconstructs `OperationIntentV1`, verifies its semantic digest, begins a destination-owned `BEGIN IMMEDIATE` transaction, checks predecessor/CAS inside that transaction, and returns deterministic `NotApplied` for a mismatch. Queue/transport acknowledgement never proves terminal success. Lost acknowledgement is reconciled through the destination-owned observer without redispatch.

Current-main `automation.taskflow` is a second producer-owned `OperationIntentV1` / final-use consumer with its own durable effect-dispatch lineage. It is not folded into the CognitiveStore transaction and does not make kernel.operations the owner of Automation facts.

## Reference oracle

The in-memory `OperationLedger` and `Outbox` remain useful as deterministic oracles. They cover semantic replay/conflict, owner handoff, generation fencing, bounded claim leases, attempts, expiry/renewal/takeover and terminal observation. Their 16,384-record ceilings are reference-model bounds only.

## Agentd composition

`AgentdProductionWriterHost` is now final-use-only: targets are attached with a `FinalUseAuthority`, and product dispatch requires either an externally supplied signed grant or an `AgentdFinalUseGrantProvider` that receives the exact derived `FinalUseBinding`. Multiple destinations are registered by stable destination id; observer-only reconciliation is bounded.

The current Agentd lifecycle now accepts this host only through `AgentdConfig::with_production_operations(...)`. When explicitly supplied, runtime construction requires an available CognitiveStore, retains the verified host in `AgentdState`, starts an immediate-then-periodic observer-only reconciler, and cancels that task with the daemon lifetime. Default process-environment startup still supplies no production-operation configuration and never synthesizes authority, signing keys or a grant source.

## Capacity and verification cost

The durable journal capacity is separate from the reference oracle. Append paths reject capacity before visible mutation. Ordinary admit/outcome mutation uses targeted row/current-state checks; full append-only chain verification remains on open/reopen/recovery/audit boundaries rather than every mutation.

Long-lived physical history compaction is not implemented. The append-only lease/event/outbox history must not be deleted in place because that would destroy audit/reopen lineage. A segment/checkpoint design with anti-resurrection evidence is still required before long-lived capacity qualification.

## Current verification identities

Source tests now cover, among other cases:

- exact `OperationIntentV1` semantic binding and drift rejection;
- operation/event/outbox atomic rollback across every injected prepare cut;
- capacity rejection before mutation;
- deterministic `SQLITE_FULL` rollback and clean reopen;
- durable claim attempt/expiry/renewal/takeover semantics;
- destination semantic-digest reconstruction;
- predecessor mismatch -> deterministic `NotApplied`;
- final-use binding mismatch before target entry;
- lost acknowledgement -> indeterminate -> observer-only terminal reconciliation.

Exact-head and deterministic synthetic-merge execution receipts remain separate evidence and must be current for the final PR head.

## Remaining source/product gates

The remaining repository-controlled gates are:

1. add destination-owned dedupe/apply/terminal observation before each remaining registered effect destination is activated;
2. design and qualify bounded segment/checkpoint compaction for long-lived append-only history;
3. obtain current exact-head and deterministic synthetic-merge success for this current-main convergence candidate.

Target-host power-loss/storage qualification, independent semantic acceptance, operator acceptance, canary, promotion and release remain externally governed and false.
