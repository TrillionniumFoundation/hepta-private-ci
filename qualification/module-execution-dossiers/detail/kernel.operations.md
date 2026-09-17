# kernel.operations: implementation design

Parent: `docs/modules/kernel.operations/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: durable source ledger/outbox, fencing, recovery, final-use entry and destination-dedupe primitives implemented in the module candidate; named product composition and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-operations`.
Packages: `P0.7D-FAULT-MATRIX`.

The in-memory `OperationLedger`/`Outbox` types remain a deterministic reference oracle. Production-oriented source entrypoints are `DurableOperationStore`, `AuthorizedDispatch` and `DestinationDedupeStore`. Preserve existing stores and APIs; destination dedupe is installed in the destination owner's own migration lineage and does not create a second owner for its domain facts.

## 2. Public operations and contract details

`DurableOperationStore::prepare_intent(&OperationIntentV1) -> PreparedIntent`; `claim_next(destination, worker, owner_generation, lease) -> DispatchClaim`; `authorize_dispatch(authority, signed_grant, claim) -> AuthorizedDispatch`; `execute_authorized(authorized, effect) -> T`; `observe_terminal(scope, operation_id, observer_evidence) -> DurableOperationRecord`.

The same scoped operation identity and semantic digest is idempotent; reuse with changed predecessor, destination or payload conflicts. Owner generation fences execution ownership but is deliberately excluded from logical semantic identity so a higher generation can take over a safe expired lease. Transport dispatched/acknowledged and independently observed applied/not-applied remain different states.

## 3. State records and transaction design

`operation_ledger` keys scope+operation ID and durably records predecessor, destination, payload digest, semantic digest, state, revision, writer fence, owner generation, authority epoch/digest and terminal observer evidence. `cross_owner_outbox` keys destination+scope+operation ID and records claim fence, bounded attempts, next-eligible time, current worker/generation, lease deadline and acknowledgement digest.

`prepare_intent` writes the operation and source outbox in one `BEGIN IMMEDIATE` transaction. Store open uses WAL, `synchronous=FULL`, foreign keys, bounded busy timeout, `quick_check`, checksum-bound SQLx migration verification and foreign-key validation.

Destination dedupe remains destination-owned. `DestinationDedupeStore::from_migrated_pool` binds to an owner database whose migration lineage contains the exact dedupe table. `begin_apply` returns the still-open owner transaction; domain mutation and the immutable dedupe receipt therefore commit or roll back together.

## 4. Deterministic algorithm and scheduling

Local source transaction -> durable intent/outbox -> fenced lease -> real final-use grant claim -> durable `dispatching` write-ahead state -> `with_verified_use` effect entry -> destination dedupe/domain transaction -> dispatch/ack classification -> independent terminal observation -> source settlement.

A lease that expires while the operation is still `prepared` can be requeued and claimed by a current/higher owner generation. A lease that expires after `dispatching` or `dispatched` is converted to `indeterminate`; it is not resent. Missing acknowledgement also becomes `indeterminate`. Stale workers cannot renew or settle a newer fence.

`NotDispatched` is the only effect classification eligible for automatic requeue. Compensation is always a new authorized operation.

## 5. Capacity and performance profile

Implemented source ceilings are 100000 active operations per store, claim batch <= 256, attempts <= 16 and lease/retry delay <= 60000 ms. Capacity admission occurs under the source write transaction. `OperationBacklogMetrics` reports active/terminal operation counts, queued/leased/acknowledged outbox counts, indeterminate backlog and oldest active outbox age.

These ceilings are enforcement values for the source implementation, not target-host performance measurements. Composition still requires commit/fsync latency, outbox age, reconciliation backlog and contention measurements for its selected host.

## 6. Concrete verification cases

- OPS-01: atomic prepare/reopen verifies one committed operation has exactly one outbox identity.
- OPS-02: acknowledgement loss remains `indeterminate` until a current-generation terminal observer settles it.
- OPS-03: payload/semantic drift conflicts; stale expired claim is fenced when a higher generation takes over a safe prepared operation.
- OPS-04: crash/reopen after durable dispatch admission changes the operation to `indeterminate` and makes it ineligible for blind claim/retry.
- OPS-05: migration-checksum drift and corrupt SQLite fail store open.
- OPS-06: concurrent exact prepare across independent handles is idempotent.
- OPS-07: destination domain SQL and dedupe receipt commit atomically; rollback removes both; exact replay returns the receipt without repeating the domain mutation.
- OPS-08: terminal GC writes a permanent semantic tombstone before deleting source rows, preventing identity resurrection.

Source test identities are `src/durable_store_tests.rs` and `src/destination_dedupe_tests.rs`. These paths are not an exact-candidate pass receipt until the applicable CI reaches terminal success. Disk-exhaustion and target-host power-loss qualification remain required external/source qualification work where the CI host can provide the fault.

## 7. Integration, rollback and capability ceiling

Each destination adapter supplies its actual domain mutation, terminal observer and compensation semantics. A destination owner must include `destination_operation_dedupe` in its own migration set before calling `from_migrated_pool`; a standalone dedupe store is qualification-only.

Rollback across the source schema boundary must retain unresolved effects and tombstones. Restoring an older binary that cannot interpret current pending/indeterminate rows is not an admissible rollback. Immediate revocation remains effective because the final-use token is revalidated immediately around effect entry.

No source test, migration or documentation record grants activation, operator acceptance, promotion or release.

## 8. Current native implementation

- **Durable owner:** `DurableOperationStore` in [codex-rs/hepta-operations/src/durable_store.rs](../../../codex-rs/hepta-operations/src/durable_store.rs), schema in [codex-rs/hepta-operations/migrations/0001_durable_operations.sql](../../../codex-rs/hepta-operations/migrations/0001_durable_operations.sql).
- **Durable contract/state types:** [codex-rs/hepta-operations/src/durable_model.rs](../../../codex-rs/hepta-operations/src/durable_model.rs).
- **Destination dedupe transaction:** `DestinationDedupeStore` in [codex-rs/hepta-operations/src/destination_dedupe.rs](../../../codex-rs/hepta-operations/src/destination_dedupe.rs), with the owner-schema reference in [codex-rs/hepta-operations/destination_migrations/0001_operation_dedupe.sql](../../../codex-rs/hepta-operations/destination_migrations/0001_operation_dedupe.sql).
- **Reference oracle retained:** `OperationLedger` in `src/ledger.rs`, `Outbox` in `src/outbox.rs`, and [REFERENCE_MODEL_V1.md](../../../docs/lane-a-foundation/kernel.operations/REFERENCE_MODEL_V1.md).
- **Focused source tests:** [durable_store_tests.rs](../../../codex-rs/hepta-operations/src/durable_store_tests.rs), [destination_dedupe_tests.rs](../../../codex-rs/hepta-operations/src/destination_dedupe_tests.rs), plus the retained reference tests.
- **Remaining product work:** compose at least one named product caller/destination owner, install the destination dedupe table in that owner's migration lineage, bind a trusted terminal observer, measure the selected host and complete independent activation/acceptance gates. Source implementation does not make those product gates true.
