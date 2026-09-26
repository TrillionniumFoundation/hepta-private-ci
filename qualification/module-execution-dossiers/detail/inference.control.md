# inference.control: implementation design

Parent: `docs/modules/inference.control/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable native App Server slot admission and observed settlement implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-infer-core`, `codex-rs/hepta-inferd`.
Packages: `P0.7B-B1A-PROVIDER-BOUNDARY`, `INFER-V4-T1`, `INFER-V4-T2`, `INFER-V4-T3`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`reserve_request(request, model_manifest, quota) -> InferenceReservation`; `schedule(reservation, eligible_worker_snapshot) -> WorkerAssignment`; `cancel(request_id, expected_revision) -> CancelDisposition`; `settle(observation, authority_epoch) -> InferenceReceipt`. Model, tokenizer, template, payload and token/resource limit must agree across the request, reservation and worker lease.

## 3. State records and transaction design

`inference_request` records request/principal/model/payload, deadline and state; `inference_reservation` records quota, resource and worker generation; `inference_receipt` records observed terminal output digest, usage, cancellation and unresolved outcome. Reserve and dispatch intent share a durable transaction/outbox. The worker cannot directly release or rewrite the control owner's reservation.

## 4. Deterministic algorithm and scheduling

Apply model/scope admission; reserve resources; choose an eligible enrolled worker using a deterministic feasible ranking; persist assignment; dispatch under current authority. Separate queued, running, cancelling, terminal and indeterminate states. Cancel racing completion follows an explicit settlement order; late valid usage is accounted even after a cancellation request. Provider-specific adapters cannot escape into direct ungranted calls.

## 5. Capacity and performance profile

Pilot queue <= 4096 per configured shard, scheduling batch <= 256, request metadata <= 64 KiB, retry budget only for proven pre-dispatch failures. Record model-memory reservation, token cost, queue wait, cancellation latency and unsettled reservation age.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- INFER-01: request/lease/reservation model or payload mismatch rejects.
- INFER-02: quota exhaustion prevents dispatch, not merely later accounting.
- INFER-03: cancel/finish race records one terminal settlement and no double refund.
- INFER-04: worker timeout with unknown consumption remains indeterminate until reconciliation.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

A source library that validates an observation is not proof that a real provider ran. Actual worker, runtime/device and consumer evidence remain required. Rollback drains assignments and settles current resource holders before switching scheduler/model generations.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `reserve_native` in [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs); `dispatch_native` in [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs); `settle_native` in [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs). Durable native App Server slot admission and observed settlement implemented.
- **State and recovery:** One retained owner holds `<journal>.writer.lock` and the data-file lock through replay, calls and checkpoint publication. Independent opens fail until owner drop. Replacement keeps the sidecar inode stable; mixed-version writers are unsupported. Unknown execution retains slots and replay never sends a replacement turn.
- **Incremental publication:** Legacy and native mutations stage only the affected record, append and sync the event, then publish the prepared record and derived active count. An uncertain write/sync failure fences the owner. This is single-record staging, not multi-writer delta replay.
- **Capacity and recovery boundary:** The 64 MiB / 8 MiB-line / configured identity limits remain. Per-request, state-dependent future-byte liabilities protect already-admitted terminal writes and cancellation metadata. Current-state checkpoint replacement reclaims superseded events, not identities. Tests cover rename crash cuts, publication failure, old overcommitted journals draining, maximum escaped terminal output, and process-level writer handoff. External archives and identity reclamation are not implemented.
- **Source tests:** [codex-rs/hepta-infer-core/src/native_control_tests.rs](../../../codex-rs/hepta-infer-core/src/native_control_tests.rs), [codex-rs/hepta-infer-core/src/durable_control_tests.rs](../../../codex-rs/hepta-infer-core/src/durable_control_tests.rs), and the incremental/history tests linked from those modules. These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [docs/modules/inference.control/IMPLEMENTATION_MAP.json](../../../docs/modules/inference.control/IMPLEMENTATION_MAP.json).
- **Remaining work:** Qualify target-host filesystem/power-loss semantics, external archive/identity retention and trusted backup anti-rollback. Integrate economic quota/hardware authorities and independent provider reconciliation. Exact-head and applicable synthetic-merge build/test/lint/source-binding results must be recorded for the final candidate; local owner tests do not change production, acceptance, activation or release flags.


### First observed usage after terminal release

The current native owner separates execution-slot release from missing-usage persistence. A terminal observation with `observed_output_tokens=None` releases the slot but retains 4 KiB of durable capacity. The first matching usage-only observation is written as a predecessor-revision-bound `RefineUsage` event; it does not repeat the final output payload. Failed writes leave the previous missing-usage record and counters unchanged and fence the writer. Reopen/checkpoint reconstruct that responsibility, and old full-observation usage frames remain replayable. This is not provider billing finality or unbounded history retention. The exact-source native qualification now requires its built `codex-app-server` executable through `HEPTA_TEST_CODEX_EXE`; an empty runtime-path configuration is rejected rather than silently passed.
