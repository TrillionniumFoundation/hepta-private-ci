# automation.taskflow: implementation design

Parent: `docs/modules/automation.taskflow/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable scheduling, deterministic occurrence identity, durable TaskFlow run/step state, stable App Server reconciliation, terminal observation, and the final-use-authorized effect seam are source-implemented. Product activation and independently accepted downstream effect providers remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-automation`, with the existing owning runtime caller in `codex-rs/hepta-agentd`.
Packages: `TASKFLOW-1-EXECUTION-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration/evidence gates. Preserve the existing scheduler, Agentd runtime, App Server queue, TaskFlow ledger and final-use authority; do not create another authority or execution spine.

## 2. Public operations and contract details

`register_schedule(spec, principal, revision) -> ScheduleId`; `materialize_due(schedule, interval, clock_profile) -> OccurrenceSet`; `claim_occurrence(id, fence) -> Claim`; `execute_step(claim, typed_intent) -> ObservedStepState`. Schedules, occurrences and external effects have distinct identities. The durable occurrence identity binds owner Agent + schedule/task ID + schedule revision + canonical scheduled instant. A safely retryable reclaim preserves the occurrence and stable client identity while allocating a new step attempt; an unknown provider outcome does not create a new attempt.

The compatibility timer API still exposes `Once` and `FixedInterval`. Calendar V2 is additive and versioned: timezone ID + tzdb digest + bounded transition profile + start/end + every-N-days local civil time + explicit gap (`skip`/`next_valid`) and overlap (`first`/`second`) policy. Schedule policy separately records missed-run (`skip`, `coalesce`, bounded `catch_up`) and execution overlap (`allow`, `forbid`). A materialized occurrence freezes its revision until terminalization.

## 3. State records and transaction design

The existing `automation_tasks`/`automation_runs` tables remain the compatibility timer and Core-admission records. `automation_schedule_metadata` adds immutable-in-flight schedule revision and recurrence policy. `automation_calendar_schedule_versions` is an append-only authoritative Calendar V2 history; a policy-only revision copies the exact prior calendar bytes, while a calendar replacement writes a new immutable version. `automation_occurrence_lifecycle` stores deterministic occurrence identity, schedule revision, claim generation/token, TaskFlow run identity, Core queue identity, persisted turn identity, provider payload digest, recovery phase and terminal receipt. `automation_occurrence_events` is append-only and hash chained.

The existing `taskflow_definitions`, `taskflow_runs` and `taskflow_events` ledger owns durable orchestration projection and transition history. `taskflow_step_outbox` is part of the normal automation schema and records the per-step `prepared -> claimed -> recorded -> reconciled` chain. External effects add immutable dispatch-attempt identity, an immutable first provider observation and—only when that first observation is indeterminate—a separate immutable terminal reconciliation. A step DAG owns orchestration state, not another module's source facts.

Queue admission is an intermediate observation, never execution success. `AutomationTaskState::Completed` for a one-shot schedule means no further schedule instant exists; the corresponding occurrence remains non-terminal until its TaskFlow/provider observation settles.

## 4. Deterministic algorithm and scheduling

1. Claim due timer work under the Agent generation lease.
2. Freeze the current schedule revision and derive the deterministic occurrence ID.
3. Create/claim the deterministic durable TaskFlow run.
4. Append and claim the durable TaskFlow step intent before provider contact.
5. Persist dispatch uncertainty and cross the owning App Server queue through `thread/queue/reconcile(AllowIfAbsent)` using one stable `client_user_message_id` and canonical payload digest.
6. Record Core admission without declaring the occurrence terminal.
7. On subsequent ticks, reconcile lost replies with `ReconcileOnly`; `Missing` is the only automatic path that appends `requeued_proven_absent`, releases the same occurrence/client identity, and permits a new step attempt.
8. Bind a persisted Core turn ID, observe its terminal status through a bounded persisted-turn scan, reconcile the durable TaskFlow step/run, then terminalize the automation occurrence.
9. Advance recurrence from the frozen authoritative schedule. Calendar V2 resolves local civil instants against the exact supplied transition profile, applies registered DST gap/overlap policy, then applies the frozen overlap/missed-run policy. `forbid` parks the timer until occurrence terminalization; `allow` preserves the historical behavior of advancing after durable Core admission while retaining the earlier occurrence as non-terminal.

An unknown effect blocks dependent steps. Compensation is another separately authorized operation. External/domain effects consume an independently signed kernel final-use grant immediately before the registered provider driver; automation does not mint that authority.

## 5. Capacity and performance profile

Current hard bounds include <=1024 recovery/due frontier records per owner query, <=1024 catch-up occurrences per configured window, <=512 timezone transitions per Calendar V2 profile, <=1032 bounded calendar-day probes, TaskFlow's registered graph/step bounds, and <=16 pages of 100 persisted turns for one terminal-observation scan. Agentd still admits at most one new scheduler occurrence per tick and reconciles at most one historical occurrence per tick. No busy-loop retry or unlimited backlog is introduced.

Pilot ceilings remain design/qualification inputs, not deployment measurements. Bind selected-host latency, backlog, restore and saturation evidence before activation.

## 6. Concrete verification cases

- FLOW-01: Calendar V2 resolves DST gap/overlap deterministically from the supplied tzdb-bound transition profile; changing tzdb identity changes the schedule digest; an in-flight occurrence freezes its schedule revision.
- FLOW-02: generation reclaim preserves occurrence/client identity and allocates a new step attempt only after provider absence is proven.
- FLOW-03: crash/lost reply after possible Core admission is reconciled with `ReconcileOnly`, not blind queue replay.
- FLOW-04: Core queue admission leaves the occurrence and TaskFlow non-terminal.
- FLOW-05: persisted terminal turn reconciles TaskFlow step/run before occurrence terminalization.
- FLOW-06: `overlap=forbid` parks recurrence until terminal observation; explicit `allow` preserves legacy overlapping recurrence.
- FLOW-07: automation computes the canonical external-effect intent digest over run/step/attempt/operation/subject/destination/payload/scope/policy/dependencies/compensation; the signed final-use binding must match it before the driver can run.
- FLOW-08: restart after an indeterminate provider observation reopens the same immutable attempt, appends terminal/proven-absent reconciliation evidence, reconciles the historical step first and never replays the effect.

Focused source tests live in `codex-rs/hepta-automation/tests/durable_causal_chain.rs` plus the existing scheduler/TaskFlow tests. Exact candidate CI output remains the pass/fail receipt.

## 7. Integration, rollback and capability ceiling

The implementation intentionally reuses:

- Agentd's existing `AutomationScheduler` as the sole wake-up owner;
- the existing per-Agent `AutomationStore` SQLite database;
- the existing TaskFlow definition/run/event ledger;
- the existing App Server `thread/queue/reconcile` stable-client-id primitive;
- the kernel-owned durable `FinalUseAuthority` for external effect admission.

No second scheduler, TaskFlow engine, queue writer, authority issuer or terminality oracle was introduced. Rollback must preserve schema v13 records or use a binary that understands Calendar V2 and provider reconciliation history; older binaries must not replace the owner against an upgraded store.

Source implementation does not by itself authorize a concrete external provider, deployment, operator acceptance, canary, promotion or release.

## 8. Current native implementation

- **Schedule/occurrence owner:** `codex-rs/hepta-automation/src/store.rs`, `src/lifecycle.rs`, `src/schedule_v2.rs`, migrations `0004`-`0012`. Legacy schedule semantics remain compatible; Calendar V2 adds append-only timezone/tzdb/start/end/civil-time/DST schedule versions, deterministic canonical UTC materialization, missed-run/overlap policy and durable occurrence identity.
- **Scheduler composition:** `codex-rs/hepta-automation/src/scheduler.rs` freezes occurrence/TaskFlow intent before App Server contact. The public legacy `AutomationTick::Submitted` now means durable Core queue admission only; it is not occurrence terminality.
- **TaskFlow durable chain:** `src/automation_taskflow.rs`, `src/taskflow.rs`, `src/taskflow_step.rs`, `src/taskflow_recovery.rs`. Every materialized automation occurrence gets one deterministic TaskFlow run and versioned step-attempt chain; indeterminate effects are reconciled before terminal propagation.
- **Stable queue recovery and terminal observer:** `codex-rs/hepta-agentd/src/automation.rs` uses `thread/queue/reconcile(AllowIfAbsent)` for first admission. `src/automation_recovery.rs` uses `ReconcileOnly` after lost acknowledgement and observes bounded persisted turn history before publishing terminality.
- **External effect seam:** `src/authorized_effect.rs` computes a closed-world typed intent digest inside automation and consumes the durable kernel `FinalUseAuthority`; `src/effect_dispatch_ledger.rs` plus migration `0013` persist pre-contact grant lineage, first provider observation and append-only terminal reconciliation after `indeterminate`. Restart scanning never authorizes redispatch.
- **Focused verification:** `src/schedule_v2.rs`, `src/authorized_effect.rs`, `src/effect_dispatch_ledger.rs`, `tests/durable_causal_chain.rs`, existing `tests/automation.rs`, `tests/taskflow*.rs`, the test-only legacy reducer, and Agentd automation tests.

### Remaining source/product boundary

The repository-controlled source boundary is closed for the durable causal spine: Agentd -> App Server automation activity is composed, Calendar V2 has explicit deterministic timezone/DST source semantics, the external-effect seam owns canonical intent/final-use/pre-contact durability, and indeterminate attempts have restart reconciliation. A concrete downstream domain-effect provider/terminal observer remains owned by its registered module and must be activated independently. Authentic/current IANA tzdb provenance, selected-host DST/multi-scheduler behavior and performance remain qualification evidence, not source claims.

Product execution, target-host deployment, independent acceptance, activation, promotion and release remain false until their separate evidence gates pass.
