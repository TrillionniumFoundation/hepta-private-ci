# kernel.operations: implementation design

Parent: `docs/modules/kernel.operations/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: bounded reference semantics and the repository-owned durable ledger/outbox backend are implemented in source; product composition, exact-candidate execution evidence and independent acceptance remain separate gates listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-operations`.
Packages: `P0.7D-FAULT-MATRIX`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`prepare_intent(operation_id, owner, payload_digest, expected_predecessor) -> PreparedIntent`; `claim_outbox(operation_id, fence) -> DispatchClaim`; `observe_terminal(operation_id, observer_evidence) -> ReconciliationReceipt`. The same operation ID and semantic digest is idempotent; reuse with another payload is a conflict. Transport accepted/dispatched and independently observed applied/not-applied are different states.

## 3. State records and transaction design

`operation_ledger` keys scope+operation ID and records predecessor, payload, destination, state, writer fence, authority epoch and terminal-evidence digest. `cross_owner_outbox` keys destination+operation ID and records intent reference, claim fence, bounded attempts, next eligible time and acknowledgement watermark. Persist intent and local outbox atomically. Destination dedupe is owned by the destination and keyed by the same semantic identity.

## 4. Deterministic algorithm and scheduling

Local transaction -> durable intent/outbox -> fenced claim -> authorized adapter entry -> destination dedupe/apply -> terminal observation -> source settlement. After send/acknowledgement loss, mark indeterminate and reconcile; do not resend blindly. Stale workers cannot settle a newer attempt. State handoff uses the shared phased protocol and preserves unresolved-operation ownership.

## 5. Capacity and performance profile

Pilot pending intents <= 100000 per configured shard; claim batch <= 256; attempt counters bounded by operation profile; queue saturation rejects new work before mutation. Benchmark commit/fsync, outbox age and reconciliation backlog rather than only dispatch throughput.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- OPS-01: crash before intent commit yields no dispatch; crash after commit recovers exactly one outbox identity.
- OPS-02: acknowledgement loss remains indeterminate until trusted reconciliation.
- OPS-03: changed retry digest and stale writer fence conflict.
- OPS-04: disk-full/corrupt-frame/reopen and every handoff interruption preserve one authoritative writer and no duplicate terminal effect.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Each adapter supplies its actual terminal observer and compensation semantics. Compensation is a new authorized operation. Restoring an old binary must preserve current revocation and pending effects; no rollback may invent a successful external outcome.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `OperationLedger` in [codex-rs/hepta-operations/src/ledger.rs](../../../codex-rs/hepta-operations/src/ledger.rs); `Outbox` in [codex-rs/hepta-operations/src/outbox.rs](../../../codex-rs/hepta-operations/src/outbox.rs); `DurableOperationStore` in [codex-rs/hepta-operations/src/durable.rs](../../../codex-rs/hepta-operations/src/durable.rs). The first two remain bounded deterministic semantic oracles; the durable entrypoint is backed by [migrations/0001_operations.sql](../../../codex-rs/hepta-operations/migrations/0001_operations.sql). The native source atomically co-commits ledger/outbox prepare state, implements bounded expiring claim leases and fencing, owner/authority handoff, a durable no-blind-retry dispatch boundary, acknowledgement/terminal separation, indeterminate reconciliation and terminal-outbox retention without operation-identity resurrection.
- **Authority boundary:** `DispatchEnvelope::final_use_binding` and `execute_with_final_use` bind the exact destination, scope, payload and attempt/fence identity to `kernel.authority`'s non-serializable final-use token immediately around one synchronous checked effect closure. The operation store does not mint authority.
- **State and recovery:** the durable lineage is `hepta_operations_1.sqlite`, opened through the shared FULL-synchronous WAL SQLite shim. Open verifies SQLite quick/foreign-key integrity, migration state and required safety schema objects. A committed dispatch is never requeued after crash/reopen; a newer owner generation must hand it to indeterminate reconciliation.
- **Source tests:** [ledger_tests.rs](../../../codex-rs/hepta-operations/src/ledger_tests.rs), [outbox_tests.rs](../../../codex-rs/hepta-operations/src/outbox_tests.rs), and [durable_tests.rs](../../../codex-rs/hepta-operations/src/durable_tests.rs). The durable suite includes injected atomic-prepare failure, reopen replay, competing/expired lease fencing, owner handoff, acknowledgement separation, terminal retention, schema-guard corruption, an actual subprocess exit after the dispatch-start commit and a qualification-only final-use/destination vertical slice.
- **Implementation and operating references:** [REFERENCE_MODEL_V1.md](../../../docs/lane-a-foundation/kernel.operations/REFERENCE_MODEL_V1.md), [CURRENT_IMPLEMENTATION.md](../../../docs/lane-a-foundation/kernel.operations/CURRENT_IMPLEMENTATION.md), and [DURABLE_STORE_V1.md](../../../docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md).
- **Remaining repository integration:** bind the durable backend to a named authenticated product caller and a real destination owner's atomic dedupe/apply plus trusted terminal observer. The filesystem destination in the source test is qualification-only. Exact-head/synthetic-merge execution, target-host fault/measurement evidence and independent acceptance remain separate gates and are not created by this documentation update.
