# Calibrated low-budget Cell study, local phase 2

This is an additive protocol. The original study and its analysis remain intact.
The old repair-shape holdout has already been observed: any new score on it is a
**repeated-use diagnostic**, not an independent confirmation or a new winner
qualification. New operational, image and audio task families have separately
declared source-group holdouts. Task definitions and feature conditions must be
fixed before evaluation. Missing/null labels mean not applicable, never negative.

## Fixed plan

For each declared binary target and feature condition, use 8, 32 and 128 training
examples, with seeds 7, 17 and 29. The training-only deterministic sampler takes
equal class counts, at most one event from each source group and predictor
identity. A budget that cannot satisfy those conditions is unavailable; there is
no replication. Text identity uses normalized text. Image/audio identity uses a
declared full input-content SHA256; their neutral text does not define identity.
Source IDs and groups remain disjoint in every modality. Input digests are bound
to the dataset/feature receipt; this head runner does not authenticate publishers
or independently establish the source-byte truth of caller-provided digests.

The existing calibration cohort is partitioned, without labels, into tuning and
calibration halves. Connected group/predictor-identity duplicates stay together.
Components are ordered by a fixed SHA256 key with seed 20261024. The first half
is tuning; the remainder is calibration. Every source group has total fitting
weight one, divided among its applicable rows. Missing classes and effective
group counts are reported. Fewer than two calibration components is unavailable.

Compare exact text lookup, BM25, dense nearest-neighbor, prototype, linear,
feature-gated and rank-4 gated residual heads, plus an explicit no-evidence
Laplace-smoothed calibration-prior baseline. For media, exact/BM25 operate only
on neutral text metadata and are marked modality-inappropriate. They are not
substitutes for image/audio retrieval. Source-retrieval relevance is not inferred
from semantic task labels.

Each learned mode has L2 values 0.1 and 1.0. Each path uses full-batch Adam,
learning rate 0.02, gradient norm cap 5 and checkpoints 10, 40 and 100. At each
checkpoint, measure group-weighted tuning NLL after correcting the effective
balanced training prior to the Laplace-smoothed tuning prior. Stop a path at the
first checkpoint that fails to improve NLL by 0.0001; restore its best checkpoint.
Choose the lower tuning NLL of the two L2 paths, breaking exact ties toward
stronger regularization. All attempted and discarded updates count as costs.

The common private parameter ceiling is 100,000; learned heads reserve four
stored calibration scalars inside that ceiling. This is a cap, not an assertion
of equal parameters, FLOPs, memory or wall time. Report actual parameters, updates,
example updates, optimizer/gradient/checkpoint buffers, wall and CPU time. Dense
matrix FLOPs are counted from executed shapes at two FLOPs per multiply-add;
elementwise operations are estimates and transcendental costs are explicitly
excluded. Feature extraction, baselines, calibration and fresh-process overhead
are reported separately. No adaptive permutations or extra grid search are used.

## Calibration and operating rule

After tuning choices, fit binary scale and bias on the disjoint calibration half
only. Standardize the raw logit difference using its weighted mean and standard
deviation; fit a nonnegative evidence scale in [0,32] and bias in [-12,12].
Projected Newton optimization has at most 100 iterations and 24 line-search
attempts per iteration. It uses scale ridge 0.001 and one positive/one negative
pseudo-observation at the mean score. At scale zero it reduces to the
Laplace-smoothed calibration prior. Thus infinite temperature is available,
without the old finite-temperature ceiling. Report convergence and every
boundary; a nonconverged fit prevents evaluation. Projected gradient tolerance
is 1e-8 per effective observation, including the two pseudo-observations.

The calibration-only selector uses **tuning NLL**, with exact-tie order prior,
prototype, linear, gated, residual. Its choice never removes any reported arm.
A selected constant prior is not evidence of learning. The fixed operating rule
accepts eligible predictions at maximum calibrated probability at least 0.7.
The complete fixed threshold/risk/coverage curve is also reported. No heldout
threshold is fitted. Secondary AUROC and a decision threshold equal to the
calibration prior distinguish ranking evidence from majority-prior decisions;
neither changes the primary metrics or selection policy.

Report balanced accuracy, positive recall, NLL, multiclass-sum Brier, ECE,
coverage, selective risk, ordinary accuracy and all-row success. Abstention is
never success. Binary balanced accuracy/AUROC are unavailable when a heldout
class is absent. Do not convert that absence into a perfect score.

## Freeze, controls and evaluation

Preparation accepts training and calibration cohorts only. All declared task
preparations and choices are sealed before any evaluation phase starts. The
evaluation API cannot change those preparations. It verifies source/group/input
disjointness and evaluates each fixed output directory once; a completed result
can be read on resume only after its full artifact inventory is verified.

Every learned arm retains disabled-parameter and deterministically shuffled-
parameter controls with the fitted calibration held fixed. A fresh process
replays both logits and probabilities bitwise from saved weights, feature
identity, features and four calibration scalars. No test labels are provided to
the child; the child does share the parent filesystem, so this is an input
allowlist, not an operating-system isolation claim.

Task-seed means are descriptive. Correlated targets, seeds, repeated evaluations
and source groups are not independent replications. A result is scoped to its
declared family and inputs; no universal encoder, head or multimodal winner is
qualified by this protocol alone.

## Local execution

`run_calibrated_cells.py --dataset DATASET --features FEATURE_DIRECTORY --output
NEW_OUTPUT --phase prepare --holdout-use legacy_repeated_use_diagnostic` freezes
all declared targets without scoring their heldout rows. After every planned
feature condition is prepared, invoke the same command with `--phase evaluate`.
For untouched operational or media holdouts, use `new_operational_holdout` or
`new_multimodal_holdout` respectively. The CLI does not expose grid overrides;
smaller explicit grids are reserved for source-controlled fixture tests.

The feature directory contains an FP32 `features.npz` with only the `features`
matrix, plus a receipt binding the dataset SHA256, exact source-ID order, feature
identity, tensor SHA256, archive SHA256 and shape. Missing/null per-task labels
are filtered with applicability counts; empty applicable splits are explicitly
unavailable. No unlabelled event is counted as a negative outcome.
