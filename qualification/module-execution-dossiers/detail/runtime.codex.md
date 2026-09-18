# runtime.codex: implementation design

Parent: `docs/modules/runtime.codex/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: existing Codex App Server execution spine, receipt adapter, named Agentd-owned App Server caller and durable lost-ack reconciliation path are source-composed; selected-host qualification, delegated tool-effect qualification, final-use authority composition and independent acceptance remain open in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

Repository-controlled source tests now exercise CODEX-02, CODEX-03 and the model-turn portion of CODEX-04 through the adapter, native caller and durable journal. CODEX-01 remains tied to the existing exact-admission path in codex-core/App Server, and delegated tool-effect lost-ack qualification remains external. Source test identities are not executed-test receipts; current-head and merge-candidate CI must still supply exact execution evidence.

## 7. Integration, rollback and capability ceiling

Boundary tests must use a named app-server caller, not only the adapter library. Preserve dependency inversion: the upstream execution spine consumes contracts rather than Hepta domain-store implementations. Rollback preserves thread compatibility and pending effect reconciliation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented execution spine:** `thread_start` in [codex-rs/app-server/src/request_processors/thread_processor.rs](../../../codex-rs/app-server/src/request_processors/thread_processor.rs) and `turn_start` in [codex-rs/app-server/src/request_processors/turn_processor.rs](../../../codex-rs/app-server/src/request_processors/turn_processor.rs) remain the single Codex App Server thread/turn owner.
- **Named caller:** [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs) `AppServerModelDriver` obtains the exact Agentd session ingress, connects to the Agentd-owned App Server Unix socket, starts an ephemeral thread with the configured model, journals `dispatch_native` before `turn/start`, and records `native_started` only after a concrete turn id is returned.
- **Transport provenance witness:** [codex-rs/app-server-client/src/remote.rs](../../../codex-rs/app-server-client/src/remote.rs) mints `ObservedAppServerEvent` only when a real event is dequeued from the initialized remote connection. The production type has no public constructor. A synthetic constructor exists only behind the explicit `test-support` feature.
- **Adapter semantics:** [codex-rs/hepta-codex-adapter/src/lib.rs](../../../codex-rs/hepta-codex-adapter/src/lib.rs) preserves `Completed`, `Failed` and `Interrupted` separately; correlates thread, optional/actual turn, App Server protocol id and Agent/session generation; classifies rejected, overloaded, unavailable, timed-out, indeterminate and quarantined outcomes; and emits an all-negative authority posture. `-32001` overload is the only App Server response classified `BackoffSafe`.
- **Deadline and reconciliation:** `validate_for_dispatch` enforces the dispatch deadline. `adapt` still accepts a late terminal witness after that deadline because reconciliation must not erase a fact that arrived late.
- **Durable lost-ack boundary:** [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs) owns the durable native reservation/dispatch/running/cancelling/indeterminate/released record. A reopen after a possibly admitted dispatch never reconnects and replays automatically. A proven App Server rejection before a turn exists is encoded with the existing `native-v1` `Observe` record shape as a correlation-bound, nonterminal `Indeterminate` marker. Current readers validate the request/generation/model/payload/thread/provider/context binding and may release the local slot; predecessor readers still parse the same journal schema and conservatively retain the attempt as indeterminate. No provider terminal output is invented.
- **Cancellation:** `turn/interrupt` acknowledgement is never treated as terminal. The caller records cancel intent first, sends the interrupt, and uses a bounded grace window only to observe a matching real `turn/completed` terminal event.
- **Owner fencing:** Agentd health/generation is rechecked before dispatch, during observation and after terminal cleanup. A lost owner remains sticky and a later provider completion cannot retroactively authorize success.
- **Source tests:** [codex-rs/hepta-codex-adapter/src/lib_tests.rs](../../../codex-rs/hepta-codex-adapter/src/lib_tests.rs), [codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs](../../../codex-rs/hepta-codex-adapter/src/deadline_digest_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs), and [codex-rs/hepta-infer-core/src/native_control_tests.rs](../../../codex-rs/hepta-infer-core/src/native_control_tests.rs). These remain test identities until current exact-head and merge-candidate CI completes.
- **Capability ceiling:** the adapter and native caller do not mint model/provider/tool authority. The current structural payload binding uses the durable native request digest and the adapter receipt remains `DENY_ALL`. `VerifiedUseTokenWitnessV1` composition is still required at any provider/tool effect boundary where final-use authority is normative.
- **Remaining external/activation work:** qualify this exact named caller against the selected deployment host and real provider stream; qualify delegated tool terminal observation including acknowledgement loss; compose the external final-use authority where required; obtain independent acceptance; and only then activate/release. The historical global qualification report is not evidence for this candidate.

