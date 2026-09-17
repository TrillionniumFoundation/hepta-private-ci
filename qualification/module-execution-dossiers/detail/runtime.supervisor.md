# runtime.supervisor: implementation design

Parent: `docs/modules/runtime.supervisor/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: native process lifecycle and release transition supervisor implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-supervisor`.
Packages: `P0.7A-RUNTIME-BOOTSTRAP`, `P0.8B-READINESS`, `P0.8C-RESOURCE-BUDGETS`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`start_instance(selected_snapshot, host_profile) -> InstanceGeneration`; `observe_health(instance, generation, monotonic_time, status) -> HealthTransition`; `drain(instance, reason) -> DrainReceipt`; `load_next(selected_artifact_set, evidence) -> NextRunSnapshot`. Selection consumes independently issued decisions and does not turn the loader into a candidate generator or evaluator. Model/tool/secret invocation is not a supervisor operation.

## 3. State records and transaction design

`fleet_registry`, `agent_lifecycle`, `runtime_instance_projection` and `release_selection` retain their canonical writer. Instance records bind process identity, launch artifact/configuration, body generation, phase, watchdog deadline, restart counter and predecessor. Release-selection facts reference signed, independently selected artifact sets. Runtime-health projections are not evidence of a completed user task.

A signed production transition publishes a durable intent before it can touch the release/process state machine. Publication is the mutation-start boundary: after that point a failure is indeterminate until the exact intent and current state are reconciled. Non-terminal signed intents globally freeze ordinary lifecycle mutations. Recovery is explicit, binds the current control fence plus exact intent digest, and is effect-free: it may acknowledge the already-durable source or target release but may not launch a new release as part of the recovery ceremony.

## 4. Deterministic algorithm and scheduling

Validate configuration, ownership and artifacts; establish a new process fence; start dependencies in initialization order; wait for readiness, not merely liveness; admit runs only after all critical gates. Shutdown stops admission, drains owned work, reconciles unknown effects and releases only resources actually acquired.

Automatic restart for the primary Agent and Matrix companion uses a shared bounded exponential policy. The source-compatible pilot policy is 250 ms minimum backoff, doubling per attempt, capped at 30 seconds, with at most three automatic attempts in a five-minute recovery window. A brief healthy interval does not reset the budget for a flapping process. Explicit operator drain/stop/kill/restart cancels pending automatic recovery so operator intent takes precedence. Budget exhaustion stops automatic restart and emits an explicit supervisor event.

The daemon copies the bounded Agent identity list and releases the global supervisor mutex between per-Agent tick slices. This removes one whole-fleet critical section; synchronous registry/filesystem/process-driver work inside one selected Agent can still hold the mutex for that slice and therefore remains a selected-host latency qualification obligation.

## 5. Capacity and performance profile

Pilot <= 256 managed instances per supervisor, health batch <= 256, restart budget <= 3 per configured recovery window. Watchdog period/deadline are plant/host-profile fields; no language-model round trip is allowed on an emergency path. Record startup, drain, stop and new-generation load latency.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state. For the selected host, measure snapshot/control p50/p95/p99 latency, maximum single-Agent tick duration and full-fleet tick-cycle duration at 1/64/128/256 Agents, including a deliberately slow child.

## 6. Concrete verification cases

- SUP-01: a live process with failed store integrity is not ready.
- SUP-02: stale-generation health/callback cannot advance the new instance.
- SUP-03: kill at each launch acquisition step releases only acquired resources.
- SUP-04: revoked or incompatible rollback artifact is refused and quarantined; a NEW process generation is required for the reload acceptance test.
- SUP-05: primary-Agent and Matrix crash loops stop after the fixed automatic restart budget in the recovery window.
- SUP-06: once a signed intent is durably published, a later failure is reported as indeterminate, never as a safe preflight rejection.
- SUP-07: an unresolved signed intent makes the daemon not-ready, freezes ordinary mutations, remains inspectable, and can reach a terminal journal state only through a current-fence + exact-intent-digest recovery request.
- SUP-08: the daemon releases its supervisor mutex between Agent tick slices; one fleet sweep is not one monolithic 256-Agent critical section.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence. Source-level crash/recovery coverage and mandatory selected-host fault injection are specified in [codex-rs/hepta-supervisor/RECOVERY_AND_CRASH_QUALIFICATION.md](../../../codex-rs/hepta-supervisor/RECOVERY_AND_CRASH_QUALIFICATION.md).

## 7. Integration, rollback and capability ceiling

Agentd remains a composition host; durable domain ownership does not move into the supervisor. The CNS brainstem and local controller schedules stay separate. Rollback consumes an independently authorized compatible predecessor and checks current revocations, not an old release-selection backup.

`runtime.supervisor` owns release transition, not candidate generation, evaluation or independent release selection. The signed transition path can consume an externally verified decision, but source availability does not establish that a production selector, production caller or production writer is composed. Preserve `productionImplementation=false`, `productCallerState=not_composed`, activation/release false, and independent-acceptance false until those external gates are actually satisfied.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `start`, `drain`, `stop`, `kill`, `restart`, `upgrade`, `rollback`, signed production grant admission, signed-intent inspection/resolution, `tick` and per-Agent daemon `tick_agent` are implemented under [codex-rs/hepta-supervisor/src](../../../codex-rs/hepta-supervisor/src). Native process lifecycle and release transition supervision is implemented.
- **Bounded restart:** primary-Agent unexpected exits/startup-health failures and Matrix failures use one bounded exponential scheduler with a fixed three-attempt pilot budget per five-minute recovery window. Explicit lifecycle control cancels pending automatic restart.
- **Signed mutation semantics:** durable intent publication is the mutation-start boundary. Errors after that boundary surface as `operation_indeterminate`. Non-terminal intents freeze ordinary mutation and keep health not-ready until exact reconciliation.
- **Signed recovery:** recovery requests bind the current control fence and exact `intent_sha256`, require process/lease quiescence, and may only reconcile the already-durable source or accept the already-durable target. They never cause a new release launch. Contradictory durable lineage remains strict fail-closed rather than being accepted as ambiguity.
- **State and recovery:** Supervisor keeps managed-process phases in memory and uses FleetRegistry lifecycle/release facts plus exact process leases for recovery. Generation and release predecessor checks govern drain/restart/upgrade/rollback; process liveness alone is not full readiness.
- **Daemon concurrency:** periodic fleet advancement releases the supervisor mutex between Agent tick slices. This reduces fleet-level head-of-line amplification but does not eliminate one-Agent synchronous I/O/driver blocking; target-host measurements remain required.
- **Source tests:** [codex-rs/hepta-supervisor/src/supervisor_tests.rs](../../../codex-rs/hepta-supervisor/src/supervisor_tests.rs), [codex-rs/hepta-supervisor/src/unix_tests.rs](../../../codex-rs/hepta-supervisor/src/unix_tests.rs), restart-scheduler tests in `runtime.rs`, signed-intent durability tests in `signed_intent.rs`, daemon error/recovery tests in `daemon.rs`, and sliced-tick isolation tests in `daemon_tick.rs`. These are test identities, not execution receipts for this documentation revision.
- **Crash and host qualification:** [codex-rs/hepta-supervisor/RECOVERY_AND_CRASH_QUALIFICATION.md](../../../codex-rs/hepta-supervisor/RECOVERY_AND_CRASH_QUALIFICATION.md) separates repository-controlled proof from selected-host `SIGKILL`, `ENOSPC`, fsync/rename, PID-reuse, timeout and 256-Agent latency evidence.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json](../../../docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json).
- **Remaining work:** execute exact-candidate package/strict-lint/merge-candidate CI; qualify the actual deployed executable and selected-host crash/watchdog/drain/HOL behavior; compose a named independent production release-selection caller/writer; obtain independent operational acceptance. Source tests do not prove those external gates.
