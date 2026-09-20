# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: actual App Server driver with durable exact-admission reconciliation and a concrete digest-pinned local runtime-process driver implemented. Repository source still does not prove target-host CPU/GPU enforcement, OS sandboxing, deployed product composition or independent acceptance; those remaining gates are listed in section 8 and the module production-readiness runbook. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** hosted `run` in [codex-rs/hepta-infer-worker-host/src/native_run_control.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control.rs); model lifecycle in [codex-rs/hepta-infer-worker-host/src/model_worker.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker.rs); concrete local process execution in [codex-rs/hepta-infer-worker-host/src/local_process_driver.rs](../../../codex-rs/hepta-infer-worker-host/src/local_process_driver.rs). The cross-module source seam is `hepta-inferd::worker_port::NativeWorkerPort`; it consumes kernel-owned final-use authority and does not mint it.
- **Local runtime boundary:** `LocalProcessDriver` verifies the selected runtime executable and weights/tokenizer/preprocessor/quantization/device-descriptor digests, requires a nonzero reservation/load handshake within the authenticated resource grant, re-hashes artifacts before publishing the handle, binds run input to the lease payload digest, bounds protocol/output size, and puts the complete child protocol write/response exchange under `min(caller remaining deadline, local operation cap)`. Exchange timeout kills/waits the child; after a run exchange may have begun, timeout remains `indeterminate` rather than becoming replay permission. `VerifiedResourceGrant` makes the trust boundary explicit: a raw `ResourceGrant` is not external authenticity proof, the verified token is non-cloneable, and every load/run/unload consumes freshly verified evidence for the exact current admission time and established authority identity.
- **Hosted state and recovery:** before `turn/start`, inference.control durably binds the provider/thread, stable `client_user_message_id == request_id`, canonical input SHA-256 and context digest. Reopen performs Core exact client-message reconciliation without submitting a replacement turn. `Persisted` rebinds only the original turn and refines terminal/history/usage observations; `Missing` or `Cancelled` records durable no-admission proof and releases the local slot; unavailable or still-in-progress recovery remains `indeterminate`. Missing usage stays unknown rather than becoming zero.
- **Isolation claim:** current source proves execution ownership/generation fencing, exact model/artifact identity, bounded runtime protocol/resource contracts and cleanup behavior. It does **not** itself prove cgroup/namespace/seccomp/LSM policy, GPU device ACL/IOMMU/MIG enforcement, immutable mount ancestry, accelerator reset behavior or leak freedom.
- **Source tests:** [native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs), [native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs), [model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs) and [local_process_driver_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/local_process_driver_tests.rs). The local tests cover stale verified-grant rejection and a hung runtime watchdog in addition to artifact mutation and protocol execution. These are source test identities, not target-hardware or deployment pass receipts.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [docs/modules/inference.worker/IMPLEMENTATION_MAP.json](../../../docs/modules/inference.worker/IMPLEMENTATION_MAP.json), and [docs/modules/inference.worker/PRODUCTION_READINESS.md](../../../docs/modules/inference.worker/PRODUCTION_READINESS.md).
- **Remaining work / non-claims:** qualify an identified real runtime/model on target CPU/GPU hardware; prove required OS/device isolation and memory/leak/reset behavior; compose and exercise the named deployed product caller; attach exact-candidate CI/fault-injection evidence; and obtain independent activation/acceptance/release evidence. Economic/token/device quota authority remains owned outside this worker. Provider terminal recovery is implemented where Core exposes the exact persisted admission/history; missing late usage remains unknown unless a trusted replay exposes it.
