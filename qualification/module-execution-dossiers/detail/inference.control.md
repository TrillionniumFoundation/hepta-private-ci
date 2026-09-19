# inference.control: implementation design

Parent: `docs/modules/inference.control/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable native App Server admission now binds cross-checked quota/resource evidence, conservative token/economic holds and an exact signed final-use grant; read-only post-crash terminal reconciliation and bounded journal compaction are implemented. Remaining target composition/scheduling and independent deployment acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** `reserve_native`, `dispatch_native`, `cancel_native` and `settle_native` in [codex-rs/hepta-infer-core/src/native_control.rs](../../../codex-rs/hepta-infer-core/src/native_control.rs); deterministic feasible multi-worker `schedule` in [codex-rs/hepta-inferd/src/lib.rs](../../../codex-rs/hepta-inferd/src/lib.rs); `DurableInferenceControl::compact_native_journal` in [codex-rs/hepta-infer-core/src/durable_control.rs](../../../codex-rs/hepta-infer-core/src/durable_control.rs) folds native history into exact snapshots while retaining a bounded private content-addressed predecessor archive.
- **Admission and quota:** the native host validates cross-bound `QuotaReservation` and `ResourceAdvertisement` evidence before reserve. One reservation enforces request count, output-token holds, active concurrency and conservative owner-defined economic budget units. A proven pre-dispatch stop releases token/economic holds; after a possible provider effect, missing token usage retains the token maximum and economic budget is not fabricated as refunded.
- **Scheduling and physical dispatch authority:** `hepta-inferd::schedule` canonicalizes at most 256 candidate workers, rejects duplicate/invalid candidates, filters by exact model/token/concurrency feasibility, and deterministically ranks by explicit preference, remaining token capacity and stable worker ID. The complete eligible snapshot and selected generation are digest-bound; its resulting plan remains `DENY_ALL`. [codex-rs/hepta-infer-worker-host/src/native_policy.rs](../../../codex-rs/hepta-infer-worker-host/src/native_policy.rs) then constructs the final-use binding from the exact request/provider/model/context/payload and current authority epoch. A kernel-owned `FinalUseAuthority` consumes the signed grant before `turn/start`; the durable dispatch record stores the matching witness. Terminal success additionally requires a final authority revalidation.
- **State and recovery:** DurableInferenceControl remains the single locked/synced writer. Reopened possibly-dispatched runs never issue another turn. The worker performs a read-only `ThreadRead` against the exact persisted thread and can settle a matching `Completed`/`Failed` observation without replay. Because `VerifiedUseToken` is intentionally non-serializable, a restart can establish terminal effect truth and release local concurrency but cannot recreate final-use authority or retroactively report successful authorization.
- **Source choke point:** [scripts/hepta-inference-control-boundary.py](../../../scripts/hepta-inference-control-boundary.py) verifies the Hepta production Rust `turn/start` callsite and ordering `claim_turn -> dispatch_native -> TurnStart`. [hepta-lane-b-truth.yml](../../../.github/workflows/hepta-lane-b-truth.yml) is triggered by inference owner/worker changes and runs the inference libraries, binaries and boundary guard.
- **Source tests:** [codex-rs/hepta-infer-core/src/native_control_tests.rs](../../../codex-rs/hepta-infer-core/src/native_control_tests.rs), [codex-rs/hepta-inferd/src/lib_tests.rs](../../../codex-rs/hepta-inferd/src/lib_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_policy_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_policy_tests.rs), [codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs) and [codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs](../../../codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs). Test identity is not an execution receipt; exact-head CI supplies candidate-bound results.
- **Repository source boundary:** no remaining inference.control source gap is recorded for request/reservation/scheduling/final-use dispatch/reconciliation/compaction. The named non-test source entrypoint is `hepta-infer-worker --profile native-app-server`; it remains inactive until Supervisor/Agentd deployment composition supplies owner-issued current policy/grant inputs.
- **External evidence still required:** activate the named worker under the deployed Supervisor/Agentd composition; real provider billing reconciliation, measured physical device-capacity authority, deployed signer/revocation behavior, target crash/cancellation/reconciliation/retention qualification and independent acceptance. Source budget units and resource advertisements do not by themselves prove provider charges, VRAM/device availability or production activation.
