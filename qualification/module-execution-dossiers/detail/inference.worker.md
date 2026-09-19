# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: concrete digest-pinned local runtime adapter, durable provider admission/reconciliation, an authority-gated `inference.control -> inference.worker` seam, and the named hosted-provider source root `hepta-inference-runtime-host` are implemented. Local-model product composition, target-host isolation/hardware qualification, deployed runtime proof, authoritative recovered usage evidence, independent acceptance and activation remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-infer-worker-host`; the cross-owner composition seam is `codex-rs/hepta-inferd/src/worker_port.rs` and durable native reconciliation state remains owned by `codex-rs/hepta-infer-core`.
Packages: `INFER-V4-T4`, `INFER-V4-T5`, `NEU-1-LOCAL-MODEL-BAKEOFF`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`load_model(verified_manifest, verified_resource_grant) -> LoadedModelHandle`; `run(request, lease, reservation, cancellation) -> ExecutionObservation`; `unload(handle, drain_deadline) -> UnloadObservation`.

Hosted provider execution exposes `NativeWorkerPort::execute`. `NativeWorkerConfig` owns the kernel `FinalUseAuthority`; `execute` receives `NativeAdmission` plus a grant resolver, and the worker invokes that resolver only after provider, context, quota/resource policy and exact serialized `TurnStartParams` are frozen. The port never accepts a caller-precomputed final-use binding or raw signed grant for an earlier/partial payload. Planning remains authority-free. Local model construction accepts `VerifiedResourceGrant`, not caller-controlled raw grant material.

## 3. State records and transaction design

No authoritative fleet or grant state is owned here. Worker-local state contains process/model generation, loaded artifact digests, bounded runtime handles, request handles and observed memory/usage. Persistent model files belong to the artifact/cache owner. `DurableInferenceControl` remains the single persistent native reservation/dispatch/observation writer.

`ResourceGrant` is a process-local resource-capability payload. Public callers must obtain `VerifiedResourceGrant` through `ResourceGrantVerifier`; the trusted-in-process constructor is crate-private. `FinalUseResourceGrantVerifier` is the concrete kernel-backed verifier: it binds every resource-grant field plus exact worker identity/generation into `FinalUseBinding`, checks the current `FinalUseAuthority` epoch/revocation state and durably consumes the signed nonce before one worker generation can be created. The authenticated worker subject remains in `GrantVerification`, and `InferenceWorker::new` rejects any subject mismatch so the verified capability cannot be transferred to a different worker. `VerifiedResourceGrant` is move-only, preventing the post-claim proof from being cloned into multiple worker instances after the durable authority nonce has been consumed. This source boundary still does not replace product-host lifecycle fencing or target-host resource authority.

The hosted path persists a dispatch binding containing the dedicated App Server thread, stable `client_user_message_id` and canonical input digest before provider admission. Unknown execution retains capacity and unknown token usage stays `None`.

`VerifiedResourceGrant` is a bounded verification snapshot, not a revocation feed. The kernel-backed verifier performs current authority admission at generation creation; a production local-model caller must still fence/replace that generation when resource authority changes later. The worker must not infer live authority from a stale in-process copy.

## 4. Deterministic algorithm and scheduling

Local execution verifies the runtime executable plus weights, tokenizer, preprocessing, quantization and device-descriptor digests; sums existing live model reservations before each load; passes only the remaining worker memory budget to the new runtime; requires an explicit load acknowledgement with nonzero reserved memory; rejects aggregate or observed memory above the grant/reservation; re-hashes the selected artifacts before declaring the model usable; executes requests with protocol waits capped by the exact request deadline; and requires an unload acknowledgement before compatible release.

Hosted execution first reserves through `inference.control` with cross-bound quota/resource evidence. For a fresh request it freezes the exact provider/context/`TurnStartParams`, resolves and claims final-use authority, then under the same revocation fence durably records dispatch intent and synchronously admits the request into the bounded single-owner App Server queue. Successful queue admission is the local effect linearization point; later transport loss is accepted-or-unknown. Explicit queue rejection is exact pre-effect evidence and is reconciled as `NoAdmission`. On restart it uses App Server `thread/queue/reconcile` with `ReconcileOnly`: a persisted binding recovers the exact original turn; missing/cancelled proves no durable admission and releases safe holds; ambiguous/unavailable reconciliation remains indeterminate. Recovery never submits a replacement turn.

## 5. Capacity and performance profile

Local ceilings are explicit: bounded model count, active requests, token count, runtime protocol line size, protocol response time and aggregate grant memory. The concrete driver records both reserved and observed memory, admits each load only against remaining grant memory and fails closed when observation exceeds reservation. A post-write run timeout is indeterminate and kills/fences the resident runtime instead of authorizing replay. Hosted admission additionally binds `QuotaReservation`/`ResourceAdvertisement` request-count, token, concurrency and owner-defined economic-budget holds. Those source records are authority inputs, not proof of real provider billing or measured physical VRAM/device availability.

Target qualification must measure load/unload, peak model/KV memory, CPU/GPU placement, token rate, p99 inference, cancellation, repeated restart, OOM/device reset, process/FD leak and concurrency behavior on the selected runtime/device tuple. These are deployment measurements, not source-level claims.

## 6. Concrete verification cases

- WORKER-01: changed weights/tokenizer/preprocessor/quantization/runtime/device tuple fails before use.
- WORKER-02: raw external `ResourceGrant` cannot directly construct a production worker; `FinalUseResourceGrantVerifier` binds the exact worker/resource scope to kernel authority and a durable single-use nonce, the authenticated worker subject cannot be reused for another worker identity, and the resulting `VerifiedResourceGrant` is non-cloneable; local structure/generation/expiry/capacity checks still run.
- WORKER-03: a real resident child process completes digest-pinned load/run/unload and artifact mutation before spawn is rejected.
- WORKER-04: observed memory greater than the runtime reservation is rejected; unknown terminal usage is never inferred as zero.
- WORKER-05: provider dispatch carries stable client-message and payload identities; reopen reconciles without a replacement turn.
- WORKER-06: exact Core `Missing`/`Cancelled` reconciliation releases the local slot without fabricating provider terminality or usage.
- WORKER-07: owner/generation loss cannot be relabelled as authorized success even if a provider terminal event is later observed.
- WORKER-08: target-host CPU/GPU/OOM/device-reset/cancellation/crash/leak/sandbox matrix is required before deployment qualification.
- WORKER-09: multiple loaded models cannot cumulatively reserve more than the worker grant; each new runtime receives only the remaining memory budget.
- WORKER-10: a local runtime that stops responding after request write is bounded by the request deadline and returns indeterminate without replay.

Source tests implement the repository-controlled cases; target-host and independent gates require retained external evidence.

## 7. Integration, rollback and capability ceiling

`hepta-inferd::worker_port::NativeWorkerPort` is the source-composed `ModulePort::inference.control::inference.worker` seam. It does not mint grants or own inference state. The named hosted-provider source root is `hepta-inference-runtime-host`, which composes protected host configuration, the canonical durable control owner and independently issued final-use grants. Deployment of that root is still an evidence gate. A separate local-model product caller with authenticated resource authority is not yet composed.

“Isolated” at this source boundary means exact owner/generation fencing, stable execution identity, bounded protocol/resource accounting, digest-pinned artifacts and fail-closed recovery. This module does not self-certify cgroups, namespaces, seccomp/Landlock, GPU ACL/MIG, network or filesystem sandboxing. Rollback drains/unloads local runtimes and preserves durable provider truth; an indeterminate external effect is never converted into a safe replay.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Local runtime:** `LocalProcessDriver` in `codex-rs/hepta-infer-worker-host/src/local_process_driver.rs` maps a verified model manifest to digest-pinned local artifacts and an exact runtime executable, performs the resident load/run/unload protocol, records reserved/observed memory, enforces aggregate grant memory via a remaining-memory load budget, and bounds run response waits by the request deadline. Uncertain post-write I/O remains indeterminate. `InferenceWorker` in `model_worker.rs` requires `VerifiedResourceGrant`; `FinalUseResourceGrantVerifier` provides the kernel-authenticated single-use generation-creation path.
- **Hosted provider path:** `AppServerModelDriver` plus `native_run_control.rs` performs quota/resource-aware durable admission, exact-payload final-use claim, revocation-fenced durable dispatch plus synchronous transport-queue admission, exact turn/output/optional-token observation, cancellation and owner fencing. The one-shot effect token yields only a non-authorizing terminal revalidation receipt.
- **Crash/restart reconciliation:** `native_app_server.rs` uses Core `thread/queue/reconcile` in `ReconcileOnly` mode against the journaled client-message identity and canonical payload digest. It can recover the original persisted turn or durably prove no admission; it never creates a replacement provider request. Recovered terminal turns wait under the normal RPC bound for the exact turn's persisted token-usage replay. Missing authoritative usage remains unknown.
- **Composition seam:** `codex-rs/hepta-inferd/src/worker_port.rs::NativeWorkerPort` wires the canonical `DurableInferenceControl` to a worker whose configuration owns kernel `FinalUseAuthority`; the port accepts a resolver for the exact runtime-frozen binding rather than a caller-precomputed signed grant. `codex-rs/hepta-inferd/src/bin/hepta-inference-runtime-host.rs` is the named hosted-provider source root.
- **Source tests:** `model_worker_tests.rs`, `local_process_driver_tests.rs`, `native_run_control_tests.rs`, `native_app_server_tests.rs`, `hepta-infer-core/src/native_control_tests.rs` and `hepta-inferd/src/worker_port.rs` tests. Test identity is not an execution receipt.
- **Operating reference:** `docs/modules/inference.worker/PRODUCTION_READINESS.md`, `docs/readiness/LANE_B_NATIVE_HOST.md`, and `docs/modules/inference.worker/IMPLEMENTATION_MAP.json`.
- **Remaining repository-controlled integration:** compose the local-model product caller around `FinalUseResourceGrantVerifier` and lifecycle fencing for later revocation; add a trusted provider/billing usage reconciler for recovered terminal runs when persisted App Server history lacks authoritative usage. Hosted-provider source composition and the concrete local grant verifier already exist; deployment remains external evidence.
- **External gates:** exact target model/runtime/device tuple, real CPU/GPU/OOM/device-reset/cancellation/crash/leak/concurrency qualification, host sandbox evidence, deployed authenticated control channel, independent acceptance, activation and release.
