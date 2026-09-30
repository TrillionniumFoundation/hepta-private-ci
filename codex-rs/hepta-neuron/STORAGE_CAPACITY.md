# Completion-safe HPTNGS02 admission

The generation store admits a new operation only when

```
end_offset + commit_frame + outstanding_ack_frames + new_ack_frame
    <= min(max_file_bytes, max_startup_replay_bytes).
```

Acknowledgement sizes come from the existing canonical encoder, not a second
wire format. The outstanding-byte counter is a cache rebuilt from the validated
unacknowledged records on every reopen. It is updated in memory only after the
corresponding frame has been appended and synced. A write/sync uncertainty still
poisons the handle; reopening reconstructs both the outbox and its capacity
obligation. Historical duplicates neither reserve additional space nor invoke a
model. Same tick with different input remains a conflict.

The witness is a contiguous acknowledged prefix, starting at sequence one in
this version. Pending count and first-pending lookup therefore use that verified
prefix instead of scanning all retained payloads for every replay event. Reopen
also enforces the frozen per-checkpoint and per-receipt limits, not only the
global decoder ceilings.

## Compatibility and limits

No header, frame, event digest or operation digest is changed. Existing exact
results are not recalibrated, rewritten or deleted. An old store already written
without sufficient acknowledgement headroom can still be read within its frozen
replay budget, but this patch cannot create missing disk capacity. It rejects new
work rather than changing that store's quotas or erasing pending obligations.
A separate explicit migration/segment-retirement protocol is needed to reclaim
space; this fix is not compaction, physical preallocation, or a disk-full guarantee.
Physical ENOSPC/EROFS and sync uncertainty continue to use poison/reopen behavior.

## Verification

`tests/generation_capacity.rs` exercises the public implementation with real
files. Frame limits are measured from the production encoder. Regressions cover
one commit exhausting its ACK space, several pending ACKs across reopen, a replay
budget smaller than the write budget, and exact-capacity completion with full
receipt retry and changed-input conflict. Existing process-cut tests remain.

The read-only `neuron-storage-regression.yml` lane tests source-head and a merge
with the explicitly pinned main baseline. It records the candidate SHA/tree,
commands, toolchain, test/lint/format logs and a separate formatting proposal.
A formatting proposal does not replace a failed format check. Retention is 90
days, not a substitute for independently retained acceptance evidence. No test
source or workflow definition is a passing execution receipt or activation grant.
