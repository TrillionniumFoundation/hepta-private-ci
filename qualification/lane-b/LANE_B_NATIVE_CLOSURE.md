# Lane B native implementation closure

Base: `f278a89eea18fccb6d37b876aa5679863a64139d` / tree `5baa144717d4b3e3c596501fb56ce911d009e728`

Candidate branch: `codex/hepta-lane-b-truth-runtime-closure-20260911`

Truth-index SHA-256: `64c6af0c546fdde6b366be6462613384c62b83a915e2bf28691689b19a5fb0fb`

## 1. Review and state model

All 39 design operations have exact repository source anchors. Detailed topology, state, linearization, recovery, security, capacity and terminal-observer contracts are canonical in each module `IMPLEMENTATION_MAP.json`. Delegated callees are separate from owner entrypoints. Repository closure does not prove deployment or external effects.

## 2. `runtime.supervisor`

Owner/deputy: `runtime-control` / `fleet-runtime`. Maturity: `native_lifecycle_runtime`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `start_instance` | `codex-rs/hepta-supervisor/src/supervisor.rs` → `pub fn start(` | none | `SUP-01`, `SUP-03` |
| `observe_health` | `codex-rs/hepta-supervisor/src/supervisor.rs` → `pub fn tick(` | none | `SUP-01`, `SUP-02` |
| `drain` | `codex-rs/hepta-supervisor/src/supervisor.rs` → `pub fn drain(` | none | `SUP-03` |
| `load_next` | `codex-rs/hepta-supervisor/src/supervisor.rs` → `pub fn upgrade(` | none | `SUP-04` |

Separately governed evidence: deployed binary/configuration identity and target-host watchdog measurements; independent operator acceptance of restart, upgrade and rollback behavior.

## 3. `runtime.fleet`

Owner/deputy: `fleet-runtime` / `runtime-control`. Maturity: `lease_runtime_boundary`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `admit_host` | `codex-rs/hepta-fleet/src/bin/hepta-fleet-leased.rs` → `pub fn admit_host(` | none | `FLEET-02`, `FLEET-04` |
| `allocate` | `codex-rs/hepta-fleet/src/bin/hepta-fleet-leased.rs` → `pub fn issue(` | none | `FLEET-01`, `FLEET-03` |
| `renew_or_revoke` | `codex-rs/hepta-fleet/src/bin/hepta-fleet-leased.rs` → `pub fn renew_or_revoke(` | none | `FLEET-02`, `FLEET-04` |

Separately governed evidence: target-host capacity freshness, physical lease-store selection and local grant enforcement; partition and uncertain-holder reconciliation on the deployed fleet.

## 4. `runtime.agentd`

Owner/deputy: `agent-runtime` / `runtime-control`. Maturity: `delegating_composition_runtime`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `compose_runtime` | `codex-rs/hepta-agentd/src/app_runtime.rs` → `pub(crate) async fn run_app_server(` | none | `AGENT-02`, `AGENT-04` |
| `start_run` | `codex-rs/hepta-agentd/src/app_runtime.rs` → `pub(crate) async fn run_app_server(` | `runtime.codex`: `codex-rs/app-server/src/request_processors/turn_processor.rs` → `pub(crate) async fn turn_start(` | `AGENT-01`, `AGENT-02` |
| `cancel_run` | `codex-rs/hepta-agentd/src/app_runtime.rs` → `pub(crate) async fn run_app_server(` | `runtime.codex`: `codex-rs/app-server/src/request_processors/turn_processor.rs` → `pub(crate) async fn turn_interrupt(` | `AGENT-03` |
| `attach_context` | `codex-rs/hepta-agentd/src/app_runtime.rs` → `pub(crate) async fn run_app_server(` | `runtime.codex`: `codex-rs/core/src/codex_thread.rs` → `pub(crate) async fn submit_turn_input_and_wait_for_exact_admission(` | `AGENT-01`, `AGENT-04` |

Separately governed evidence: deployed Agentd process/socket peer identity and non-test session consumer; target-process backpressure, cancellation acknowledgement and restart qualification.

## 5. `runtime.codex`

Owner/deputy: `codex-integration` / `agent-runtime`. Maturity: `native_execution_spine`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `open_thread` | `codex-rs/app-server/src/request_processors/thread_processor.rs` → `pub(crate) async fn thread_start(` | none | `CODEX-03` |
| `submit_turn` | `codex-rs/app-server/src/request_processors/turn_processor.rs` → `pub(crate) async fn turn_start(` | none | `CODEX-01`, `CODEX-03` |
| `dispatch_tool` | `codex-rs/core/src/tools/router.rs` → `pub async fn dispatch_tool_call_with_code_mode_result(` | none | `CODEX-02`, `CODEX-04` |
| `observe_delivery` | `codex-rs/core/src/codex_thread.rs` → `pub(crate) async fn submit_turn_input_and_wait_for_exact_admission(` | none | `CODEX-01`, `CODEX-04` |

Separately governed evidence: real model/provider stream identity and terminal observation; deployed Agentd-to-App-Server trace and external tool terminality.

## 6. `inference.control`

Owner/deputy: `inference-platform` / `runtime-control`. Maturity: `durable_control_runtime`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `reserve_request` | `codex-rs/hepta-infer-core/src/bin/hepta-infer-control.rs` → `pub fn reserve(` | none | `INFER-01`, `INFER-02` |
| `schedule` | `codex-rs/hepta-infer-core/src/bin/hepta-infer-control.rs` → `pub fn assign(` | none | `INFER-01`, `INFER-04` |
| `cancel` | `codex-rs/hepta-infer-core/src/bin/hepta-infer-control.rs` → `pub fn cancel(` | none | `INFER-03` |
| `settle` | `codex-rs/hepta-infer-core/src/bin/hepta-infer-control.rs` → `pub fn settle(` | none | `INFER-03`, `INFER-04` |

Separately governed evidence: deployed worker discovery, quota owner and provider/device observation; target-host persistence path, performance and recovery qualification.

## 7. `inference.worker`

Owner/deputy: `inference-platform` / `security-authority`. Maturity: `isolated_worker_boundary`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `load_model` | `codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs` → `pub fn load_model(` | none | `WORKER-01`, `WORKER-02`, `WORKER-03` |
| `run` | `codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs` → `pub fn run(` | none | `WORKER-01`, `WORKER-02`, `WORKER-04` |
| `unload` | `codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs` → `pub fn unload_model(` | none | `WORKER-03` |

Separately governed evidence: qualified real model driver with exact weights/runtime/device identity; authenticated control transport, OOM/device-reset and target-host measurements.

## 8. `automation.taskflow`

Owner/deputy: `automation-platform` / `agent-runtime`. Maturity: `durable_fenced_orchestrator`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `register_schedule` | `codex-rs/hepta-automation/src/taskflow.rs` → `pub async fn register_taskflow_definition(` | none | `FLOW-01` |
| `materialize_due` | `codex-rs/hepta-automation/src/scheduler.rs` → `pub async fn tick(` | none | `FLOW-01` |
| `claim_occurrence` | `codex-rs/hepta-automation/src/bin/hepta-taskflow-runtime.rs` → `pub fn claim_occurrence(` | none | `FLOW-02` |
| `execute_step` | `codex-rs/hepta-automation/src/bin/hepta-taskflow-runtime.rs` → `pub fn execute_step(` | none | `FLOW-03`, `FLOW-04` |

Separately governed evidence: deployed App Server/effect adapter callsite and trusted external terminal observer; target scheduler timezone database, DST, crash-reopen and compensation qualification.

## 9. `channel.matrix`

Owner/deputy: `channels-platform` / `security-authority`. Maturity: `durable_channel_boundary`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `admit_event` | `codex-rs/hepta-matrixd/src/runtime.rs` → `pub async fn process_event(` | none | `MATRIX-01`, `MATRIX-04` |
| `prepare_send` | `codex-rs/hepta-matrixd/src/bin/hepta-matrix-send-observer.rs` → `pub fn prepare_send(` | none | `MATRIX-02`, `MATRIX-03` |
| `observe_send` | `codex-rs/hepta-matrixd/src/bin/hepta-matrix-send-observer.rs` → `pub fn observe_send(` | none | `MATRIX-03`, `MATRIX-04` |

Separately governed evidence: real homeserver transport, authenticated encryption/device session and server-event observation; target reconnect, pagination, rate-limit, media, redaction and restore qualification.

## 10. `browser.servo`

Owner/deputy: `browser-platform` / `security-authority`. Maturity: `profile_and_effect_boundary`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `open_profile` | `apps/hepta-browser/src/runtime.js` → `async openProfile(` | none | `BROWSER-02`, `BROWSER-03` |
| `observe_page` | `apps/hepta-browser/src/runtime.js` → `async observePage(` | none | `BROWSER-01`, `BROWSER-02` |
| `navigate_or_act` | `apps/hepta-browser/src/runtime.js` → `async navigateOrAct(` | none | `BROWSER-01`, `BROWSER-04` |

Separately governed evidence: reproducible Servo binary, isolated process driver and exact patch/build identity; target browser sandbox, DNS/redirect/download/credential policy and remote outcome qualification.

## 11. `ui.control`

Owner/deputy: `ui-platform` / `accessibility`. Maturity: `authenticated_web_runtime_client`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `read_view` | `apps/hepta-control-ui/src/runtime-client.js` → `readView()` | none | `UI-01`, `UI-04` |
| `submit_request` | `apps/hepta-control-ui/src/runtime-client.js` → `async submitRequest(` | none | `UI-02`, `UI-03` |
| `request_stop` | `apps/hepta-control-ui/src/runtime-client.js` → `async requestStop(` | none | `UI-01`, `UI-04` |

Separately governed evidence: selected Web framework/build artifact, deployed authenticated transport, CSP/CSRF and browser support matrix; target accessibility, screen-reader, keyboard, reconnect and backend E2E qualification.

## 12. `ui.native`

Owner/deputy: `ui-platform` / `accessibility`. Maturity: `native_shell_runtime_boundary`. Repository-controlled gaps: **none**.

| Operation | Owner entrypoint | Delegated callee | Tests |
|---|---|---|---|
| `connect_runtime` | `apps/hepta-native/src/shell-runtime.js` → `async connectRuntime(` | none | `NATIVE-01`, `NATIVE-03` |
| `render_runtime_view` | `apps/hepta-native/src/shell-runtime.js` → `renderRuntimeView(` | none | `NATIVE-01`, `NATIVE-03` |
| `request_platform_capability` | `apps/hepta-native/src/shell-runtime.js` → `async requestPlatformCapability(` | none | `NATIVE-02`, `NATIVE-03` |
| `apply_shell_update` | `apps/hepta-native/src/shell-runtime.js` → `async applyShellUpdate(` | none | `NATIVE-04` |

Separately governed evidence: selected native framework, signed/notarized packages, secure storage and supported OS/architecture matrix; target OS permission, accessibility, crash/restart and updater rollback qualification.

## 13. Cross-module closure conditions

The v3 verifier rejects a missing module or operation, owner-root or delegated-root escape, duplicate source anchor, test-only mapping, untraced acceptance case, stale companion, open repository-controlled gap, unsafe workflow or unsupported external positive claim.

All nine `RDY-EXT-*` gates remain open, fail-closed and non-self-certifiable.
