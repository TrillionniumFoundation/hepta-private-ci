# Lane B native implementation closure status

**Lane:** `LANE-B-RUNTIME`  
**Baseline:** `40997ba8082a6f550f9d09dcb52ceac2b7e9f127` / tree `929efaa6ba428c1d5cc8762ca53a12a95d2985ec`  
**Machine truth:** `qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json`  
**Composition:** `docs/readiness/LANE_B_RUNTIME_COMPOSITION.md`  
**Status:** repository-controlled mappings closed; target implementation and external evidence remain explicitly open

## 1. Review method

Each module is reviewed against five distinct surfaces:

1. canonical target design in `docs/modules/<module>/TECHNICAL.md`;
2. module execution design in `qualification/module-execution-dossiers/detail/<module>.md`;
3. declared and resolved source roots;
4. observed native source symbols at the exact baseline;
5. product caller, host, state, terminal observer and executable evidence.

A mapping is `implemented` only when a committed source symbol directly performs the designed local operation. `implemented_partial` means a real implementation exists but omits part of the target semantics. `boundary_only` means the source validates or projects caller-supplied values without owning the target runtime effect. `mapping_required` means a likely implementation exists in a larger package but the design operation is not yet bound to an exact symbol. `planned` means no current native mapping is claimed.

No source file, dependency edge, unit test, source pin or local observation is counted as a non-test product callsite. No component may authenticate its own terminal outcome when another owner controls the effect.

## 2. `runtime.supervisor`

### Current source

- Root: `codex-rs/hepta-supervisor`.
- Primary observed source: `codex-rs/hepta-supervisor/src/supervisor.rs`.
- Current native lifecycle surface includes recovery, snapshots, start, release start, drain, stop, kill, restart, upgrade, rollback, production-grant application and periodic tick processing.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `start_instance` | `Supervisor::start` and release-aware start path | implemented partial |
| `observe_health` | `Supervisor::tick` plus process-driver observations | implemented partial |
| `drain` | `Supervisor::drain` | implemented |
| `load_next` | `Supervisor::upgrade` and rollback paths | implemented partial |

### State and ownership

The supervisor controls lifecycle transitions and embeds the fleet registry implementation. Records bind agent identity, lifecycle generation, release state, process identity and pending transitions. Embedding a registry library does not by itself settle whether `runtime.supervisor` or `runtime.fleet` is the canonical writer of every physical registry byte; that ownership must be explicit at the field/table/file level.

### Remaining implementation closure

- Bind each externally reachable control RPC to one exact method and authorization path.
- Publish exact binary, command-line/configuration and host process identity.
- Define signed-intent fsync and crash-recovery linearization as a public implementation contract.
- Execute process kill, stale callback, upgrade, automatic rollback and restart qualification on every supported native host.
- Bind readiness to store integrity and dependency readiness, not only process liveness.

## 3. `runtime.fleet`

### Current source

- Root: `codex-rs/hepta-fleet`.
- Registry implementation: `src/registry.rs`.
- Deterministic allocator: `src/allocation.rs` with validation and digest helpers.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `admit_host` | `FleetRegistry::register` covers local agent registration, not full federated host enrollment | implemented partial |
| `allocate` | `calculate_local_allocation_v1` computes bounded weighted max-min shares | boundary only |
| `renew_or_revoke` | no native grant/lease publisher mapping | planned |

### State and ownership

`FleetRegistry` persists manifests and lifecycle generations with physical-directory checks and compare-and-transition behavior. The allocator is deliberately authority-free: all capacities, floors, weights and demands are caller supplied, and the result is not a grant, lease or scheduling receipt.

### Remaining implementation closure

- Separate the physical registry owner from the allocation-grant owner in canonical data authority.
- Implement a grant publisher that consumes authenticated capacity, current authority epoch, revocation frontier and generation fence.
- Persist coherent capacity/allocation generations and reconcile uncertain resource holders before reallocation.
- Bind a real production consumer that enforces the grant locally.
- Qualify partition, lease expiry, double allocation, resource conservation and rollback drain.

## 4. `runtime.agentd`

### Current source

- Root: `codex-rs/hepta-agentd`.
- Relevant components include app runtime, automation host, client, configuration, control socket, error handling, event buffer, process entrypoints and explicit durable-writer host seams.
- `src/app_runtime.rs` launches the existing Codex App Server over a configured local socket with strict configuration, local thread-store requirements and explicit feature-state constraints.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `compose_runtime` | `run_app_server` and runtime-option construction | implemented partial |
| `start_run` | app-server launch and queue admission infrastructure | implemented partial |
| `cancel_run` | no exact Agentd-to-app-server cancellation mapping in the truth registry | planned |
| `attach_context` | no exact receipt-to-turn attachment mapping in the truth registry | planned |

### State and ownership

Agentd is a composition host. It may hold ephemeral run handles, socket/process state and runtime-health observations, but it must not become the objective, memory, learning, prompt, artifact or operation-ledger owner. The default profile remains read-only; any positive writer capability must be explicit, externally verified and separately qualified.

### Remaining implementation closure

- Publish process tree, socket paths, peer authentication and platform transport matrix.
- Bind run admission, cancellation and context attachment to exact app-server handlers.
- Define startup/readiness/shutdown sequencing for every required owner port.
- Prove queue limits, backpressure and cancellation acknowledgement deadlines.
- Execute native process qualification, including socket failures, restart and configuration drift.

## 5. `runtime.codex`

### Current source

- Canonical alias root: `codex-rs/codex-app-server`.
- Resolved implementation: `codex-rs/app-server`.
- Hepta boundary: `codex-rs/hepta-codex-adapter`.
- The alias is not a duplicate Cargo package; the real app-server remains the single execution spine.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `open_thread` | exact app-server protocol handler not yet registered | mapping required |
| `submit_turn` | exact app-server protocol handler not yet registered | mapping required |
| `dispatch_tool` | exact final tool-dispatch handler not yet registered | mapping required |
| `observe_delivery` | `hepta_codex_adapter::adapt` validates request/observation binding | boundary only |

### State and ownership

The app-server owns thread and turn execution state. The adapter verifies payload/deadline binding and maps a supplied terminal observation, but it does not open a thread, invoke a model, dispatch a tool or independently observe the app-server transport.

### Remaining implementation closure

- Register canonical alias resolution in the machine-readable mapping.
- Map all four design operations to exact app-server protocol methods and callsites.
- Bind Agentd startup and request admission to those methods.
- Specify thread-store schema, migrations, recovery and pending effect links.
- Qualify model request, streamed response, cancellation, tool effect and acknowledgement-loss paths through the named product host.

## 6. `inference.control`

### Current source

- Roots: `codex-rs/hepta-infer-core`, `codex-rs/hepta-inferd`.
- `hepta-infer-core` implements an in-process request ledger.
- `hepta-inferd` creates exact-bound dispatch plans.
- Neither current boundary invokes a provider or executes a model.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `reserve_request` | `InferenceLedger::reserve` | implemented partial |
| `schedule` | `hepta_inferd::plan` | boundary only |
| `cancel` | `InferenceLedger::cancel` | implemented partial |
| `settle` | `InferenceLedger::complete` | implemented partial |

### State and ownership

The current ledger is process-local and bounded. It is not yet evidence of the declared durable request, reservation and receipt owner. Completion consumes a terminal receipt digest supplied by a caller rather than observing provider/model execution.

### Remaining implementation closure

- Implement durable request/reservation/settlement storage and migration.
- Add quota, resource reservation, worker eligibility and deterministic assignment ownership.
- Add durable dispatch intent/outbox and acknowledgement reconciliation.
- Define cancellation-versus-completion settlement and usage accounting.
- Bind real provider/model execution and a non-test Codex caller.

## 7. `inference.worker`

### Current source

- Root: `codex-rs/hepta-infer-worker-host`.
- The present `execute` function validates request, lease and reservation compatibility and maps a caller-supplied observation into a receipt.
- It explicitly does not load weights, call a runtime/provider, mutate fleet state or infer terminality from queue acceptance.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `load_model` | no implementation | planned |
| `run` | `execute` receipt boundary | boundary only |
| `unload` | no implementation | planned |

### State and ownership

Current state is ephemeral input validation only. A real worker must bind process identity, model generation, weights, tokenizer, preprocessing, quantization, runtime, device, resource grant, cache handles and request handles.

### Remaining implementation closure

- Implement isolated worker process entrypoint and authenticated control transport.
- Implement model manifest verification and resource-bounded load/unload.
- Integrate at least one real model runtime without granting ambient provider authority.
- Implement bounded generation, streaming, cancellation, usage observation and crash cleanup.
- Qualify OOM, device reset, load-stage kill, mixed artifacts and acknowledgement loss.
- Bind a real inference-control product caller and exact binary/model/device evidence.

## 8. `automation.taskflow`

### Current source

- Root: `codex-rs/hepta-automation`.
- Existing sources include schedule/store logic, a substantial TaskFlow definition and run ledger, taskflow kernel, step state machine, scheduler and a fail-closed execution-boundary assessment.
- The implemented TaskFlow namespace is qualification-only and does not execute external callbacks.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `register_schedule` | current TaskFlow definition/store surface | implemented partial |
| `materialize_due` | scheduler `tick` path | implemented partial |
| `claim_occurrence` | scheduler/store `claim_due` path | implemented partial |
| `execute_step` | `assess_local_taskflow_boundary` rejects unavailable effect/terminal owners | boundary only |

### State and ownership

The SQLite-backed qualification ledger owns definition/run transitions under generation fences. It does not own final-use authority, the external effect or the trusted terminal observer. A content digest does not authenticate a capability or completion.

### Remaining implementation closure

- Bind design terminology to exact current tables, migrations and symbols.
- Connect the canonical schedule/occurrence model to the TaskFlow graph/run ledger without a second scheduler.
- Admit typed final-use capability through the registered authority owner.
- Route production steps through the Codex/App Server seam.
- Persist terminal/indeterminate state from a trusted observer and implement separately authorized compensation.
- Qualify DST, missed-run policy, two-scheduler fencing, crash after dispatch and partial compensation.

## 9. `channel.matrix`

### Current source

- Roots: `codex-rs/hepta-matrix-sdk`, `codex-rs/hepta-matrixd`.
- Supporting protocol/store packages are non-authoritative evidence roots unless separately registered.
- `MatrixRuntime` performs serialized inbox processing, pending recovery, room/thread binding, app-server admission and outbox projection over a durable store.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `admit_event` | `MatrixRuntime::process_event` | implemented partial |
| `prepare_send` | `MatrixRuntime::project_app_server_event` and durable outbox construction | implemented partial |
| `observe_send` | exact homeserver transport observer not registered | mapping required |

### State and ownership

The durable store binds event, room/thread, dispatch, outbox and transaction identities. App-server turn terminality and Matrix homeserver send terminality are different observations. Reconnect must preserve the same identities and current redaction/deletion frontier.

### Remaining implementation closure

- Register exact sync ingress, SDK decoder and outbox transport callsites.
- Bind homeserver/user/device/room/encryption generation and credentials to an enrolled scope.
- Implement and map server-event send acknowledgement and unknown-send reconciliation.
- Qualify response-size limits, pagination, reconnect, redaction, duplicate events, rate limits and restore.
- Prove the named Agentd product host and target homeserver configuration.

## 10. `browser.servo`

### Current source

- Roots: `apps/hepta-browser`, `third_party/servo-patches`.
- `browser.js` supplies authority-free URL intent and page-projection primitives.
- The Servo manifest pins an upstream source commit and currently lists no patches.
- No Servo process, profile store, network adapter or terminal browser observer is proved.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `open_profile` | no implementation | planned |
| `observe_page` | `projectPageState` over caller-supplied observations | boundary only |
| `navigate_or_act` | `buildNavigationIntent` over caller-supplied input | boundary only |

### State and ownership

No current source owns `browser_profile_state`. The JavaScript package cannot grant network, filesystem, credential or effect authority. A source pin is not a reproducible deployed browser binary.

### Remaining implementation closure

- Implement a reproducible Servo build and isolated process host.
- Implement authenticated Agentd IPC and explicit profile lifecycle.
- Enforce origin, DNS/network, redirect, upload/download, filesystem and credential capabilities at the final boundary.
- Implement bounded DOM/page observations with document and element generations.
- Add trusted navigation/action/download terminal observations and reconciliation.
- Qualify profile isolation, stale element, malicious page instructions, crash/hang and form-submission uncertainty.

## 11. `ui.control`

### Current source

- Root: `apps/hepta-control-ui`.
- Current package is a Node-tested presentation core with one JavaScript source file.
- It projects bounded runtime observations and constructs authority-free local requests; it is not a deployed Web application and has no registered production caller.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `read_view` | `projectRuntime` | boundary only |
| `submit_request` | `buildOperationIntent` local proposal surface | boundary only |
| `request_stop` | no implementation | planned |

### State and ownership

Only view/session-local state is permitted. Backend facts, authority, operation identities and terminal outcomes remain with their owners. A stale or optimistic view cannot become a mutation receipt.

### Remaining implementation closure

- Select and record Web framework, build target, browser support and deployment topology.
- Generate the protocol client from the canonical backend schema.
- Implement authentication, session expiry, CSRF/CSP, reconnect and coherent snapshot handling.
- Implement pending/indeterminate/terminal presentation and authenticated stop requests.
- Qualify accessibility, keyboard/screen-reader paths, stale confirmation and reconnect deduplication.
- Bind an exact production deployment and backend callsite.

## 12. `ui.native`

### Current source

- Root: `apps/hepta-native`.
- Current package defines bounded native-operation intents and rejects terminal success without a trusted backend receipt.
- It does not contain a native application framework, platform API calls, secure storage or an updater.

### Design mapping

| Design operation | Current mapping | State |
|---|---|---|
| `connect_runtime` | no implementation | planned |
| `render_runtime_view` | no implementation | planned |
| `request_platform_capability` | `buildNativeIntent` boundary | boundary only |
| `apply_shell_update` | no implementation | planned |

### State and ownership

No platform writer, keychain owner or updater exists in the current scaffold. Native OS permission and a Hepta effect grant are separate requirements. The UI cannot authenticate its own terminal outcome.

### Remaining implementation closure

- Select native framework and supported Windows/macOS/Linux targets.
- Implement authenticated IPC and the shared generated runtime client.
- Implement narrowly scoped platform adapters for file reveal/open, clipboard and notifications.
- Integrate secure opaque session references through the designated secret boundary.
- Implement signed updates, compatibility checks, anti-rollback and predecessor recovery.
- Qualify OS permission denial/revocation, crash/restart, accessibility, signing and updater rollback.

## 13. Cross-module closure conditions

Repository-controlled target implementation closure requires all of the following at one exact source and synthetic merge candidate:

- all 39 design operations map to compiled native symbols;
- no operation remains `planned`, `mapping_required`, `boundary_only` or `implemented_partial`;
- each service/worker/UI names an exact build target, binary/artifact, host and configuration;
- each state-bearing module binds physical schema, migration, single writer, recovery and rollback;
- each effect boundary binds current authority, revocation, final payload, destination and terminal observer;
- every module has a non-test product caller or proved `none_by_design` disposition;
- exact product tests exercise success, rejection, timeout, cancellation, crash, recovery, drift, saturation and rollback;
- target-host resource measurements are attached;
- exact-head and synthetic-merge CI are terminal-success;
- independent and external gates are separately evidenced rather than self-issued.

Until those conditions hold, the repository truth model is closed but target implementation closure remains false.
