# inference.worker: implementation design

Parent: `docs/modules/inference.worker/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-infer-worker-host`.
Packages: `INFER-V4-T4`, `INFER-V4-T5`, `NEU-1-LOCAL-MODEL-BAKEOFF`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
