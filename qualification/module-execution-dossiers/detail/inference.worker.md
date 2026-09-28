# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: the hosted App Server profile is a repository production candidate with durable admission, final-use authority and no-replay recovery. The local-model profile is explicitly feature-gated and experimental. Repository source does not establish real hardware, real-provider, deployed-issuer, independent-acceptance, activation or release evidence. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-infer-worker-host`.
Packages: `INFER-V4-T4`, `INFER-V4-T5`, `NEU-1-LOCAL-MODEL-BAKEOFF`.

Operation signatures below describe the target contract. Section 8 identifies the implemented profiles and remaining integration. Preserve the existing `inference.control` durable owner and runtime.codex effect spine; do not create a second authority or execution ledger.

## 2. Public profiles and contract details

- `HostedAppServerWorker`: production candidate, externally gated. `run` accepts a durable admission and invokes exactly one exact-generation Agent/App Server turn after final-use authority.
- `LocalModelWorker`: experimental/non-production behind `experimental-local-model`. `load_model`, `run`, `inspect` and `unload` use verified local types and an injected asynchronous driver plus independent resource observer.
- `LegacyReceiptBoundary`: validation-only. Existing pure request/lease/reservation receipt APIs are boundary primitives and cannot be labelled provider execution.

Target local signatures are `load_model(verified_manifest, verified_resource_grant) -> AttestedModelHandle`; `run(attested_handle, verified_input, cancellation, trusted_deadline) -> ExecutionObservation`; `inspect(operation_id, attested_handle) -> DriverReconciliation`; and `unload(attested_handle) -> UnloadObservation`.

## 3. State records and transaction design

Persistent request, slot, dispatch and observation facts remain in `DurableInferenceControl`. Hosted execution owns only live App Server client state. Experimental local execution owns generation-scoped aggregate accounting, attested handles, model lifecycle and request resource guards in process; persistent model files remain with the artifact/cache owner.

A signed local resource grant binds issuer, authority epoch, nonce, worker subject and generation, the complete model tuple, device identity and lease, aggregate memory, concurrency, token and usage ceilings, validity and a monotonic revocation frontier. Verified grant, manifest, input, handle and deadline constructors are boundary controlled rather than public field assembly.

## 4. Deterministic algorithm and scheduling

Hosted execution durably reserves before provider work, persists exact dispatch and authority correlation before `turn/start`, enters the non-constructible final-use token immediately before the effect, observes terminal events, and commits normalized output/optional usage before returning. A lost acknowledgement is reconcile-only and is never replayed.

Experimental local execution verifies grant/manifest/input compatibility, reserves aggregate model or request resources before driver entry, verifies independent resource observations, persists the same durable dispatch state before `run`, and uses `inspect` only after possible effect entry. Missing, pending or ambiguous recovery stays indeterminate and fences the generation. Failed unload retains the handle as `Zombie`/repair-required rather than forgetting physical state.

## 5. Capacity and performance profile

Hosted capacity is a durable local in-flight slot limit, not economic quota or provider billing. Local capacity is the checked aggregate of resident model bytes, transient request bytes, loaded models and active/quarantined requests under the verified grant.

Measure model load/unload, peak resident and transient memory, KV memory, token rate, p99 inference, cancellation-to-interrupt latency, reconcile success/miss/failure, held reservation age, missing usage and journal capacity. Pilot ceilings are design targets, not measurements; the selected target host supplies actual thresholds and evidence.

## 6. Concrete verification cases

- WORKER-01: changed tokenizer/weights/runtime/device tuple fails before inference.
- WORKER-02: forged, expired, revoked, stale-frontier or wrong-subject resource grants fail before load/run.
- WORKER-03: aggregate model plus transient request memory cannot exceed the verified grant.
- WORKER-04: kill or channel loss after durable effect entry never causes `run` replay; recovery calls `inspect` only.
- WORKER-05: failed physical unload preserves the handle and accounting as `Zombie` until trusted zero-residency repair.
- WORKER-06: missing App Server history remains quarantined; only an exact trusted provider receipt may establish terminal provider truth.
- WORKER-07: unknown token or usage observations remain `None`, never fabricated zero.
- WORKER-08: actual model consumer proof includes binary, weights, tokenizer, runtime, device lease and trusted resource observations; a synthetic driver or unit fixture does not pass it.

Repository tests cover source invariants and deterministic fixtures. WORKER-08 and named target-host fault tests require external evidence and are not satisfied by repository unit tests.

## 7. Integration, rollback and capability ceiling

Attach Neuron's encoder only after the real-model qualification gate. Rollback cannot mix old checkpoints with new encoders; unload/drain and trusted resource reconciliation precede compatible reload. Device reset fences the complete local generation.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every external gate; no generator, worker, provider adapter or CI workflow may self-accept, self-promote or self-release.

## 8. Current native implementation

- **Hosted entrypoint:** `run` in [codex-rs/hepta-infer-worker-host/src/native_run_control.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control.rs), with the physical App Server path in [native_app_server.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server.rs).
- **Hosted state and recovery:** exact thread-history reconciliation is implemented. The bounded `NativeRecoveryPolicy`, operational counters/snapshot, explicit missing-history quarantine and trusted terminal-receipt verification port are in [native_recovery.rs](../../../codex-rs/hepta-infer-worker-host/src/native_recovery.rs). A trusted receipt can establish terminal provider truth but cannot retroactively manufacture owner authority.
- **Experimental local entrypoints:** signed grants and verified types are in [experimental_local/authority.rs](../../../codex-rs/hepta-infer-worker-host/src/experimental_local/authority.rs); the asynchronous driver and trusted resource-observer ports are in [experimental_local/driver.rs](../../../codex-rs/hepta-infer-worker-host/src/experimental_local/driver.rs); aggregate RAII accounting and lifecycle fencing are in [experimental_local/resources.rs](../../../codex-rs/hepta-infer-worker-host/src/experimental_local/resources.rs); durable load/run/inspect/unload composition is in [experimental_local/durable.rs](../../../codex-rs/hepta-infer-worker-host/src/experimental_local/durable.rs).
- **Legacy boundary:** [lib.rs](../../../codex-rs/hepta-infer-worker-host/src/lib.rs) remains validation-only. The former `model_worker` path is feature-gated and deprecated and may not be used as production evidence.
- **Source tests:** [native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs), [native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs), [native_recovery_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_recovery_tests.rs) and [experimental_local_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/experimental_local_tests.rs). Test identities are not pass receipts; exact-candidate CI artifacts supply execution results.
- **Qualification:** [.github/workflows/inference-worker-qualification.yml](../../../.github/workflows/inference-worker-qualification.yml) separates infer-core, infer-worker-host and Agentd across Linux, macOS and deterministic synthetic merge; it retains library, binary, all-target, strict Clippy, clean-tree and nextest/JUnit evidence.
- **Operating references:** [RECOVERY_AND_OPERATIONS.md](../../../docs/modules/inference.worker/RECOVERY_AND_OPERATIONS.md), [CURRENT_STATUS.json](../../../docs/modules/inference.worker/CURRENT_STATUS.json), [IMPLEMENTATION_MAP.json](../../../docs/modules/inference.worker/IMPLEMENTATION_MAP.json), [LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md) and [FINAL_USE_AUTHORITY_PORT.md](../../../codex-rs/hepta-infer-worker-host/FINAL_USE_AUTHORITY_PORT.md).
- **Remaining product/external work:** compose and prove a real local weights/device driver, target-hardware OOM/reset/load-kill behavior, deployed provider terminal/usage verifier and history-retention contract, deployed final-use issuer/trusted-time/revocation/anti-rollback, named production caller, independent acceptance, activation and release.
