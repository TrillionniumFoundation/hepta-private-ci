# Frozen pixel-Conv2d CPU dispatch qualification — NOT pretrained CLIP

The existing video suite demonstrates fewer *calls* to a frozen CLIP interface
for depth-synchronous microbatch dispatch. That does not establish net latency,
resident memory, throughput or energy savings. We therefore execute the exact
`FrameCacheTowers` and `video_batch.stream_cases` logic against a real CPU
PyTorch Conv2d tower, with real PNG bytes, Pillow decoding, SHA-256-bound
file reads, a single trained `AnytimeCell` GRU Reader and its frozen weights.
**The Conv2d image tower is randomly initialized and never pretrained. It is
not CLIP; its representation quality is not a proxy for pretrained CLIP.**

Run using an existing staged public-video study root (the original licensed
source status is unchanged), or the fixture constructed by test_public_video:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m experiments.shared_stem_cell.video_cpu_proxy \
  --root /path/to/staged-video-study --output /new/unique/cpu-proxy --rounds 5
python -m experiments.shared_stem_cell.audit_video_cpu_proxy \
  --root /path/to/staged-video-study --output /new/unique/cpu-proxy
```

The SHA-bound immutable protocol is written **before** Reader training or any
source-label access. The fixed 80-step Reader trains once using original source
training videos only; this is separately charged. The benchmark then uses the
SAME frozen Reader, the SAME frozen real Conv2d network, and exactly the SAME
source-bound frame identities in scalar and 4-Cell paths. Fixed2 and fixed8
policies are used, so any probability difference is a scheduling bug, not a
threshold switch. Both source-order profiles are included:
`forward_only` has lower exact-frame reuse and `paired` contains both directions
of source videos; this changes the data mix and must not be used for comparing
model quality. The 8/16/32 Cell slices measure only execution costs and do not
establish population generalization or label-independent source selection.

For each grid point there is an explicit warmup and **five** subsequent paired
CPU1 timing repetitions in alternating scalar/microbatch order. A fresh feature
cache is constructed for every arm: no contamination by earlier arms. Measures
include elapsed research-wrapper wall clock, dispatch-only stream wall clock,
process CPU, Pillow preprocess, Conv2d forward time, exact image bytes read,
unique frames, hits and physical calls, and endpoint RSS (NOT peak). Record
all rounds, even regressions. Nearest-rank p95/p99 over five samples are
descriptive extremes, not tail latency certification; energy and FLOPs remain
unmeasured. Relative speed for this *particular random Conv2d* cannot predict
real CPU/GPU CLIP. Training, all warmups and all competing arms also count in
the **whole-study** execution total: do not relabel this as production savings.

An entirely standalone standard-library auditor recomputes each batch/depth
cache miss, complete record order, probabilities and CPU timing summaries,
against the frozen cohort manifest and archived report. The output can be
recomputed from JSON without the source/derived video frames. This is archival
consistency checking, not independent time/energy attestation or legal media
rights review. Raw MP4/PNG frames and pretrained weights are excluded from
retained CI artifacts. Nothing activates production or satisfies FinalUse.
