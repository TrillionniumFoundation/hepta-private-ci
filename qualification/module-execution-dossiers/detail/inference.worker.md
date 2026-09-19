# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: concrete digest-pinned local runtime adapter, durable provider admission/reconciliation, and an authority-gated `inference.control -> inference.worker` source composition seam are implemented. Target-host isolation/hardware qualification, deployed product composition, authoritative recovered usage evidence, independent acceptance and activation remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-infer-worker-host`; the cross-owner composition seam is `codex-rs/hepta-inferd/src/worker_port.rs` and durable native reconciliation state remains owned by `codex-rs/hepta-infer-core`.
Packages: `INFER-V4-T4`, `INFER-V4-T5`, `NEU-1-LOCAL-MODEL-BAKEOFF`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`load_model(verified_manifest, verified_resource_grant) -> LoadedModelHandle`; `run(request, lease, reservation, cancellation) -> ExecutionObservation`; `unload(handle, drain_deadline) -> UnloadObservation`.

Hosted provider execution additionally exposes `NativeWorkerPort::final_use_binding` and `NativeWorkerPort::execute`. The port accepts a kernel-owned `FinalUseAuthority` and independently signed `SignedFinalUseGrant`; planning remains authority-free. Local model construction accepts `VerifiedResourceGrant`, not caller-controlled raw grant material.

## 3. State records and transaction design

No authoritative fleet or grant state is owned here. Worker-local state contains process/model generation, loaded artifact digests, bounded runtime handles, request handles and observed memory/usage. Persistent model files belong to the artifact/cache owner. `DurableInferenceControl` remains the single persistent native reservation/dispatch/observation writer.

`ResourceGrant` is a process-local resource-capability payload. Public callers must obtain `VerifiedResourceGrant` through `ResourceGrantVerifier`; the trusted-in-process constructor is crate-private. This type boundary does not replace a production issuer, enrollment, revocation-distribution or target-host resource authority.

The hosted path persists a dispatch binding containing the dedicated App Server thread, stable `client_user_message_id` and canonical input digest before provider admission. Unknown execution retains capacity and unknown token usage stays `None`.

## 4. Deterministic algorithm and scheduling

Local execution verifies the runtime executable plus weights, tokenizer, preprocessing, quantization and device-descriptor digests; starts one resident runtime process; requires an explicit load acknowledgement with nonzero reserved memory; rejects observed memory above that reservation; re-hashes the selected artifacts before declaring the model usable; executes bounded requests; and requires an unload acknowledgement before compatible release.

Hosted execution reserves locally, verifies/claims final-use authority only on a fresh request, durably records dispatch intent, then submits the exact provider input. On restart it uses App Server `thread/queue/reconcile` with `ReconcileOnly`: a persisted binding recovers the exact original turn; missing/cancelled proves no durable admission and releases the local slot; ambiguous/unavailable reconciliation remains indeterminate. Recovery never submits a replacement turn.

## 5. Capacity and performance profile

Local ceilings are explicit: bounded model count, active requests, token count, runtime protocol line size and grant memory. The concrete driver records both reserved and observed memory and fails closed when observation exceeds reservation. Hosted capacity is a local in-flight slot limit, not economic quota or provider billing authority.

Target qualification must measure load/unload, peak model/KV memory, CPU/GPU placement, token rate, p99 inference, cancellation, repeated restart, OOM/device reset, process/FD leak and concurrency behavior on the selected runtime/device tuple. These are deployment measurements, not source-level claims.

## 6. Concrete verification cases

- WORKER-01: changed weights/tokenizer/preprocessor/quantization/runtime/device tuple fails before use.
- WORKER-02: raw external `ResourceGrant` cannot directly construct a production worker; verifier output binds authority identity/evidence and local structure/generation/expiry/capacity checks still run.
- WORKER-03: a real resident child process completes digest-pinned load/run/unload and artifact mutation before spawn is rejected.
- WORKER-04: observed memory greater than the runtime reservation is rejected; unknown terminal usage is never inferred as zero.
- WORKER-05: provider dispatch carries stable client-message and payload identities; reopen reconciles without a replacement turn.
- WORKER-06: exact Core `Missing`/`Cancelled` reconciliation releases the local slot without fabricating provider terminality or usage.
- WORKER-07: owner/generation loss cannot be relabelled as authorized success even if a provider terminal event is later observed.
- WORKER-08: target-host CPU/GPU/OOM/device-reset/cancellation/crash/leak/sandbox matrix is required before deployment qualification.

Source tests implement the repository-controlled cases; target-host and independent gates require retained external evidence.

## 7. Integration, rollback and capability ceiling

`hepta-inferd::worker_port::NativeWorkerPort` is the source-composed `ModulePort::inference.control::inference.worker` seam. It does not mint grants or own inference state. A deployed product caller still has to provide trusted host configuration, the canonical durable control owner and independently issued final-use grants; source composition is not activation proof.

“Isolated” at this source boundary means exact owner/generation fencing, stable execution identity, bounded protocol/resource accounting, digest-pinned artifacts and fail-closed recovery. This module does not self-certify cgroups, namespaces, seccomp/Landlock, GPU ACL/MIG, network or filesystem sandboxing. Rollback drains/unloads local runtimes and preserves durable provider truth; an indeterminate external effect is never converted into a safe replay.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Local runtime:** `LocalProcessDriver` in `codex-rs/hepta-infer-worker-host/src/local_process_driver.rs` maps a verified model manifest to digest-pinned local artifacts and an exact runtime executable, performs the resident load/run/unload protocol, records reserved/observed memory and conservatively returns indeterminate after uncertain runtime I/O. `InferenceWorker` in `model_worker.rs` requires `VerifiedResourceGrant`.
- **Hosted provider path:** `AppServerModelDriver` plus `native_run_control.rs` performs durable admission, final-use-gated dispatch, exact turn/output/optional-token observation, cancellation and owner fencing.
- **Crash/restart reconciliation:** `native_app_server.rs` uses Core `thread/queue/reconcile` in `ReconcileOnly` mode against the journaled client-message identity and canonical payload digest. It can recover the original persisted turn or durably prove no admission; it never creates a replacement provider request. Missing authoritative usage remains unknown.
- **Composition seam:** `codex-rs/hepta-inferd/src/worker_port.rs::NativeWorkerPort` wires the canonical `DurableInferenceControl`, kernel `FinalUseAuthority` and worker final-use boundary without widening authority.
- **Source tests:** `model_worker_tests.rs`, `local_process_driver_tests.rs`, `native_run_control_tests.rs`, `native_app_server_tests.rs`, `hepta-infer-core/src/native_control_tests.rs` and `hepta-inferd/src/worker_port.rs` tests. Test identity is not an execution receipt.
- **Operating reference:** `docs/modules/inference.worker/PRODUCTION_READINESS.md`, `docs/readiness/LANE_B_NATIVE_HOST.md`, and `docs/modules/inference.worker/IMPLEMENTATION_MAP.json`.
- **Remaining repository-controlled integration:** compose a named deployed product host around `NativeWorkerPort` and an authenticated local-resource grant issuer/verifier; add a trusted provider/billing usage reconciler for recovered terminal runs when App Server history lacks authoritative usage.
- **External gates:** exact target model/runtime/device tuple, real CPU/GPU/OOM/device-reset/cancellation/crash/leak/concurrency qualification, host sandbox evidence, deployed authenticated control channel, independent acceptance, activation and release.
