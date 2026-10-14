# Video Cell: schedule-matched microbatch calibration (research, not deployment)

## Why this increment is required

Previous `video_value.select` freezes FIFO-per-Cell continuation thresholds on
calibration. `video_batch.stream_cases` instead groups up to four active Cells at
one depth. Its frame cache acquires **all** frames requested at that depth
before each Cell's next-pair marginal is priced. Another Cell can therefore
make the same future frame SHA free **before** it becomes visible in the FIFO
scheduler. Reusing FIFO-calibrated prices in microbatches may change the stop
policy and invalidate an apparent same-quality resource comparison.

`video_batch_calibration.py` fixes **selection/execution schedule mismatch**, not
the small-sample population uncertainty. It uses the **same frozen Reader, the
same source-disjoint trained 15-coefficient critic, and the same 16 calibration
rows** as the FIFO experiment. There is no new optimization step. It replays
the exact microbatch grouping on frozen multi-exit *calibration predictions*
and declared frame hashes; only the current depth's probability and future
frame **identity**, never future feature pixels, influence a simulated online
stop. The per-policy SHA cache is empty at each new candidate trial and
shared across microbatches in exactly the same order as the actual executor.

Each candidate measures group-level **physical vision forwards**, unique SHA
frames, previously cached hits, and requested frame rows. Prices are chosen
from the original fixed grids. A dynamic family must match the best 2/4/6/8
fixed-depth calibration correct count; otherwise its result is a fixed-depth
fallback. Candidates minimize physical forward calls first, then unique frames
and frame rows. The *overall research-recommended arm* prefers a **fixed**
baseline on complete resource/accuracy ties. This recommendation does **not**
activate the model or select a production path.

The `microbatch_calibration` object is inserted into the original `selection.json`
**before reading any holdout row**. This is a second calibration on the SAME
small data already used to train/select the Reader/Critic/FIFO controls, so it
is **not independent confirmation**, a valid multiple-comparison adjusted
nonregression bound, or a guaranteed future-speaker/source policy. It consumes
no holdout labels to choose settings.

## Actual additional execution

`video_batch.run_shadow` retains old fixed2/fixed8/FIFO-cache-value shadow arms
and adds separately charged group-native `confidence`, `value`, `cache_value`
arms selected *on microbatch calibration*. Each arm gets a fresh frame cache.
All predictions, event receipts and the `predictions.json` aggregate are sealed
before heldout labels are read. Original scalar and grouped strong controls are
unchanged and still execute. This research study therefore **does not save its
whole-run work**: its new arms add three more heldout shadow executions.

Audits:

```bash
python -m experiments.shared_stem_cell.audit_video_value --root /staged/video
python -m experiments.shared_stem_cell.audit_video_batch --root /staged/video
python -m experiments.shared_stem_cell.audit_video_batch_calibration --root /staged/video
```

`audit_video_batch_calibration.py` imports only Python standard-library code
and the existing independent stdlib auditors, not Torch or scoring/runtime
code. It independently recalculates all seven calibration candidate families,
source/batch identities, cache membership, every grouped stop, physical call
counter, correct count and total extra shadow cost. Tampered group calls are
rejected even if receipt and aggregate hashes are recomputed. This is
**archival consistency**, not physical forward attestation.

## Observed local fixture and remaining gates

The source fixture uses **generated video frames, a synthetic vision tower, and
real PyTorch Reader/Critic learning**. For 16 heldout records, each of the
three microbatch-native policies achieved `16/16`, `32` unique frames and `4`
physical vision callbacks. The old single-Cell fixed2 arm also achieved
`16/16`, with `16` separate physical callbacks, while the original microbatch
fixed2 arm used `4`. Therefore the native NDU/critic is **not** shown to beat
the best fixed2 group baseline in this fixture. Old grouped controls consumed
another 16 vision calls, and **all** three new native controls another 12;
these diagnostic calls are charged, not falsely subtracted from total cost.

The pending GitHub-hosted real pretrained CLIP run must finish before any
real-image accuracy, latency, memory, FLOPs or energy conclusions. Only two
source videos are held out, insufficient for independent population risk,
long-horizon retention or p99 latency certification. The public sample source
metadata does not declare a license; source MP4s and derived frames are not
exported in workflow artifacts. No change to CURRENT, production routing,
permissions, computer-use effects, multimodal generation or NDU/FBSDE claims.
