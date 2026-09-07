# automation.taskflow: implementation design

Parent: `docs/modules/automation.taskflow/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-automation`.
Packages: `TASKFLOW-1-EXECUTION-BOUNDARY`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
