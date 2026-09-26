# Lane B source contracts and implementation gaps

**Lane:** `LANE-B-RUNTIME`
**Immutable source base:** `7e8379b3954808d4138a7bd2f3773f75691291a3` / tree `ff9fa6baf95a35fd2f49816e0a80097688f2aeeb`
**Exact candidate:** derived from Git at verification time; never hard-coded
**Repository-controlled scope:** documentation, operation inventory and source mapping verified; implementation gaps are reported per module
**External scope:** product execution, deployment, real effects and independent acceptance remain open

## 1. Truth model

The central truth is a closed index. Detailed module roots, ownership, terminal observers, native symbols, delegated callees, tests and external evidence gates live in each module's `IMPLEMENTATION_MAP.json`. This file and `TEST_TRACEABILITY.json` are generated from those maps. A source symbol or fixture is not deployment or external-effect evidence.

## 2. `runtime.supervisor`

Owns generation-fenced process lifecycle, durable bounded restart state and the unified durable release-transition journal; Fleet owns immutable release catalog/allow-revoke admission facts and user-task truth remains outside this module.

The exact process driver, Agentd readiness/drain acknowledgements and current-generation observations establish lifecycle terminality; drain acknowledgement closes admission but never establishes user-task success.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `start_instance` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn start(` |
| `observe_health` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn tick(` |
| `drain` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn drain(` |
| `stop_instance` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn stop(` |
| `kill_instance` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn kill(` |
| `restart_instance` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn restart(` |
| `load_next` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn upgrade(` |
| `rollback_release` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn rollback(` |
| `signed_upgrade` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn apply_production_grant(` |
| `signed_rollback` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn apply_production_grant(` |
| `reconcile_signed_intent` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn resolve_production_recovery(` |

Remaining repository implementation gaps:

- Retained signed history has a bounded fail-closed capacity; export acknowledgement and safe reclamation are not implemented.
- Current exact-head and deterministic-merge executions must pass; source composition alone is not qualification.

External evidence gates:

- exact deployed hepta-supervisord binary, host identity and externally pinned production grant/H7 verifier configuration
- target-host startup, watchdog, typed Agentd drain, bounded restart and signed-recovery crash/fault/latency measurements
- deployment and independent verification of the external release-policy/authority distribution feeding Fleet allow/revoke state and signer rotation
- independent operational acceptance of signed upgrade, rollback and recovery outcomes

## 3. `runtime.fleet`

Owns coherent host enrollment and allocation-lease records; consumers enforce grants locally.

Current-fence reconciliation records the observed holder disposition; pure allocation arithmetic cannot self-attest use.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `admit_host` | `owner_native` | `codex-rs/hepta-fleet/src/lease_ledger.rs` — `pub fn admit_host(` |
| `allocate` | `owner_native` | `codex-rs/hepta-fleet/src/lease_ledger.rs` — `pub fn issue(` |
| `renew_or_revoke` | `owner_native` | `codex-rs/hepta-fleet/src/lease_ledger.rs` — `pub fn renew_or_revoke(` |

Remaining repository implementation gaps:

- Connect the in-memory lease component to supervisor-owned durable FleetRegistry grants, fences, and a real capacity observer.

External evidence gates:

- real enrolled host capacity observation
- non-test local grant enforcement
- partition and lease-expiry target qualification

## 4. `runtime.agentd`

Owns only ephemeral run admission, immutable snapshot references, and runtime-health composition state.

Agentd preserves dispatch-boundary uncertainty and accepts terminal state only from the delegated execution/effect owner.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `compose_runtime` | `owner_native` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` — `pub fn compose_runtime(` |
| `start_run` | `owner_native` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` — `pub fn start_run(` |
| `admit_revalidated_run_start` | `owner_native` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` — `pub(crate) fn start_revalidated_run_start(` |
| `cancel_run` | `owner_native` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` — `pub fn cancel_run(` |
| `attach_context` | `owner_native` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` — `pub fn attach_context(` |
| `daemon_run_lifecycle_control` | `owner_native` | `codex-rs/hepta-agentd/src/state_control.rs` — `crate::AgentdMethod::RunStart` |
| `agentd_neuron_owner` | `owner_native` | `codex-rs/hepta-agentd/src/neuron_runtime.rs` — `pub struct AgentdNeuronOwner` |
| `shared_terminal_cell_train` | `owner_native` | `codex-rs/hepta-agentd/src/shared_terminal_cell.rs` — `pub async fn train(` |
| `shared_terminal_cell_load` | `owner_native` | `codex-rs/hepta-agentd/src/shared_terminal_cell.rs` — `pub async fn load(` |
| `shared_terminal_cell_predict` | `owner_native` | `codex-rs/hepta-agentd/src/shared_terminal_cell.rs` — `pub async fn predict(` |
| `shared_terminal_cell_restore` | `owner_native` | `codex-rs/hepta-agentd/src/shared_terminal_cell.rs` — `pub async fn restore(` |
| `compose_authoritative_owner_inputs` | `owner_native` | `codex-rs/hepta-agentd/src/intelligence_ingress.rs` — `pub fn authoritative_provider<` |

Remaining repository implementation gaps:

- Compose the canonical caller through runtime.codex so physical turn start/interrupt and terminal observations are real invocation edges rather than design-only delegated targets.
- Bind current AuthBus/trust revalidation to the durable RunStartRecordV1 before start_revalidated_run_start; raw journal records are not current authentication evidence. Post-dispatch recovery remains Indeterminate and non-redispatchable.
- Compose AgentdNeuronOwner into the daemon-owned run lifecycle once the canonical runtime.agentd coordinator line converges, with selected-artifact/current inference.control/witness dependencies constructed by the registered owner composition rather than an ambient singleton.
- Provide a repository-shipped authenticated canonical invocation profile and wire the actual Circuit-to-Cell normal daemon consumer. Shared Replay owner tests and cross-process restore do not establish these product paths.

External evidence gates:

- deployed Agentd process and authenticated socket identity
- target-host drain/restart/backpressure measurements
- independent acceptance, promotion and release

## 5. `runtime.codex`

The existing App Server and Codex core remain the sole thread, turn, model, and tool execution spine.

The App Server/client path supplies typed process-local terminal and request-level observations; runtime.codex validates exact correlation. External tool/provider terminality remains with its effect owner and target-host trust is independently qualified.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `open_thread` | `resolved_alias_native` | `codex-rs/app-server/src/request_processors/thread_processor.rs` — `pub(crate) async fn thread_start(` |
| `submit_turn` | `resolved_alias_native` | `codex-rs/app-server/src/request_processors/turn_processor.rs` — `pub(crate) async fn turn_start(` |
| `dispatch_tool` | `owner_boundary` | `codex-rs/app-server/src/request_processors/turn_processor.rs` — `pub(crate) async fn turn_start(` |
| `observe_delivery` | `owner_boundary` | `codex-rs/app-server/src/request_processors/turn_processor.rs` — `pub(crate) async fn turn_start(` |

Remaining repository implementation gaps:

- current runtime.codex exact-head, deterministic synthetic-merge, focused product fault-matrix, and product E2E evidence are pending for this composed candidate

External evidence gates:

- independently operated final-use authority endpoint, signer-key custody, pathname plus connected-peer socket identity, trusted time/revocation distribution, and external anti-rollback recovery for replay/epoch state
- authenticated target-host Agentd/App Server process, generation and socket identity
- real model/provider terminal stream observation under the selected target deployment
- delegated external-tool terminal observation and acknowledgement-loss qualification
- independent policy/evidence for resolving or quarantining indeterminate effects when ephemeral App Server history is unavailable; no unauthenticated manual release
- independent acceptance, activation/canary, promotion and release

## 6. `inference.control`

One retained DurableInferenceControl owns legacy/native records and future-byte liabilities, with a stable writer sidecar across checkpoint replacement; checkpoints retain all identities and unknown-effect responsibilities.

The actual Agent-fenced App Server client supplies matching turn observations through a trusted in-process port. Missing tokens remain null; uncertain execution holds its local slot. This is not provider billing or signed remote-worker authority.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `reserve_request` | `owner_native` | `codex-rs/hepta-infer-core/src/native_control.rs` — `pub fn reserve_native(` |
| `schedule` | `owner_native` | `codex-rs/hepta-infer-core/src/native_control.rs` — `pub fn dispatch_native(` |
| `cancel` | `owner_native` | `codex-rs/hepta-infer-core/src/native_control.rs` — `pub fn cancel_native(` |
| `settle` | `owner_native` | `codex-rs/hepta-infer-core/src/native_control.rs` — `pub fn settle_native(` |
| `compact_journal` | `owner_native` | `codex-rs/hepta-infer-core/src/journal_maintenance.rs` — `pub fn compact_journal(` |
| `journal_capacity_status` | `owner_native` | `codex-rs/hepta-infer-core/src/journal_maintenance.rs` — `pub fn journal_capacity_status(` |

Remaining repository implementation gaps:

- Connect economically meaningful quota and hardware-capacity authorities; the shipped native policy reserves only local in-flight run slots.
- Implement authenticated recovery of actual provider terminal/usage observations after process loss; reopening a dispatched run conservatively holds capacity and never replays it.
- Current-state checkpoints reclaim superseded events; content-addressed external archives, identity garbage collection and trusted backup anti-rollback remain unimplemented.

External evidence gates:

- real provider deployment and crash/cancellation acceptance
- real economic quota/capacity authority integration
- authenticated remote-worker transport if a separate process is introduced

## 7. `inference.worker`

Owns live provider client handles; persistent request/slot/observation facts remain in the inference.control journal. App Server owns ephemeral thread execution; artifact/cache owners retain model bytes.

The hosted native-app-server profile observes real matching turn events; the local manifest driver remains injected and does not prove physical weights/device behavior.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `load_model` | `owner_native` | `codex-rs/hepta-infer-worker-host/src/model_worker.rs` — `pub fn load_model(` |
| `run` | `owner_native` | `codex-rs/hepta-infer-worker-host/src/native_run_control.rs` — `pub async fn run(` |
| `unload` | `owner_native` | `codex-rs/hepta-infer-worker-host/src/model_worker.rs` — `pub fn unload_model(` |

Remaining repository implementation gaps:

- Implement a local model driver that acquires and proves actual weights, device and memory grants before claiming isolated local inference.
- Implement trusted provider reconciliation for dispatch-unknown/reopened runs and later missing token usage; do not infer zero usage or safe replay from transport loss.

External evidence gates:

- identified real weights/tokenizer/runtime/device
- isolated deployed worker process and authenticated control channel
- OOM/device-reset/load-kill target qualification

## 8. `automation.taskflow`

Owns durable legacy and Calendar V2 schedule revisions, deterministic occurrence identity, claim, TaskFlow run/step orchestration, provider-attempt/reconciliation evidence, and terminal occurrence projection without owning downstream domain effects.

Agentd observes the existing App Server persisted-turn terminal state for Codex activity; registered external effect owners supply their own terminal/reconciliation receipts through the final-use-authorized durable step seam.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `register_schedule` | `owner_native` | `codex-rs/hepta-automation/src/schedule_v2.rs` — `pub async fn create_calendar_task_v2(` |
| `materialize_due` | `owner_native` | `codex-rs/hepta-automation/src/scheduler.rs` — `pub async fn tick(` |
| `claim_occurrence` | `owner_native` | `codex-rs/hepta-automation/src/lifecycle.rs` — `pub async fn materialize_occurrence(` |
| `execute_step` | `owner_native` | `codex-rs/hepta-automation/src/authorized_effect.rs` — `pub async fn execute_authorized_taskflow_effect` |

External evidence gates:

- selected-host Agentd/App Server execution receipt for the composed durable causal path
- independently provisioned FinalUseAuthority signer/verifying-key/revocation-head configuration plus a concrete attested downstream effect provider and trusted terminal/reconciliation evidence for every activated external effect
- real IANA timezone-profile provenance/tzdb refresh plus DST and multi-scheduler target qualification
- independent acceptance, activation, promotion and release evidence

## 9. `channel.matrix`

Owns Matrix ingress projection, sync frontier, dispatch ledger, outbox, and transaction identities.

A homeserver event observation settles send terminality; App Server turn completion and HTTP acceptance cannot substitute.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `admit_event` | `owner_native` | `codex-rs/hepta-matrixd/src/runtime.rs` — `pub async fn process_event(` |
| `prepare_send` | `owner_native` | `codex-rs/hepta-matrixd/src/send_observer.rs` — `pub fn prepare_send(` |
| `observe_send` | `owner_native` | `codex-rs/hepta-matrixd/src/send_observer.rs` — `pub fn observe_send(` |

Remaining repository implementation gaps:

- Integrate any new send-observer state with the existing MatrixDurableStore transaction identity; the component alone is not a second durable sender.

External evidence gates:

- real enrolled homeserver/user/device/encryption identity
- live sync and send transport callsites
- rate-limit/reconnect/redaction/restore target qualification

## 10. `browser.servo`

Owns in-process profile/session/page/operation state around an injected browser driver; raw credentials remain external references.

The driver must supply process, page, action, and reconciliation observations; unit tests use deterministic fake drivers.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `open_profile` | `owner_boundary` | `apps/hepta-browser/src/runtime.js` — `async openProfile(` |
| `observe_page` | `owner_boundary` | `apps/hepta-browser/src/runtime.js` — `async observePage(` |
| `navigate_or_act` | `owner_boundary` | `apps/hepta-browser/src/runtime.js` — `async navigateOrAct(` |

External evidence gates:

- reproducible Servo binary and patch digest
- OS sandbox/profile/credential/network enforcement
- real navigation/download/business terminal observation

## 11. `ui.control`

Owns presentation/session state and pending request identities only; backend modules retain authority and durable facts.

The authenticated backend observation establishes terminal state; local acknowledgement or disconnect never does.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `read_view` | `owner_boundary` | `apps/hepta-control-ui/src/runtime-client.js` — `readView()` |
| `submit_request` | `owner_boundary` | `apps/hepta-control-ui/src/runtime-client.js` — `async submitRequest(` |
| `request_stop` | `owner_boundary` | `apps/hepta-control-ui/src/runtime-client.js` — `async requestStop(` |

External evidence gates:

- selected Web framework/build artifact and browser support matrix
- deployed authentication/CSP/CSRF/WebSocket topology
- end-to-end accessibility and backend deployment qualification

## 12. `ui.native`

Owns shell/window/session state and opaque platform references; domain facts and secrets remain with their owners.

The backend, platform permission adapter, and updater each supply their own observations; the shell cannot self-issue success.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `connect_runtime` | `owner_boundary` | `apps/hepta-native/src/shell-runtime.js` — `async connectRuntime(` |
| `render_runtime_view` | `owner_boundary` | `apps/hepta-native/src/shell-runtime.js` — `renderRuntimeView(` |
| `request_platform_capability` | `owner_boundary` | `apps/hepta-native/src/shell-runtime.js` — `async requestPlatformCapability(` |
| `apply_shell_update` | `owner_boundary` | `apps/hepta-native/src/shell-runtime.js` — `async applyShellUpdate(` |

External evidence gates:

- selected native framework and supported platform matrix
- real code signing/notarization/keychain and updater trust roots
- packaged crash/restart/accessibility/update rollback qualification

## 13. Cross-module acceptance boundary

All 56 operations require an owner entrypoint, build target and test path. Owner entrypoints remain inside owner roots; delegated callees name their real owner. Exact-head and deterministic synthetic-merge validation must agree with all eleven maps and generated projections.

Repository source closure does not self-issue real model/provider execution, Servo or Matrix effects, deployed Web/native artifacts, target-host measurements, hardware evidence, external-owner consent, independent acceptance, selection, promotion or release.
