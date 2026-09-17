# runtime.codex: implementation design

Parent: `docs/modules/runtime.codex/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: the existing Codex App Server execution spine is preserved; the receipt adapter now has a real model-turn caller and protocol-derived terminal observation on the production candidate branch. Independent final-use authority, delegated tool terminal observation and external acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/codex-app-server`, `codex-rs/hepta-codex-adapter`.
Primary package: `P0.7B-B1B-MODEL-BOUNDARY`. The real model call site is exercised under the existing `P0.7B-B4-CALLSITE-PROOF` envelope, whose declared write path includes `codex-rs/hepta-infer-worker-host/**`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`open_thread(authenticated_session, schema_version) -> ThreadHandle`; `submit_turn(thread, context_attachment, objective) -> TurnHandle`; `dispatch_tool(turn, final_call, verified_use) -> DispatchObservation`; `observe_delivery(turn, compiled_payload_digest) -> PromptDeliveryObservationV1`. Preserve the existing app-server protocol; model requests and tool calls are traced to this single high-level spine.

The native adapter exposes a two-stage model boundary. `prepare(now_ms, CodexOperationIntent)` performs the synchronous pre-dispatch gate and freezes the request digest. `observe_server_notification`, `observe_app_server_event` and `observe_turn_start_error` derive receipts from actual App Server v2 protocol objects. Settlement does not re-run the admission clock gate because a valid terminal event may arrive after the original dispatch deadline.

## 3. State records and transaction design

`thread_session` owns thread/turn identities, principal scope, selected model/runtime tuple, context digest, tool-schema digest, lifecycle and sequence. External effect outcomes remain with their observing adapters/operation ledger. Session event persistence must retain exact attachment/delivery links without copying secrets or unrestricted model payloads into general learning receipts.

The adapter itself remains stateless. Lost-ack/no-replay persistence for the native model caller remains in the existing `DurableInferenceControl` journal: the request is durably marked as dispatching before `turn/start`; a reopened possibly-dispatched request is reconciled/settled indeterminate rather than replayed as a new model effect.

## 4. Deterministic algorithm and scheduling

Validate thread generation and frozen objective; revalidate context evidence at physical request assembly; bind the actual template/tokenizer/tool schema; record delivery only when the exact payload is submitted; run model calls through governed inference; final-check tool authority and payload immediately before adapter entry. Provider timeout or lost acknowledgement is not automatically a safe retry.

For the native model call site the concrete order is: obtain exact-generation Agentd ingress -> create App Server thread -> assemble final `TurnStartParams` -> hash exact payload -> `runtime.codex::prepare` -> durably mark possible dispatch -> issue `turn/start` -> correlate exact thread/turn events -> derive runtime.codex receipt from the real protocol notification -> settle the existing inference journal. An interrupt acknowledgement is not a terminal outcome; only the matching `turn/completed` notification can produce Completed/Failed/Interrupted terminality.

## 5. Capacity and performance profile

Pilot turn attachment and output bounds follow the selected model/context profile; tool calls <= 128 candidates per boundary and dispatch concurrency is explicitly reserved. Measure template assembly, provider queue, first/last token and terminal-tool latency separately.

The real caller uses bounded App Server request and event channels. App Server ingress overload (`-32001`) is represented separately from transport/event loss. A proven pre-admission overload/closed validation rejection can be labelled retry-safe by the adapter, while a caller that has already written its durable dispatch marker remains conservative and does not blindly replay that operation identity.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- CODEX-01: compiled-but-undelivered prompt cannot receive delivered-intervention credit.
- CODEX-02: payload changed after authorization is rejected at the effect gate.
- CODEX-03: unknown session/model/schema generation does not fall back to an ambient default.
- CODEX-04: acknowledgement loss keeps the operation indeterminate and does not create a duplicate model/tool effect.
- CODEX-05: `turn/completed` with `Failed` or `Interrupted` never maps to `Succeeded`.
- CODEX-06: cross-thread or cross-turn terminal evidence cannot settle the native model request.
- CODEX-07: event-stream lag/disconnect and turn-start timeout require reconciliation before replay.
- CODEX-08: App Server overload/closed validation failures are distinct from ambiguous transport/server failures.

Source test identities include `codex-rs/hepta-codex-adapter/src/lib_tests.rs`, `codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs`, `codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs` and `codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs`. Test source presence is not an execution receipt; exact-head and merge-candidate runs remain required.

## 7. Integration, rollback and capability ceiling

Boundary tests use the named `AppServerModelDriver` caller rather than only the adapter library. Preserve dependency inversion: the upstream App Server/Core execution spine is unchanged; Hepta code consumes its protocol and does not move Codex state ownership into a second runtime.

`CodexAdapterReceipt` is observational and permanently `DENY_ALL`; it cannot mint model/provider authority. `VerifiedUseToken`/`VerifiedUseTokenWitnessV1` remains an independent kernel-authority gate. The current model caller proves exact payload/correlation and no-replay behavior but does not self-issue or self-certify final-use authority. That authority integration must be independently supplied and accepted before activation.

Rollback removes the Hepta observation/call-site integration without rewriting Codex thread history. Pending or unknown effects remain in the durable inference journal and are never reclassified as absent merely because the adapter code is rolled back.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Codex execution spine:** `thread_start` in [codex-rs/app-server/src/request_processors/thread_processor.rs](../../../codex-rs/app-server/src/request_processors/thread_processor.rs), `turn_start` in [codex-rs/app-server/src/request_processors/turn_processor.rs](../../../codex-rs/app-server/src/request_processors/turn_processor.rs), exact admission in `codex-rs/core/src/codex_thread.rs`, and tool dispatch in `codex-rs/core/src/tools/router.rs`. These remain the sole upstream thread/turn/model/tool execution path.
- **Adapter gate and receipts:** [codex-rs/hepta-codex-adapter/src/lib.rs](../../../codex-rs/hepta-codex-adapter/src/lib.rs) implements `prepare`, protocol-derived terminal/error mapping, thread/turn correlation, closed terminal status, retry disposition and content-bound receipt digests. `Failed` and `Interrupted` are not success; lag/disconnect/timeout are not safe replay signals.
- **Named real model caller:** [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs) binds the exact final `TurnStartParams` before dispatch, consumes real App Server events, requires adapter/native status parity, and preserves the existing exact-generation Agentd health fence.
- **Lost acknowledgement / idempotency:** [codex-rs/hepta-infer-worker-host/src/native_run_control.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control.rs) and the inference-control durable journal record possible dispatch before the external call. Reopening a maybe-dispatched request does not create a duplicate turn.
- **Other App Server consumers:** Agentd automation/authbus and Matrix ingress use their existing durable queue/reconcile protocols and are not reclassified as model-terminal observers. Their admission/reconciliation contracts remain separately owned. Direct model `turn/start` terminal observation is the runtime.codex model boundary exercised here.
- **Source tests:** [codex-rs/hepta-codex-adapter/src/lib_tests.rs](../../../codex-rs/hepta-codex-adapter/src/lib_tests.rs), [codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs](../../../codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs). These are test identities until exact-candidate execution evidence is recorded.
- **Implementation and operating references:** [docs/modules/runtime.codex/IMPLEMENTATION_MAP.json](../../../docs/modules/runtime.codex/IMPLEMENTATION_MAP.json), [codex-rs/app-server/README.md](../../../codex-rs/app-server/README.md).
- **Repository-controlled work still required before source qualification:** focused compile/test/clippy evidence, generated Cargo lock synchronization, canonical dependency/implementation-map refresh, and removal of any temporary qualification-only workflow from the final candidate.
- **External/independent gates retained open:** independently issued final-use authority at the exact model/tool effect gate; real delegated tool terminal observer and acknowledgement-loss qualification; named deployed Agentd/product identity; independent acceptance, activation, selection, promotion and release.
