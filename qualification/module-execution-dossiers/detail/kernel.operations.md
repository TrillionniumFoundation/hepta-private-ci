# kernel.operations: implementation design

Parent: `docs/modules/kernel.operations/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: integrated SQLite operation owner, atomic local outbox publication, persisted claim lease/attempt/takeover, fenced effect entry/handoff, real final-use adapter entry, CognitiveStore predecessor-aware destination and Automation destination are source-implemented; exact-candidate execution, enrolled deployment authority, remaining activated destinations, bounded journal compaction and independent acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Reference oracle:** `OperationLedger` / `Outbox` in `codex-rs/hepta-operations` remain bounded deterministic reference models. Their 16,384-record limits are not production store limits.
- **Durable owner:** `codex-rs/hepta-memory/src/local_lease_outbox.rs` and migration `0011_kernel_operations.sql` bind the complete `OperationIntent` to the existing CognitiveStore event/outbox owner. Event + outbox + operation row commit in one `BEGIN IMMEDIATE` transaction.
- **Claim/handoff:** migration `0012_kernel_operation_dispatch_claims.sql` plus `operation_claims.rs` persist bounded attempts, lease expiry, renewal, backoff and strictly newer-generation takeover. Immediately before effect entry the writer appends the one-shot indeterminate fence; entered work cannot be retried and must reconcile. Terminal predecessor generations reuse the same queued event/outbox identity.
- **Authority:** `ProductionFinalUseOutboxDispatcher` consumes the actual non-serializable final-use capability with `FinalUseAuthority::claim` and `with_verified_use` immediately around target entry.
- **Real destinations:** `CognitiveSourceOutboxTarget` verifies the complete operation semantic digest and predecessor expectation, performs destination CAS + apply/dedupe under one `BEGIN IMMEDIATE`, and exposes terminal observation. Automation independently commits task mutation + semantic dedupe receipt in its owner transaction and exposes observation.
- **Product composition:** `AgentdProductionOperationRuntimeConfig` is consumed by the real Agentd `runtime::run`, attaches the production host to `AgentdState`, and spawns an immediate-then-periodic observer-only reconciler. The host keeps a destination-keyed dispatcher registry: duplicate/empty destinations reject, multi-destination dispatch requires an explicit destination, and the reconciler bounds total work while visiting registered destination observers. Default process-environment startup remains inactive unless externally enrolled authority/verifier/final-use/grant-provider/target inputs are supplied.
- **Fault evidence sources:** `local_lease_outbox_tests.rs`, `production_writer.rs`, `production_cognitive_source_target_tests.rs` and Automation destination tests cover atomic rollback, exact capacity fencing, deterministic SQLite `SQLITE_FULL` rollback/reopen, reopen/tamper, child-process crash/reopen, claim renewal/takeover, concurrent effect-entry exclusion, owner handoff, final-use binding, destination dedupe/CAS and lost-ack reconciliation. These are source identities, not current-candidate pass receipts.
- **Retention boundary:** operation metadata is not bounded by the reference-model 16k ceiling, but the authoritative lease/event/outbox journals are append-only hash chains. Bounded physical journal compaction/checkpoint retention remains a repository-controlled gap and must not be emulated with unsafe row deletion.
- **Remaining work:** obtain current exact-head and deterministic merge-candidate qualification and close every compile/test/security finding; enroll a real deployment authority/grant source without self-minting credentials; add destination adapters before activating remaining effect owners; add a versioned journal segment/checkpoint retention protocol; then obtain target-host physical power-loss/storage and independent acceptance/promotion/release evidence.
