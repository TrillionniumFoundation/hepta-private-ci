# automation.taskflow: implementation design

Parent: `docs/modules/automation.taskflow/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable scheduling, deterministic occurrence identity, fair/exact recovery,
durable TaskFlow run/step state, capability-negotiated Calendar V2, a named Agentd
external-effect prepare/execute/reconcile host, and one authority-free threshold
DecisionCell are source-composed. Selected-host provider/tzdb qualification,
independent acceptance, activation and release remain separate gates. Common
requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership
and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-automation`, with the existing owning runtime caller in `codex-rs/hepta-agentd`.
Packages: `TASKFLOW-1-EXECUTION-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration/evidence gates. Preserve the existing scheduler, Agentd runtime, App Server queue, TaskFlow ledger and final-use authority; do not create another authority or execution spine.

## 2. Public operations and contract details

`register_schedule(spec, principal, revision) -> ScheduleId`;
`materialize_due(schedule, interval, clock_profile) -> OccurrenceSet`;
`claim_occurrence(id, fence) -> Claim`;
`prepare_product_effect(operation, wire_digest, predecessor) -> PreparedEffect`;
`execute_step(claim, signed_final_use) -> ObservedStepState`;
`run_threshold_circuit(candidate, parameters, input) -> DurableChoice`.
Schedules, occurrences, circuit choices and external effects have distinct identities.
A safely retryable reclaim preserves occurrence/client/provider identity; an unknown
provider outcome does not create a new attempt.

The compatibility timer API still exposes `Once` and `FixedInterval`. Calendar V2 is additive and versioned: timezone ID + tzdb digest + bounded transition profile + start/end + every-N-days local civil time + explicit gap (`skip`/`next_valid`) and overlap (`first`/`second`) policy. Schedule policy separately records missed-run (`skip`, `coalesce`, bounded `catch_up`) and execution overlap (`allow`, `forbid`). A materialized occurrence freezes its revision until terminalization.

## 3. State records and transaction design

The existing `automation_tasks`/`automation_runs` tables remain the compatibility timer and Core-admission records. `automation_schedule_metadata` adds immutable-in-flight schedule revision and recurrence policy. `automation_calendar_schedule_versions` is an append-only authoritative Calendar V2 history; a policy-only revision copies the exact prior calendar bytes, while a calendar replacement writes a new immutable version. `automation_occurrence_lifecycle` stores deterministic occurrence identity, schedule revision, claim generation/token, TaskFlow run identity, Core queue identity, persisted turn identity, provider payload digest, recovery phase and terminal receipt. `automation_occurrence_events` is append-only and hash chained.

The existing `taskflow_definitions`, `taskflow_runs` and `taskflow_events` ledger
owns durable orchestration projection and transition history. `taskflow_step_outbox`
records `prepared -> claimed -> recorded -> reconciled`. External effects add
immutable product preparation, dispatch attempt, first observation and terminal
reconciliation. The minimal Circuit slice adds create-only candidate and threshold
parameter registries plus a durable choice committed before the selected edge. A
step DAG owns orchestration state, not another module's source facts.

Queue admission is an intermediate observation, never execution success. `AutomationTaskState::Completed` for a one-shot schedule means no further schedule instant exists; the corresponding occurrence remains non-terminal until its TaskFlow/provider observation settles.

## 4. Deterministic algorithm and scheduling

1. Claim due timer work under the Agent generation lease.
2. Freeze the current schedule revision and derive the deterministic occurrence ID.
3. Create/claim the deterministic durable TaskFlow run.
4. Append and claim the durable TaskFlow step intent before provider contact.
5. Persist dispatch uncertainty and cross the owning App Server queue through `thread/queue/reconcile(AllowIfAbsent)` using one stable `client_user_message_id` and canonical payload digest.
6. Record Core admission without declaring the occurrence terminal.
7. On subsequent ticks, reconcile lost replies with `ReconcileOnly`; `Missing` is the only automatic path that appends `requeued_proven_absent`, releases the same occurrence/client identity, and permits a new step attempt.
8. Bind a persisted Core turn ID and observe its terminal status through at most 16 pages × 100 turns per pass. If more history remains, persist the opaque App Server `next_cursor` under an exact previous-cursor CAS and resume from it on the next recovery pass. Only authoritative pagination exhaustion without the bound turn becomes indeterminate; no pass materializes unbounded full history. Reconcile the durable TaskFlow step/run only from a trusted observation or explicit reconciliation receipt.
9. Advance recurrence from the frozen authoritative schedule. Calendar V2 resolves local civil instants against the exact supplied transition profile, applies registered DST gap/overlap policy, then applies the frozen overlap/missed-run policy. `forbid` parks the timer until occurrence terminalization; `allow` preserves the historical behavior of advancing after durable Core admission while retaining the earlier occurrence as non-terminal.

An unknown effect blocks dependent steps. Compensation is another separately
authorized operation. Agentd freezes the product intent and original provider key
before final use; external/domain effects consume an independently signed kernel
grant immediately before the registered provider driver. Automation does not mint
that authority. Threshold circuits expose no provider capability or effect node.

## 5. Capacity and performance profile

Current hard bounds include <=1024 recovery/due records per discovery page,
exact task/occurrence lookup independent of that page, <=1024 catch-up occurrences,
<=512 timezone transitions, <=1032 calendar-day probes, TaskFlow graph/step limits,
<=16 pages of 100 turns per terminal scan, bounded effect payload/config files, and a
minimal 3-node threshold circuit. Schema v20 retains fair discovery progress across
reopen. The ordinary-disk qualification test executes 256 durable choices, reopens
the owner and verifies first/middle/last identities exactly; it records elapsed time
without converting one machine's timing into a portable SLA.

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
- FLOW-09: a named Agentd host prepares the exact wire/provider identity, dispatches once, then a rotated scope and expired run lease reconcile through the stored provider key without redispatch.
- FLOW-10: a threshold DecisionCell reloads the stored parameter bundle, commits the exact choice before routing, survives a crash cut and preserves V1/V2 histories independently.
- FLOW-11: 256 ordinary-disk circuit runs retain balanced success/failure outcomes and exact durable lookup after full owner reopen.

Focused source tests live in `codex-rs/hepta-automation/tests/durable_causal_chain.rs` plus the existing scheduler/TaskFlow tests. Exact candidate CI output remains the pass/fail receipt.

## 7. Integration, rollback and capability ceiling

The implementation intentionally reuses:

- Agentd's existing `AutomationScheduler` as the sole wake-up owner;
- the existing per-Agent `AutomationStore` SQLite database;
- the existing TaskFlow definition/run/event ledger;
- the existing App Server `thread/queue/reconcile` stable-client-id primitive;
- the kernel-owned durable `FinalUseAuthority` for external effect admission.

No second scheduler, TaskFlow engine, queue writer, authority issuer or terminality
oracle was introduced. Rollback must preserve schema v23 records or use a binary
that understands Calendar V2, fair/exact recovery, frozen product-effect identity,
create-only circuit/parameter registries and durable decisions; older binaries must
not replace the owner against an upgraded store.

Source implementation does not by itself authorize a concrete external provider, deployment, operator acceptance, canary, promotion or release.

## 8. Current native implementation

- **Schedule/occurrence owner:** `codex-rs/hepta-automation/src/store.rs`, `src/lifecycle.rs`, `src/schedule_v2.rs`, migrations `0004`-`0022`. Legacy schedule semantics remain compatible; Calendar V2 adds append-only timezone/tzdb/start/end/civil-time/DST schedule versions, deterministic canonical UTC materialization, missed-run/overlap policy and durable occurrence identity. Schema v14 freezes historical schedule revision on claimed legacy runs; v15 adds append-only proven-absence reconciliation for pre-v14 dispatch-unknown rows whose historical revision cannot be reconstructed.
- **Scheduler composition:** `codex-rs/hepta-automation/src/scheduler.rs` freezes occurrence/TaskFlow intent before App Server contact. The public legacy `AutomationTick::Submitted` now means durable Core queue admission only; it is not occurrence terminality. Calendar V2 creation is exposed through the existing Agentd control socket as `AutomationCreateCalendarV2`; the server advertises `automation.calendar_v2@1.0` and clients negotiate it before sending the additive method.
- **TaskFlow durable chain:** `src/automation_taskflow.rs`, `src/taskflow.rs`, `src/taskflow_step.rs`, `src/taskflow_recovery.rs`. Every materialized automation occurrence gets one deterministic TaskFlow run and versioned step-attempt chain; indeterminate effects are reconciled before terminal propagation.
- **Stable queue recovery and terminal observer:** `codex-rs/hepta-agentd/src/automation.rs` uses `thread/queue/reconcile(AllowIfAbsent)` for first admission. `src/automation_recovery.rs` uses `ReconcileOnly` after lost acknowledgement and scans at most 16 pages × 100 turns per pass. Schema v20 adds durable fair occurrence rotation; an already-known task/occurrence uses exact lookup and cannot disappear behind a 1024-row discovery page.
- **External effect product path:** `src/product_effect.rs` plus migration `0021` freeze the exact operation, payload, predecessor/compensation semantics, provider key/profile and claimed step. Agentd `automation_effect_host.rs`, `state_control.rs` and `client.rs` form the named prepare/execute/reconcile caller. `src/authorized_effect.rs` composes the producer-owned `kernel.operations::OperationIntentV1` and consumes `FinalUseAuthority`; `src/effect_dispatch_ledger.rs` persists pre-contact grant lineage, first observation and append-only terminal reconciliation. Running/Draining recovery uses the historical fence and original stored provider key and cannot redispatch.
- **Minimal Circuit runtime:** `src/neural_circuit.rs`, `src/threshold_circuit*.rs` and migration `0022` register immutable candidates and threshold-cell parameters, load the exact bundle, commit the choice, then route the existing TaskFlow run. It has no capability/effect authority. Crash-cut, reopen, successor-version and ordinary-disk capacity tests keep prior decisions immutable.
- **Focused verification:** migration convergence, `tests/durable_causal_chain.rs`, `tests/product_effect.rs`, `tests/threshold_circuit_capacity.rs`, threshold crash/successor unit tests, existing TaskFlow tests and Agentd effect-host tests. These cover signed final-use binding, at-most-once provider contact, scope rotation, expired-lease reconciliation, fair/exact recovery, choice-before-route and restart/version recovery.

### Remaining source/product boundary

The repository-controlled source/product-call boundary is closed for the named
Agentd -> App Server causal spine, Calendar V2 control, product effect preparation,
final-use HTTP dispatch/reconciliation and the minimal threshold DecisionCell. This
does not select a concrete production provider, trust root, revocation feed, tzdb or
host. Authentic/current IANA data, selected-host DST/multi-scheduler behavior,
provider fault/capacity evidence and general Circuit/organ semantics remain separate
qualification work. `AuthorizedEffectIntent` remains a TaskFlow orchestration envelope
over producer-owned `OperationIntentV1`, not a competing authority dialect.

Exact-head/synthetic-merge CI, target-host deployment, independent acceptance,
activation, promotion and release remain false until their separate gates pass.


### September 26 continuation: exact candidate and qualification boundary

Continue PR #990, not the historical local WIP branch. Schema v20 already supplies
occurrence rotation and exact lookup; v21 adds an immutable product preparation
reservation and a distinct completion receipt; v22 holds the restricted threshold
candidate/parameter/choice records; v23 adds a separate fair unknown-dispatch cursor.
A public preparation value is not a permit: the executor reloads its complete
immutable identity and readiness receipt before consuming final-use authority.
Incomplete preparation never licenses provider contact. A no-contact preparation may
resume under a newer native run fence as a new bounded immutable attempt, retaining
the operation and provider key. The provider-attempt insert checks the current fence
in the same SQLite writer order as takeover. Unknown/terminal contact is not retried.
The signed final-use deadline cannot outlive the frozen preparation lease.

The product host uses the existing async final-use/provider bridge, retaining the
original `for_operation` key rather than converting old records to the generic
logical-key algorithm. Host configuration schema v2 may list up to 16 independently
attested historical provider profiles for lookup only. An unbound legacy unknown
attempt cannot infer its old provider from current configuration. A missing original
profile fails closed; a 404/NotFound remains indeterminate rather than proving that
an active or previously dispatched operation did nothing.

`automation.effect_preparation@1.0` is separately negotiated from the older external
execution capability. Recovery remains available during Running/Draining with the
current Agent generation and required stores. Normal scheduling still requires open
admission. Each quantum visits at most one pending occurrence and one unknown queue
admission; transient observation I/O is deferred with the durable identity retained,
while corruption, identity mismatch and stale generation are not downgraded.

The minimal threshold profile actually reads stored parameter bytes, commits its
choice and advances existing TaskFlow routes. It is a pure, capability-free control
profile, not a Laya invocation, learned neural model, general DecisionCell/Intuition
product integration, feedback interpreter or independently accepted neural circuit.
Its presence must not close those separate design obligations.

Execution receipts must identify the final source commit, storage medium, toolchain,
commands and any failed/skipped/timed-out cases. Source mapping and mock HTTP contract
signatures never constitute independently provisioned deployment authority, real
provider acceptance, long-run target qualification, activation or release.


### Candidate validation status (2026-09-26 continuation)

This continuation is a review candidate on the existing #990 line, not a release
receipt. The earlier exact source `68d28d68` passed the Lane B path guard. That is
not an execution receipt for this larger continuation. The candidate has been
rebased onto the concurrently advanced branch rather than overwriting it.

The ordinary-disk nextest command and native check were attempted without test
retries or relaxed watchdogs. An exploratory check reached Agentd and exposed a
missing logging-crate reference; that reference was removed. Later exact check
attempts were blocked during dependency resolution by absent locked crate archives
and Git cache restoration. A scoped dependency inventory found 229 absent registry
archives; HTTP restoration also timed out. No final package-pass count, strict
Clippy pass, synthetic-merge pass, target-host latency or provider acceptance is
claimed. One requested local caller/Lane-B command was blocked by the connection's
safety check and was not routed around it.

The new regressions cover no-contact preparation restart, immutable preparation
substitution, stale-generation provider entry, original-profile lookup after host
rotation, same-frontier revocation substitution, cursor fairness, and restricted
parameter/choice recovery. Their source presence is not an executed pass. A full
Agentd public-socket qualification, crash-cut matrix and real target-host resource
measurement are still required; the restricted threshold fixture is not general
Neuron/Laya/Intuition qualification. All deployment and independent-acceptance flags
remain false.
