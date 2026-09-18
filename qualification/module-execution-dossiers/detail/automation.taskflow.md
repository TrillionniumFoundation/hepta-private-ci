# automation.taskflow: implementation design

Parent: `docs/modules/automation.taskflow/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable scheduling plus a repository-local durable causal execution boundary implemented; concrete product/provider composition, target schedule grammar and independent acceptance remain listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-automation`.
Packages: `TASKFLOW-1-EXECUTION-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`register_schedule(spec, principal, revision) -> ScheduleId`; `materialize_due(schedule, interval, clock_profile) -> OccurrenceSet`; `claim_occurrence(id, fence) -> Claim`; `execute_step(claim, typed_intent) -> ObservedStepState`. Schedules, occurrences and effects have distinct identities. The occurrence key is schedule ID + schedule revision + canonical scheduled instant; a retry cannot change the intended action payload.

## 3. State records and transaction design

`automation_schedule` stores timezone, recurrence grammar, start/end, missed-run policy and revision. `automation_occurrence` stores scheduled UTC instant, claim fence, step graph generation, intent references, terminal observation and recovery phase. Civil-time ambiguity must choose a registered skip/first/second policy. A step DAG owns orchestration state, not another module's source facts.

## 4. Deterministic algorithm and scheduling

Compute due instants deterministically; apply the preregistered missed-run policy (skip, bounded coalesce or bounded catch-up); create occurrences idempotently; claim with a current fence; route effects through Codex/operation owners; wait for terminal observations. An unknown effect blocks dependent steps. Compensation is another authorized step and is never automatically assumed successful.

## 5. Capacity and performance profile

Pilot <= 1024 due occurrences per scan, <= 128 steps per graph, <= 32 ready steps per occurrence and a bounded catch-up horizon. No busy-loop schedule or unlimited backlog. Record due-time lag, duplicates rejected, aged indeterminate steps and restore latency.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- FLOW-01: DST overlap/gap and timezone revision produce declared deterministic occurrences.
- FLOW-02: two schedulers claim one occurrence; only the current fence proceeds.
- FLOW-03: crash after effect dispatch does not blindly rerun the step.
- FLOW-04: recovery after partial compensation records unresolved effects and blocks downstream mutation.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Procedural skills expose preconditions, termination, effects and recovery through the same typed step contract. Skill generation does not grant execution. Rollback preserves schedule/occurrence identities and current operation reconciliation across graph generations.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `create_task` and `claim_due` in [codex-rs/hepta-automation/src/store.rs](../../../codex-rs/hepta-automation/src/store.rs); `tick` in [codex-rs/hepta-automation/src/scheduler.rs](../../../codex-rs/hepta-automation/src/scheduler.rs); deterministic occurrence/run binding and terminal projection in [causal_chain.rs](../../../codex-rs/hepta-automation/src/causal_chain.rs); durable step execution in [effect_runtime.rs](../../../codex-rs/hepta-automation/src/effect_runtime.rs).
- **Durable causal state:** schema v4 adds schedule revision/policy fields, a deterministic `automation_occurrences` ledger, provider observations and a final-use dispatch journal. `claim_due` materializes the semantic occurrence in the scheduler transaction. App Server queue acceptance advances only to `queue_admitted`; it does not complete the occurrence or advance recurring scheduling.
- **TaskFlow reuse rather than a second engine:** `ensure_occurrence_taskflow_run` deterministically binds the occurrence to the existing durable TaskFlow run/event ledger. The existing [taskflow_step.rs](../../../codex-rs/hepta-automation/src/taskflow_step.rs) append-only step outbox is available in the default build. The older in-memory [effect_executor.rs](../../../codex-rs/hepta-automation/src/effect_executor.rs) remains a reusable state-machine component, not the durability boundary.
- **Effect boundary and crash behavior:** [authority.rs](../../../codex-rs/hepta-automation/src/authority.rs) verifies exact operation/epoch/semantic/payload/deadline bindings at final use. Before provider dispatch, `effect_runtime` durably records the verified authority receipt. A restart that sees an authorized dispatch without a durable provider outcome records `indeterminate` and does not redispatch. Durable provider outcomes repair the step outbox/occurrence projection idempotently.
- **Recurring progression:** the currently activated overlap behavior is conservative `forbid`. `next_run_at_ms` is blocked while a semantic occurrence is open and is advanced only by `reconcile_occurrence_from_taskflow` after TaskFlow reaches `succeeded`, `failed` or `cancelled`. Missed-run policies are explicit and bounded; `queue` and `allow` overlap values remain reserved and are rejected by the public setter until they can be implemented without a second scheduler.
- **Source tests:** [tests/automation.rs](../../../codex-rs/hepta-automation/tests/automation.rs), [tests/taskflow.rs](../../../codex-rs/hepta-automation/tests/taskflow.rs), [tests/taskflow_step.rs](../../../codex-rs/hepta-automation/tests/taskflow_step.rs), and [tests/causal_chain.rs](../../../codex-rs/hepta-automation/tests/causal_chain.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json](../../../docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json), [docs/readiness/LANE_B_RUNTIME_COMPOSITION.md](../../../docs/readiness/LANE_B_RUNTIME_COMPOSITION.md).
- **Remaining work:** compose a non-test product caller and concrete downstream effect provider/final-use verifier/terminal observer; complete timezone/tzdb recurrence semantics and qualification; qualify multi-scheduler behavior and any future `queue`/`allow` overlap modes. Production implementation, activation and independent acceptance remain false until those gates are evidenced.
