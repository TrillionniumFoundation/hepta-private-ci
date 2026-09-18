# automation.taskflow: implementation design

Parent: `docs/modules/automation.taskflow/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable scheduling, deterministic occurrence identity, durable TaskFlow run/step state, stable App Server reconciliation, terminal observation, and the final-use-authorized effect seam are source-implemented. Product activation and independently accepted downstream effect providers remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-automation`, with the existing owning runtime caller in `codex-rs/hepta-agentd`.
Packages: `TASKFLOW-1-EXECUTION-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration/evidence gates. Preserve the existing scheduler, Agentd runtime, App Server queue, TaskFlow ledger and final-use authority; do not create another authority or execution spine.

## 2. Public operations and contract details

`register_schedule(spec, principal, revision) -> ScheduleId`; `materialize_due(schedule, interval, clock_profile) -> OccurrenceSet`; `claim_occurrence(id, fence) -> Claim`; `execute_step(claim, typed_intent) -> ObservedStepState`. Schedules, occurrences and external effects have distinct identities. The durable occurrence identity binds owner Agent + schedule/task ID + schedule revision + canonical scheduled instant. A safely retryable reclaim preserves the occurrence and stable client identity while allocating a new step attempt; an unknown provider outcome does not create a new attempt.

The compatibility timer API still exposes `Once` and `FixedInterval`. Schedule policy is revisioned separately and records explicit missed-run (`skip`, `coalesce`, bounded `catch_up`) and overlap (`allow`, `forbid`) behavior. A materialized occurrence freezes its revision until terminalization.

## 3. State records and transaction design

The existing `automation_tasks`/`automation_runs` tables remain the compatibility timer and Core-admission records. `automation_schedule_metadata` adds immutable-in-flight schedule revision and recurrence policy. `automation_occurrence_lifecycle` stores deterministic occurrence identity, schedule revision, claim generation/token, TaskFlow run identity, Core queue identity, persisted turn identity, provider payload digest, recovery phase and terminal receipt. `automation_occurrence_events` is append-only and hash chained.

The existing `taskflow_definitions`, `taskflow_runs` and `taskflow_events` ledger owns durable orchestration projection and transition history. `taskflow_step_outbox` is now part of the normal automation schema and records the per-step `prepared -> claimed -> recorded -> reconciled` chain. A step DAG owns orchestration state, not another module's source facts.

Queue admission is an intermediate observation, never execution success. `AutomationTaskState::Completed` for a one-shot schedule means no further schedule instant exists; the corresponding occurrence remains non-terminal until its TaskFlow/provider observation settles.

## 4. Deterministic algorithm and scheduling

1. Claim due timer work under the Agent generation lease.
2. Freeze the current schedule revision and derive the deterministic occurrence ID.
3. Create/claim the deterministic durable TaskFlow run.
4. Append and claim the durable TaskFlow step intent before provider contact.
5. Persist dispatch uncertainty and cross the owning App Server queue through `thread/queue/reconcile(AllowIfAbsent)` using one stable `client_user_message_id` and canonical payload digest.
6. Record Core admission without declaring the occurrence terminal.
7. On subsequent ticks, reconcile lost replies with `ReconcileOnly`; `Missing` is the only automatic path that releases the same occurrence for retry.
8. Bind a persisted Core turn ID, observe its terminal status through a bounded persisted-turn scan, reconcile the durable TaskFlow step/run, then terminalize the automation occurrence.
9. Advance recurrence according to the frozen overlap/missed-run policy. `forbid` parks the timer until occurrence terminalization; `allow` preserves the historical behavior of advancing after durable Core admission while retaining the earlier occurrence as non-terminal.

An unknown effect blocks dependent steps. Compensation is another separately authorized operation. External/domain effects consume an independently signed kernel final-use grant immediately before the registered provider driver; automation does not mint that authority.

## 5. Capacity and performance profile

Current hard bounds include <=1024 recovery/due frontier records per owner query, <=128 reference executor steps per occurrence, <=1024 catch-up occurrences per configured window, and <=16 pages of 100 persisted turns for one terminal-observation scan. Agentd still admits at most one new scheduler occurrence per tick and reconciles at most one historical occurrence per tick. No busy-loop retry or unlimited backlog is introduced.

Pilot ceilings remain design/qualification inputs, not deployment measurements. Bind selected-host latency, backlog, restore and saturation evidence before activation.

## 6. Concrete verification cases

- FLOW-01: schedule revision and canonical instant produce deterministic occurrence identity; an in-flight occurrence freezes its schedule revision.
- FLOW-02: generation reclaim preserves occurrence/client identity and allocates a new step attempt only after provider absence is proven.
- FLOW-03: crash/lost reply after possible Core admission is reconciled with `ReconcileOnly`, not blind queue replay.
- FLOW-04: Core queue admission leaves the occurrence and TaskFlow non-terminal.
- FLOW-05: persisted terminal turn reconciles TaskFlow step/run before occurrence terminalization.
- FLOW-06: `overlap=forbid` parks recurrence until terminal observation; explicit `allow` preserves legacy overlapping recurrence.
- FLOW-07: final-use binding must match the durable intent and payload before an external effect driver can run; ambiguous provider contact records `Indeterminate`.
- FLOW-08: recovery after run-lease expiry reconciles the historical step first, then a newer Agent generation may re-fence only the run projection for `Indeterminate -> Reconcile`; it cannot replay the effect.

Focused source tests live in `codex-rs/hepta-automation/tests/durable_causal_chain.rs` plus the existing scheduler/TaskFlow tests. Exact candidate CI output remains the pass/fail receipt.

## 7. Integration, rollback and capability ceiling

The implementation intentionally reuses:

- Agentd's existing `AutomationScheduler` as the sole wake-up owner;
- the existing per-Agent `AutomationStore` SQLite database;
- the existing TaskFlow definition/run/event ledger;
- the existing App Server `thread/queue/reconcile` stable-client-id primitive;
- the kernel-owned durable `FinalUseAuthority` for external effect admission.

No second scheduler, TaskFlow engine, queue writer, authority issuer or terminality oracle was introduced. Rollback must preserve the v9 automation schema records or use a binary that understands them; older binaries that only understand schema v3 must not be started against an upgraded owner store.

Source implementation does not by itself authorize a concrete external provider, deployment, operator acceptance, canary, promotion or release.

## 8. Current native implementation

- **Schedule/occurrence owner:** `codex-rs/hepta-automation/src/store.rs`, `src/lifecycle.rs`, migrations `0004`-`0009`. Schedule revision, deterministic occurrence identity, missed-run/overlap policy and append-only occurrence events are durable.
- **Scheduler composition:** `codex-rs/hepta-automation/src/scheduler.rs` freezes occurrence/TaskFlow intent before App Server contact. The public legacy `AutomationTick::Submitted` now means durable Core queue admission only; it is not occurrence terminality.
- **TaskFlow durable chain:** `src/automation_taskflow.rs`, `src/taskflow.rs`, `src/taskflow_step.rs`, `src/taskflow_recovery.rs`. Every materialized automation occurrence gets one deterministic TaskFlow run and versioned step-attempt chain; indeterminate effects are reconciled before terminal propagation.
- **Stable queue recovery and terminal observer:** `codex-rs/hepta-agentd/src/automation.rs` uses `thread/queue/reconcile(AllowIfAbsent)` for first admission. `src/automation_recovery.rs` uses `ReconcileOnly` after lost acknowledgement and observes bounded persisted turn history before publishing terminality.
- **External effect seam:** `codex-rs/hepta-automation/src/authorized_effect.rs` consumes the existing durable kernel `FinalUseAuthority`. It verifies the signed grant's exact request/intent and payload binding under the current revocation fence immediately around the provider driver and durably records succeeded/failed/indeterminate observation.
- **Focused verification:** `codex-rs/hepta-automation/tests/durable_causal_chain.rs`, existing `tests/automation.rs`, `tests/taskflow*.rs`, `src/effect_executor_tests.rs`, and Agentd automation tests.

### Remaining source/product boundary

The repository-controlled durable causal path is now composed for the existing Agentd -> App Server automation activity. The generic final-use-authorized external effect seam exists, but a concrete downstream domain-effect provider/terminal observer remains owned by its registered module and must be activated independently. Full calendar/timezone recurrence grammar and DST gap/overlap qualification remain separate schedule-surface work; the current executable schedule surface remains `Once`/`FixedInterval` with explicit missed-run and overlap policy.

Product execution, target-host deployment, independent acceptance, activation, promotion and release remain false until their separate evidence gates pass.
