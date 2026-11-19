# Frozen study001: completed analysis and exactly-128 secondary

## Finding

The implementation runs and jointly trains its content, dynamics, boundary,
reset and refractory parameter groups, but the registered accuracy claims fail
in this small CPU-budget study. **All 244 searches are valid; zero of six
positive mechanism contrasts are accepted; zero of six 2-percentage-point
content screens pass.** These are genuine measured negative results, not
missing-run substitutions.

The only Holm-significant two-sided mechanism difference points against the
new free-boundary cell: `free_dual - two_gates` is −35.01 percentage points,
with nominal paired-t 95% interval [−39.32, −30.70] points and Holm-adjusted
exact sign-flip p=0.046875. This is evidence of worse performance for `free_dual`
under the registered paired experiment and its sign-exchangeability assumption,
not acceptance of a free-cell advantage.

The primary comparison gives each LR candidate 20 training CPU seconds.
Different models complete very different numbers of updates. A separately
registered exactly-128-update evaluation was executed without new training,
but its coverage is insufficient for a complete equal-update comparison of the
free cell. Both results and their distinct limitations are preserved below.

## Audit, selection and statistical units

The analysis began only after `COMPLETE.json`. All 244 searches, both LR
candidates per search, numeric checkpoints, supervised prediction coordinates,
labels, argmax decisions, cross entropies, accuracy counts and frozen data/source
identities passed the audit. No primary or secondary checkpoint was changed.

The six-task core uses seeds 9101–9103. The mechanism family uses seeds
9101–9108 on two fixed tasks, selective copy and multimodal selection. Shared
jobs are reused, giving 244 searches and 488 completed LR candidates. Within an
LR, primary selection is minimum validation cross entropy, then earlier CPU
time and step. Across LRs, it is minimum validation cross entropy, then smaller
LR, the operational reading documented before outcomes. There were no exact
cross-LR validation ties. Both candidates finish and selection is durably
recorded before test/OOD evaluation.

The mechanism unit is **one seed's mean accuracy difference across the two
fixed tasks**, giving n=8, not 16 independent task-seed observations. The exact
two-sided sign-flip test enumerates 256 sign assignments and assumes sign
exchangeability/symmetry under its null. Holm correction retains all six
predeclared comparisons. Acceptance also requires a mean gain of at least 1
point and a nominal paired-t 95% lower endpoint above zero. These t intervals
are not simultaneous intervals. Core three-seed means and sample SDs are
descriptive only. No episode-level binomial confidence intervals are invented.

All 28 task/seed pairing groups have identical minibatch streams through their
common update count, which ranges from 112 to 131. Shared frontend/readout
initialization also matches. Comparing the common prefix does not assert that
the faster models stop at the same update; their additional updates are part
of the registered equal-CPU experiment.

## Six-task core results

Accuracy in percent, mean ± sample SD over the three registered seeds. These are the tested small-budget implementations, not claims about the best possible member of a model family.

| Model | Selective copy | MQAR | Irregular | MNIST | FSDD | Multimodal select |
| --- | --- | --- | --- | --- | --- | --- |
| free_dual | 34.02 ± 1.52 | 28.14 ± 5.39 | 93.95 ± 1.60 | 54.10 ± 2.30 | 10.42 ± 0.79 | 15.17 ± 1.30 |
| legacy_hcsn | 36.59 ± 3.86 | 29.48 ± 2.63 | 95.77 ± 0.98 | 70.25 ± 3.63 | 19.40 ± 3.47 | 18.49 ± 2.66 |
| two_gates | 89.57 ± 2.05 | 34.68 ± 8.68 | 96.29 ± 0.52 | 80.99 ± 9.08 | 17.25 ± 0.98 | 23.37 ± 5.10 |
| continuous_rnn | 39.83 ± 4.58 | 30.57 ± 1.71 | 95.51 ± 2.20 | 71.88 ± 5.02 | 13.87 ± 4.42 | 25.59 ± 2.17 |
| cfc | 11.67 ± 0.59 | 12.53 ± 0.28 | 91.93 ± 1.19 | 44.47 ± 1.66 | 11.13 ± 2.03 | 17.77 ± 2.77 |
| mamba1 | 91.21 ± 3.75 | 50.60 ± 10.50 | 87.43 ± 2.83 | 82.49 ± 2.25 | 21.61 ± 9.00 | 20.96 ± 10.13 |
| transformer | 49.10 ± 0.29 | 100.00 ± 0.00 | 92.38 ± 0.52 | 82.42 ± 0.98 | 28.45 ± 1.11 | 27.28 ± 2.93 |
| lif_snn | 12.89 ± 0.34 | 12.70 ± 0.43 | 93.16 ± 1.03 | 38.15 ± 3.60 | 12.83 ± 2.55 | 22.01 ± 3.33 |

The strongest observed candidate varies by task. Mamba1 is the core mean
leader on selective copy and MNIST, Transformer on MQAR, FSDD and multimodal
selection, and two_gates on irregular observations. These are maxima among
this registered candidate set. FSDD performance is low for **all** candidates:
even its best mean is only 28.45%; this is neither state of the art nor strong
absolute speech-recognition capability. The MNIST and multimodal results are
also small-data, short-budget pilot results.

On these same six tasks the legacy Hepta HCSN candidate has a higher mean than
the new `free_dual` in every core cell. That is a three-seed descriptive finding,
not a separately corrected six-task significance claim.

### Registered content screens

The rule is `free_dual` within 2 points of the best mean among all seven baselines, including legacy_hcsn. This is a point-estimate screen, not an equivalence or noninferiority test.

| Task | Free % | Best tested baseline | Baseline % | Free − best, pp | Screen |
| --- | --- | --- | --- | --- | --- |
| selective_copy | 34.02 | mamba1 | 91.21 | -57.19 | fail |
| mqar | 28.14 | transformer | 100.00 | -71.86 | fail |
| irregular | 93.95 | two_gates | 96.29 | -2.34 | fail |
| mnist | 54.10 | mamba1 | 82.49 | -28.39 | fail |
| fsdd | 10.42 | transformer | 28.45 | -18.03 | fail |
| multimodal_select | 15.17 | transformer | 27.28 | -12.11 | fail |

Irregular observations miss the screen by 0.34 points beyond its 2-point allowance. The screen failure alone does not establish a statistically significant three-seed deficit on that task.

### Prespecified OOD probes

Selective copy and MQAR increase sequence length from 32 to 64; irregular observations multiply elapsed intervals by three. No real-data OOD split was silently substituted. Values are accuracy %, mean ± sample SD, n=3.

| Model | Copy length 64 | MQAR length 64 | Irregular 3× time |
| --- | --- | --- | --- |
| free_dual | 30.76 ± 3.24 | 27.65 ± 6.12 | 53.58 ± 2.69 |
| legacy_hcsn | 26.43 ± 4.24 | 24.76 ± 2.49 | 62.96 ± 9.60 |
| two_gates | 82.34 ± 2.40 | 32.94 ± 8.03 | 69.86 ± 9.97 |
| continuous_rnn | 26.46 ± 3.79 | 21.79 ± 2.78 | 81.58 ± 6.44 |
| cfc | 12.24 ± 0.16 | 11.75 ± 0.23 | 59.51 ± 5.33 |
| mamba1 | 63.28 ± 2.19 | 37.08 ± 8.07 | 55.21 ± 3.52 |
| transformer | 18.44 ± 1.82 | 74.69 ± 19.94 | 52.99 ± 2.18 |
| lif_snn | 13.48 ± 0.54 | 12.19 ± 0.29 | 75.26 ± 1.59 |

The free cell does not show a general OOD robustness advantage. Its irregular-task mean falls from 93.95% to 53.58%; the continuous_rnn candidate reaches 81.58% in that OOD probe. The result does not isolate the cause of the drop.

## Full six-contrast mechanism family

Direction is always `free_dual minus comparator`. Effect and interval are percentage points. All comparisons contain all eight required seed pairs.

| Comparator | Mean difference, pp | Nominal paired-t 95% CI | Two-sided sign-flip p | Holm p | Positive gate |
| --- | --- | --- | --- | --- | --- |
| fixed_dual | -2.182 | [-4.901, +0.537] | 0.0468750 | 0.2343750 | not accepted |
| direct_dual | -1.324 | [-3.374, +0.725] | 0.1562500 | 0.4687500 | not accepted |
| free_margin | -0.836 | [-2.382, +0.709] | 0.2421875 | 0.4843750 | not accepted |
| free_continuation | +1.099 | [-0.333, +2.530] | 0.1015625 | 0.4062500 | not accepted |
| free_ordinary | +0.082 | [-0.962, +1.127] | 0.8593750 | 0.8593750 | not accepted |
| two_gates | -35.010 | [-39.315, -30.704] | 0.0078125 | 0.0468750 | not accepted |

The fixed_dual raw p is below 0.05 but its Holm p is not; it must not be reported as a corrected significant result. free_continuation has a point gain above 1 point, but its interval includes zero and its Holm p fails. The free_ordinary difference is close to zero. The two_gates result is a significant negative difference, not a positive-gate success.

### Mechanism-task descriptive cells

These eight-seed task means explain the paired family but do not add task-specific significance claims.

| Model | Selective copy % | Multimodal select % |
| --- | --- | --- |
| free_dual | 33.63 ± 2.71 | 16.58 ± 2.06 |
| fixed_dual | 37.65 ± 2.82 | 16.92 ± 4.79 |
| direct_dual | 37.13 ± 2.24 | 15.72 ± 4.17 |
| free_margin | 37.65 ± 2.50 | 14.23 ± 2.17 |
| free_continuation | 33.53 ± 3.72 | 14.48 ± 2.93 |
| free_ordinary | 36.00 ± 3.20 | 14.04 ± 2.70 |
| two_gates | 92.08 ± 5.73 | 28.15 ± 9.02 |

The original fixed/direct threshold controls are per-neuron static while free_dual's boundary responds to input-dependent drift. That limits a pure interpretation as analytic-root versus equally conditional ordinary gating. A separately registered conditional_dual extension addresses this issue; it is additional/exploratory and is not retroactively inserted into the original six-comparison Holm family. Its results are outside this report.

## Parameters, actual updates and complete CPU

Backbone matching uses actual trainable parameters with no dummy padding. Every baseline is within 5% of the 8,800-parameter free backbone. The frontend has 2,208 parameters for every model. Readout size is shared within a task; the total column below uses the 10-class MNIST configuration.

| Model | Backbone parameters | Absolute backbone gap % | Total, 10-class task |
| --- | --- | --- | --- |
| free_dual | 8800 | 0.000 | 11338 |
| legacy_hcsn | 8608 | 2.182 | 11146 |
| two_gates | 8810 | 0.114 | 11348 |
| continuous_rnn | 8924 | 1.409 | 11462 |
| cfc | 8876 | 0.864 | 11414 |
| mamba1 | 8872 | 0.818 | 11410 |
| transformer | 8816 | 0.182 | 11354 |
| lif_snn | 8702 | 1.114 | 11240 |

### Balanced six-task, three-seed core compute

Each row covers 18 searches and 36 LR candidates. The full process includes both complete candidates regardless of which earlier checkpoint was selected.

| Model | Searches | Updates/LR median [min,max] | Selected step median | Full search CPU median, s | Full search CPU sum, s |
| --- | --- | --- | --- | --- | --- |
| free_dual | 18 | 124 [112,154] | 119.5 | 46.975 | 844.844 |
| legacy_hcsn | 18 | 228.5 [198,267] | 216 | 44.507 | 800.580 |
| two_gates | 18 | 1055.5 [848,1247] | 697 | 43.568 | 784.908 |
| continuous_rnn | 18 | 1284 [1153,1634] | 1241 | 43.603 | 786.273 |
| cfc | 18 | 854 [713,1016] | 246.5 | 43.566 | 783.959 |
| mamba1 | 18 | 596.5 [508,702] | 553 | 43.833 | 790.469 |
| transformer | 18 | 2180.5 [1887,2642] | 584 | 43.851 | 789.731 |
| lif_snn | 18 | 917.5 [801,1059] | 823 | 43.552 | 784.802 |

### Two-task, eight-seed mechanism compute

Each row covers 16 searches. These rows overlap the core where task/model/seed match and must not be added to the core bill. They give actual update/CPU information for every additional mechanism arm.

| Model | Searches | Updates/LR median [min,max] | Selected step median | Full search CPU median, s | Full search CPU sum, s |
| --- | --- | --- | --- | --- | --- |
| free_dual | 16 | 124.5 [112,137] | 123 | 46.962 | 750.715 |
| fixed_dual | 16 | 155.5 [124,181] | 144 | 44.923 | 717.184 |
| direct_dual | 16 | 146.5 [127,177] | 138 | 45.050 | 718.447 |
| free_margin | 16 | 148 [130,172] | 133 | 46.913 | 751.338 |
| free_continuation | 16 | 129 [113,152] | 125 | 46.893 | 751.698 |
| free_ordinary | 16 | 139 [119,154] | 127 | 46.868 | 751.995 |
| two_gates | 16 | 1049.5 [902,1272] | 758 | 43.552 | 697.230 |

### Cost reconciliation

| Measured scope | CPU seconds | Meaning |
| --- | --- | --- |
| Nominal training-update allocation | 9760.000000 | 488 LR candidates × 20 CPU s |
| Actual measured training-update CPU | 9781.257108 | Includes finishing the update that crosses the budget |
| All complete search children: aggregate RUSAGE_CHILDREN | 10958.946598 | Includes imports/setup/two LRs/validation/checkpoint/holdout costs |
| All complete search children: sum of individual wait4 receipts | 10958.946351 | Preserved second measurement route |
| Scheduler self CPU | 2.086670 | Separate from search children |
| Primary analysis complete child | 8.308143 | Imports, integrity audit, metrics, statistics and output writes |
| Exactly-128 secondary complete child | 83.157664 | Eligibility/hash checks and new heldout inference; no new training |

The main matrix wall time is 3961.125580 seconds. The two child-CPU routes differ by 0.000247000 seconds (247 microseconds). Every one of the 244 COMPLETE result rows exactly matches its per-run EXECUTION receipt. The tiny aggregate-versus-sum difference is consistent with separately accumulated microsecond reporting; neither value is adjusted or redistributed. These nested cost scopes must not be added as independent costs.

The analysis also preserves setup, validation, holdout and outside-search-function costs per run. The latter combines interpreter/import/startup/shutdown overhead; it is not a separately isolated import benchmark. Whole-process peak RSS is not model-only allocation, and per-process peaks are not summed into a simultaneous-memory estimate. No hardware energy was measured. Shared data/native/scaling/solver work has separate receipts and is not hidden inside the main training total.

## Joint trainability and selected-checkpoint evidence

All 108 required HCSN-family runs pass all five parameter-group checks: finite gradients through the selected update, at least one nonzero gradient, and independently recomputed nonzero change from initialization to the actual selected checkpoint. No recorded gradient element is missing. All separately named drift/noise/discount/cost/reset/refractory tensors changed.

For the 28 free_dual searches specifically:

| Parameter group | Runs | Minimum selected-change L2 | Minimum across runs of observed max absolute gradient | Check |
| --- | --- | --- | --- | --- |
| content | 28 | 0.754486 | 0.237783 | pass |
| dynamics | 28 | 0.34588 | 0.000538224 | pass |
| boundary | 28 | 0.03365 | 2.70942e-06 | pass |
| reset | 28 | 0.0545064 | 3.98495e-05 | pass |
| refractory | 28 | 0.043809 | 9.49718e-06 | pass |

A group passing this audit proves that the implemented loss reaches and updates it. It does not prove every scalar has a large gradient, that the learned mechanism is causally necessary, or that optimization found a good solution. The accuracy results above remain negative despite valid gradients and actual updates.

## Data strata and scope of multimodality

Every task has 1,024 training, 256 validation and 512 test episodes. Copy/MQAR supervise four query positions per episode; the other tasks supervise one. Source-image IDs, audio recording IDs and speakers are disjoint across train/validation/test where applicable. The FSDD subset has only 600 unique recordings: 300 train, 100 validation and 200 test; test episodes repeat those 200 recordings. Test speakers are lucas and yweweler, with 100 recordings each. These are not official FSDD benchmark splits.

Audio features use complete utterances. The multimodal task combines image/audio inputs with four fixed query tokens; it does not test raw live microphone causality or open-ended natural language. The test has 272 image queries, 240 spoken queries, 46 image/audio digit agreements and 466 disagreements. Repeated recordings and the training-seed repetitions do not create new independent recordings.

The table is accuracy %, mean ± sample SD over three seeds. FSDD speaker columns each have 256 episodes. Multimodal agreement and disagreement strata have different sizes and must not be averaged equally to reconstruct overall accuracy.

| Model | FSDD lucas | FSDD yweweler | MM image query | MM spoken query | MM digits agree | MM digits disagree |
| --- | --- | --- | --- | --- | --- | --- |
| free_dual | 10.81 ± 1.85 | 10.03 ± 0.45 | 18.38 ± 2.92 | 11.53 ± 0.64 | 15.94 ± 3.32 | 15.09 ± 1.22 |
| legacy_hcsn | 28.12 ± 5.91 | 10.68 ± 1.26 | 23.16 ± 3.62 | 13.19 ± 1.58 | 21.74 ± 11.50 | 18.17 ± 1.79 |
| two_gates | 23.57 ± 2.60 | 10.94 ± 0.68 | 34.07 ± 11.03 | 11.25 ± 1.82 | 31.16 ± 1.26 | 22.60 ± 5.61 |
| continuous_rnn | 19.66 ± 4.10 | 8.07 ± 4.98 | 37.25 ± 4.60 | 12.36 ± 2.44 | 27.54 ± 1.26 | 25.39 ± 2.41 |
| cfc | 12.50 ± 3.73 | 9.77 ± 0.39 | 22.55 ± 5.36 | 12.36 ± 1.27 | 13.04 ± 2.17 | 18.24 ± 2.84 |
| mamba1 | 29.17 ± 13.07 | 14.06 ± 5.37 | 28.43 ± 22.23 | 12.50 ± 4.23 | 28.26 ± 13.22 | 20.24 ± 9.83 |
| transformer | 37.76 ± 3.28 | 19.14 ± 3.58 | 31.37 ± 3.77 | 22.64 ± 4.28 | 39.86 ± 3.32 | 26.04 ± 2.91 |
| lif_snn | 15.10 ± 4.71 | 10.55 ± 1.03 | 33.82 ± 6.14 | 8.61 ± 0.64 | 27.54 ± 3.32 | 21.46 ± 3.33 |

The free cell's modality-specific means are low on both image and spoken queries; this does not support a claim that it solves all modalities. The complete query-by-agreement and speaker strata, including source counts, remain in DATA_STRATA.json. No episode-independence significance claim is made from these descriptive strata.

## Exactly-128-update secondary: completed evaluation, incomplete coverage

The secondary requires **both** prescribed LR candidates to contain a saved checkpoint at exactly update 128. LR selection uses only each candidate's validation loss at that update, with a smaller-LR tie break. Missing 128 checkpoints are not replaced with nearby updates, a single available LR, extrapolation, or new training. Primary choices and costs are unchanged.

202 of 244 run-level searches are eligible and evaluated; 42 are explicitly incomplete; zero are invalid. All newly saved supervised predictions, coordinate mappings and metrics were independently verified after evaluation. The two-LR availability counts below are `evaluated/scheduled (−missing)`.

| Model | Copy | MQAR | Irregular | MNIST | FSDD | Multimodal |
| --- | --- | --- | --- | --- | --- | --- |
| free_dual | 1/8 (−7) | 0/3 (−3) | 1/3 (−2) | 0/3 (−3) | 1/3 (−2) | 0/8 (−8) |
| legacy_hcsn | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) |
| two_gates | 8/8 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 8/8 (−0) |
| continuous_rnn | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) |
| cfc | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) |
| mamba1 | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) |
| transformer | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) |
| lif_snn | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) | 3/3 (−0) |
| fixed_dual | 8/8 (−0) | not scheduled | not scheduled | not scheduled | not scheduled | 7/8 (−1) |
| direct_dual | 8/8 (−0) | not scheduled | not scheduled | not scheduled | not scheduled | 7/8 (−1) |
| free_margin | 8/8 (−0) | not scheduled | not scheduled | not scheduled | not scheduled | 8/8 (−0) |
| free_continuation | 2/8 (−6) | not scheduled | not scheduled | not scheduled | not scheduled | 5/8 (−3) |
| free_ordinary | 6/8 (−2) | not scheduled | not scheduled | not scheduled | not scheduled | 4/8 (−4) |

Only 2 of 18 core task-seed panels contain all eight models, and 0 of six tasks has all eight models across all three core seeds. The two complete task-seed panels are FSDD/9103 and irregular/9103. free_dual has only 3/28 eligible searches in the entire matrix: selective_copy/9108, irregular/9103 and fsdd/9103. Its multimodal_select coverage is 0/8, so no eight-seed two-task free-cell mechanism comparison at exactly128 is available.

This secondary therefore does not establish an equal-update advantage or deficit for the free cell across the registered matrix. The seven baseline models' complete coverage cannot repair missing free-cell observations. No failed completeness gate is silently reduced to a convenient subset. The saved eligible predictions remain available for explicitly limited descriptive inspection, but the main equal-CPU result is not replaced by such a subset.

Equal update counts would also not imply equal CPU cost. The recorded training-prefix CPU describes already existing snapshots; all original full LR searches remain charged. The additional secondary inference consumes new CPU and is recorded separately. There is no basis here to infer that the large equal-CPU gaps are exclusively update-count effects or exclusively differences in representation quality.

## Interpretation and reproducibility

This study supports a narrower feasibility statement: the stationary scalar
oracle, its first derivative, and a content-carrying neural cell can be
implemented and trained jointly; selections and predictions can be audited.
It does not support the proposed accuracy or compute superiority of this cell
over the tested ordinary recurrent/gated/attention alternatives under the
registered small CPU budget. It also gives no foundation-model, full-modality,
hardware-energy or optimized deployment result.

The underlying neuron is a frozen-local mean-state closure, not exact
continuous stochastic regeneration. Its independently measured closure bias
remains a separate limitation; these task results do not identify that bias as
the sole cause of poor accuracy. Likewise, an optional faster scalar root was
tested in a separate extension and was not retroactively used in these runs.
An exact scalar optimal-control proof does not by itself certify a neural
content advantage.

The baseline implementations, dataset transformations, two-rate search,
20-CPU-second allocation and three/eight seed counts define the evidence's
scope. Other configurations may behave differently; none were substituted
after seeing these outcomes. Original static-direct fairness limitations and
the separately registered conditional control are reported openly.

Primary artifacts are `ANALYSIS.json`, `CORE_TABLE.csv`, `MECHANISM_TABLE.csv`,
`TRAINABILITY.json` and `DATA_STRATA.json`. This report adds
`SUPPLEMENTARY_AUDIT.json`, `MODEL_COMPUTE.csv` and `SECONDARY_COVERAGE.csv`.
The latter audit binds all report inputs, rechecks every original selected
checkpoint, verifies every eligible secondary prediction archive, and records
all 42 missing secondary searches with their actual primary update counts.
Both complete analysis-process receipts are preserved next to analysis001.

The reproducible reporting command is:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m experiments.hcsn_free_boundary_v1.analysis_report
```

It performs no new neural inference or training and refuses to overwrite
existing reporting evidence. The original analysis/secondary commands likewise
preserve their first outputs. No frozen training source, data, protocol,
checkpoint or primary outcome was edited for this report.
