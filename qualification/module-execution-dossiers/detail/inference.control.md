# inference.control: implementation design

Parent: `docs/modules/inference.control/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: V2 exact-plan native execution, unique writer actor, signed recovery and checkpoint/archive maintenance are source-composed; exact-candidate evidence and external qualification remain required. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-infer-core`, `codex-rs/hepta-infer-worker-host`, `codex-rs/hepta-inferd`.
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

- **Current operation registry:** [generated current state](inference.control.current-state.md), [implementation status](../../../docs/modules/inference.control/TECHNICAL_STATUS.generated.md), [operator runbook](../../../docs/modules/inference.control/OPERATIONS.md) and [writer boundaries](../../../docs/modules/inference.control/WRITER_BOUNDARIES.md) describe the V2 candidate. Sections 1–7 retain target designs, not a second registry of current symbols.
- **Exact-plan product path:** Manifest/quota/resource/data-policy signatures from four distinct actual verification keys bind one execution; final-use verification, synced dispatch and a one-shot pre-effect capability precede provider effect. `AppServerModelDriver::run_authorized` uses the unique writer actor for protected-output settlement. Production actor paths deny legacy compatibility execution.
- **Concurrency and durability:** One actor owns `DurableInferenceControl`. A stable lifecycle sidecar lock is acquired before active journal open/replay and retained across checkpoint inode replacement; the active inode lock remains for compatibility. Never delete the sidecar. Cloned handles feed one bounded FIFO; provider execution runs outside the writer. Ambiguous storage/replacement errors poison the owner. Accepted response loss/timeout does not cancel the command or permit replay.
- **State and recovery:** `Reserved`, `Dispatching`, `Running`, `Cancelling` and `Indeterminate` retain capacity. Matching terminal evidence, explicit safe rejection, proven pre-effect stop or audited retirement can release it; restart cannot recreate a pre-effect capability or dispatch a replacement. Production reopen recovery uses independent fresh signed evidence or revision-bound dual-control retirement. Proof expiry is rechecked at durable consumption, with owner wall-clock sampling in the recovery actor. Dual control requires different actual public keys as well as signer/key IDs. Missing usage remains unknown. Signed terminal receipts preserve historical owner authority or `Unverified` when absent; they cannot mint `ObservedReady` or erase lost authority.
- **Usage and output:** When exact binding and current output policy admit a matching terminal observation, actual tokens/reported signed cost above quota are retained with released capacity and quarantined qualification. Late monotonic usage can lower qualification but cannot turn denied success into success. Protected-output metadata is rechecked against the signed policy, including required reference/cipher/key fields; these checks do not independently prove encryption or deletion. Exact-plan active journals contain no plaintext output; historical compatibility records and predecessor archives may contain plaintext.
- **Capacity and checkpoints:** Active journal <=64 MiB, line <=8 MiB, combined distinct legacy/native records <=16384, and native admission/dispatch requires 16 MiB headroom. Checkpoint/archive compaction recovers byte headroom while retaining all request identities, including released ones. Replay validates checkpoint content and recorded archive bindings; it does not rehash every historical archive file.
- **Compatibility upgrade:** New checkpoints use schema 2; schema 1 remains readable with full state/observation/audit semantic validation. Schema-1 signed-reconciliation `ObservedReady` without independent host evidence becomes `Unverified`, retaining provider facts. Retirement audits now preserve distinct actual-key fingerprints; historical audits without them remain held `Indeterminate` until fresh revision-bound dual control, and over-budget recovered holds fail closed. Unsupported schemas are rejected.
- **Module placement:** `InferenceLedger` is an in-memory authority-denied compatibility ledger. `hepta-inferd::plan` is a pure digest/deadline planner, not an enrolled-worker scheduler. Typed neuron feature contracts and worker/consumer projections still need a real control port, selected worker and Agentd daemon lifecycle composition.
- **Remaining repository work:** Retain final exact-source-head/base-merge/native-host receipts; implement selected telemetry export/alert delivery, signed vault deletion confirmation and archive retention/transfer; define a bounded request-retention/dedup lifecycle beyond the distinct-record ceiling; complete real feature-port/scheduler/capacity/billing composition.
- **External qualification:** Independently operated issuers, vault encryption/deletion, real provider/model/device behavior, selected-host fault/pressure/timing and independent acceptance/canary/release remain evidence gates. Source libraries or repository CI cannot supply those authorities.
