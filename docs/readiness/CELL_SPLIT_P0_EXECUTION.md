# Cell Split P0: receipt-gated Supervisor execution seam

**Status: source-only, not product-composed, not target-host-qualified.**
**Default:** no automatic Cell Split, activation, production promotion or physical split.

This specification accompanies codex-rs/hepta-supervisor/src/cell_split_owner.rs.
It does not change the durable writer-handoff format, override independently
issued final-use authority, or give learning.plasticity self-authorization.

## Exact native sequence

The single Supervisor journal owner advances one observed phase at a time:

1. AdmissionStopped: predecessor admission owner attests stopped admission.
2. Drained: native outbox readback reports a stable watermark and zero unknown effects.
3. OldWriterFenced: authoritative writer lease/fence readback rejects old result commits.
4. Snapshotted: **two independent native readbacks are required**: the Artifact
   CAS owner's acknowledged immutable payload, exact bytes and signed registry
   head; AND the authoritative predecessor State Owner's durable state-snapshot
   receipt bound to the original writer, operation, scope and Generation. Model
   payload publication alone cannot satisfy the native writer Snapshot phase.
5. Migrated: **native state owner** returns bound artifact, source and child
   state digests. Its source digest must equal the predecessor's observed
   Snapshotted-state digest; an unrelated child-state migration fails closed.
6. Validated: child bootstrap owner returns loaded artifact and observed state readback;
   the coordinator requires it to match the preceding migration.
7. NewWriterFenced: **Supervisor / writer lease owner** returns the exact successor fence.
8. RoutePublished: **CNS owner** returns the old/new hierarchy digests and new
   observed generation following real route replacement.
9. Retired: **writer owner** observes old generation retirement and unchanged
   active successor route.

For every phase the adapter must issue an authenticated lookup against the
authoritative native owner. execute(phase) success alone is never evidence.
A conclusive native Absent permits one idempotency-keyed execution; timeout,
split-brain, unavailable receipt, uncertain commit or indeterminate readback must
return Indeterminate and MUST NOT trigger a retry.

Before EVERY phase change, the Supervisor now reopens its existing bounded,
fsync-backed Writer Handoff Journal under the same exclusive lock, verifies
the full revision/receipt hash chain against the current acknowledged head,
and compares each earlier native owner's present authenticated historical
readback with the exact evidence digest first recorded for that phase. The
durable split Binding commits to the exact Artifact ID as well as the content
digest; identical bytes in a different registry lineage are not interchangeable.
An owner may not substitute a newly valid-looking Drain, old writer fence,
Artifact CAS, predecessor snapshot, child migration, boot validation, successor
fence or CNS route receipt after the journal has advanced past that phase.

The coordinator therefore re-queries the native CURRENT Artifact CAS owner
on every later change including route publication and retirement. Any source
revocation, missing native receipt, payload tamper, changed historical receipt,
or indeterminate result blocks further external effects even when an older
CAS checkpoint remains structurally valid. This full-chain reread is bounded
by the journal's existing 8 MiB cap; it does NOT replace independently retained
anti-rollback minimum custody or native signature verification.

The checkpoint receipt commits to a domain-separated binary encoding of the
typed native observation and the frozen artifact/route binding. Reopening must
use DurableWriterHandoffJournalV1::recover_at_least with an independently
retained authenticated minimum checkpoint. The coordinator re-reads the last
ACKed native phase before any new effect, and validates the terminal retirement
readback even after it is complete.

## Native readback bridge (separate crate)

The independent codex-hepta-cell-split-executor crate implements
ProductSplitNativeReadbackV1. Its construction requires the opaque
VerifiedSelfEvolutionSelectionV1 token produced by independent NDU evaluation,
selector-signature verification and role separation. The signed predecessor Cell identity, candidate ID,
exact Artifact ID and digest, predecessor/successor generations, frozen no-change baseline
and exact selection digest must match the Supervisor's immutable binding. A
plain selection checksum alone is NOT authorization. Only the binding digest
is persisted in the Supervisor observation chain, and the product bridge must
retain a verified token throughout execution. This is selection *admission*,
not proof that the NDU learning loop has completed target-host qualification.

Each advance_receipt_gated_phase and attach_live_cutover call now requires a
fresh trustworthy timestamp, monotonically nondecreasing across the bound
operation; a bootstrap clock reading must not be reused for later Artifact
CURRENT expiry checks. A native snapshot query against the predecessor State
Owner is mandatory before Snapshotted can commit. Until that owner is really
composed the bridge returns Indeterminate and refuses unsafe CAS/CNS writes.

The bridge connects the **real**
LearningArtifactOwnerService::observe_cell_split_artifact_cas_v1 and
HeptaRuntime::observe_governed_topology_cutover directly to the locked
Supervisor CellSplitOwnerV1 native lookup trait. It keeps Agentd and Worker
free of new direct Supervisor/Runtime dependency edges.

It binds the exact Artifact publication operation and payload, and separately
binds the CNS proposal/candidate, its native handoff digest and the Final-use
request digest. A current signed Artifact registry is mandatory. CNS readback
requires the *same live Runtime owner's* previous successful Final-use apply
receipt and actual current graph re-read. No route receipt can survive a process
restart by assertion alone.

ProductSplitNativeReadbackV1::advance_receipt_gated_phase is the
single-step source composition into the real fsync-backed Supervisor
DurableWriterHandoffJournalV1. It uses the same validated, immutable
CellSplitBindingV1 rather than bypassing CellSplitOwnerV1.

This adapter **intentionally refuses** to execute native Artifact/CNS
side effects. Those effects require their original idempotent publication
service and independently authorized Final-use route owner. Unknown native
effects yield Indeterminate; a missing receipt is never treated as a conclusive
negative result. Other stages must be supplied by separate real domain owners,
not by an implicit default allow or a digest oracle.

Accordingly, this integration is a **partial native readback composition**,
NOT the required full production Cell Split executor.

## Product wiring still required

The generic CellSplitNativeOwnerV1 trait is **not** a production implementation.
The product host must supply actual adapters, using authorized preexisting owners:

- Artifact CAS: reuse LearningArtifactOwnerHost::ensure_payload_durable,
  ensure_registry_durable, ensure_witness_durable and acknowledge. The newly
  added observe_cell_split_artifact_cas_v1 method reopens the actual native
  publication checkpoint, historical registry and payload; verifies the CURRENT
  signed registry and reads exact bytes before returning CellSplitArtifactCasReadbackV1.
  The product service additionally **requires an independently retained
  signed current-head recovery floor**; without that floor it refuses to issue
  a split CAS proof, even when local signed snapshots look consistent.
  The service also binds the native ACK to the exactly one Register event
  created by this publication, rather than a coincidentally matching artifact
  from unrelated history. The bridge maps the authenticated native receipt
  into the source-only CellSplitNativeOwnerV1 lookup implementation; no
  production Artifact publication execution role is installed by the bridge.
- Child migration: actual predecessor State Owner's durable snapshot must
  be observed through lookup_predecessor_snapshot before Snapshotted advances.
  The snapshot ACK and content digest are included in the Supervisor
  observation commitment and must match the Migrated source-state digest.
  The independent state Owner must still provide idempotent child-state write,
  readback, cancellation and recovery for unknown effects.
- CNS: the new HeptaRuntime::observe_governed_topology_cutover verifies
  that a real Final-use-guarded transition receipt equals the in-process
  runtime owner's last successful apply receipt, and that the live route still
  has the exact successor hierarchy and generation. A forged receipt and a
  process restart fail closed. This is **process-local** evidence only: a
  durable CNS CAS route owner, native persistent cutover receipt and restart
  reconciliation remain to be composed; no route mutation on digest-only plans.
- Supervisor: persistent writer authority fence, old task/result rejection
  and exclusive successor writer issue after independent final-use admission.
- Observer: separate signed evidence of reconciliation and outcome windows.
  No role may both generate and accept its own candidate.

The Supervisor file lock serializes local calls only. Real remote/native owners
MUST independently enforce operation idempotency, monotonic generation fences,
revocation and stable historical receipt reads. Receipt hashes are **not**
signatures. Retaining a checkpoint solely inside the same rollback domain as
the journal does not prevent backup rollback or media loss.

## Qualification and gates

The isolated test owner uses fsync-backed fixture files to force observable CAS
readbacks, migration state readbacks, route readbacks and fault states. These are
**fixture native owners**, not the real production CAS or CNS and not a
physical power-loss test.

Run when a matching Rust toolchain is available:

    cd codex-rs
    cargo test --locked -p codex-hepta-supervisor cell_split_owner
    cargo test --locked -p codex-hepta-learning-artifacts cell_split_cas_readback
    cargo test --locked -p codex-hepta-learning-artifacts named_owner_service_publishes
    cargo test --locked -p codex-hepta-runtime governed_topology_requires_final_use
    cargo test --locked -p codex-hepta-cell-split-executor
    cargo clippy --locked -p codex-hepta-supervisor -p codex-hepta-learning-artifacts -p codex-hepta-runtime -p codex-hepta-cell-split-executor --all-targets -- -D warnings
    cargo fmt --all -- --check

Before P0 can be accepted, demonstrate a *product* caller that wires the native
owners, forces crashes immediately before/after all nine durable boundaries,
recovers from a separate process, rejects stale generations and mismatched
native receipts, and preserves every original native operation receipt and
observer signature. Then run the frozen NDU selection study and the 16-cell
target-host matrix. None of these latter gates are satisfied by this branch.
