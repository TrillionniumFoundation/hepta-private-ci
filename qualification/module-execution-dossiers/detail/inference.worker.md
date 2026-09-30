# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: actual App Server driver with durable admission, independent final-use authorization and exact-owner terminal reconciliation, plus a separate local-model driver interface; remaining target capabilities and independent acceptance are listed in sections 8–9. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-infer-worker-host`.
Packages: `INFER-V4-T4`, `INFER-V4-T5`, `NEU-1-LOCAL-MODEL-BAKEOFF`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`load_model(verified_manifest, resource_grant) -> LoadedModelHandle`; `run(request, lease, reservation, cancellation) -> ExecutionObservation`; `unload(handle, drain_deadline) -> UnloadObservation`. Existing pure validation/receipt APIs remain boundary primitives; they cannot be labelled provider execution unless a real runtime consumes the exact verified model bytes.

## 3. State records and transaction design

No authoritative fleet or grant state. Worker-local ephemeral state contains process/model generation, loaded artifact digests, bounded KV/cache handles, request handles and usage counters. Persistent model files belong to the artifact/cache owner; the worker receives read-only descriptors and verifies weights, tokenizer, preprocessing, quantization, license/SBOM and device/runtime identity.

## 4. Deterministic algorithm and scheduling

Verify request/lease/reservation compatibility before loading or generation; load once per admitted model generation; reserve accelerator/CPU memory; perform bounded inference; observe cancellation; emit output/usage and terminality through the control port. Model-load failures release only acquired resources. A lost channel is indeterminate, not a fabricated successful response.

## 5. Capacity and performance profile

Pilot maximum tokens uses the existing request bound with a stricter selected-model profile; concurrent loaded models and accelerator memory are explicit grants. Measure load/unload, peak/KV memory, token rate, p99 inference and cancellation under maximum input and repeated restarts.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- WORKER-01: changed tokenizer/weights/runtime tuple fails before inference.
- WORKER-02: request resource overflow and expired/revoked grant are denied before loading.
- WORKER-03: kill at every load stage does not leak locks, memory or descriptors.
- WORKER-04: actual model consumer proof includes binary/weights/device digests; a synthetic observation does not pass it.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Attach Neuron's encoder only after the real-model qualification gate. The deterministic feature fixture remains available without claiming real-model use. Rollback cannot mix old checkpoints with new encoders; unload/drain precedes compatible reload.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

### 8.1 Hosted App Server profile

`AppServerModelDriver::run` and `run_intelligence` in [native_run_control.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control.rs) wrap the actual [App Server driver](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs). The non-test CLI is `hepta-infer-worker --profile native-app-server`; [RUNBOOK.md](../../../codex-rs/hepta-infer-worker-host/RUNBOOK.md) documents its required final-use configuration and exact inputs. A named source CLI does not establish a selected deployment or paid-provider qualification.

The request is admitted through `inference.control` before provider contact. It freezes Agent/generation/model and prompt/query/socket/timeout digest; an intelligence request also freezes the Agentd run/revision/context/envelope binding. The worker checks Agent readiness, connects to its App Server, requires initialized home identity and exact model, and creates an ephemeral read-only thread. Cognitive context, if requested, is obtained after preparation and revalidated immediately before physical turn entry.

The exact final `turn/start` payload and transport/session binding are adapted through `runtime.codex`. `UnixFinalUseAuthorizer` asks an independent host-owned issuer for a signed grant; the existing `kernel.authority` verifier owns nonce/revocation persistence. The worker stores no signing key. Durable dispatch records actual thread/provider/context, correlation and claim-time authority frontier/witness before effect entry. Owner/ingress, cancellation/deadline and optional context are checked again; a consumed `VerifiedUseToken` is required to cross the effect boundary.

Provider output is a bounded per-item projection of matching observed deltas/completed items. Completion requires the exact request connection/thread/turn binding. Provider terminality, boundary status and owner authority are distinct. Cancellation, timeout, event loss and fencing trigger a real interrupt and cannot become success from an interrupt acknowledgement or later provider completion. Missing observed tokens are unknown, not zero.

### 8.2 Durable state and recovery

One `DurableInferenceControl` lock/journal owns admission, synced dispatch and observations. Terminal duplicates consume recorded facts without a new model turn. A live pre-effect abort proof can release an operation known not to have crossed entry; that proof is neither serialized nor reconstructible after a crash.

Reopened possible dispatches have a source implementation of exact-owner `thread/read(includeTurns=true)` reconciliation. It requires current exact Agent generation, matching App Server home/version/provider and persisted correlation, plus the stable `client_user_message_id` and original user input. Mismatched input or duplicate matching turns conflict; missing bindings/history remain indeterminate and hold the slot. Recovery never submits a new `turn/start`. Ephemeral thread loss or a changed owner generation is not covered by this source path. Thread history does not supply missing token-usage events.

The journal retains compatibility with legacy records; incomplete historical bindings cannot be upgraded into current execution authority. Append/sync ambiguity fences the owner, and malformed/partial/oversize replay fails without truncation. Current capacity and rollback rules are in the technical guide and runbook.

For `run_intelligence`, terminal inference settlement is durable before Agentd terminal publication. Cached and recovered terminal paths retry the same exact run publication, not the model call. Publication errors retain provider terminality in the journal and return an error. Recovery preserves known usage and sticky boundary/owner-loss facts; an absent history usage field cannot erase previously observed tokens. [native_recovery.rs](../../../codex-rs/hepta-infer-worker-host/src/native_recovery.rs) owns this shared logic.

### 8.3 Injected local-model component

`InferenceWorker<D>` in [model_worker.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker.rs) implements `load_model`, `run`, `unload_model` and the optional Neuron-feature port. These are the native subset corresponding to the target signatures in section 2; an actual drain-deadline or asynchronous cancellation API is not supplied by the synchronous trait.

The component validates supplied manifest/grant and request bindings, limits models/requests and aggregate per-model resident-memory high-water marks, and delegates physical execution to `ModelDriver`. Neuron feature buffers additionally count against observed peak memory. A resource overrun fences admission until all known idle models have been unloaded; expiry/revocation does not prevent that cleanup. An ambiguous driver run retains its active slot and blocks unload; unknown load/unload outcome creates a separate fence and cannot be retried as known cleanup. No physical stop/reconciliation API exists yet.

Its `ResourceGrant` is a host-supplied Rust value, not a signature-verifying allocator. Repository drivers are test fixtures; no physical weights/tokenizer/runtime/device consumer or production local encoder is established. Feature execution lives in [model_worker_features.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_features.rs) and shares the same owner/capacity state.

### 8.4 Source verification references

- [native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs): duplicate/reopen paths, admission binding and definitive pre-dispatch stop.
- [native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs): matching terminal/output/usage, owner health, final-use cognitive validation and failure classification.
- [final_use_authorizer_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs): independently signed grant, peer identity, denial and revocation rollback.
- [model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs): manifest/resource tuple, model lifecycle and feature path.
- [native_recovery_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_recovery_tests.rs): retained observation facts, definitive pre-effect timeout and retry of exact intelligence terminal publication.
- [runtime_codex_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs): real supervisor/Agentd/App Server and named worker caller with an independent test issuer and mock Responses provider. It asserts one physical provider request and durable terminal correlation; it is not a paid-provider or local-device qualification.

These are source test identities, not execution receipts for this documentation revision. See also [IMPLEMENTATION_MAP.json](../../../docs/modules/inference.worker/IMPLEMENTATION_MAP.json) and the [runtime.codex fault matrix](../../../docs/modules/runtime.codex/FAULT_MATRIX.md).

## 9. Remaining integration and completion criteria

| Area | Current source boundary | Required before the corresponding completion claim |
| --- | --- | --- |
| Hosted execution | Explicit CLI, owner-fenced App Server caller, final-use authority seam and durable observation. | Selected target host/issuer/process identity and exact-candidate provider fault evidence. |
| Recovery | Same-operation exact-owner terminal history reconciliation; unknown work is not replayed. | Operational quarantine/release policy for lost ephemeral history, authenticated later usage, retention/archival and any cross-generation provider recovery. |
| Local model | Manifest/grant state machine and injected trait. | Actual bytes/device/memory driver, authenticated resource authority, stop/reconciliation path and OOM/device-reset/load-kill qualification. |
| Intelligence/Neuron | Exact Agentd handoff and typed optional feature bindings. | Actual selected product host, physical encoder/model proof and independent outcome evidence; do not substitute deterministic fixtures. |
| Acceptance/release | Source/document mapping only. | Independent acceptance, activation, promotion and release decisions from their existing owners. |

Source presence and documentation detail are established separately from test execution. Economic quota, physical isolation/device performance, deployment qualification, product execution evidence, independent acceptance and release remain unestablished by this dossier.
