# Independent grouped Head fitting on shared feature tensors

Parent: `c17d2b9e017b7a47330c3826f50c5327a547d524`, existing Draft PR #1648.
This is a separate ordinary-Torch learning change. It does NOT incorporate or
republish the previous unpushed native Q24/kernel patch. No code generator,
machine-code loader, production owner, authority or Rust dependency is changed.

`development_head_training.fit_linear_cells` groups at most 32 independent
Linear Heads for batched matrix multiplication. It preserves the existing
`development_ablation.fit_candidate` SGD profile, learning rate, per-Cell random
minibatch stream and norm-1 clipping. The objective sums individual per-Cell mean
cross-entropies; averaging across Cells would silently change their gradients.
Gradient norms include each Cell's own weight and bias, not the whole bank.
Unequal training counts are masked and independently normalized; padded lanes
are charged as physical work, not counted as useful examples. Only supplied
Cells acquire candidate copies; selected/source parameters and absent peers
are not changed. Complete input validation precedes any optimizer entry.

The low-level fitter accepts up to 4096 Heads within the 4,194,304-parameter
budget, CPU float32/float64, shared width <=512, classes <=128, 1..1000 updates.
This is not general dynamic-gated, nonlinear, recurrent or AdamW fitting.
`development_learning.py --head-batch-size 2..32` is the optional real consumer:
it keeps the existing whole-census scope/fold/time and safe offline weight loader,
reuses identical in-scope feature rows, then trains separate Heads. Default 1
retains the original scalar fitter. The consumer still has its original 64-Cell /
4096-row envelope. The 4096-Head benchmark is NOT 4096-Cell product integration.

The study fixes three seeds (1111/2222/3333), four sizes (1/64/256/4096), identical
initial weights, per-Cell examples/update counts and random streams before work.
Both fitting arms execute independently; setup, warmup, training and verification
are measured separately. Full fitting time includes validation, packing, candidate
copying and content checks. It reports no p95/p99 or statistical speed guarantee
from three trials. Features and four label-generating task families are SYNTHETIC;
64 repeated source inputs per size are not thousands of independent observations.
All output classifications are saved before the scoring pass.

Three complete fresh-process final-source runs show scalar/grouped total fitting
wall ratios: 64 Heads 5.97..6.73; 256 Heads 5.17..5.95; 4096 Heads 5.02..5.63.
Single-Head grouping is slower (ratios 0.66..0.86), so no automatic/default switch
is made. Across these registered CPU profiles, every trained parameter and heldout
logit matched exactly; this is empirical equality, not a universal numerical proof.
Each 4096-Head arm performs 655,360 useful example updates and five SGD updates
per Head. Optimizer dispatches reduce from 20,480 scalar to 640 grouped calls,
not from fewer per-Cell training steps. The parameter bank is 12,615,680 raw bytes;
source/candidate copies, activations, Python metadata and process memory are extra.
Whole-process RSS is reported only as a combined high watermark, not per-arm RAM.

114 sparse-source tests pass: 95 retained plus 19 new. Tests compare the existing
scalar fitter, ragged and single-row batches, float64, clipping under large peer
gradients, independent RNG streams across grouping/order, group tails, source
immutability, aggregate bounds and fail-before-optimizer behavior. A synthetic
SharedStemEngine integration preserves actual encoder counts and predictions,
reducing materialized feature tensor rows from 24 to 12; raw cached feature objects
remain additional memory. No real pretrained weights or independent NDU result.
A combined shell execution timed out during the third study; its incomplete
outputs are retained and clearly marked. A new directory contains the complete
same-seed rerun; historical timings/source versions are not relabeled.

The existing read-only head/merge CI keeps every prior test and study, adds these
regressions and one complete 1..4096-Head study. Exact-head hosted CI, global
Rust/Bazel/security and original product admission remain mandatory. No main
merge, production model promotion, native patch publication or runtime activation.

```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest -v development_head_training_checks
PYTHONPATH=qualification/stem-cell-v1 python \
  qualification/stem-cell-v1/development_head_training_study.py --synthetic \
  --seed 1111 --output /new/head-training-study
# Existing real-weight CLI: add --head-batch-size 32 to development_learning.py.
# Supply approved local safetensors and frozen public rows/TRAIN labels as before.
```

## Input-dependent gated Heads on the same grouped fitter

Parent: `4ae44223437d307962b5306bcf541b1a42db328b`. The preceding Linear
results remain historical. `SwiGLUCellHead` now supplies a private gate, value
projection and readout per Cell: `readout(silu(gate(x)) * value(x))`. Shared
features are detached; all six weight/bias tensors learn independently. This
is ordinary Torch, not machine-code generation or the unpublished Q24 patch.
The internal grouped SGD implementation is reused for Linear and SwiGLU;
existing Linear defaults and tests are retained. New opt-in real consumer
arguments are `--head-kind swiglu --head-hidden-size 8 --head-batch-size 32`.
The safe offline Encoder loader, sealed training-label API and 64-Cell/4096-row
consumer envelope are unchanged. This nonlinear Head is not an affine Q24 export.

Per-Cell mean cross-entropy is summed across the group. Gradient clipping
includes that Cell's gate, value and readout, not another Cell's parameters.
Ragged minibatches, distinct RNG streams, source immutability, padded work and
whole-call resource limits retain the original semantics. The constructor and
fitter reject mixed dimensions, frozen/missing/extra projections, invalid data
and aggregate over-budget parameters before any optimizer. Failures never
select a fallback model or change live Cell state.

Three predeclared fresh-process seeds 1414/2525/3636 execute identical scalar and
grouped fits. Both arms see the same initial Heads, shared feature table, labels,
per-Cell minibatches and updates; complete fitting calls are timed, not merely
matrix multiplication. All predictions are saved before heldout scoring. No
threshold or winner is chosen from heldout scores.

| Heads / input / hidden / classes / updates | Scalar/grouped wall ratio |
| --- | --- |
| 1 / 16 / 8 / 2 / 20 | 0.746..1.060; no consistent advantage |
| 64 / 384 / 8 / 4 / 12 | 3.787..3.809 |
| 256 / 384 / 8 / 4 / 6 | 2.655..3.246 |
| 4096 / 64 / 4 / 2 / 3 | 2.464..3.381 |

The 4096-Head profile uses 64-wide supplied features, NOT truncated 384-wide
Encoder outputs. Each arm performs 393,216 useful example updates; optimizer
calls reduce from 12,288 to 384 while each Cell still has three updates. The
candidate tensors occupy 8,683,520 raw bytes; this is not full process RSS.
Across 848,064 correlated Cell predictions, classification disagreements are
zero; maximum parameter error is 2.981e-8 and maximum logit error 2.981e-7.
Unlike some Linear fixtures, gated parameters are NOT bitwise identical.
Predeclared numerical tolerances are absolute 2e-6 / relative 2e-5, not a proof
of equality for all inputs, longer training or other hardware.

Features and four task families are synthetic. Each profile has only 64
independent heldout inputs; repeated Cell tasks do not increase that number.
Few-step training is an implementation benchmark, not training to convergence:
seed 2525's 4096-Head trained score is lower than its frozen score and is retained.
No general learning superiority, pretrained outcome, p95/p99, statistical speed
guarantee, energy/RSS or production acceptance is asserted. Initial studies
used Python 3.13.5 / Torch 2.10.0+cpu, one CPU thread.

```sh
PYTHONPATH=qualification/stem-cell-v1 python -m unittest -v development_gated_training_checks
PYTHONPATH=qualification/stem-cell-v1 python \
  qualification/stem-cell-v1/development_gated_training_study.py --synthetic \
  --seed 1414 --output /new/gated-head-study
```

The existing source-head and prospective-merge CPU workflow retains all earlier
checks and adds the gated tests/study. 134 local sparse-source tests pass (114
retained plus 20 new), not the full repository suite. The parent development
workflow 38299074028 passed both lanes, while parent Stem/global CI remained
failed. Separately identified CI-generated Worker Rustfmt and Bazel-fixture Ruff
patches are imported by exact matching source blobs, without changing assertions
or runtime behavior. New exact-head hosted checks remain required; unresolved
dependency security, cross-platform tests and other format findings are not waived.
