# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: hosted App Server execution now has durable identity/reconciliation and the local path has a verified private-runtime adapter plus signed product composition. Repository-controlled source-boundary gaps are closed by this candidate; target-host hardware/sandbox qualification and independent acceptance remain external gates listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** hosted `run` in [codex-rs/hepta-infer-worker-host/src/native_run_control.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control.rs); manifest/resource state machine `load_model` and `unload_model` in [codex-rs/hepta-infer-worker-host/src/model_worker.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker.rs); Unix physical adapter `LocalProcessDriver` in [codex-rs/hepta-infer-worker-host/src/local_process.rs](../../../codex-rs/hepta-infer-worker-host/src/local_process.rs); composed local product boundary `execute_local_product` in [codex-rs/hepta-infer-worker-host/src/local_product.rs](../../../codex-rs/hepta-infer-worker-host/src/local_product.rs).
- **Hosted state and recovery:** The native run reserves in the inference.control journal before provider admission, creates a private durable App Server thread, binds the stable request ID as `client_user_message_id`, and persists thread/turn/provider/output/token observations. Reopen uses App Server `thread/queue/reconcile` with the canonical input digest; a persisted turn is read or recovered in place, `Missing` permits a same-thread retry only when the frozen context digest still matches, and transport loss never authorizes a fresh blind replay. Missing token usage remains unknown and cannot produce authorized success.
- **Local resource authority:** Serialized `ResourceGrant` values are policy data, not capabilities. `verify_resource_grant` binds every lifetime/capacity field and semantic digest into the existing kernel `FinalUseAuthority`, consumes the signed single-use grant, and returns a non-serializable `VerifiedResourceGrant`. Parsed IPC/JSON cannot directly construct an admitted worker.
- **Local physical execution:** `LocalProcessDriver` hashes exact weights, tokenizer, preprocessor, quantization, runtime binary, device descriptor and isolation receipt before connecting to a direct private Unix socket. The runtime receives the verified capacity before load/infer and must return the same observed digests and bounded memory. Output is returned as bytes/text and hashed by the worker rather than trusting a runtime-supplied output digest.
- **Isolation claim boundary:** this source proves identity/generation fencing, signed admission, exact artifact/device/isolation-receipt binding, private Unix transport, bounded memory observations and fail-closed symlink checks. It does **not** self-prove that a deployment actually configured cgroups, namespaces, seccomp, GPU/device ACLs or equivalent OS controls; those controls must be represented by the exact isolation receipt and independently qualified on the selected host before the deployment may claim OS sandbox isolation.
- **Source tests:** [codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs), [codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/model_worker_tests.rs), [codex-rs/hepta-infer-worker-host/src/local_process_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/local_process_tests.rs), and [codex-rs/hepta-infer-worker-host/tests/local_product.rs](../../../codex-rs/hepta-infer-worker-host/tests/local_product.rs). These are source test identities; exact-candidate CI is the execution receipt.
- **Remaining work is external qualification, not a repository source-boundary gap:** run identified real weights/tokenizer/runtime/device on the selected CPU/GPU host; independently verify the deployed OS/device sandbox; inject OOM, device reset, process kill, runtime disconnect and cancellation-during-unload faults; bind those receipts to the exact release candidate; obtain independent acceptance and activation/promotion/release decisions.
