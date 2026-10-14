# Source-disjoint CPU microbatch selection — research only

`video_cpu_tune.py` adds a new **label-blind CPU runtime scheduling control**
for the previously staged ten-video temporal-order study. It does not change
`video_value.py`, model structure, the NDU decision rule, original execution,
or ANY production scheduler. The existing fixed batch-4 microbatch experiments
are retained for comparison.

## What this controls

After training **one** shared GRU Reader on six video sources (48 paired
records, 80 optimizer steps), use two distinct calibration sources to compare
microbatch sizes **1, 2, 4**, separately for six registered workloads:
forward-only 8 Cells at depth 2/8; paired 8 and paired 16 Cells at depth 2/8.
All six workloads have entirely source-disjoint two-video holdout sources.
No original source video crosses any fold. Predictions are compared across
schedules before optimizing for time; unequal fixed-depth outputs fail.

Use an **identical frozen real CPU Conv2d feature tower**, SHA-bound PNG inputs,
Pillow decoding/resizing and the same trained PyTorch GRU in all arms. The
pixel tower is **randomly initialized and frozen, NOT CLIP/pretrained**.
Calibrate on **three wall-clock rounds** with batch execution order rotated
across rounds; warm up every arm once, separately charge the warmups. Choose
the smallest batch whose median calibration wall time is within **5% of the
fastest calibration median**. This is a heuristic for a noisy environment, not
a confidence interval, proof of optimality or production enablement.

Freeze and seal the selection before executing any holdout arm; repeat **five
holdout rounds**, count all three comparison arms and reveal labels only for
final descriptive scoring. The original public records contain labels, so the
loader materializes them; the schedule selector's argument includes **only
calibration timing**, and receives no labels. A new future source, independent
pretraining-clean split or long-lived runtime trace has not been supplied.

## Full resource and latency accounting

Every arm starts from an isolated empty feature cache, with exactly the same
Reader and convolution weights. Log original requested frame rows, exact
unique SHA frames, actual Conv2d batches, physical forwards, image read bytes,
PIL time, convolution time, wrapper time and process CPU time. Log training,
calibration, warmups, holdout and **all shadow arms**, not just the selected
arm. Total study time includes their overhead. RSS endpoints are **not peak
RSS** and do not establish memory savings; energy and GPU numbers are absent.

Additionally, assume all Cell requests arrive at **t=0**. The FIFO group
completion time equals the sum of prior and current group wall times. This
reports **first-result completion** and each Cell's p50/p95/p99 completion;
these approximate group-internal completion and exclude some wrapper work,
so are **not production RPC latency distributions**. The five-run tail
statistics are descriptive, not population-level p95/p99 guarantees.

The standard-library `audit_video_cpu_tune.py` independently replays cached
frame SHA misses, the full rotated schedule, model outputs, per-Cell group
completion times, calibration medians and small-batch tie policy, sealed
prediction identities and scores, and complete charged work including warmup.
It uses only archived JSON and dataset/cohort manifests; **no PNG/MP4 or
model package** is needed to audit. Passing this audit checks consistency, not
external attestation of physical timing or hardware counters.

## Reproduction

Run after the normal `public_video` staging using:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m experiments.shared_stem_cell.video_cpu_tune \
  --root /scratch/video-study --output /scratch/video-study/cpu-tune \
  --calibration-rounds 3 --evaluation-rounds 5
python -m experiments.shared_stem_cell.audit_video_cpu_tune \
  --root /scratch/video-study --output /scratch/video-study/cpu-tune
```

Default workload includes six source-disjoint timing profiles; reduced
workloads/rounds are available **only** as explicit Python test arguments.
Source MP4 and derivative frames are not persisted to GitHub artifacts because
the video source repository declares no license in its metadata. This does not
assert that the source is legally cleared for a product dataset.

**Research status:** this tests a CPU scheduling question with an untrained
surrogate, not real CLIP throughput, GPU kernels, memory/energy savings,
semantic video capability, learned System 2 gains or product acceptance.
Do not promote quality or deployment based on these proxy results.
