# kernel.operations: implementation design

Parent: `docs/modules/kernel.operations/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: durable operation owner and final-use CognitiveStore destination are source-implemented on the current-main convergence line; exact-candidate execution, default daemon activation, long-lived compaction, remaining destinations and independent acceptance remain separate gates.

## 1. Source and work envelope

Canonical contract root: `codex-rs/hepta-operations`.

Delegated durable implementation/evidence roots: `codex-rs/hepta-memory`, `codex-rs/hepta-agentd`, and the current-main `automation.taskflow` consumer.

Package: `P0.7D-FAULT-MATRIX`.

The durable implementation reuses the existing CognitiveStore SQLite owner. It must not create a second authority service, second operation semantic dialect, or cross-owner direct-write spine.

## 2. Public operations and contract details

Canonical operation semantics are `OperationIntentV1(operation_id, subject_id, destination_id, payload_digest, scope_digest, policy_generation, expected_predecessor)`.

Implemented durable flow:

`prepare_operation(intent, topic, payload) -> queued receipt`;
`claim_dispatch_lease(operation, generation, now) -> durable claim`;
`renew_dispatch_claim(...)`;
`final_use_binding(receipt, destination) -> FinalUseBinding`;
`ProductionFinalUseOutboxDispatcher::dispatch(...)`;
destination-owned `observe_terminal(request)`;
source-side observer-only reconciliation.

The same operation id and full semantic digest is idempotent. Any semantic drift conflicts. Transport acknowledgement is never terminal effect evidence.

## 3. State records and transaction design

Migration `0011_kernel_operations.sql` stores the immutable operation semantic tuple and binds it to the local event/outbox identity. Migration `0012_kernel_operation_dispatch_claims.sql` stores bounded dispatch attempt, owner generation/fence, lease expiry and next-eligible time.

Source prepare commits operation + event + outbox atomically under the existing CognitiveStore owner. The source does not write destination facts.

The dispatch request carries full semantic identity, including `operation_semantic_sha256` and `expected_predecessor_sha256`. A destination with CAS semantics must compare the predecessor against its authoritative current predecessor inside the same transaction that performs the mutation/dedupe decision.

`CognitiveSourceOutboxTarget` implements that rule using destination-owned `BEGIN IMMEDIATE`. A predecessor mismatch is deterministic `NotApplied`; it is not an indeterminate send and is not retried by the source.

## 4. Deterministic algorithm and scheduling

Source local transaction -> durable outbox -> bounded claim lease -> durable one-shot effect-entry fence -> final-use authority consumption -> destination-owned dedupe/CAS/apply -> independent terminal observation -> source settlement.

A pre-contact proven failure may use bounded retry eligibility. Once target entry may have occurred, restart stays indeterminate and only observer/reconciliation may settle it. Stale claimants/generations cannot acknowledge or settle newer ownership.

Owner handoff preserves immutable operation/outbox identity and requires a strictly newer fence. Compensation is always a new authorized operation.

## 5. Capacity and performance profile

Durable configured source ceilings are separate from the 16,384-record reference-oracle limit. Current durable event/outbox/operation capacity checks fail before visible mutation; the source tests exercise the exact boundary.

The pilot target remains pending intents <= 100000 per configured shard and reconciliation batch <= 256. These are source-level ceilings/targets, not target-host throughput claims.

Ordinary mutation uses targeted current-row checks. Full append-only chain verification is reserved for open/reopen/recovery/audit boundaries. Long-lived physical history still requires segment/checkpoint compaction with anti-resurrection evidence.

## 6. Concrete verification cases

- OPS-01: fault before any prepare commit leaves operation/event/outbox absent; exact replay after commit yields one identity.
- OPS-02: target commit with acknowledgement loss remains `Indeterminate`; observer-only reconcile settles it without redispatch.
- OPS-03: semantic drift, stale generation/claim or expired claim rejects.
- OPS-04: deterministic `SQLITE_FULL`, corruption/tamper, reopen and handoff preserve the last committed cut; physical power-loss qualification remains target-host evidence.
- OPS-05: changed `expected_predecessor` changes the canonical semantic digest; destination mismatch returns deterministic `NotApplied` in the destination transaction.
- OPS-06: final-use binding mismatch/revocation fails before destination entry.

Source test identities are not execution receipts. Only current exact-head and deterministic synthetic-merge workflow results count as candidate qualification.

## 7. Integration, rollback and capability ceiling

`AgentdProductionWriterHost` is a final-use-only named host primitive. It accepts externally supplied authority and a grant provider for the exact `FinalUseBinding`; it does not mint grants or signing keys.

Current-main `automation.taskflow` separately consumes producer-owned `OperationIntentV1` plus final-use authority and owns its own durable effect-dispatch lineage. This demonstrates a second consumer without moving Automation facts into kernel.operations.

Agentd daemon lifecycle composition is now source-implemented as an explicit opt-in: `AgentdConfig::with_production_operations(...)` is the only configuration seam, runtime requires an available CognitiveStore, retains the verified host, and runs bounded observer-only reconciliation for the daemon lifetime. Default process-environment startup still has no production-operation authority or grant source. Each additional registered effect destination must add its own dedupe/apply/terminal-observer contract before activation.

Restoring old software or data must never resurrect consumed authority, an expired claim, or a terminal external outcome.

## 8. Current native implementation

- **Canonical contract/oracle:** `OperationIntentV1`, `OperationLedger`, `Outbox` in `codex-rs/hepta-operations`.
- **Durable source owner:** `ProductionDurableWriter`, `LocalLeaseOutbox`, `operation_claims`, migrations 0011/0012 in `codex-rs/hepta-memory`.
- **Final-use and real destination:** `ProductionFinalUseOutboxDispatcher` and `CognitiveSourceOutboxTarget`; destination recomputes complete intent semantics and owns predecessor/CAS + terminal observation.
- **Named host and daemon composition:** `AgentdProductionWriterHost`, `AgentdConfig::with_production_operations` and the `runtime::run` operations reconciler compose the explicit host into Agentd lifetime without adding a default authority source; legacy non-final-use dispatcher is not exported as a product API.
- **Second current-main consumer:** `codex-rs/hepta-automation/src/authorized_effect.rs` uses producer-owned `OperationIntentV1` and final-use authority.
- **Source tests:** reference ledger/outbox tests, `local_lease_outbox_tests.rs`, production-writer tests and `production_cognitive_source_target_tests.rs`.
- **Exact source truth:** `docs/modules/kernel.operations/IMPLEMENTATION_MAP.json` uses `path_blob_manifest_v1`; the verifier compares every mapped file against `git rev-parse HEAD:<path>`.
- **Remaining repository work:** remaining destination adapters, long-lived segment/checkpoint compaction, and current exact-head/synthetic-merge success.
- **External gates:** target-host physical storage/power-loss qualification, independent acceptance, operator acceptance, canary, promotion and release.
