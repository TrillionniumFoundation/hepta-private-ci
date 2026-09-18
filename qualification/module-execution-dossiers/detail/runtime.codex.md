# runtime.codex: implementation design

Parent: `docs/modules/runtime.codex/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: the repository-controlled Codex App Server execution boundary is source-composed through the native worker host, typed receipt adapter and durable reconciliation journal; target-host execution evidence, delegated external-tool terminality and independent acceptance remain open in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/codex-app-server`, `codex-rs/hepta-codex-adapter`.
Packages: `P0.7B-B1B-MODEL-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`open_thread(authenticated_session, schema_version) -> ThreadHandle`; `submit_turn(thread, context_attachment, objective) -> TurnHandle`; `dispatch_tool(turn, final_call, verified_use) -> DispatchObservation`; `observe_delivery(turn, compiled_payload_digest) -> PromptDeliveryObservationV1`. Preserve the existing app-server protocol; model requests and tool calls are traced to this single high-level spine.

## 3. State records and transaction design

`thread_session` owns thread/turn identities, principal scope, selected model/runtime tuple, context digest, tool-schema digest, lifecycle and sequence. External effect outcomes remain with their observing adapters/operation ledger. Session event persistence must retain exact attachment/delivery links without copying secrets or unrestricted model payloads into general learning receipts.

## 4. Deterministic algorithm and scheduling

Validate thread generation and frozen objective; revalidate context evidence at physical request assembly; bind the actual template/tokenizer/tool schema; record delivery only when the exact payload is submitted; run model calls through governed inference; final-check tool authority and payload immediately before adapter entry. Provider timeout or lost acknowledgement is not automatically a safe retry.

## 5. Capacity and performance profile

Pilot turn attachment and output bounds follow the selected model/context profile; tool calls <= 128 candidates per boundary and dispatch concurrency is explicitly reserved. Measure template assembly, provider queue, first/last token and terminal-tool latency separately.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- CODEX-01: compiled-but-undelivered prompt cannot receive delivered-intervention credit.
- CODEX-02: payload changed after authorization is rejected at the effect gate.
- CODEX-03: unknown session/model/schema generation does not fall back to an ambient default.
- CODEX-04: acknowledgement loss keeps the operation indeterminate and does not create a duplicate model/tool effect.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Boundary tests must use a named app-server caller, not only the adapter library. Preserve dependency inversion: the upstream execution spine consumes contracts rather than Hepta domain-store implementations. Rollback preserves thread compatibility and pending effect reconciliation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `thread_start` in [codex-rs/app-server/src/request_processors/thread_processor.rs](../../../codex-rs/app-server/src/request_processors/thread_processor.rs); `turn_start` in [codex-rs/app-server/src/request_processors/turn_processor.rs](../../../codex-rs/app-server/src/request_processors/turn_processor.rs); typed `adapt`/observation constructors in [codex-rs/hepta-codex-adapter/src/lib.rs](../../../codex-rs/hepta-codex-adapter/src/lib.rs); the named caller `run_once` and reconciler `reconcile_existing` in [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs).
- **Terminal semantics and correlation:** `TurnStatus::Completed`, `Failed` and `Interrupted` map to distinct adapter statuses. Observations bind the exact request digest and validate thread/turn identity; the request digest binds operation, Agent/App Server session, thread, method, payload, owner generation, protocol v2 and deadline. Request-level rejection, overload, timeout, transport loss and unknown decode outcomes preserve separate retry/reconciliation postures.
- **State and recovery:** App Server remains the real thread/turn execution owner. `DurableInferenceControl` journals the exact session/thread/request binding before `turn/start`, persists returned turn identity, holds capacity for unknown effects, and rejects blind replay. A reopened uncertain request uses `thread/read(includeTurns=true)` and the stable `client_user_message_id` to reconcile the original turn; missing ephemeral App Server history remains indeterminate rather than inferred not-applied.
- **Witness boundary:** production construction consumes typed App Server protocol outcomes through the bounded local client, and `AppServerObservation` fields are private. This is a source/type trust boundary, not cryptographic process attestation; target-host qualification must still establish the authenticated Agentd/App Server process/socket and exact generation.
- **Authority ceiling:** adapter receipts remain `DENY_ALL` and do not mint model/provider/tool authority. Final-use authority, revocation and delegated external-tool terminality remain with their owning contracts/effect owners.
- **Source tests:** [codex-rs/hepta-codex-adapter/src/lib_tests.rs](../../../codex-rs/hepta-codex-adapter/src/lib_tests.rs), [codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs](../../../codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs), [codex-rs/hepta-infer-core/src/native_control_tests.rs](../../../codex-rs/hepta-infer-core/src/native_control_tests.rs), and the native worker-host tests. These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/modules/runtime.codex/IMPLEMENTATION_MAP.json](../../../docs/modules/runtime.codex/IMPLEMENTATION_MAP.json), [docs/modules/runtime.codex/FAULT_MATRIX.md](../../../docs/modules/runtime.codex/FAULT_MATRIX.md), [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), and [codex-rs/app-server/README.md](../../../codex-rs/app-server/README.md).
- **Remaining repository-controlled work:** compose `kernel.authority` final-use admission into the native caller so a non-constructible `VerifiedUseToken` (or its canonical one-entry consumption boundary) is consumed immediately before `turn/start`, with its signed binding covering the exact final `TurnStart` payload including runtime-selected model and compiled additional context. The current equal `payload_digest` / `lease_payload_digest` fields are a local consistency check, not authority authentication.
- **Remaining qualification work:** obtain current exact-head and merge-candidate CI receipts; execute/qualify the named caller against the authenticated target-host Agentd/App Server and real provider stream; qualify delegated external-tool terminal observation and acknowledgement-loss behavior; complete independent acceptance, activation/canary, promotion and release gates. Repository source must not self-certify those external facts.
