# automation.taskflow technical development guide

Current executable behavior, component owners and implementation gaps: [Lane B native host](../../readiness/LANE_B_NATIVE_HOST.md).

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `automation.taskflow`  
**Owner:** `automation-platform`  
**Deputy:** `agent-runtime`  
**Lifecycle:** `existing`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `TASKFLOW-1-EXECUTION-BOUNDARY`

This stable document is the implementation guide for `automation.taskflow`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation/source closure never implies deployment, independent acceptance, activation, promotion or release.

## 1. Identity, mission and ownership

Own schedules and occurrences while routing orchestration through the existing Agentd/Codex spine and routing external effects through their registered owners. `automation-platform` owns `codex-rs/hepta-automation`; `agent-runtime` owns the existing Agentd composition caller. Cross-owner facts remain in their owner stores.

The module is a stateful domain service/execution plant. It may coordinate an operation but does not become the authority issuer, downstream domain writer, provider terminality oracle or fleet owner.

## 2. Source binding and implementation status

Declared primary target root:

- `codex-rs/hepta-automation`

Existing owning runtime composition:

- `codex-rs/hepta-agentd/src/automation.rs`
- `codex-rs/hepta-agentd/src/automation_recovery.rs`

The durable causal-chain implementation is described in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/automation.taskflow.md). The legacy local execution-boundary calculator in `src/taskflow_execution_boundary.rs` remains a deny-all structural assessment and is **not** the positive provider dispatcher. Positive external effect dispatch is the separately bounded `src/authorized_effect.rs` seam consuming kernel-owned final-use authority.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `runtime.codex`
- `kernel.operations`

Authoritative write domains:

- `automation_schedule`
- `automation_occurrence`

Explicitly denied capabilities:

- `direct_session_store_write`
- `blind_effect_retry`

The module accepts registered, bounded, versioned inputs, freezes schedule/occurrence identity before provider contact, persists pre-dispatch intent, and never converts queue acceptance into external success. Unknown/ambiguous provider outcomes remain durable and block unsafe retry. Automation does not mint the final-use authority consumed by an external effect adapter.

## 4. Internal architecture and component decomposition

The active implementation is one composed owner path, not parallel engines:

```text
AutomationScheduler (existing wake-up owner)
  -> AutomationStore timer lease
  -> schedule revision + deterministic occurrence
  -> existing TaskFlow run/event ledger
  -> durable taskflow_step_outbox
  -> Agentd App Server thread/queue/reconcile for Codex activity
  -> persisted turn terminal observer
  -> TaskFlow reconciliation
  -> automation occurrence terminalization

External TaskFlow effect
  -> durable claimed step
  -> kernel FinalUseAuthority exact intent/payload binding
  -> registered effect-owner driver
  -> durable succeeded/failed/indeterminate observation
  -> provider-specific reconciliation when required
```

The old `effect_executor.rs` remains a bounded reference state machine/test component; it is not a second durable runtime owner.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::automation_occurrenceV1`
- `DomainRead::automation_scheduleV1`

Consumed contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `DomainRead::thread_sessionV1`
- `ModulePort::kernel.operations::automation.taskflow`
- `ModulePort::runtime.codex::automation.taskflow`
- `OperationIntentV1`
- kernel final-use authority/grant binding at the registered effect seam

The compatibility timer API keeps `AutomationTick::Submitted`; its meaning is explicitly narrowed to **durable Core queue admission**, not occurrence or effect completion. Existing `Once`/`FixedInterval` callers keep their historical overlap behavior through an explicit default `overlap=allow`; callers requiring serial execution set `overlap=forbid` before the first occurrence is materialized.

## 6. Data authority, persistence and migrations

Schema v11 retains the original `automation_tasks`, `automation_runs` and dispatch-outcome tables and adds:

- `automation_schedule_metadata`: revision, missed-run policy, bounded catch-up state and overlap policy.
- `automation_occurrence_lifecycle`: deterministic occurrence identity, frozen schedule revision, claim generation/token, TaskFlow run ID, queue/turn identity, recovery phase and terminal receipt.
- `automation_occurrence_events`: append-only hash-chained occurrence history.
- `taskflow_step_outbox`: normal-schema durable `prepared -> claimed -> recorded -> reconciled` per-step receipt chain.
- `automation_schedule` / `automation_occurrence` read views for canonical domain naming.

`taskflow_definitions`, `taskflow_runs` and `taskflow_events` remain the durable TaskFlow ledger. A materialized occurrence freezes its schedule revision until it becomes terminal. Safe generation reclaim preserves occurrence/client identity and allocates a new step attempt; an indeterminate provider outcome does not.

Migrations are additive from v3 through v11. An older binary that only understands automation schema v3 must not be started against a v11 owner store.

## 7. Runtime, concurrency and transaction model

One Agent generation owns the per-Agent writer. Scheduler lease generation/token becomes the TaskFlow run/step fence. Pre-dispatch intent is durable before App Server contact. App Server admission uses `thread/queue/reconcile` with stable `client_user_message_id` and canonical payload digest, eliminating a separate lookup/add race.

`DispatchUnknown` no longer authorizes retry or permanently kills the scheduler. The next tick first performs bounded `ReconcileOnly` recovery for the same identity. Only an explicit `Missing` result may append `requeued_proven_absent`, release that same occurrence/client identity, and allocate a new durable step attempt on reclaim.

For external effects, `FinalUseAuthority::claim` durably consumes the signed grant nonce and `with_verified_use` revalidates current authority while the registered driver crosses the provider boundary. Driver errors are allowed only before provider contact; ambiguous contact must return `Indeterminate` so the outbox can quarantine the step.

## 8. Failure semantics, recovery and rollback

Crash boundaries are explicit:

- before durable intent: no provider claim exists;
- after intent/claim but before proven provider contact: an exact provider-absence proof requeues the same TaskFlow run, preserves occurrence/client identity, and allocates a new step attempt before any retry;
- after possible App Server admission: stable-id `ReconcileOnly`; no blind duplicate;
- after persisted turn: store turn identity, then observe terminal status from persisted turn history;
- after terminal provider observation but before run projection settlement: reconcile the historical step first, then a newer Agent generation may re-fence only the TaskFlow run projection for `Indeterminate -> Reconcile`; it does not replay the effect;
- indeterminate external effect: dependent mutation remains blocked until the effect owner supplies reconciliation.

Rollback preserves schedule revision, deterministic occurrence identity, stable queue identity and provider reconciliation state.

## 9. Security, privacy and threat controls

Authority is operation-bound, payload-bound, destination-bound, short-lived and revocation-aware. `authorized_effect.rs` verifies that the signed final-use binding's `request_sha256` matches the durable TaskFlow intent digest and `payload_sha256` matches the durable payload before the effect driver can run. Automation never owns the signing key.

Credentials and provider secrets remain outside general TaskFlow receipts; durable records carry stable identifiers and digests. Stale generation, changed payload, changed stable-client input, reused final-use nonce and revoked grant fail closed.

## 10. Performance, capacity and hot-path policy

Current source bounds include:

- schedule catch-up ceiling <=1024 occurrences;
- occurrence recovery query <=1024 rows;
- Agentd terminal scan <=16 pages × 100 persisted turns per recovery pass;
- one historical occurrence reconciliation plus at most one new scheduler admission per Agentd tick;
- TaskFlow graph/step bounds inherited from the existing TaskFlow ledger/outbox.

These are source limits, not deployment measurements. Target-host latency, backlog and restore evidence remain activation gates.

## 11. Observability and operations

Operate the existing Agentd `AutomationScheduler` and `AutomationStore`. Treat the compatibility task state as schedule-control state, not execution terminality. The authoritative execution status is the durable occurrence/TaskFlow chain.

Important operator classes include aged `indeterminate`, queue-reconcile mismatch, persisted turn not found within bounded history, schedule parked by `overlap=forbid`, catch-up saturation and run-recovery re-fencing. An unknown effect is not safely rerunnable by default.

## 12. Verification and qualification

Focused source tests include:

- `codex-rs/hepta-automation/tests/durable_causal_chain.rs`
- `codex-rs/hepta-automation/tests/automation.rs`
- `codex-rs/hepta-automation/tests/taskflow.rs`
- `codex-rs/hepta-automation/tests/taskflow_kernel.rs`
- `codex-rs/hepta-automation/tests/taskflow_step.rs`
- `codex-rs/hepta-automation/src/effect_executor_tests.rs`
- Agentd automation/recovery unit and process qualification paths.

In `codex-rs`, the focused package command remains `just test -p codex-hepta-automation`; exact-head CI output is the result receipt. Documentation, source mapping and fixture presence are not substitutes for an executed provider/host qualification.

## 13. Implementation sequence and work packages

Applicable package: `TASKFLOW-1-EXECUTION-BOUNDARY`.

Implemented convergence sequence:

1. preserve existing scheduler/store;
2. add schedule revision and deterministic occurrence identity;
3. compose occurrence into existing durable TaskFlow run/events;
4. promote the qualified step outbox into normal schema;
5. replace ordinary queue-add with stable-id reconcile semantics;
6. add bounded lost-reply and persisted-turn terminal reconciliation;
7. propagate TaskFlow terminal state before occurrence terminal state;
8. expose final-use-authorized external-effect driver seam;
9. keep product activation/evidence gates independent.

No second TaskFlow engine or scheduler is admitted by this work package.

## 14. Activation, compatibility and retirement

The existing Agentd -> App Server automation activity now has a repository source composition path. This does not activate arbitrary external effects: each concrete effect owner/terminal observer still requires its own registered adapter, authority configuration, target-host qualification and acceptance evidence.

Compatibility adapters and the legacy `Submitted` tick can be retired only after all callers move to occurrence-terminal semantics. Historical causal-chain records remain interpretable during retirement.

## 15. Definition of module completion

For this source candidate, repository completion means the causal state chain is present, bounded and connected to its existing owner caller; documentation/source mapping then must match exact candidate tests. Product completion additionally requires concrete provider composition where applicable, deployment qualification, independent acceptance and activation evidence. Promotion/release remain separate externally governed states.

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `automation.taskflow` to `LANE-B-RUNTIME` and continues to require:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Consumed readiness protocol:

- `ActuatorReconciliationReceiptV1`

This overlay changes no acceptance, activation, promotion or release authority.

## 17. Source implementation receipt

| Operation | Native source | Composition / observation |
|---|---|---|
| `register_schedule` | `codex-rs/hepta-automation/src/store.rs`, `src/lifecycle.rs` | durable revision/policy metadata |
| `materialize_due` | `codex-rs/hepta-automation/src/scheduler.rs` | deterministic occurrence before provider contact |
| `claim_occurrence` | `src/lifecycle.rs` | Agent generation/token + durable occurrence event |
| `taskflow_run` | `src/automation_taskflow.rs`, `src/taskflow.rs` | deterministic durable run and transition ledger |
| `step_outbox` | `src/taskflow_step.rs` | durable prepare/claim/observe/reconcile chain |
| `queue_dispatch` | `codex-rs/hepta-agentd/src/automation.rs` | App Server `thread/queue/reconcile(AllowIfAbsent)` |
| `queue_recovery` | `codex-rs/hepta-agentd/src/automation_recovery.rs` | `ReconcileOnly`, bounded persisted-turn terminal observer |
| `run_recovery` | `src/taskflow_recovery.rs` | historical-step-first, projection-only re-fence |
| `external_effect` | `src/authorized_effect.rs` | kernel final-use verification + registered driver + durable observation |
| `occurrence_terminal` | `src/lifecycle.rs` | occurs after TaskFlow reconciliation; advances forbidden-overlap recurrence |

Current repository source work still does **not** claim calendar/IANA-timezone recurrence support, a concrete arbitrary downstream effect provider, deployment, independent acceptance, activation or release. Those claims remain false until their own evidence gates close.
