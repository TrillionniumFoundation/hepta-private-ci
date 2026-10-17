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
4. Snapshotted: **native Artifact CAS owner** returns immutable payload digest,
   exact CAS readback digest and persistent registry head receipt.
5. Migrated: **native state owner** returns bound artifact, source and child state digests.
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

The checkpoint receipt commits to a domain-separated binary encoding of the
typed native observation and the frozen artifact/route binding. Reopening must
use DurableWriterHandoffJournalV1::recover_at_least with an independently
retained authenticated minimum checkpoint. The coordinator re-reads the last
ACKed native phase before any new effect, and validates the terminal retirement
readback even after it is complete.

## Product wiring still required

The generic CellSplitNativeOwnerV1 trait is **not** a production implementation.
The product host must supply actual adapters, using authorized preexisting owners:

- Artifact CAS: reuse LearningArtifactOwnerHost::ensure_payload_durable,
  ensure_registry_durable, ensure_witness_durable and acknowledge. The newly
  added observe_cell_split_artifact_cas_v1 method reopens the actual native
  publication checkpoint, historical registry and payload; verifies the CURRENT
  signed registry and reads exact bytes before returning CellSplitArtifactCasReadbackV1.
  Map its native_ack_digest/payload_digest/readback_digest/registry_head_digest
  into ArtifactCasCommitted only after independent operation-ID, admission,
  authority and frozen split binding checks. This bridge is NOT composed in a
  product CellSplitNativeOwnerV1 implementation yet.
- Child migration: old-state snapshot, idempotent new-state write, readback
  of the new child state, cancellation and recovery for unknown external effects.
- CNS: native compare-and-swap route/generation cutover, then authoritative
  query against the current generation; no route mutation on digest-only plans.
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
    cargo test -p codex-hepta-supervisor cell_split_owner
    cargo test -p codex-hepta-learning-artifacts cell_split_cas_readback
    cargo clippy -p codex-hepta-supervisor --all-targets -- -D warnings
    cargo fmt --all -- --check

Before P0 can be accepted, demonstrate a *product* caller that wires the native
owners, forces crashes immediately before/after all nine durable boundaries,
recovers from a separate process, rejects stale generations and mismatched
native receipts, and preserves every original native operation receipt and
observer signature. Then run the frozen NDU selection study and the 16-cell
target-host matrix. None of these latter gates are satisfied by this branch.
