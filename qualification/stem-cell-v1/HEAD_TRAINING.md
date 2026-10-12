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
