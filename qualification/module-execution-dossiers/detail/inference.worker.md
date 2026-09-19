# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: actual App Server execution with durable admission and no-replay post-crash reconciliation, plus a verified local-runtime process driver, are implemented in source. Product caller composition, target-host CPU/GPU/sandbox qualification, missing-usage reconciliation and independent acceptance remain separate gates listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** `run` in [codex-rs/hepta-infer-worker-host/src/native_run_control.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control.rs); post-crash hosted reconciliation in [codex-rs/hepta-infer-worker-host/src/native_reconcile.rs](../../../codex-rs/hepta-infer-worker-host/src/native_reconcile.rs); `load_model` / `run` / `unload_model` state control in [codex-rs/hepta-infer-worker-host/src/model_worker.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker.rs); and the production local-runtime adapter `LocalProcessModelDriver` in [codex-rs/hepta-infer-worker-host/src/local_process_driver.rs](../../../codex-rs/hepta-infer-worker-host/src/local_process_driver.rs).
- **Hosted state and recovery:** The native run invokes the private Agent/App Server once and commits matching terminal/output/optional-token observations through inference.control. Each request owns a dedicated durable App Server thread. Reopened dispatched requests reconnect to the exact Agent generation and read that exact thread. A known durable turn ID must match; when `turn/start` response loss left the turn ID unknown, recovery requires a persisted user item whose `client_user_message_id` equals the original stable request ID. A matching terminal turn is settled without replay. Missing, ambiguous or still-running provider state remains `indeterminate`; no replacement turn is submitted.
- **Local-runtime state and execution:** `WorkerRequest` carries the actual bounded payload and the worker recomputes its SHA-256 before dispatch. The manifest includes weights, tokenizer, preprocessor, quantization, license, SBOM, runtime and device digests. `LocalProcessModelDriver` verifies the corresponding regular non-symlink files before spawn, clears inherited environment, invokes the exact runtime executable, and requires a bounded protocol acknowledgement binding the artifact tuple, OS PID, stable handle and non-zero memory reservation. Aggregate loaded-model memory is checked against the grant. The runtime returns raw output and the worker computes the output digest itself.
- **Authority boundary:** `ResourceGrant` is a trusted process-local capability. Local expiry/revocation/generation/resource/device checks do not replace authentication, signature/revocation or epoch verification required by the external `kernel.authority` adapter before constructing that type.
- **Source tests:** [codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_reconcile.rs](../../../codex-rs/hepta-infer-worker-host/src/native_reconcile.rs), [codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs), and [codex-rs/hepta-infer-worker-host/src/local_process_driver.rs](../../../codex-rs/hepta-infer-worker-host/src/local_process_driver.rs). These are test identities, not execution receipts for this documentation revision.
- **Exact-revision source evidence:** [`.github/workflows/inference-worker-qualification.yml`](../../../.github/workflows/inference-worker-qualification.yml) checks out the exact candidate SHA, runs focused inference-control/worker tests plus strict worker Clippy, and emits a source/tree-bound receipt. That receipt does not grant hardware qualification, independent acceptance, activation or release.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [docs/modules/inference.worker/IMPLEMENTATION_MAP.json](../../../docs/modules/inference.worker/IMPLEMENTATION_MAP.json), and the [production readiness/runbook](../../../docs/modules/inference.worker/PRODUCTION_READINESS.md).
- **Remaining work:** Compose a named production caller/authority adapter around the canonical inference.control writer; reconcile authoritative provider/billing token usage when terminal history lacks usage; execute real CPU/GPU/device/OOM/reset/cancellation/crash/leak/concurrency qualification; prove deployment-specific OS/device isolation; and obtain independent acceptance/activation/release evidence.
