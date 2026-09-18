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

## 4. Deterministic algorithm and scheduling

Validate configuration, ownership and artifacts; establish a new process fence; start dependencies in initialization order; wait for readiness, not merely liveness; admit runs only after all critical gates. Shutdown stops admission, drains owned work, reconciles unknown effects and releases only resources actually acquired. Restart uses bounded exponential backoff and a fixed attempt budget; a flapping essential organ falls back or stops.

The native main-Agent watchdog now distinguishes initial readiness from post-readiness health loss. A Running process that loses health enters a bounded unhealthy grace period; expiry transitions the Fleet lifecycle to Failed, stops the exact process, observes exit, and only then schedules an automatic replacement. Automatic retries use the configured recovery window, capped exponential backoff and attempt budget. Explicit stop, kill or restart supersedes queued automatic recovery. This source behavior is not a target-host timing measurement.

## 5. Capacity and performance profile

Pilot <= 256 managed instances per supervisor, health batch <= 256, restart budget <= 3 per configured recovery window. Watchdog period/deadline are plant/host-profile fields; no language-model round trip is allowed on an emergency path. Record startup, drain, stop and new-generation load latency.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- SUP-01: a live process with failed store integrity is not ready.
- SUP-02: stale-generation health/callback cannot advance the new instance.
- SUP-03: kill at each launch acquisition step releases only acquired resources.
- SUP-04: revoked or incompatible rollback artifact is refused and quarantined; a NEW process generation is required for the reload acceptance test.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Agentd remains a composition host; durable domain ownership does not move into the supervisor. The CNS brainstem and local controller schedules stay separate. Rollback consumes an independently authorized compatible predecessor and checks current revocations, not an old release-selection backup.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `start` in [codex-rs/hepta-supervisor/src/supervisor.rs](../../../codex-rs/hepta-supervisor/src/supervisor.rs); `tick` in [codex-rs/hepta-supervisor/src/supervisor.rs](../../../codex-rs/hepta-supervisor/src/supervisor.rs); `upgrade` in [codex-rs/hepta-supervisor/src/supervisor.rs](../../../codex-rs/hepta-supervisor/src/supervisor.rs). Native process lifecycle and release transition supervisor implemented.
- **State and recovery:** Supervisor keeps managed-process phases, watchdog grace and bounded automatic-restart accounting in memory and uses FleetRegistry lifecycle/release facts for durable recovery. Generation and release predecessor checks govern drain/restart/upgrade/rollback; process liveness alone is not full readiness. A child whose process-lease publication fails is retained as a fenced cleanup runtime until its exit is observed in the live supervisor generation rather than dropping the process handle.
- **Release admission:** Ordinary rollback re-resolves the recorded predecessor through the current Fleet allowance and immutable release manifest. When supervisord is booted with an external production grant verifier, unsigned Upgrade and Rollback RPCs fail closed and callers must use SignedUpgrade/SignedRollback. Matrix-only bundle changes are compared using both agentd and matrixd commands.
- **Unix shutdown semantics:** Drain and stop are distinct process controls: supervisor drain uses SIGUSR1 and Agentd handles it as a drain request that closes local admission; the later stop phase uses SIGTERM. The Unix driver does not fabricate a drained-complete observation; process exit remains the local terminal observation, and target-host drain timing/behavior remains an external qualification gate.
- **Source tests:** [codex-rs/hepta-supervisor/src/supervisor_tests.rs](../../../codex-rs/hepta-supervisor/src/supervisor_tests.rs), [codex-rs/hepta-supervisor/src/unix_tests.rs](../../../codex-rs/hepta-supervisor/src/unix_tests.rs). Focused regressions cover Matrix-only release changes, current-allowance rollback checks, lease-publication/kill failure retention, post-readiness health loss, bounded restart exhaustion, and distinct Unix drain/stop signals. These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json](../../../docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json).
- **Remaining work:** Qualify the actual deployed executable, target-host watchdog/restart/drain timing and behavior, process cleanup under host-level crash/filesystem failure, and independently accepted release transition. Source tests do not prove the target host process lifecycle or issue independent acceptance.
