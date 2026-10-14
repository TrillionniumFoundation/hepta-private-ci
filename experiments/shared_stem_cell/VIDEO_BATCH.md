# Shared frozen CLIP + many light temporal Cells: microbatch strong control

Research-only extension of `VIDEO_VALUE.md` and Draft PR #1875. The existing
single-Cell study, trained GRU Reader, disjoint Reader/Critic/calibration/holdout
sources, `value`/`cache_value`/`confidence`/fixed-depth arms and postseal scalar
auditor are retained. The new experimental `--microbatch-shadow` uses the
**same fitted GRU and the same presealed policies** to compare two execution
schedules, not new training, an NDU optimizer or a new authority.

## Execution and resource semantics

- Original FIFO serial: complete each video Cell to its stopping point before
  serving the next one; SHA feature cache persists between rows within an arm.
- New grouped schedule: in groups of up to 4 Cells, request *only the active*
  Cells' 2-frame chunks synchronously by depth. Deduplicate the batch's frame
  SHA identities, perform one frozen CLIP call for all missing frames (up to
  8 requested frames), then perform two **batched GRUCell** state updates.
  Stopped Cells never enter later CLIP requests. One shared Reader instance;
  no CLIP/model copies and no recurrent state mixing.
- Test arms: fixed2, fixed8, and cache-aware NDU. All start with a separate
  empty cache; the base CLIP model and its physical call counter remain shared
  solely for the research process. Each batched arm is **extra shadow work**.
- Grouping changes which earlier Cell features are visible to a later Cell's
  cache-aware stop decision. Therefore `cache_value` may make different
  *legitimate* decisions, while fixed-depth predictions/depths must remain
  unchanged within a fixed numeric tolerance. Changed cache-aware depths and
  changed costs are reported, never silently treated as equivalent.
- Physical CLIP call costs belong **once to the group**, never multiplied by
  Cell count. Events show active Cell IDs, requested frame rows, physical
  forward delta and measured group wall/CPU intervals. The original serial
  per-row timing includes a different request schedule. Batch CPU time and
  memory are not interchangeable with end-to-end latency or GPU energy.

CLI after public source staging:

```bash
python -m experiments.shared_stem_cell.video_value \
  --manifest /staged/video/manifest.json \
  --output /staged/video/value --microbatch-shadow
python -m experiments.shared_stem_cell.audit_video_value --root /staged/video
python -m experiments.shared_stem_cell.audit_video_batch --root /staged/video
```

Default execution without `--microbatch-shadow` remains unmodified. The
stdlib-only `audit_video_batch.py` independently replays active rows, exact
frame SHA cache membership, group-level forward counts, original source
identities, Critic logits and sequential-stop constraints. It also compares
both separately sealed experiment receipts and *rejects deliberately rehashed
forgeries*, but **cannot attest** actual CLIP hardware instructions.

The simulation fixtures use generated media / a deterministic **synthetic**
visual tower with real PyTorch GRU calculations. Their observed batching
throughput and physical callback reductions are **not** a claim of true
pretrained CLIP, final product speedups, source-video generalization or
quality-retaining compression. Source MP4 and derived images stay excluded
from uploaded workflow artifacts while their license remains unverified.

The real-CLIP CI must run on the exact committing SHA before any hardware
p50/p95/p99 or incremental encoder savings can be attributed to this change.
The 16 paired holdout rows from only two source videos cannot certify tails
or population risks. No new permissions, CURRENT, split topology, FinalUse,
computer use effect authority, audio/video generation or full NDU/FBSDE claims.
