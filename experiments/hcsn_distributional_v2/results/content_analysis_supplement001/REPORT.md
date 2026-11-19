# Post-hoc producer-exact supplemental content audit

The original registered strict audit remains **175 valid / 1 invalid**, with its FP64 absolute CE tolerance still failed. It has not been amended or overwritten.
This separate engineering audit repeats all 176 complete audits using exact original FP32/128-sample-batch CE summary reconstruction. FP64 cross-check differences remain explicit. Scientific comparisons, thresholds, training, predictions and selections are unchanged; FSDD's previously missing core row and descriptive screen are separately identified.

Supplemental integrity: **176/176 valid**, 0 invalid.
Positive mechanism gates: **0/4**. Descriptive content screens: **0/6**.

## Three-seed core ID accuracy

| Model | Copy | MQAR | Irregular | MNIST | FSDD | Multimodal |
|---|---:|---:|---:|---:|---:|---:|
| distribution_free_dual | 21.60 ± 3.75 | 19.89 ± 5.32 | 92.19 ± 2.06 | 44.01 ± 6.66 | 11.33 ± 3.25 | 12.11 ± 1.53 |
| distribution_conditional_dual | 23.47 ± 7.16 | 21.63 ± 2.93 | 91.08 ± 2.96 | 37.83 ± 2.15 | 12.30 ± 3.22 | 12.43 ± 3.05 |
| distribution_free_ordinary | 20.30 ± 7.94 | 19.65 ± 7.00 | 94.08 ± 2.49 | 41.28 ± 6.28 | 11.78 ± 1.59 | 14.58 ± 0.56 |
| active_mean_collapse_free_dual | 21.83 ± 10.17 | 21.31 ± 1.77 | 91.08 ± 4.26 | 34.24 ± 8.06 | 11.65 ± 1.66 | 14.13 ± 1.39 |
| legacy_free | 61.26 ± 5.89 | 34.85 ± 6.08 | 95.44 ± 2.49 | 75.39 ± 5.78 | 18.75 ± 1.86 | 15.04 ± 2.17 |
| two_gates | 98.91 ± 1.07 | 37.79 ± 1.95 | 96.74 ± 0.96 | 87.50 ± 0.39 | 24.67 ± 6.07 | 29.56 ± 3.21 |
| transformer | 48.86 ± 0.44 | 100.00 ± 0.00 | 94.01 ± 1.08 | 84.05 ± 2.22 | 40.10 ± 7.35 | 35.87 ± 1.66 |

## 8-seed paired mechanism comparisons

Differences are free distribution dual minus comparison, averaged over the two fixed tasks within each seed. Intervals are nominal; four exact two-sided sign-flip p values share one Holm family.

| Comparison | Difference pp | Nominal 95% interval pp | Holm p | Positive gate |
|---|---:|---|---:|---|
| distribution_conditional_dual | 0.470 | [-1.939, 2.879] | 1.000000 | False |
| distribution_free_ordinary | 0.012 | [-2.418, 2.443] | 1.000000 | False |
| active_mean_collapse_free_dual | 0.360 | [-2.504, 3.224] | 1.000000 | False |
| two_gates | -48.398 | [-51.039, -45.756] | 0.031250 | False |

## Scope and costs

Complete search worker CPU: **25273.811006 s**. Coordinator self CPU: **29.466034 s**. Training CPU inside valid workers: **21226.171330 s**, a nested component, not an additional charge.

The invalid-duration content001 registration remains sealed: 20 searches started, 16 completed and 4 failed. Its complete worker cost was **2224.722337 s**. Combined worker CPU across both studies is **27498.533343 s**, before engineering, analysis or separate execution work. No content001 scores or weights enter these comparisons; its completed searches did expose heldout outcomes, and this rerun is not fresh-test confirmation.

All seven models use the same frontend/readout initialization and actual paired minibatch sequence. Backbone counts differ by at most3%; conditional threshold adds16 active parameters. The ordinary physical-feature arm sees the complete probability and the same seven physical coefficients. The legacy comparator is the original mean-state mechanism with active projections and a re-matched internal width, retrained here.

The ordinary-feature arm omits its unused J/G solve, so it is not charged for unnecessary value computation. Its active_center_variance feature is an active-mass-weighted conditional cell-center variance, excluding within-cell and refractory-position variance. The conditional threshold uses a bounded gap(.01,4) to preserve its grid's reset/initial-state validity; its two learned boundary coefficients are unchanged in number.

The 60 training CPU second budget and common [15.0, 30.0, 60.0] CPU checkpoints were fixed before this study's heldout evaluation, after train-only engineering probes. Both LR candidates finish before selection is locked; fixed128 snapshots add no primary selection opportunity. No failed search may disappear from comparisons.

The registered neural numerical profile uses fixed uniformization rate8.1 and21Poisson terms per substep. Each token uses max(1,ceil(physical_dt/.36)) equal substeps with one boundary remapping; binary composition preserves all event/reward integrals and leaves completed neighboring tokens unchanged. The explicit resource cap is1048576substeps. Neither a future suffix nor a neighboring sample selects another token's numerical effort. This repairs content001's incorrect per-observation duration bound. Adaptive oracle profiles remain separate.

The physical model retains eight spatial cells and two Erlang phases; it is not exact Brownian dynamics. The input-dependent analytic boundary uses the Brownian/Erlang optimum, while J/G evaluate its actual finite-generator policy. Neither value is a proved classification Bellman value. Active-mean collapse preserves every refractory phase and is not identical to the old v1 mean/cooldown implementation.

Synthetic OOD doubles length32→64; irregular OOD additionally multiplies the dt distribution by3. Real tasks have no OOD split. FSDD uses600speaker-disjoint recordings with repeated episodes and offline features; this is not a foundation-model or broad speech benchmark. Core statistics use three seeds and are descriptive. The two mechanism tasks are fixed, not a random task population. Same test datasets were already observed during v1 and partial content001; this is a registered post-baseline study, not fresh-test confirmation.

ANALYSIS.json records all prediction-coordinate/label/CE checks, complete minibatch prefixes, source/selection identities, actual parameter updates, checkpoint inference replay and available OOD results. Missing/invalid evidence makes the affected contrast incomplete. Energy was not measured.
