# Lane B source contracts and implementation gaps

**Lane:** `LANE-B-RUNTIME`
**Immutable source base:** `f278a89eea18fccb6d37b876aa5679863a64139d` / tree `5baa144717d4b3e3c596501fb56ce911d009e728`
**Exact candidate:** derived from Git at verification time; never hard-coded
**Repository-controlled scope:** documentation, operation inventory and source mapping verified; implementation gaps are reported per module
**External scope:** product execution, deployment, real effects and independent acceptance remain open

## 1. Truth model

The central truth is a closed index. Detailed module roots, ownership, terminal observers, native symbols, delegated callees, tests and external evidence gates live in each module's `IMPLEMENTATION_MAP.json`. This file and `TEST_TRACEABILITY.json` are generated from those maps. A source symbol or fixture is not deployment or external-effect evidence.

## 2. `runtime.supervisor`

Owns generation-fenced process lifecycle and release transition records; user-task truth remains outside this module.

The process driver and current-generation health observations establish process terminality, not user-task success.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `start_instance` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn start(` |
| `observe_health` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn tick(` |
| `drain` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn drain(` |
| `load_next` | `owner_native` | `codex-rs/hepta-supervisor/src/supervisor.rs` — `pub fn upgrade(` |

External evidence gates:

- deployed binary and host identity
- target-host watchdog/start/drain measurements
- independent operational acceptance

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
| `cancel_run` | `owner_native` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` — `pub fn cancel_run(` |
| `attach_context` | `owner_native` | `codex-rs/hepta-agentd/src/lane_b_runtime.rs` — `pub fn attach_context(` |

External evidence gates:

- deployed Agentd process and authenticated socket identity
- non-test caller through the full Codex turn path
- target backpressure/restart measurements

## 5. `runtime.codex`

The existing App Server and Codex core remain the sole thread, turn, model, and tool execution spine.

The App Server observes admission and streaming state; external tool/provider terminality remains with its effect owner.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `open_thread` | `resolved_alias_native` | `codex-rs/app-server/src/request_processors/thread_processor.rs` — `pub(crate) async fn thread_start(` |
| `submit_turn` | `resolved_alias_native` | `codex-rs/app-server/src/request_processors/turn_processor.rs` — `pub(crate) async fn turn_start(` |
| `dispatch_tool` | `resolved_alias_native` | `codex-rs/core/src/tools/router.rs` — `pub async fn dispatch_tool_call_with_code_mode_result(` |
| `observe_delivery` | `resolved_alias_native` | `codex-rs/core/src/codex_thread.rs` — `pub(crate) async fn submit_turn_input_and_wait_for_exact_admission(` |

External evidence gates:

- named deployed Agentd caller identity
- real model/provider stream observation
- real tool terminal observation and acknowledgement-loss qualification

## 6. `inference.control`

The same single-writer DurableInferenceControl journal owns legacy records and native hosted request identity, local in-flight slot reservations, dispatch bindings and observations.

The actual Agent-fenced App Server client supplies matching turn observations through a trusted in-process port. Missing tokens remain null; uncertain execution holds its local slot. This is not provider billing or signed remote-worker authority.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `reserve_request` | `owner_native` | `codex-rs/hepta-infer-core/src/native_control.rs` — `pub fn reserve_native(` |
| `schedule` | `owner_native` | `codex-rs/hepta-infer-core/src/native_control.rs` — `pub fn dispatch_native(` |
| `cancel` | `owner_native` | `codex-rs/hepta-infer-core/src/native_control.rs` — `pub fn cancel_native(` |
| `settle` | `owner_native` | `codex-rs/hepta-infer-core/src/native_control.rs` — `pub fn settle_native(` |

Remaining repository implementation gaps:

- Connect economically meaningful quota and hardware-capacity authorities; the shipped native policy reserves only local in-flight run slots.
- Implement authenticated recovery of actual provider terminal/usage observations after process loss; reopening a dispatched run conservatively holds capacity and never replays it.
- Add bounded archival/retention under the same journal owner; the current 64 MiB journal rejects further appends without truncating acknowledged history.

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

Owns schedule, occurrence, claim, and step-orchestration facts without owning downstream domain effects.

The registered effect driver supplies terminal observations; unknown effects block dependent steps and compensation is separately authorized.

| Operation | Class | Owner entrypoint |
|---|---|---|
| `register_schedule` | `owner_native` | `codex-rs/hepta-automation/src/store.rs` — `pub async fn create_task(` |
| `materialize_due` | `owner_native` | `codex-rs/hepta-automation/src/scheduler.rs` — `pub async fn tick(` |
| `claim_occurrence` | `owner_native` | `codex-rs/hepta-automation/src/effect_executor.rs` — `pub fn claim_occurrence(` |
| `execute_step` | `owner_native` | `codex-rs/hepta-automation/src/effect_executor.rs` — `pub fn execute_step(` |

Remaining repository implementation gaps:

- Connect the effect-executor component to the existing durable TaskFlow step outbox and a real final-use authorized effect provider.
- Implement post-crash effect reconciliation before permitting dependent steps.

External evidence gates:

- non-test Codex/App Server caller
- real downstream effect owner and terminal observer
- DST/timezone-database and multi-scheduler target qualification

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

All 39 operations require an owner entrypoint, build target and test path. Owner entrypoints remain inside owner roots; delegated callees name their real owner. Exact-head and deterministic synthetic-merge validation must agree with all eleven maps and generated projections.

Repository source closure does not self-issue real model/provider execution, Servo or Matrix effects, deployed Web/native artifacts, target-host measurements, hardware evidence, external-owner consent, independent acceptance, selection, promotion or release.
