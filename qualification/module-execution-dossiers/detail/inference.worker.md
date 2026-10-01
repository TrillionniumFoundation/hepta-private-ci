# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: actual App Server driver with durable admission, independently signed final-use entry, exact retained-history recovery and a separate local-model driver interface implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

### 8.1. Hosted source composition

The production CLI in [hepta-infer-worker.rs](../../../codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs) requires explicit `--profile native-app-server`, exact owning Agent/generation/model, a stable request ID, local admission ceiling, private journal and protected `--final-use-authority-config`. `AppServerModelDriver::run` and `run_intelligence` in [native_run_control.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control.rs) use the existing inference.control owner; they do not own a second durable request store.

[native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs) obtains the existing Agentd ingress, opens one fresh ephemeral model-only App Server thread, freezes exact v2 `TurnStartParams`, and obtains a non-constructible final-use token for that payload/transport/session binding. The independently operated Unix issuer signs; [final_use_authorizer.rs](../../../codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs) verifies the signed grant and monotonic revocation head through the shared authority. The worker has no issuer private key and exposes no model-visible tool topology.

Dispatch identity and authority/request witnesses are synced before effect entry. Cancellation, deadline, owner health/ingress and optional cognitive context are checked again before entry; only the live one-shot pre-effect abort proof may release a definitely-unsent prepared operation. Optional intelligence bindings must already identify the exact Agentd `ContextAttached` handoff and are included in the admission digest. [native_intelligence.rs](../../../codex-rs/hepta-infer-worker-host/src/native_intelligence.rs) checks the exact dispatched receipt again after cognitive revalidation and polls it on the existing 500 ms owner-health tick. Only matching owning-Agent cancellation may advance the tracked revision; unexpected binding, revision or phase drift fails closed. The final Agentd phase reflects the local boundary, so late provider completion cannot make cancellation or deadline denial succeed.

### 8.2. Observations and recovery

[native_observation.rs](../../../codex-rs/hepta-infer-worker-host/src/native_observation.rs) owns matching event interpretation and monotonic recovery checks. A matching provider terminal establishes terminality; an interrupt acknowledgement or accepted request does not. Deadline/cancellation checks precede ready-event consumption so an event stream cannot starve the stop condition. The local boundary may remain cancelled, timed out or quarantined even when the provider later reports completion. Owner authority loss is permanent for that attempt. Usage is an optional matching observation, not a synthetic zero or economic settlement.

A completed duplicate returns the historical observation without a new provider call. An uncertain duplicate/reopen can run `reconcile_existing`: exact same Agent generation, home/version/provider, original stable client-message identity and original user input must match retained App Server `thread/read` history. It never creates a new `turn/start`. Recovery retains the earlier output prefix, known token usage, lost authority and denied local boundary; contradictory observations fail rather than releasing capacity. Missing ephemeral history remains indeterminate and holds the slot. Historical dispatches missing the claim-time authority epoch/revocation frontier are normalized to quarantined before Agentd publication, while retaining provider terminal truth.

For an intelligence-bound terminal, `native_intelligence.rs::reconcile_intelligence_terminal` reads the exact owning run and submits `run_observe_terminal` with its observed current revision. Matching `Dispatched`, `Cancelling` or `Indeterminate` runs can receive the bounded CAS update; an already exact terminal receipt is accepted as historical truth without requiring its old execution deadline to remain live. Cancellation, deadline and denied local outcomes are preserved. A revision/CAS conflict does not overwrite the owner; it produces a bounded reason and denies local success. Missing/mixed owner targets, lost generation or unavailable provider history remain unresolved. This source recovery does not prove a deployed provider reconciliation service or recover missing token counts.

A definitely-unsent live abort after Agentd recorded `Dispatched` can release the worker's local slot, but cannot fabricate provider terminality or an owner terminal receipt. Explicit owner-side no-effect reconciliation remains required for that conservative ledger state.

### 8.3. Local driver component

[model_worker.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker.rs) exposes `InferenceWorker<D>` and its manifest/resource/request and optional Neuron feature interfaces. It checks aggregate driver-reported resident allocation with checked arithmetic, preserves high-water observations, and checks transient feature allocation against the grant. Driver run/feature errors, nonterminal work or malformed/resource-overflow observations fence new load/run/feature operations until explicit confirmed cleanup.

The driver contract requires a failed load that returns no handle to release anything acquired before returning its error. Rejected post-load handles are registered before automatic driver cleanup, so cleanup errors or unwinding retain ownership for explicit retry. A load unwind before returning any handle leaves worker-wide load uncertainty and denies new load/run/feature calls. Known-handle cleanup remains available but cannot clear this unknown-load fence; physical cleanup and a fresh driver generation are required. Unload is available for resource release after grant expiry/revocation and returns success only when the driver confirms drain and release. A propagated driver panic with a known handle retains the pre-invocation fence; confirmed unload can drain that model despite stale active counters and only then clear its active-request entries. These are component checks over caller-constructed records and driver observations. `ModelManifest`, `ResourceGrant` and `WorkerRequest` have no independent signed-issuer provenance in this interface. The feature payload v1 does not bind authorization IDs or token/deadline terms; a versioned issuer/control contract remains required for full local authority proof. The source does not supply or qualify a physical local weights/tokenizer/runtime/device implementation, enforce actual accelerator allocation, or prove post-crash physical resource release.

### 8.4. Verification and remaining scope

Source cases are in [native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs), [native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs), [final_use_authorizer_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs) and [model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs). The [Agentd product E2E](../../../codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs) composes real Agentd/App Server processes with a controlled mock Responses provider and independently signed test grant. These references are test identities, not execution receipts for this revision.

Regression scenarios include aggregate model allocation/overflow; invalid-handle cleanup and retry after unload failure; caught run/feature panic followed by failed and confirmed drain; no-handle load unwind retaining worker-wide denial; invalid-handle cleanup unwind preserving retry ownership; uncertain driver work denying new execution until driver-confirmed drain; revoked/expired-grant cleanup; over-limit feature tokens/allocation; non-success feature-vector exclusion; reopened terminal preservation of usage, lost authority and cancellation/deadline boundary; contradictory output rejection; historical missing-authority-frontier quarantine before owner CAS; exact owner terminal/revision recovery and concurrent CAS rejection; event-flood deadline enforcement; and expiry during awaited cognitive final-use revalidation. Physical load-kill/device-reset cases in section 6 remain target-host qualification designs.

| Scope | Implemented in source | Still required |
| --- | --- | --- |
| Hosted execution | Named CLI, durable control calls, signed final-use entry, exact turn observations/history recovery | Applicable source tests and separate real-provider/target-host evidence |
| Local inference component | Manifest/request/resource validation, reported-allocation accounting, cleanup fencing | Versioned independent local authorization, physical verified driver, actual memory enforcement and crash/resource qualification |
| Recovery | No replay after possible entry; exact retained history refines terminality and reconciles the exact Agentd owner through revision CAS while preserving prior facts | Missing usage, unavailable/mixed owner or history resolution, authenticated archival and owner-side no-effect recovery |
| Deployment | Configuration and signed-grant consumer protocol exist | Independent issuer/time/revocation/key/socket trust, acceptance, activation/canary, promotion and release |

Implementation and operating references: [Lane B native host](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [worker implementation map](../../../docs/modules/inference.worker/IMPLEMENTATION_MAP.json), [final-use authority port](../../../codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md). Canonical module dependencies remain unchanged; Agentd and runtime.codex are the delegated hosted composition and sole execution spine.
