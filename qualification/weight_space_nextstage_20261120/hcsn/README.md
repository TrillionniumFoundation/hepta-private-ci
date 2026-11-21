# Fixed-law HCSN finite-horizon specialization

Date: 2026-11-20 (America/New_York); execution 2026-11-21 UTC.

The raw records, checkpoints and frozen execution protocols named below are
retained in the separate research evidence bundle. This public directory contains
source and public upstream retrieval pins only. A replay requires those records;
source publication does not authorize a new scientific run.

## Outcome

**All six real trained checkpoints passed the frozen numerical contract.** This is a compute specialization of the existing model with frozen physics; no parameters were trained or edited. It does not claim a classification-quality improvement, bitwise equivalence, production adoption, or full-state memory reduction.

The six checkpoints are flow and flow_fixed, seeds 101/211/307, from hepta-private-ci #6754 at 298fae004356f4adb5b58f2bc4d61fdde5bdab75. All 831 historical archive members were independently hashed before copying the six selected checkpoints and original TRAIN data. Forty-five exact source/input files were frozen before the scientific child.

## Compiled mathematical structure

With rate_drive=False, probability and timing law do not depend on the sample. Signed content evolves linearly conditional on this law. An impulse written at time s produces a known emission and full-state response at each later time t. Precompute the time-varying triangular kernel K[t,s]; keep each original writer and tanh, and retain the one-interval interlayer latency. The final signed-state fields and each pending Flux.alpha are linear combinations of the same impulse basis. Probability, generator, reset law, discount and event times remain unchanged.

This requires the declared zero signed initial content, fixed CPU FP64 physics, exact rational dt and fixed horizon. Input-driven rate changes, physics gradients, horizon mismatch and modified cache constants are rejected. A new law or horizon requires recompilation. The implementation does not compress arbitrary histories into constant memory.

## Numerical qualification

| Measure | Result |
|---|---:|
| Original source classifier parity, max abs | 2.6645352591003757e-15 |
| Full output/state/emission, max abs | 3.5527136788005009e-15 |
| One-step cold continuation, max abs | 1.3322676295501878e-15 |
| Input/writer/readout gradient, max abs | 4.4408920985006262e-16 |
| Independently reread paired arrays / coordinates | 2334 / 1,553,274 |
| Recorded bitwise mismatches | 941,367 |
| Frozen error rule | abs <= 1e-10 + 1e-9 * abs(reference) |
| Argmax agreement | all 18 declared cases |
| Operational fault rejections | 30 / 30 |

The large count of unequal FP64 bit patterns is retained. These are tolerance-based functional checks, a new contract that does not replace the existing N256 strict-bitwise RED evidence. Gradients exclude raw_cost/task physics because these tensors are frozen; compiled execution rejects requires_grad physics. Original full-graph forward was separately checked on every selected checkpoint, while repeated timings compare the two frozen-physics execution paths.

## Measured complete-call cost

Each row aggregates 18 timed calls: six checkpoints times three fixed interleaved repetitions. Each optimized call checks graph/physics/cache identities, performs nonlinear writers and readout, and reconstructs the entire final state. No test labels or adaptive selection were used.

| Input | Reference wall total (s) | Specialized wall total (s) | Ratio of totals | Complete state bytes, both paths |
|---|---:|---:|---:|---:|
| training64 | 0.911938267 | 0.056706814 | 16.082 | 521,360 |
| synthetic1 | 0.683056361 | 0.035197404 | 19.406 | 20,384 |
| synthetic20 | 1.527169217 | 0.035070759 | 43.545 | 158,448 |

Twelve compilation calls together cost 0.571414554 CPU seconds and 0.570301468 wall seconds. Compiled constants occupy 23,776 bytes at T=10 and 85,536 bytes at T=20, **in addition to** the reconstructed state. Build-only break-even is below one call for the measured cases, but this excludes development, qualification, package loading and deployment costs; it is not a universal amortization promise.

Short process CPU timers returned exact zero for 22 optimized timing observations; all zeros are preserved and no per-call infinite ratios are reported. Wall totals are reported alongside nonzero aggregate CPU totals. These single-host sequential measurements are descriptive, with no hardware-independent or production throughput claim.

## Complete research cost and provenance

- One scientific child, exit 0: 10.223666000 CPU seconds, 10.297324210 wall seconds; peak RSS 240,803,840 bytes.
- Independent NumPy-only arithmetic reader body: 0.571576425 CPU seconds; zero Torch imports, model forwards or optimizer calls.
- Actual counters: {"checkpoint_writes": 0, "compile_exponentials": 984, "compiled_forward": 96, "continuation_steps": 36, "gradient_backward": 36, "optimizer_calls": 0, "original_classifier_forward": 6, "reference_exponentials": 6696, "reference_forward": 90}.
- No checkpoint writes. All six original file hashes and every loaded model tensor remained equal.
- Initial outer launch failed before Python because /usr/bin/time was absent (exit 127, zero model calls). Its stderr and LAUNCH_UNAVAILABLE.json are preserved. A separately sealed standard-library supervisor then ran the sole scientific child; there was no retry of model execution.
- Setup/download/extraction and environment installation are outside the scientific-child cost and are not represented as free.

## Reproduction and evidence

The source/input freeze is PROTOCOL_FROZEN.json; its SHA256 is 6c0920e48dd99a5428d45e149dcb68bda28fc91d49189f5438d5d41718bd77c6. The exact upstream source/archives can be retrieved by fetch_sources.py, then authenticated/extracted by extract_originals.py. Original archive SHA256 is b6f4969ccc5f75b526223b9f83ff0c6348a324ad3bc93342558a13f72b5fe35c. Do not overwrite attempt001 or relabel a new execution as this run.

Pinned runtime: Python 3.12.14, Torch 2.8.0+cpu; original NumPy 2.3.5 / SciPy 1.17.0 / ncps 1.0.1 package versions are recorded upstream. Our Torch dependencies were obtained in an isolated path; no production runtime was changed. A fresh execution requires a new identity and its own source/runtime/cost seal. The retained 60 NPZ files hold both sides of every numerical comparison; read_results.py rechecks all arrays without model execution.
