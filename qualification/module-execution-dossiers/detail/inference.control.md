# inference.control: implementation design

Parent: `docs/modules/inference.control/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-infer-core`, `codex-rs/hepta-inferd`.
Packages: `P0.7B-B1A-PROVIDER-BOUNDARY`, `INFER-V4-T1`, `INFER-V4-T2`, `INFER-V4-T3`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
