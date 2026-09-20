# runtime.codex: implementation design

Parent: `docs/modules/runtime.codex/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: existing Codex App Server execution spine and separate receipt adapter implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Execution spine and named caller:** the existing App Server remains the sole thread/turn execution owner through `thread_start` and `turn_start`. The named native caller is `AppServerModelDriver::run_once` in [codex-rs/hepta-infer-worker-host/src/native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs), reached from the fail-closed `hepta-infer-worker --profile native-app-server` CLI. No second Codex execution spine is introduced.
- **Terminal correctness and witness provenance:** [codex-rs/hepta-codex-adapter/src/lib.rs](../../../codex-rs/hepta-codex-adapter/src/lib.rs) preserves `Completed`, `Failed`, and `Interrupted` as distinct outcomes. Terminal success cannot be constructed from an ambient boolean or arbitrary digest: production adapters consume process-local observed App Server events/responses, then verify connection, initialized server version, codex home, thread, turn, session, generation, protocol, payload, and request correlation.
- **Request identity:** the adapter request digest binds operation, thread, actual v2 method, final payload plus lease payload, one absolute deadline, source-admission digest, Agent generation, App Server session, stable client user-message identity, exact user-input digest, protocol id, initialized App Server version, codex-home digest, and connection id. Terminal receipts additionally bind the actual turn and terminal response digest.
- **Final-use authority:** the native caller freezes the exact final `TurnStartParams`, requests an independently signed exact-binding grant through [codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs](../../../codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs), synchronizes the revocation head returned by the issuer, claims a non-constructible `VerifiedUseToken`, rechecks cancellation/deadline/Agent readiness/ingress, and consumes the token at final-use entry. The authority witness binds the exact signed grant plus the claim-time authority epoch/revocation frontier, and `enter()` requires that frontier to remain unchanged after revalidating expiry/revocation; any frontier advance requires a fresh claim before physical `turn/start`. Fresh frontier delivery itself remains a target-host revocation-distribution obligation. The worker does not own the issuer signing key. Adapter receipts remain `AuthorityPosture::DENY_ALL`.
- **Error, cancellation, and overload semantics:** explicit App Server overload `-32001` is `Overloaded + SafeBeforeAdmission`; invalid request/method/params are `Rejected + Never`; internal or otherwise unclassified `turn/start` errors are accepted-or-unknown and reconcile-only. Transport loss or timeout after write-ahead dispatch never proves “not applied”. Cancellation/deadline after admission produce non-success native boundary states; late terminal provider facts are retained without upgrading that boundary to success. Owner/generation loss is sticky and can quarantine otherwise completed provider work.
- **Lost acknowledgement and durable reconciliation:** [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs) commits the exact dispatch before the external await and emits a non-serializable one-shot pre-effect abort proof. Only the same live process may use that proof to release a definitely-unsent dispatch. After process loss the proof cannot be recreated, so recovery is reconcile-only. Same-connection `turn/started` can recover a lost `turn/start` response; reopened unknown requests use `thread/read(includeTurns=true)` and require the exact stable `client_user_message_id` plus original `UserMessage` content. Same-id/different-input and duplicate exact turns are hard conflicts. Missing App Server history remains indeterminate.
- **Repository fault matrix:** [docs/modules/runtime.codex/FAULT_MATRIX.md](../../../docs/modules/runtime.codex/FAULT_MATRIX.md) records the source-level failure/replay contract and focused tests. It is not target-host qualification evidence.
- **Source tests:** adapter terminal/correlation tests, adapter deadline tests, durable-control tests, native caller/reopen tests, final-use authority tests, and `hepta-agentd/tests/runtime_codex_product_e2e.rs` are present under the paths listed in the technical guide. The product E2E starts the real Agentd/App Server composition and the named runtime.codex caller against a controlled mock Responses provider; test presence is not a pass receipt and does not replace real-provider/target-host qualification.
- **Current repository-controlled gate:** exact-head and merge-candidate CI must compile, test, format and lint this exact reviewed candidate. Any failure attributable to this composition is repository-controlled work and reopens source closure. The historical September 10 global qualification report is not current-head evidence.
- **Exact-source truth:** `IMPLEMENTATION_MAP.sourceBase` is explicitly historical provenance, not current-head proof. The map's `exactCandidateProvenance` contract requires `scripts/hepta-lane-b-truth.py verify` to derive the checked-out `HEAD` and tree and emit them as `exactHead`/`exactTree`. Exact-head and merge-candidate qualification still must pass for the reviewed candidate before source-closure claims change.
- **Remaining external qualification:** establish deployed final-use issuer/key/socket/peer identity, trusted time/revocation and anti-rollback recovery; authenticate the target-host Agentd/App Server process/generation/socket; execute the named caller against the real provider stream; qualify delegated external-tool terminality and acknowledgement loss; define independent handling for unresolved indeterminate effects; then complete independent acceptance, activation/canary, promotion and release. Repository source must not self-certify those facts.
