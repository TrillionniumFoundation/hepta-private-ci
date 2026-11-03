# runtime.fleet durable execution candidate

Revision: 2026-09-28. Delivery line: PR #1103, `codex/runtime-fleet-durable-owner-v1-20260927`.

This is an implementation supplement to [TECHNICAL.md](TECHNICAL.md). [CURRENT_STATE.json](CURRENT_STATE.json) separates source presence, command execution, real product composition and release. PR #1060 is superseded. Its JSON-journal owner, start-admission test and status binary are not the current SQLite candidate and must not be silently transplanted as a second owner.

## Source boundary and qualification

The existing supervisor remains the intended single owner. The crate now contains a SQLite-backed `DurableFleetStore`; the in-memory `LeaseLedger` remains a reusable state machine. This source revision adds occupancy and native observation primitives inside the SQLite owner. It does not install a second fleet service.

`durable_execution.rs` is compiled through `lib.rs`, not through a qualification-time replacement script. The root exports the canonical `AllocationGrant` and `HostObservation` used by the durable implementation. `durable_store_tests.rs` imports its `Sha256` helper explicitly. These are source fixes, not proof that the workspace compiles.

The existing fleet lockfile dependency entry still needs SQLx/Tokio synchronization. Rust compilation, rustfmt, strict clippy, exact-source qualification and synthetic-merge qualification have not been accepted. Never disable `--locked`, write back source from a qualification job, or reinterpret a queued job as a pass.

## Ordered host incarnation

`register_local_boot(host_id)` reads and validates the native Linux boot UUID. There is no hash-to-ordered-integer conversion and no wall-clock fallback. Under one immediate SQLite writer transaction, `fleet_host_incarnations` records the current boot and ordered generation; `fleet_seen_boots` retains boot tombstones and uniqueness of host/generation. A repeat of the same boot keeps its generation, a new boot allocates the next checked integer, and a replay of a retired boot fails.

The public native entrypoint does not accept caller-supplied boot identity. The internal identity entrypoint exists for deterministic counter/replay tests. A process restart within one OS boot is not a new OS incarnation. Supervisor process epochs and launch identities remain separate fences.

The capacity observer must use this persisted incarnation, not manufacture its own. That product composition is still required. Existing clock samples taken before writer-lock acquisition also require a concurrency review; conservative rejection is not a substitute for a correct transaction-time sampling protocol.

## Execution occupancy is distinct from lease validity

`FleetExecutionContextV1` carries the execution/allocation/principal/host identities, host and lease generations, exact six-axis resource demand, immutable execution manifest digest and containment identity. `prepare_local_execution` compares those values to the current grant and host. A correct caller derives this context from the actual immutable execution configuration, not from the grant it is trying to validate.

Preparation persists an execution hold before launch. A duplicate execution identity returns a conflict requiring reconciliation; it does not issue another successful launch ticket. Binding records native PID, process group and process start ticks, checks the launch marker and actual cgroup membership, and rechecks process identity before publication.

The intended state progression is:

```text
prepared -> running -> stop_requested -> stopped
prepared ------------> stop_requested
```

Expiry, revocation and host fencing immediately remove the grant from future-use admission. When an execution hold remains, retirement writes a durable stop obligation and retains its capacity. Without an execution hold, unused-grant retirement retains its previous capacity-release behavior. Capacity is subtracted once at native stop confirmation, not merely because a lease timestamp elapsed.

`confirm_local_exit` requires the original process to be absent/reaped, its complete process group to be absent, and the original protected cgroup subtree to report empty. PID reuse is distinguished using start ticks; the cgroup object is distinguished using device/inode. A native reboot can retire old OS occupancy only after the owner records the current boot. Missing paths, unreadable procfs, unbound launches and unsupported platforms do not prove exit.

### Product obligations that are not closed by this API

The current Supervisor daemon and Unix process driver do not yet call these APIs. This revision therefore does not claim full product final-use validation, cancellation or capacity reclamation. The consumer must bind generic authority at the effect boundary, ensure the verified immutable configuration is what actually launches, prevent a prepared launch from racing recovery, and process stop obligations through the existing owner.

The native containment checks assume workloads cannot mutate or escape supervisor-controlled cgroups. They are not sufficient for privileged/root workloads. The launch implementation must establish unprivileged credentials, capability restrictions, non-escalation, physical CPU/memory controls and logical resource consumers before acceptance. An empty protected directory alone is not proof of those launch guarantees. Prepared-but-unbound interruption remains a conservative occupancy hold until producer-fenced reconciliation is implemented.

## Persistence and migration

The base schema is retained in `durable_schema.sql`; the added incarnation and execution tables are in `durable_execution_schema.sql`. The SQLite schema version is 2 while owner lineage is unchanged. Initialization/migration and its clock update share an immediate transaction. A schema-v1 database with active grants is rejected rather than assuming its tasks have stopped.

This SQL guard is necessary but not sufficient for migration. A selected product owner must establish complete quiescence first; expired or historically removed grant rows are not native stop evidence. Old state and its recovery material must be retained until a rehearsed migration succeeds. Restoring an old backup requires a separately trusted anti-rollback strategy; the SQL file cannot independently authenticate its own historical freshness.

## Pressure, observability and efficiency

`DurableFleetError::disposition` separates temporary capacity/storage/clock unavailability, indeterminate commits, request rejection and owner integrity quarantine. The existing capacity refresh persists physical shrink rather than granting additional resources against the old capacity. The Supervisor still needs to consume the disposition with admission pause, recovery and continued lifecycle control; an enum alone does not implement that policy.

Metrics are read in a single transaction. Missing authoritative resource totals are errors, not zero. Operational gauges are nullable until observed. `revocation_update_age_ms` measures only update age; convergence lag remains unknown without the expected recipient roster and observed acknowledgements. These are changes to an unreleased candidate structure, not a claim of compatibility with an already-deployed wire version.

The revision removes repeated independent metric snapshots. It does not claim measured startup, recovery or tail-latency improvements. Long-term hold/history retention, streaming recovery and compaction require measured workloads and must preserve incarnation and allocation tombstones.

## Test inventory and evidence limits

The eight new Rust tests cover ordered/replayed boots, independent connections, native-boot owner reopen, pressure classification, a real two-process Unix group, rejected containment paths, retained occupancy across expiry/reopen, and nullable telemetry. They are source tests awaiting actual Rust execution. The SQL occupancy fixture is explicitly not generic-authority or product acceptance evidence.

The Python diagnostic suite has 12 locally executed tests using the actual SQL files and command entrypoint. The receipt-runner suite has six locally executed fault tests using isolated real Git repositories and deliberately failing Cargo fixtures. All fixture execution receipts must remain failed. These 18 tests do not establish full-workspace or selected-host qualification.

The read-only workflow tests exact source and a deterministic source/base merge, records individual commands and exits, identifies runner/toolchain/workflow/source trees, and hashes logs and receipt artifacts. Product and release acceptance remain false even when those source checks eventually pass. The immutable head is bound by the workflow event and PR record rather than an impossible self-referential SHA embedded inside its own source commit.
