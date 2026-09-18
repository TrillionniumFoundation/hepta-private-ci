# kernel.operations: implementation design

Parent: `docs/modules/kernel.operations/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: transactional SQLite operation owner, leased outbox, real final-use dispatch boundary, destination receipt reconciliation and retained reference oracle are source-implemented; product activation and independent acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** `DurableOperationStore::prepare_intent` in [codex-rs/hepta-operations/src/durable/store.rs](../../../codex-rs/hepta-operations/src/durable/store.rs); `DurableDispatcher::dispatch_authorized` in [codex-rs/hepta-operations/src/durable/dispatcher.rs](../../../codex-rs/hepta-operations/src/durable/dispatcher.rs); `DurableOperationStore::reconcile_destination_receipt` in [codex-rs/hepta-operations/src/durable/reconcile.rs](../../../codex-rs/hepta-operations/src/durable/reconcile.rs); `OperationLedger` in [codex-rs/hepta-operations/src/ledger.rs](../../../codex-rs/hepta-operations/src/ledger.rs); `Outbox` in [codex-rs/hepta-operations/src/outbox.rs](../../../codex-rs/hepta-operations/src/outbox.rs).
- **State and recovery:** `DurableOperationStore` persists scoped operation identity plus semantic/predecessor/payload/destination digests, owner generation, authority epoch, revision, dispatch/indeterminate/terminal evidence and timestamps. It atomically co-commits `operation_ledger` and `cross_owner_outbox` under `BEGIN IMMEDIATE`; claims carry bounded attempts, monotonically increasing fence, worker identity, generation and lease expiry. Expired pending work can be taken over by a non-stale generation, and a higher generation can adopt a previously dispatched/indeterminate operation only while settling matching terminal destination evidence. Retired source and destination identities keep immutable tombstones so retention cannot resurrect an effect.
- **Authority and dispatch:** `DurableDispatcher::dispatch_authorized` consumes the real non-serializable `kernel.authority` final-use token immediately around adapter entry. The source persists conservative `Dispatched` before entry; acknowledgement is not terminal success, and unknown delivery becomes `Indeterminate`.
- **Destination-owner slice:** [codex-rs/hepta-automation/src/operation_destination.rs](../../../codex-rs/hepta-automation/src/operation_destination.rs) is the first real owner integration. Automation task creation and the immutable destination dedupe receipt commit in the automation owner's SQLite transaction. Exact replay returns the previous receipt and changed semantic payload conflicts.
- **Source tests:** [codex-rs/hepta-operations/src/durable/tests.rs](../../../codex-rs/hepta-operations/src/durable/tests.rs), [codex-rs/hepta-operations/src/durable/fault_tests.rs](../../../codex-rs/hepta-operations/src/durable/fault_tests.rs), [codex-rs/hepta-operations/src/durable/dispatcher_tests.rs](../../../codex-rs/hepta-operations/src/durable/dispatcher_tests.rs), [codex-rs/hepta-automation/tests/kernel_operations_destination.rs](../../../codex-rs/hepta-automation/tests/kernel_operations_destination.rs), plus the retained reference tests [ledger_tests.rs](../../../codex-rs/hepta-operations/src/ledger_tests.rs) and [outbox_tests.rs](../../../codex-rs/hepta-operations/src/outbox_tests.rs). These are test identities; exact-head and merge-candidate workflow success remain separate receipts.
- **Implementation and operating references:** [docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md](../../../docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md) and [REFERENCE_MODEL_V1.md](../../../docs/lane-a-foundation/kernel.operations/REFERENCE_MODEL_V1.md).
- **Remaining work:** Do not claim activation from source alone. Agentd must be supplied an enrolled production grant source and continuously hosted dispatcher/reconciler, every remaining registered destination must supply an equivalent destination-owned dedupe/apply/observer boundary, exact-head and deterministic merge qualification must pass for the selected candidate, and target-host power-loss/storage plus independent acceptance/promotion/release gates remain open.
