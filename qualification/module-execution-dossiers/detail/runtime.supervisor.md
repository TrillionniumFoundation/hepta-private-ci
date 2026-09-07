# runtime.supervisor: implementation design

Parent: `docs/modules/runtime.supervisor/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-supervisor`.
Packages: `P0.7A-RUNTIME-BOOTSTRAP`, `P0.8B-READINESS`, `P0.8C-RESOURCE-BUDGETS`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`start_instance(selected_snapshot, host_profile) -> InstanceGeneration`; `observe_health(instance, generation, monotonic_time, status) -> HealthTransition`; `drain(instance, reason) -> DrainReceipt`; `load_next(selected_artifact_set, evidence) -> NextRunSnapshot`. Selection consumes independently issued decisions and does not turn the loader into a candidate generator or evaluator. Model/tool/secret invocation is not a supervisor operation.

## 3. State records and transaction design

`fleet_registry`, `agent_lifecycle`, `runtime_instance_projection` and `release_selection` retain their canonical writer. Instance records bind process identity, launch artifact/configuration, body generation, phase, watchdog deadline, restart counter and predecessor. Release-selection facts reference signed, independently selected artifact sets. Runtime-health projections are not evidence of a completed user task.

## 4. Deterministic algorithm and scheduling

Validate configuration, ownership and artifacts; establish a new process fence; start dependencies in initialization order; wait for readiness, not merely liveness; admit runs only after all critical gates. Shutdown stops admission, drains owned work, reconciles unknown effects and releases only resources actually acquired. Restart uses bounded exponential backoff and a fixed attempt budget; a flapping essential organ falls back or stops.

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
