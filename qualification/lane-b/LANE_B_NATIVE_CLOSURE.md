# Lane B native implementation closure status

**Lane:** `LANE-B-RUNTIME`  
**Lineage anchor:** `f278a89eea18fccb6d37b876aa5679863a64139d` / tree `5baa144717d4b3e3c596501fb56ce911d009e728`  
**Exact candidate:** the clean Git `HEAD` checked by CI; no document embeds its own future commit hash  
**Machine truth:** `qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json`  
**Test traceability:** `qualification/lane-b/LANE_B_TEST_TRACEABILITY.json`  
**Status:** repository-controlled mapping and documentation gaps closed; deployment and independent external evidence remain open

## 1. Review model

The machine truth is authoritative for module ownership, implementation roots, operation state, native source anchors, delegation, build targets, test identifiers and residual gate class. This Markdown is a generated projection. Each module-specific `IMPLEMENTATION_MAP.json` carries the exact source and test mapping; canonical `TECHNICAL.md` and execution dossiers retain target semantics.

`implemented` means the repository-controlled operation has a current native boundary and executable test surface. `implemented_partial` means a real implementation exists but target deployment or part of the product path remains external. `delegated_partial` means the module deliberately calls another registered owner instead of duplicating it. None of these states proves a remote effect, real model/device execution, deployed UI, target-host timing or independent acceptance.

## 2. Closed repository-controlled surface

- Modules: **11**; design operations: **39**.
- `implemented`: **26**; `implemented_partial`: **10**; `delegated_partial`: **3**.
- `planned`, unclassified and source-inventing operations: **0**.
- Every operation has a source/delegation disposition, build target and test IDs; every module has a generated implementation map.

## 3. Module closure matrix

| Module | Maturity | Operation disposition | Current repository boundary |
|---|---|---|---|
| `runtime.supervisor` | `partial_runtime` | `start_instance`=implemented_partial, `observe_health`=implemented_partial, `drain`=implemented, `load_next`=implemented_partial | Supervisor lifecycle transitions, generation fencing, start, drain, upgrade and rollback are present in the native owner root. |
| `runtime.fleet` | `lease_runtime` | `admit_host`=implemented, `allocate`=implemented, `renew_or_revoke`=implemented | The repository implements host admission, deterministic allocation, capacity-conserving grants and generation-fenced renewal or revocation. |
| `runtime.agentd` | `composition_runtime` | `compose_runtime`=implemented_partial, `start_run`=delegated_partial, `cancel_run`=delegated_partial, `attach_context`=delegated_partial | Agentd is a thin process and transport composition owner. It does not duplicate thread, turn, memory or effect ownership. |
| `runtime.codex` | `execution_spine` | `open_thread`=implemented, `submit_turn`=implemented_partial, `dispatch_tool`=implemented_partial, `observe_delivery`=implemented_partial | The existing App Server and Codex core remain the sole thread, turn, model-call and tool-execution spine. |
| `inference.control` | `durable_control_runtime` | `reserve_request`=implemented, `schedule`=implemented, `cancel`=implemented, `settle`=implemented | A bounded append journal with reopen owns submit, reserve, assignment, cancellation and settlement state. |
| `inference.worker` | `worker_runtime_boundary` | `load_model`=implemented, `run`=implemented, `unload`=implemented | The worker boundary implements model manifest admission, resource-bounded load, execution, cancellation semantics and unload. |
| `automation.taskflow` | `fenced_execution_runtime` | `register_schedule`=implemented_partial, `materialize_due`=implemented_partial, `claim_occurrence`=implemented, `execute_step`=implemented | Schedule identity, occurrence fencing and a bounded step executor are present without taking ownership of downstream effects. |
| `channel.matrix` | `matrix_runtime_boundary` | `admit_event`=implemented_partial, `prepare_send`=implemented, `observe_send`=implemented | The Matrix runtime owns durable ingress and a bounded send-observation state machine with transaction identity and redaction. |
| `browser.servo` | `profile_runtime_boundary` | `open_profile`=implemented, `observe_page`=implemented, `navigate_or_act`=implemented | The browser host boundary implements isolated profile identity, generation-bound observations, effect grants and reconciliation. |
| `ui.control` | `authenticated_runtime_client` | `read_view`=implemented, `submit_request`=implemented, `request_stop`=implemented | The Web runtime client authenticates a protocol generation, rejects stale views and bounds pending operation identities. |
| `ui.native` | `native_shell_runtime_boundary` | `connect_runtime`=implemented, `render_runtime_view`=implemented, `request_platform_capability`=implemented, `apply_shell_update`=implemented | The native shell boundary binds authenticated runtime sessions, coherent views, narrow OS permissions and selected updates. |

## 4. Module maps and remaining external gates

### `runtime.supervisor`

Implementation map: `docs/modules/runtime.supervisor/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: Process and health terminality are owner-local. User-task and external-effect terminality remain with their respective owners.

- `external_evidence` — Publish exact deployed binary, configuration, operator control endpoint and peer identity.
- `external_evidence` — Execute restart, watchdog, drain, upgrade and rollback qualification on every supported target host.

### `runtime.fleet`

Implementation map: `docs/modules/runtime.fleet/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: Lease receipts are repository-owned facts; real capacity freshness, resource possession and host enforcement require target observations.

- `external_evidence` — Bind authenticated real-host capacity observations and local enforcement receipts.
- `external_evidence` — Qualify partitions, uncertain holders, lease expiry and rollback drain on deployed hosts.

### `runtime.agentd`

Implementation map: `docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: The delegated App Server and Codex core own turn admission and interruption; a deployed Agentd trace remains required.

- `external_evidence` — Publish deployed Agentd process tree, local transport, peer authentication and configuration identity.
- `external_evidence` — Execute backpressure, cancellation acknowledgement, socket failure and restart qualification on target platforms.

### `runtime.codex`

Implementation map: `docs/modules/runtime.codex/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: Turn admission is native; provider delivery and irreversible external tool effects remain separate terminal observations.

- `external_evidence` — Capture a deployed Agentd-to-App-Server trace binding objective, context, model and tool schema generations.
- `external_evidence` — Qualify real model streaming, cancellation, tool terminality and acknowledgement loss.

### `inference.control`

Implementation map: `docs/modules/inference.control/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: Settlement consumes a validated worker observation but cannot self-certify a real provider, weights or device.

- `external_evidence` — Bind deployed worker discovery, quota owner, dispatch transport and reconciliation.
- `external_evidence` — Attach real provider and device terminal observations with measured usage.

### `inference.worker`

Implementation map: `docs/modules/inference.worker/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: A ModelDriver supplies observations; a real weights/runtime/device implementation is an external qualification item.

- `external_evidence` — Bind a separately qualified real model driver, exact weights, tokenizer, runtime and device.
- `external_evidence` — Qualify authenticated worker transport, OOM, device reset, process kill and target-host resource measurements.

### `automation.taskflow`

Implementation map: `docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: Unknown effects remain indeterminate; compensation and terminal effect truth belong to downstream effect owners.

- `external_evidence` — Bind the deployed App Server admission seam and effect adapter caller.
- `external_evidence` — Qualify timezone database revisions, DST, crash-reopen, partial compensation and target scheduler measurements.

### `channel.matrix`

Implementation map: `docs/modules/channel.matrix/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: Only a matching homeserver observation can settle a send; repository fixtures cannot self-issue that remote fact.

- `external_evidence` — Bind a real homeserver transport, enrolled user/device/room scope and encryption session.
- `external_evidence` — Qualify pagination, reconnect, rate limits, redaction, backup restore and server acknowledgement loss.

### `browser.servo`

Implementation map: `docs/modules/browser.servo/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: The injected driver may report indeterminate state; a reproducible Servo process and remote business outcome remain external.

- `external_evidence` — Produce a reproducible deployed Servo binary and authenticated Agentd IPC driver.
- `external_evidence` — Qualify network, redirects, downloads, uploads, credentials, profile isolation, crashes and remote terminal outcomes.

### `ui.control`

Implementation map: `docs/modules/ui.control/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: Backend observations are reconciled without granting the UI terminal or effect authority.

- `external_evidence` — Bind a deployed Web build, framework, browser support matrix, authenticated transport and backend endpoint.
- `external_evidence` — Run accessibility, CSP/CSRF/XSS, reconnect and end-to-end target-browser qualification.

### `ui.native`

Implementation map: `docs/modules/ui.native/IMPLEMENTATION_MAP.json`.

Terminal observer boundary: Platform and updater observations remain injected boundaries until a signed deployed application is qualified.

- `external_evidence` — Bind signed Windows, macOS and Linux application packages, secure storage and authenticated IPC.
- `external_evidence` — Qualify OS permission revocation, accessibility, crash recovery, updater signing and rollback on target hosts.

## 5. Cross-module closure rule

Repository-controlled closure requires all 39 operations to be present, every owner entrypoint to resolve inside its registered implementation roots, every delegated callee to name a registered module and real source symbol, every operation to match test traceability, every per-module map to equal its machine projection, and exact-head plus deterministic synthetic-merge governance checks to pass.

Agentd delegation is intentionally represented separately from Codex implementation. Canonical owner roots are not widened merely because Agentd embeds App Server or because the Codex alias resolves to the existing `app-server` and `core` implementation roots.

## 6. External gates retained

The repository does not self-certify deployed Supervisor/Agentd identities, real host capacity, real provider/model/device use, Matrix homeserver delivery, Servo network effects, deployed Web/native applications, target-host performance or faults, hardware safety, future-window efficacy, operator acceptance, signing, selection, promotion or release. These remain explicit external evidence rather than hidden repository blockers.

## 7. Verification

```bash
python3 scripts/hepta-lane-b-truth.py self-test
python3 -m unittest scripts/test_hepta_lane_b_truth.py
python3 scripts/hepta-lane-b-truth.py verify
python3 scripts/hepta-lane-b-docs.py verify
```

The commands verify repository structure and mappings at one clean candidate; they issue no external authority.
