# Anchor-preserving affine consolidation: empirical retention still required

Continuation of Draft PR #1654 from `2c44b7c847f8b709fcb136706abf98acda516c6a`.
The V9 source/merge, historical-feature and physical BGE jobs subsequently all
passed in workflow 38333396515. That parent result is not a pass for new source.
Existing qualification/CI owners only; no new production runtime, persistent
store, model loader, live selection or Encoder training is introduced.

## Hypothesis and fixed comparison

V9 reduced forgetting but did not retain every old class. This extension tests
whether constraining an ACTUAL parameter update to preserve old training-input
outputs improves that result. All six V9 inference controls remain in the census.
Three additional controls inherit the same frozen teacher and task meanings:

- `affine_unconstrained`: fold FiLM into affine form and distill without constraints.
- `anchor_memory`: the same affine distillation with the original 32 memory inputs
  protected (eight per old class, original content-hash selection).
- `anchor_all_old`: protect all 160 old training inputs, explicitly using more data
  and a larger training basis. The loss still uses the SAME 32 old memory inputs.

All three use float64 optimization, zero delta initialization, T=2 teacher KL,
AdamW lr=.001 / weight_decay=.01, 200 steps, seed 7347, and identical
16-old/16-new minibatches. No task ID is passed at inference. The existing fixed
old/new partition, .02 per-old-class accuracy/Brier floors, and tie order remain.
Those are descriptive calibration rules, not confidence or NDU acceptance.
The normalizer still uses the old base only. Held-out truth is removed entirely
at the producer's baseline-verification boundary; the existing reviewer gains an
explicit calibration-only mode with unchanged full-scoring default. Teachers are
verified but NOT retrained; their historical training/preparation costs are retained
separately. The three new fits add 600 steps / 19,200 sample presentations, not zero
cost for inherited knowledge. Earlier public test inspection makes this exploratory
retrospective evidence, not a preregistered independent or prospective experiment.

## Exact linear structure and finite-precision envelope

For normalized feature x, augment a=(x,1). Fold FiLM to M0, including gamma, beta
and bias, then learn M=M0+D. Let Q contain orthonormal rows spanning the old
augmented anchor matrix A. After EVERY optimizer step apply:

    D <- D - (D @ Q.T) @ Q

In exact arithmetic A @ D.T=0 when Q spans A. This is not merely projecting the
loss gradient: Adam's preconditioning, moments and weight decay cannot bypass
projection of the actual delta. Economy SVD uses a fixed double-precision rank
threshold and no differentiation through singular vectors. Rank deficiency is
retained, not filled with arbitrary extra constraints. A full-rank anchor set
leaves no affine learning directions and the tests exercise that boundary.

The implementation checks <=1e-8 actual anchor residual after every training step,
then folds and casts to ONE float32 readout. Its actual output drift from the old
FiLM on protected inputs must be <=1e-4. No SVD basis or additional teacher is
needed to execute that readout. Independent review recomputes ranks and actual
packed-anchor drift instead of trusting saved assurances.

This only constrains the old input span. For an arbitrary augmented vector z,
D z = D(I-Q.T Q)z and ||D z|| <= ||D|| ||(I-Q.T Q)z||. A finite training sample
cannot justify a global no-forgetting assertion. Near-class-boundary examples
can change decisions even when stored anchors do not move. The original held-out
and per-class calibration gates are NOT replaced by the algebraic check.

At width 384 each packed affine Head has 3,080 parameters / 12,320 FP32 bytes,
versus V9 FiLM's 3,848 parameters / 15,392 bytes. They represent the same affine
function family but have different parameterizations and optimization trajectories;
that is why the unconstrained affine control is mandatory. Equal stored size
among the three new Heads does not mean equal effective degrees of freedom.
Memory/all-old augmented anchors occupy 98,560/492,800 float64 bytes, with equally
large retained row-space bases on this corpus. These are training-only tensor
counts, not process RSS. Input copies, optimizer states, target probabilities,
SVD workspaces and source validation remain additional costs. Timing is descriptive
fixed-order work accounting, not a fair throughput benchmark or a fastest-path claim.

## First real-feature observation (no retuning after scores)

Reuse the authenticated f30abc25 BGE feature bundle and V9's sealed teachers.
No new Encoder ran locally. All 1,200 original rows/labels remain; only the fixed
old-base/new-adapt task subsets fit the new Heads. The first run yielded:

| Rule | Old test correct / 120 | New test correct / 120 |
| --- | ---: | ---: |
| Frozen old teacher | 120 | 0 |
| New-task teacher | 109 | 119 |
| V9 distilled FiLM | 117 | 119 |
| Unconstrained affine | 117 | 119 |
| Protect 32 memory inputs | 116 | 118 |
| Protect all 160 old inputs | 117 | 113 |

The two constrained models' protected-input logit drift was
1.9073486328125e-6 after float32 packing. Ranks were 32 and 160, leaving 353 and
225 input directions respectively. More protected directions did not establish
better overall learning: the larger constraint lost six new test successes
relative to unconstrained affine. Reminder calibration improved from distilled
15/20 to 16/20 or 17/20, still below the old teacher's 19/20. Frozen remains the
calibration choice. No threshold, class assignment or seed was changed afterward.

All nine rules' 3,609 calibration+test predictions replay with zero observed error
and no argmax reversals. There are 240 distinct held-out inputs, NOT 2,160
independent tests. The original six controls use their unchanged saved checkpoints.
Forward reconstruction does not call the fitter or its projection. Metric and
selection primitives remain shared with the producer; replay does not reproduce
optimizer trajectories or authenticate hardware clocks. Fully fabricated coherent
input bundles still require independent execution evidence.

239 local tests (217 original + 22 new) passed without skips using COMPLETE original
qualification modules restored from the hosted source archive. New tests are
synthetic; real-feature outcomes above are separately identified. New head/merge
and physical CI must pass on the new exact SHA. No Rust/global/native recovery,
independent future utility, reasoning or multimodal-generation gate is waived.

## Reproduce and method references

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v cell_anchor_checks
PYTHONPATH=qualification/stem-cell-v1 python3 qualification/stem-cell-v1/cell_anchor_study.py \
  --source-run /verified/study --dataset /verified/inputs/dataset.jsonl \
  --consolidation-run /verified/consolidation --output /new/anchors
PYTHONPATH=qualification/stem-cell-v1 python3 qualification/stem-cell-v1/cell_anchor_study.py \
  --source-run /verified/study --dataset /verified/inputs/dataset.jsonl \
  --consolidation-run /verified/consolidation --review-run /new/anchors --output /new/scores.json
```

Related projection idea: Farajtabar et al., *Orthogonal Gradient Descent for
Continual Learning*, AISTATS 2020, https://proceedings.mlr.press/v108/farajtabar20a.html.
This is a bounded affine specialization, not a reproduction of all OGD experiments.
Pinned SVD contract: https://docs.pytorch.org/docs/2.10/generated/torch.linalg.svd.html.
