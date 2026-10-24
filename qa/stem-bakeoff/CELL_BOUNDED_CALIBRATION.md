# Prospective action heads and bounded calibration

This is an additive protocol. Earlier source, model and evaluation artifacts
remain unchanged. Earlier operational heldouts have been observed and can only
support explicitly repeated-use development diagnostics.

## Task and source roles

The primary target is prospective action usefulness: whether a supplied action
has different normal test outcomes on the buggy and fixed revisions. Candidate
actions are frozen before execution. Both-pass and both-test-failure are
negative; infrastructure failures and unknown results are unavailable, never
negative. Every proposal remains in the separate execution registry.

The predictor contains the supplied change and one supplied action/test source.
It must not contain candidate role/index, outcome, fixing-label hints, or a
counterpart implementation absent from the single-row task.

The independent repository roles are train (youtube-dl, scrapy), tuning (luigi),
calibration (thefuck, tqdm, PySnooper), and fresh external evaluation (the five
previously unused projects defined in the governing proposal plan). The old
black/tornado evaluation projects are excluded. The role plan is frozen before
execution and model selection. The caller verifies repository-level assignment;
the head runner also rejects source, bug-group and normalized full-text overlap.

Each `ActionCohort` has explicit role, FP32 features, separate binary labels, and
public rows with exactly `source_id`, `group_id`, `text`. Text is complete and
bounded at 131072 UTF8 bytes per row, with no silent truncation. Original source
spans and input authenticity are bound and checked by the dataset/feature owner.

## Fixed fitting and selection

The primary gradient budgets are 8, 32 and 64, each with seeds 7, 17 and 29.
128 is explicitly unavailable; the declared training pool has only 83 raw bug
groups. Each selected gradient row comes from a distinct bug group. The frozen
source-hash round-robin sampler attempts balanced classes and reports any
unavailable balanced budget; it does not replicate rows or alter the target.

The full labelled training pool is used for stratification. All applicable
tuning and calibration rows are also labelled costs. Thus an 8-example gradient
budget is not an 8-label experiment. Reports retain rows, independent groups,
raw class support and group-weighted class mass for every pool and selected draw.

Every tuning/calibration bug has total weight1, divided among its available
action rows. Linear, gated and rank4 residual heads use the unchanged
`fit_path`: Adam learning rate0.02; L2 grid0.1/1.0; checkpoints10/40/100; stop at
the first checkpoint without tuning NLL improvement of at least0.0001.
Checkpoint and regularization selection use only the independent tuning role,
with analytic balanced-training to tuning-prior correction. Ties favor stronger
regularization. The effective inverse-class-weighted training prior is exactly
`[0.5,0.5]`, regardless of raw source/action prevalence.

All heads have a common 100000-private-parameter ceiling including four stored
calibration scalars. Actual parameters, dtype, updates, discarded updates,
matrix-product FLOPs, estimated elementwise work, optimizer/gradient/checkpoint
buffers and wall/CPU time are reported. A common cap is not equal compute cost.

The explicit prior, full-text exact/BM25, dense nearest, prototype, linear,
gated and residual arms are all retained. The fixed tuning-only selector compares
prior, prototype, linear, gated and residual in that tie order. Every learned
arm is reported even when the selector or later calibrator returns the prior.
Direct Jaccard relevance is a separate no-fit group-ranking control, not an
unregistered probability-calibration candidate.

## Bounded prior-mixture calibration

Let `m` be the binary raw-logit margin, `t` the effective training prior, and `g`
the number of independent calibration bug groups. Define `q` as the positive
group-weighted class mass plus1 divided by `g+2`, and `lambda=g/(g+16)`.

For alpha in the fixed grid `0, 1/16, 1/8, 1/4, 1/2, 1`, use

```
r = sigmoid(alpha * (m - logit(t_positive)) + logit(q))
p_positive = (1 - lambda) * q + lambda * r
```

Choose the smallest alpha within1e-12 of the minimum group-weighted calibration
NLL. No heldout labels enter this choice. Alpha0 returns the prior bitwise
exactly. There is no calibration-sample score standardization, free intercept,
or alpha above1. The finite prior mass16 is a predeclared policy constant, not
16 observed labels. The binary prior has one estimated degree of freedom.

For either true class, `p_y >= (1-lambda)*q_y`. Consequently, under any unseen
raw-score shift, the per-row NLL excess over the explicit prior is at most
`log(1+g/16)`. At four groups that excess is at most0.223144; across any empirical
class mixture probabilities lie between2/15 and13/15, and a balanced prior gives
the narrower interval0.4–0.6. These are deterministic confidence-policy bounds,
not confidence intervals, calibration guarantees or evidence of learning.

The optional complement-symmetric development mode forces training/calibration
prior0.5 and bitwise reflected probability columns for opposite margins. It is
not the primary, nonsymmetric prospective action task.

## Freeze, evaluation and evidence scope

`prepare_action_curve(train, tuning, calibration, ...)` has no holdout argument.
It binds dataset, feature-report and prospective proposal-plan SHA256 values,
feature identity, role digests, code hashes, every selected predictor and its
calibrator. The caller verifies the external file pins. Preparation seals cover
all files; evaluation requires the exact seal and unchanged numerical source.
Protocol overrides exist for bounded fixtures or separately preregistered plans;
the primary uses the fixed defaults above. No source or grid changes follow
first real preparation.

`evaluate_action_curve` performs no fitting. Its explicit designation is either
prospective external holdout, reused development diagnostic, or fixture. NLL,
Brier, ECE, forced accuracy, balanced accuracy and positive recall assign each
available labelled bug total weight1. Balanced accuracy normalizes each class
by its weighted support. Missing-class BA/AUROC is unavailable.

The operating threshold is fixed at maximum probability0.7. Coverage, selective
risk and all-row success are jointly reported, plus a fixed risk/coverage grid.
Zero coverage yields zero all-row success and undefined selective risk. AUROC
and prior-threshold BA/recall are prespecified discrimination diagnostics.

Parameters-off and deterministic parameter-shuffle controls preserve the fitted
calibrator. Fresh-process weight recovery must reproduce logits/probabilities
bitwise; its file/argument allowlist excludes heldout labels but is not a
filesystem sandbox. Parent/child CPU and included wall time are recorded.

Available-label action scores cannot establish success over all proposals.
Group ranking, unknown/infrastructure cases, acquisition and execution costs
require the complete proposal/execution registry, including groups with no
available outcomes. Uncertainty must resample whole bug groups, preserve action
and model correlations, and average fixed seeds within each replicate.
Every artifact remains `DENY_ALL` and unqualified for production authority.

`predict_action_rows(features, public_rows, ...)` is the label-free path for all
feature-available proposed candidates, including unknown/infrastructure cases.
It requires the same frozen feature identity and external receipt bindings,
rejects overlap with preparation roles, and accepts no query labels or outcome
fields. The caller applies explicit feature-availability masks before calling;
unavailable vectors never enter the head. It seals all probabilities and the
same parameter/fresh-process controls before an outcome-aware ranking analysis.
The complete proposal registry retains excluded vectors, unknown results and
their group denominators. Conditions are compared on a declared common available
group set with their coverage differences also reported.

The public preparation/prediction/evaluation entry points are Python functions
for the governing orchestrator. The child replay CLI is
`python cell_action_evaluate.py --model DIR --features FILE --descriptor FILE
--calibration FILE --output NEW_FILE`; it performs no fitting or scoring.
