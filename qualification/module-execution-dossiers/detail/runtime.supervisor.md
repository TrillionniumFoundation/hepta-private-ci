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

- **Implemented entrypoints:** `start`, `drain`, `tick`, `upgrade`, `rollback`, signed production mutation admission, and production-mutation status in [codex-rs/hepta-supervisor/src/supervisor.rs](../../../codex-rs/hepta-supervisor/src/supervisor.rs) and [codex-rs/hepta-supervisor/src/daemon.rs](../../../codex-rs/hepta-supervisor/src/daemon.rs).
- **Release authority and selection:** when a production grant verifier is configured, unsigned `Upgrade`/`Rollback` RPCs fail closed. The signed grant binds source/target release-manifest digests, target Agentd/Matrixd executable digests, H7 artifact/envelope, compatibility and revocation-frontier evidence digests, authority epoch, signer, validity window and CAS fences. [release_selection.rs](../../../codex-rs/hepta-supervisor/src/release_selection.rs) persists that selection independently of process state.
- **Rollback admission:** Fleet release allowances are durably revocable. Explicit and automatic rollback re-resolve the predecessor through the current allowance/catalog before launch rather than reusing cached executable state.
- **Drain:** the Unix driver sends a generation-bound Agentd drain RPC that stops new admission; `request_drain` no longer sends SIGTERM. The acknowledgement is not terminal-work evidence. With no trusted in-flight drain observer yet wired, the process observer leaves `drained=false` and the supervisor advances at the bounded drain deadline.
- **Restart and recovery:** unexpected primary-Agent exit uses a durable, fixed-window exponential restart budget persisted in `supervisor-restart-budget.json`; daemon recovery restores the pending backoff and cannot reset the attempt count. Every registered-release retry re-resolves current release allowance. Signed intent and release-selection journals must agree at recovery; non-terminal or one-sided state fails startup closed.
- **Readiness boundary:** exact generation/process/root identity and App Server readiness are enforced. A complete current owner observation for critical-store integrity and capability-revocation availability is not yet wired into Agentd promotion readiness and remains a repository integration gap.
- **Source tests:** [codex-rs/hepta-supervisor/src/supervisor_tests.rs](../../../codex-rs/hepta-supervisor/src/supervisor_tests.rs), [codex-rs/hepta-supervisor/src/unix_tests.rs](../../../codex-rs/hepta-supervisor/src/unix_tests.rs), [codex-rs/hepta-supervisor/src/signed_authority.rs](../../../codex-rs/hepta-supervisor/src/signed_authority.rs), [codex-rs/hepta-supervisor/src/release_selection.rs](../../../codex-rs/hepta-supervisor/src/release_selection.rs), and [codex-rs/hepta-supervisor/src/restart_budget.rs](../../../codex-rs/hepta-supervisor/src/restart_budget.rs). These remain source identities until exact-candidate execution receipts exist.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json](../../../docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json).
- **Remaining repository work:** bind promotion readiness to a real current critical-store/revocation owner observation and supply a trusted in-flight drain terminal/reconciliation observer. **External qualification still required:** deployed executable/host identity, watchdog/start/drain/restart measurements, and independent acceptance of signed upgrade/rollback.
