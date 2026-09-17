# kernel.operations: implementation design

Parent: `docs/modules/kernel.operations/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: transactional durable ledger/outbox source implementation and bounded reference oracle implemented; named product composition, target-host qualification and independent acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

Pilot ceilings are design targets until target-host measurements are retained. The native implementation enforces the declared 100000 active-operation/outbox ceilings, batch <=256, bounded attempts, lease duration and retry delay. Bind the selected host and measurements before activation.

## 6. Concrete verification cases

- OPS-01: crash before intent commit yields no dispatch; crash after commit recovers exactly one outbox identity.
- OPS-02: acknowledgement loss remains indeterminate until trusted reconciliation.
- OPS-03: changed retry digest and stale writer fence conflict.
- OPS-04: disk-full/corrupt-frame/reopen and every handoff interruption preserve one authoritative writer and no duplicate terminal effect.

Repository tests now execute the atomic rollback, close/reopen, stale-fence/multi-handle, acknowledgement-loss, corrupt-store and destination-dedupe portions. Real process kill/power interruption, real ENOSPC and selected target-host filesystem behavior remain product qualification evidence, not documentation claims.

## 7. Integration, rollback and capability ceiling

Each adapter supplies its actual terminal observer and compensation semantics. Compensation is a new authorized operation. Restoring an old binary must preserve current revocation and pending effects; no rollback may invent a successful external outcome.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `DurableOperationStore` in [codex-rs/hepta-operations/src/durable.rs](../../../codex-rs/hepta-operations/src/durable.rs); `DurableDispatcher` in [codex-rs/hepta-operations/src/dispatcher.rs](../../../codex-rs/hepta-operations/src/dispatcher.rs); `OperationLedger` in [codex-rs/hepta-operations/src/ledger.rs](../../../codex-rs/hepta-operations/src/ledger.rs); `Outbox` in [codex-rs/hepta-operations/src/outbox.rs](../../../codex-rs/hepta-operations/src/outbox.rs).
- **State and recovery:** the durable owner uses a migrated SQLite WAL database with `synchronous=FULL`, one `BEGIN IMMEDIATE` transaction for operation+outbox publication, bounded leased claims, monotonically increasing fences/owner generations, open-time integrity checks and crash/reopen recovery. Expired pre-dispatch leases may be reclaimed; any expired post-dispatch lease becomes `Indeterminate` and cannot be resent without reconciliation.
- **Authority boundary:** [codex-rs/hepta-operations/src/dispatcher.rs](../../../codex-rs/hepta-operations/src/dispatcher.rs) consumes the real `kernel.authority` `SignedFinalUseGrant` and executes the adapter through `FinalUseAuthority::with_verified_use` immediately at the final-use boundary. The reference witness remains test-only.
- **Destination dedupe:** [codex-rs/hepta-operations/src/destination_dedupe.rs](../../../codex-rs/hepta-operations/src/destination_dedupe.rs) exports a destination-owned schema/helper pair that runs inside the destination owner's transaction; `kernel.operations` still never directly writes another owner's domain store.
- **Source tests:** [codex-rs/hepta-operations/src/durable_tests.rs](../../../codex-rs/hepta-operations/src/durable_tests.rs), [codex-rs/hepta-operations/src/ledger_tests.rs](../../../codex-rs/hepta-operations/src/ledger_tests.rs), [codex-rs/hepta-operations/src/outbox_tests.rs](../../../codex-rs/hepta-operations/src/outbox_tests.rs). These are source test identities; exact-candidate workflow execution remains the evidence gate.
- **Implementation and operating references:** [docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md](../../../docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md) and [docs/lane-a-foundation/kernel.operations/REFERENCE_MODEL_V1.md](../../../docs/lane-a-foundation/kernel.operations/REFERENCE_MODEL_V1.md).
- **Remaining work:** choose and compose a named product caller/destination, add the dedupe migration to that destination owner, run real kill/power-loss/disk-full target-host qualification, bind operational deployment metrics, then obtain independent acceptance/canary/promotion/release decisions. Source durability no longer depends on the in-memory reference model.
