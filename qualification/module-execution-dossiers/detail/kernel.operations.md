# kernel.operations: implementation design

Parent: `docs/modules/kernel.operations/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: durable local operation journal and transactional outbox source implemented with the bounded reference oracle retained; product composition, target-host qualification and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-operations`.
Packages: `P0.7D-FAULT-MATRIX`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration. Preserve existing stores and APIs; do not create another authority or execution spine and do not make `kernel.operations` the writer of another owner's domain facts.

## 2. Public operations and contract details

`prepare_intent(operation_id, owner, payload_digest, expected_predecessor) -> PreparedIntent`; `claim_outbox(operation_id, fence) -> DispatchClaim`; `observe_terminal(operation_id, observer_evidence) -> ReconciliationReceipt`. The same scoped operation ID and semantic digests are idempotent; identity reuse with changed semantics conflicts. Transport accepted/dispatched and independently observed applied/not-applied are different states.

The native durable surface is `DurableOperationStore::prepare_intent`, `claim_outbox`, `renew_claim`, `retry_claim`, `arm_dispatch`, `acknowledge_dispatch`, `mark_dispatch_indeterminate`, `observe_terminal`, `prune_terminal` and `metrics`. `dispatch_with_final_use` binds the current `kernel.authority` capability immediately around adapter entry. Destination transaction helpers are `reserve_destination_effect` and `record_destination_terminal`.

## 3. State records and transaction design

`operation_ledger` keys scope+operation ID and records predecessor, scope/request/final-payload digests, destination, state, writer generation, authority epoch, revision and terminal-evidence digest. `cross_owner_outbox` keys scope+operation ID+destination and records payload identity, claim generation, monotonic fence, bounded attempts, next eligible time, acknowledgement/reason digests and timestamps.

`prepare_intent` persists the operation identity and local outbox identity atomically in one SQLite `BEGIN IMMEDIATE` transaction. The store uses the shared durable SQLite profile (WAL, foreign keys, busy timeout and `synchronous=FULL`), checksum-tracked migrations and reopen integrity checks.

Destination dedupe remains owned by the destination. The supplied destination helpers act only on a destination-owned `sqlx::Transaction<Sqlite>`; the destination must reserve identity, mutate its domain and write the terminal receipt before committing that same transaction.

## 4. Deterministic algorithm and scheduling

Local transaction -> durable intent/outbox -> fenced pre-dispatch claim -> durable dispatch arm -> current final-use authority -> destination dedupe/apply -> terminal observation -> source settlement.

A pre-dispatch lease can expire and be taken over by the same or a higher writer generation. `arm_dispatch` is the boundary after which blind resend is forbidden: it atomically moves the operation to dispatched and the outbox out of the retryable lease set before adapter entry. Crash or acknowledgement loss after that point remains non-retryable and requires reconciliation. Stale workers cannot renew, arm or settle a newer fence.

State handoff uses the shared phased protocol and preserves unresolved-operation ownership. Compensation is a new operation under current authority; it is never implicit rollback.

## 5. Capacity and performance profile

Implemented V1 ceilings are active operations <= 100000, durable outbox rows <= 100000, claim/read batch <= 256, attempts <= 16 and a lease duration <= 60 seconds. Queue/operation capacity rejects before a new identity is committed. Terminal retention is bounded by age and retained-row policy; pruning first commits an anti-resurrection tombstone.

`metrics` exposes active/terminal operation counts, queued/leased/acknowledged/indeterminate outbox counts, oldest ready age and tombstone count. Target-host qualification still must benchmark commit/fsync latency, outbox age and reconciliation backlog rather than only dispatch throughput.

## 6. Concrete verification cases

- OPS-01: operation intent and outbox survive reopen together; an injected outbox write failure rolls the operation insert back rather than leaving a partial dual write.
- OPS-02: transport acknowledgement is retained without becoming terminal success; an armed attempt is never reclaimed after lease expiry and remains reconciliation-only.
- OPS-03: changed semantic identity conflicts, expired pre-dispatch lease takeover advances the fence/generation and the old worker is stale.
- OPS-04: migration checksum drift fails closed, independent SQLite handles serialize the same identity, terminal state survives reopen and pruning retains an anti-resurrection tombstone.
- OPS-05: real final-use authority is consumed at the durable dispatch boundary; a changed final-use binding rejects before adapter entry.
- OPS-06: destination dedupe and domain mutation commit/rollback in one destination-owned transaction; committed replay observes the prior receipt instead of reapplying the mutation.

These are repository source tests. Physical target-host kill/power-loss/disk-exhaustion qualification, selected destination integration and independent acceptance remain separate evidence gates.

## 7. Integration, rollback and capability ceiling

Each product adapter supplies an actual destination transaction/dedupe implementation and terminal observer. A generic helper does not prove a destination has installed the migration or composed its domain mutation. Restoring an old binary must preserve current revocation and pending effects; no rollback may invent a successful external outcome.

Immediate revocation/stop remains effective across frozen snapshots. The repository source candidate grants no self-acceptance, activation, promotion or release authority.

## 8. Current native implementation

- **Implemented entrypoints:** `DurableOperationStore` in [codex-rs/hepta-operations/src/durable_store.rs](../../../codex-rs/hepta-operations/src/durable_store.rs); `dispatch_with_final_use` in [codex-rs/hepta-operations/src/dispatcher.rs](../../../codex-rs/hepta-operations/src/dispatcher.rs); `reserve_destination_effect` in [codex-rs/hepta-operations/src/destination_dedupe.rs](../../../codex-rs/hepta-operations/src/destination_dedupe.rs); `OperationLedger` in [codex-rs/hepta-operations/src/ledger.rs](../../../codex-rs/hepta-operations/src/ledger.rs); `Outbox` in [codex-rs/hepta-operations/src/outbox.rs](../../../codex-rs/hepta-operations/src/outbox.rs).
- **State and recovery:** the durable owner stores operation/outbox state in `hepta_operations_1.sqlite` using WAL/FULL sync, one atomic intent+outbox transaction, fenced leases, reopen integrity checks, non-retryable armed dispatch, terminal reconciliation and tombstone retention. The BTreeMap ledger/outbox remain deterministic reference oracles only.
- **Authority:** durable dispatch consumes the real `FinalUseAuthority` token and rechecks live final-use state around adapter entry; `ReferenceAuthorityWitness` remains reference-only.
- **Destination semantics:** destination dedupe helpers require the destination to use its own transaction; they do not open, write or commit another owner's store independently of that transaction.
- **Source tests:** [codex-rs/hepta-operations/src/durable_tests.rs](../../../codex-rs/hepta-operations/src/durable_tests.rs), [codex-rs/hepta-operations/src/fault_tests.rs](../../../codex-rs/hepta-operations/src/fault_tests.rs), [codex-rs/hepta-operations/src/destination_dedupe_tests.rs](../../../codex-rs/hepta-operations/src/destination_dedupe_tests.rs), plus the retained reference tests [ledger_tests.rs](../../../codex-rs/hepta-operations/src/ledger_tests.rs) and [outbox_tests.rs](../../../codex-rs/hepta-operations/src/outbox_tests.rs).
- **Implementation and operating references:** [docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md](../../../docs/lane-a-foundation/kernel.operations/DURABLE_STORE_V1.md) and [REFERENCE_MODEL_V1.md](../../../docs/lane-a-foundation/kernel.operations/REFERENCE_MODEL_V1.md).
- **Remaining repository composition:** bind one named product caller, install destination-specific dedupe migrations/domain transactions, and bind a destination-authoritative terminal observer/reconciliation scheduler. Production execution, independent acceptance, activation and release remain false until their separate gates pass.
