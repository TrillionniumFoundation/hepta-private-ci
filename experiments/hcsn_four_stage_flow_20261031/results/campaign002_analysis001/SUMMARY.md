# Four-stage campaign analysis

Run: `/workspace/scratch/b25b6786d3b7/hepta-csn-four-stage/experiments/hcsn_four_stage_flow_20261031/results/campaign002`

Integrity: **PASS**. Readable completed fits: 75/75; individually valid: 75/75; retained failed attempts: 0.

Protocol SHA-256: `26e401d211a3c72f80b68d292b54980ef18601bafbb519ee4ffd3dd2f27babdc`. Analysis SHA-256: `bb6557dcf9511bfed9162076c44d07f0637049f79712f096014b8422fab0de00`.

## Interpretation and metric definitions

- Only three independent training seeds: hierarchical bootstrap intervals have low power and uncertain tail coverage.
- The fixed primary contrast is flow minus diagonal. Other arm contrasts, stresses, and interventions are exploratory; intervals are not multiplicity adjusted.
- Seed draws are paired across arms, and each bootstrap replicate uses the same resampled episodes or actors in every selected seed. Queries are never treated as independent replicates.
- Accuracy and cross entropy use archive sample weights. All-query correctness is the runner's unweighted mean over episodes; weighted all-query correctness is reported separately.
- For AVT, each episode has one query: unweighted all-query correctness equals unweighted accuracy. Always-negative gives 3/4 unweighted accuracy but 1/2 weighted accuracy. The weighted single-modality and two-modality Bayes oracles are 1/2 and 5/6.
- AVT uses two sentences and fixed non-pretrained causal-prefix features; it does not validate a foundation model, general language generation, or all-modal alignment.
- Synthetic content irregular stress redraws time from the same distribution. Dynamics irregular stress changes physical time and therefore can change its ground truth.
- Missing-observation world labels are retained. In the three synthetic content tasks, target-visible versus target-missing strata distinguish state evolution errors from information deletion; that mask is evaluation-only. Dynamics has no such target-availability mask.
- Flow no_marks and factorized_content are interventions on a trained checkpoint, not retrained ablations or proofs of causal necessity. No query-swap experiment is implemented.
- Models share information and training steps, but parameter counts and actual compute are unequal. This is not a matched-FLOP or matched-wall-time superiority test.
- Inference timing is a full-sequence CPU batch on a shared host, not batch-one latency, an incremental streaming kernel, GPU performance, or measured energy.
- Fit totals include their own training and evaluation costs and are counted once. Outer process receipts and feature preparation are separate accounting views, not quantities to add blindly to fit totals.
- Process peak RSS is a process-lifetime high-water mark, not an isolated per-fit memory measurement. Persistent state excludes training activations, optimizer state, and temporary kernels.
- Finite CTMC reference kernels and task-trained boundaries do not establish the full He-Xiong equity model, optimal stopping, a deep boundary-communicating network, or independent call/put force channels.

## Base-test quality

Mean ± sample SD across three training seeds. Accuracy and weighted all-query use sample weights; AQ is the unweighted all-query episode rate. Values are percentages except CE.

| Task | Arm | Seeds | Weighted accuracy | CE | AQ | Weighted AQ | Unweighted accuracy |
|---|---|---:|---:|---:|---:|---:|---:|
| dynamics | flow | 3 | 87.915 ± 0.042 | 0.280 ± 0.003 | 38.802 ± 0.451 | 38.802 ± 0.451 | 87.915 ± 0.042 |
| dynamics | diagonal | 3 | 87.769 ± 0.152 | 0.290 ± 0.001 | 39.062 ± 1.033 | 39.062 ± 1.033 | 87.769 ± 0.152 |
| dynamics | gru | 3 | 88.843 ± 0.794 | 0.263 ± 0.022 | 43.034 ± 1.761 | 43.034 ± 1.761 | 88.843 ± 0.794 |
| dynamics | snn | 3 | 89.893 ± 0.065 | 0.249 ± 0.002 | 45.182 ± 0.739 | 45.182 ± 0.739 | 89.893 ± 0.065 |
| dynamics | transformer | 3 | 90.088 ± 0.927 | 0.232 ± 0.015 | 48.633 ± 4.568 | 48.633 ± 4.568 | 90.088 ± 0.927 |
| mqar | flow | 3 | 24.870 ± 0.346 | 1.672 ± 0.093 | 0.000 ± 0.000 | 0.000 ± 0.000 | 24.870 ± 0.346 |
| mqar | diagonal | 3 | 25.098 ± 0.342 | 1.545 ± 0.135 | 0.000 ± 0.000 | 0.000 ± 0.000 | 25.098 ± 0.342 |
| mqar | gru | 3 | 24.756 ± 0.272 | 1.396 ± 0.001 | 0.000 ± 0.000 | 0.000 ± 0.000 | 24.756 ± 0.272 |
| mqar | snn | 3 | 25.358 ± 0.298 | 1.417 ± 0.002 | 0.000 ± 0.000 | 0.000 ± 0.000 | 25.358 ± 0.298 |
| mqar | transformer | 3 | 100.000 ± 0.000 | 0.001 ± 0.000 | 100.000 ± 0.000 | 100.000 ± 0.000 | 100.000 ± 0.000 |
| selective | flow | 3 | 23.893 ± 0.325 | 1.861 ± 0.011 | 0.000 ± 0.000 | 0.000 ± 0.000 | 23.893 ± 0.325 |
| selective | diagonal | 3 | 24.821 ± 0.360 | 1.809 ± 0.008 | 0.000 ± 0.000 | 0.000 ± 0.000 | 24.821 ± 0.360 |
| selective | gru | 3 | 24.251 ± 0.395 | 1.779 ± 0.008 | 0.000 ± 0.000 | 0.000 ± 0.000 | 24.251 ± 0.395 |
| selective | snn | 3 | 23.470 ± 0.421 | 1.944 ± 0.006 | 0.000 ± 0.000 | 0.000 ± 0.000 | 23.470 ± 0.421 |
| selective | transformer | 3 | 40.186 ± 32.622 | 1.507 ± 0.776 | 11.784 ± 20.410 | 11.784 ± 20.410 | 40.186 ± 32.622 |
| binding | flow | 3 | 24.935 ± 0.286 | 1.646 ± 0.081 | 0.000 ± 0.000 | 0.000 ± 0.000 | 24.935 ± 0.286 |
| binding | diagonal | 3 | 24.788 ± 0.241 | 1.521 ± 0.052 | 0.000 ± 0.000 | 0.000 ± 0.000 | 24.788 ± 0.241 |
| binding | gru | 3 | 25.146 ± 0.514 | 1.396 ± 0.002 | 0.000 ± 0.000 | 0.000 ± 0.000 | 25.146 ± 0.514 |
| binding | snn | 3 | 24.577 ± 1.326 | 1.429 ± 0.005 | 0.000 ± 0.000 | 0.000 ± 0.000 | 24.577 ± 1.326 |
| binding | transformer | 3 | 25.228 ± 0.489 | 1.429 ± 0.054 | 0.000 ± 0.000 | 0.000 ± 0.000 | 25.228 ± 0.489 |
| avt | flow | 3 | 49.942 ± 0.100 | 0.695 ± 0.001 | 67.274 ± 13.381 | 49.942 ± 0.100 | 67.274 ± 13.381 |
| avt | diagonal | 3 | 49.769 ± 0.401 | 0.694 ± 0.001 | 70.833 ± 6.771 | 49.769 ± 0.401 | 70.833 ± 6.771 |
| avt | gru | 3 | 49.942 ± 0.100 | 0.694 ± 0.001 | 59.809 ± 15.931 | 49.942 ± 0.100 | 59.809 ± 15.931 |
| avt | snn | 3 | 50.116 ± 0.200 | 0.695 ± 0.001 | 73.090 ± 2.869 | 50.116 ± 0.200 | 73.090 ± 2.869 |
| avt | transformer | 3 | 50.000 ± 0.000 | 0.695 ± 0.003 | 58.333 ± 28.868 | 50.000 ± 0.000 | 58.333 ± 28.868 |

## Primary contrast: flow − diagonal

Paired differences in percentage points with 95% hierarchical percentile intervals. Three seeds provide limited uncertainty resolution; no multiplicity adjustment.

| Task | Contrast | Cluster unit/count | Weighted accuracy Δ [95% CI] | AQ Δ [95% CI] |
|---|---|---|---:|---:|
| dynamics | flow - diagonal | episode / 512 | 0.15 [-0.26, 0.56] | -0.26 [-2.28, 1.76] |
| mqar | flow - diagonal | episode / 512 | -0.23 [-1.06, 0.59] | 0.00 [0.00, 0.00] |
| selective | flow - diagonal | episode / 512 | -0.93 [-1.81, -0.11] | 0.00 [0.00, 0.00] |
| binding | flow - diagonal | episode / 512 | 0.15 [-0.68, 1.01] | 0.00 [0.00, 0.00] |
| avt | flow - diagonal | actor / 8 | 0.17 [-0.75, 1.56] | -3.56 [-12.50, 0.69] |

## Exploratory base-test contrasts

Paired differences in percentage points with 95% hierarchical percentile intervals. Three seeds provide limited uncertainty resolution; no multiplicity adjustment.

| Task | Contrast | Cluster unit/count | Weighted accuracy Δ [95% CI] | AQ Δ [95% CI] |
|---|---|---|---:|---:|
| dynamics | flow - gru | episode / 512 | -0.93 [-2.06, 0.16] | -4.23 [-8.01, -0.32] |
| dynamics | flow - snn | episode / 512 | -1.98 [-2.74, -1.20] | -6.38 [-9.90, -2.99] |
| dynamics | flow - transformer | episode / 512 | -2.17 [-3.49, -0.97] | -9.83 [-15.23, -4.04] |
| mqar | flow - gru | episode / 512 | 0.11 [-1.03, 1.40] | 0.00 [0.00, 0.00] |
| mqar | flow - snn | episode / 512 | -0.49 [-1.55, 0.55] | 0.00 [0.00, 0.00] |
| mqar | flow - transformer | episode / 512 | -75.13 [-75.73, -74.56] | -100.00 [-100.00, -100.00] |
| selective | flow - gru | episode / 512 | -0.36 [-1.07, 0.34] | 0.00 [0.00, 0.00] |
| selective | flow - snn | episode / 512 | 0.42 [-0.44, 1.27] | 0.00 [0.00, 0.00] |
| selective | flow - transformer | episode / 512 | -16.29 [-53.27, 3.96] | -11.78 [-34.57, 0.00] |
| binding | flow - gru | episode / 512 | -0.21 [-1.40, 0.96] | 0.00 [0.00, 0.00] |
| binding | flow - snn | episode / 512 | 0.36 [-1.04, 1.82] | 0.00 [0.00, 0.00] |
| binding | flow - transformer | episode / 512 | -0.29 [-1.51, 0.98] | 0.00 [0.00, 0.00] |
| avt | flow - gru | actor / 8 | 0.00 [-1.16, 1.22] | 7.47 [0.00, 15.19] |
| avt | flow - snn | actor / 8 | -0.17 [-1.39, 1.04] | -5.82 [-22.92, 5.03] |
| avt | flow - transformer | actor / 8 | -0.06 [-1.04, 0.81] | 8.94 [0.00, 26.83] |

## Stress conditions

Weighted accuracy / unweighted all-query rate, each in percent and averaged across seeds. Full seed SDs, CE, and paired exploratory intervals are in SUMMARY.json.

| Task | Arm | Condition | Accuracy | AQ | Visible-target accuracy | Missing-target accuracy |
|---|---|---|---:|---:|---:|---:|
| dynamics | flow | irregular | 87.736 | 39.258 | NA | NA |
| dynamics | flow | missing | 86.100 | 32.487 | NA | NA |
| dynamics | flow | resample | 87.915 | 38.802 | NA | NA |
| dynamics | diagonal | irregular | 87.134 | 38.021 | NA | NA |
| dynamics | diagonal | missing | 85.091 | 28.841 | NA | NA |
| dynamics | diagonal | resample | 87.769 | 39.062 | NA | NA |
| dynamics | gru | irregular | 87.459 | 37.695 | NA | NA |
| dynamics | gru | missing | 85.067 | 28.385 | NA | NA |
| dynamics | gru | resample | 88.843 | 43.034 | NA | NA |
| dynamics | snn | irregular | 89.355 | 44.206 | NA | NA |
| dynamics | snn | missing | 87.394 | 33.203 | NA | NA |
| dynamics | snn | resample | 89.893 | 45.182 | NA | NA |
| dynamics | transformer | irregular | 89.624 | 47.461 | NA | NA |
| dynamics | transformer | missing | 90.023 | 48.177 | NA | NA |
| dynamics | transformer | resample | 90.088 | 48.633 | NA | NA |
| mqar | flow | irregular | 24.967 | 0.000 | 24.967 | NA |
| mqar | flow | long_delay | 24.821 | 0.000 | 24.821 | NA |
| mqar | flow | missing | 24.740 | 0.000 | 32.812 | 0.521 |
| mqar | flow | resample | 24.870 | 0.000 | 24.870 | NA |
| mqar | diagonal | irregular | 25.114 | 0.000 | 25.114 | NA |
| mqar | diagonal | long_delay | 24.837 | 0.000 | 24.837 | NA |
| mqar | diagonal | missing | 24.723 | 0.000 | 32.899 | 0.195 |
| mqar | diagonal | resample | 25.098 | 0.000 | 25.098 | NA |
| mqar | gru | irregular | 24.967 | 0.000 | 24.967 | NA |
| mqar | gru | long_delay | 24.951 | 0.000 | 24.951 | NA |
| mqar | gru | missing | 24.821 | 0.000 | 33.095 | 0.000 |
| mqar | gru | resample | 24.756 | 0.000 | 24.756 | NA |
| mqar | snn | irregular | 24.886 | 0.065 | 24.886 | NA |
| mqar | snn | long_delay | 24.707 | 0.000 | 24.707 | NA |
| mqar | snn | missing | 24.593 | 0.000 | 32.791 | 0.000 |
| mqar | snn | resample | 25.358 | 0.000 | 25.358 | NA |
| mqar | transformer | irregular | 100.000 | 100.000 | 100.000 | NA |
| mqar | transformer | long_delay | 99.984 | 99.935 | 99.984 | NA |
| mqar | transformer | missing | 77.181 | 8.919 | 99.935 | 8.919 |
| mqar | transformer | resample | 100.000 | 100.000 | 100.000 | NA |
| selective | flow | irregular | 23.877 | 0.000 | 23.877 | NA |
| selective | flow | long_delay | 23.910 | 0.000 | 23.910 | NA |
| selective | flow | missing | 22.819 | 0.000 | 27.620 | 0.000 |
| selective | flow | resample | 23.893 | 0.000 | 23.893 | NA |
| selective | diagonal | irregular | 24.723 | 0.000 | 24.723 | NA |
| selective | diagonal | long_delay | 24.137 | 0.000 | 24.137 | NA |
| selective | diagonal | missing | 23.649 | 0.000 | 28.625 | 0.000 |
| selective | diagonal | resample | 24.821 | 0.000 | 24.821 | NA |
| selective | gru | irregular | 23.958 | 0.000 | 23.958 | NA |
| selective | gru | long_delay | 24.137 | 0.000 | 24.137 | NA |
| selective | gru | missing | 23.161 | 0.000 | 28.034 | 0.000 |
| selective | gru | resample | 24.251 | 0.000 | 24.251 | NA |
| selective | snn | irregular | 23.438 | 0.000 | 23.438 | NA |
| selective | snn | long_delay | 20.654 | 0.000 | 20.654 | NA |
| selective | snn | missing | 23.096 | 0.000 | 27.916 | 0.187 |
| selective | snn | resample | 23.470 | 0.000 | 23.470 | NA |
| selective | transformer | irregular | 39.616 | 11.589 | 39.616 | NA |
| selective | transformer | long_delay | 39.746 | 11.589 | 39.746 | NA |
| selective | transformer | missing | 35.970 | 4.622 | 43.164 | 1.779 |
| selective | transformer | resample | 40.186 | 11.784 | 40.186 | NA |
| binding | flow | irregular | 24.756 | 0.000 | 24.756 | NA |
| binding | flow | long_delay | 24.870 | 0.000 | 24.870 | NA |
| binding | flow | missing | 24.284 | 0.000 | 32.161 | 0.651 |
| binding | flow | resample | 24.935 | 0.000 | 24.935 | NA |
| binding | diagonal | irregular | 25.114 | 0.000 | 25.114 | NA |
| binding | diagonal | long_delay | 25.049 | 0.000 | 25.049 | NA |
| binding | diagonal | missing | 24.414 | 0.000 | 32.465 | 0.260 |
| binding | diagonal | resample | 24.788 | 0.000 | 24.788 | NA |
| binding | gru | irregular | 25.586 | 0.000 | 25.586 | NA |
| binding | gru | long_delay | 25.342 | 0.000 | 25.342 | NA |
| binding | gru | missing | 24.854 | 0.000 | 33.138 | 0.000 |
| binding | gru | resample | 25.146 | 0.000 | 25.146 | NA |
| binding | snn | irregular | 24.544 | 0.000 | 24.544 | NA |
| binding | snn | long_delay | 25.260 | 0.000 | 25.260 | NA |
| binding | snn | missing | 24.723 | 0.000 | 32.964 | 0.000 |
| binding | snn | resample | 24.577 | 0.000 | 24.577 | NA |
| binding | transformer | irregular | 25.146 | 0.000 | 25.146 | NA |
| binding | transformer | long_delay | 25.049 | 0.065 | 25.049 | NA |
| binding | transformer | missing | 24.886 | 0.000 | 33.138 | 0.130 |
| binding | transformer | resample | 25.228 | 0.000 | 25.228 | NA |
| avt | flow | no_audio | 50.231 | 67.708 | NA | NA |
| avt | flow | no_text | 50.116 | 67.014 | NA | NA |
| avt | flow | no_video | 50.231 | 69.965 | NA | NA |
| avt | diagonal | no_audio | 50.579 | 68.924 | NA | NA |
| avt | diagonal | no_text | 49.769 | 70.312 | NA | NA |
| avt | diagonal | no_video | 50.116 | 71.007 | NA | NA |
| avt | gru | no_audio | 50.231 | 64.931 | NA | NA |
| avt | gru | no_text | 50.116 | 60.069 | NA | NA |
| avt | gru | no_video | 49.884 | 60.069 | NA | NA |
| avt | snn | no_audio | 50.231 | 73.090 | NA | NA |
| avt | snn | no_text | 50.116 | 72.917 | NA | NA |
| avt | snn | no_video | 49.769 | 72.917 | NA | NA |
| avt | transformer | no_audio | 50.000 | 58.333 | NA | NA |
| avt | transformer | no_text | 50.000 | 58.333 | NA | NA |
| avt | transformer | no_video | 50.000 | 58.333 | NA | NA |

## Flow sensitivities

Full trained flow minus its inference intervention; these are exploratory sensitivities. Positive Δ indicates the intervention worsens that metric.

| Task | Intervention contrast | Weighted accuracy Δ [95% CI] | AQ Δ [95% CI] |
|---|---|---:|---:|
| dynamics | full flow - no_marks | 0.01 [-0.27, 0.25] | -0.39 [-1.76, 0.85] |
| dynamics | full flow - factorized_content | 0.02 [-0.18, 0.21] | 0.13 [-0.72, 0.98] |
| mqar | full flow - no_marks | -0.05 [-0.29, 0.18] | 0.00 [0.00, 0.00] |
| mqar | full flow - factorized_content | 0.00 [-0.07, 0.07] | 0.00 [0.00, 0.00] |
| selective | full flow - no_marks | 0.15 [-0.16, 0.49] | 0.00 [0.00, 0.00] |
| selective | full flow - factorized_content | 0.02 [0.00, 0.10] | 0.00 [0.00, 0.00] |
| binding | full flow - no_marks | 0.00 [-0.34, 0.37] | 0.00 [0.00, 0.00] |
| binding | full flow - factorized_content | -0.02 [-0.10, 0.00] | 0.00 [0.00, 0.00] |
| avt | full flow - no_marks | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| avt | full flow - factorized_content | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |

## Dynamics recovery

First query after the jump is position 9; later queries are positions 11, 13, and 15 (zero-based). Forcing-only is the runner's recorded quantized-forcing baseline; the archive does not contain its input values for independent reconstruction.

| Arm | First after jump (%) | Later after jump (%) | Forcing-only query accuracy (%) |
|---|---:|---:|---:|
| flow | 77.799 ± 0.597 | 92.535 ± 0.263 | 81.177 ± 0.000 |
| diagonal | 78.646 ± 0.813 | 92.491 ± 0.229 | 81.177 ± 0.000 |
| gru | 79.232 ± 0.298 | 92.730 ± 1.109 | 81.177 ± 0.000 |
| snn | 81.771 ± 0.492 | 93.902 ± 0.075 | 81.177 ± 0.000 |
| transformer | 83.854 ± 1.591 | 92.057 ± 0.686 | 81.177 ± 0.000 |

## Resampling consistency

Maximum absolute logit difference at original observation positions, taking the worst of the three seeds; the declared threshold is 1e-4. This numerical gate is separate from accuracy.

| Task | Arm | Worst difference | All three seeds pass |
|---|---|---:|---|
| dynamics | flow | 0.00000381 | True (3/3 seeds) |
| dynamics | diagonal | 0.00000191 | True (3/3 seeds) |
| dynamics | gru | 0.00000191 | True (3/3 seeds) |
| dynamics | snn | 0.62722349 | False (3/3 seeds) |
| dynamics | transformer | 0.00000238 | True (3/3 seeds) |
| mqar | flow | 0.00000238 | True (3/3 seeds) |
| mqar | diagonal | 0.00000226 | True (3/3 seeds) |
| mqar | gru | 0.00000143 | True (3/3 seeds) |
| mqar | snn | 0.00000197 | True (3/3 seeds) |
| mqar | transformer | 0.00003123 | True (3/3 seeds) |
| selective | flow | 0.00000143 | True (3/3 seeds) |
| selective | diagonal | 0.00000131 | True (3/3 seeds) |
| selective | gru | 0.00000095 | True (3/3 seeds) |
| selective | snn | 0.00000036 | True (3/3 seeds) |
| selective | transformer | 0.00000978 | True (3/3 seeds) |
| binding | flow | 0.00000238 | True (3/3 seeds) |
| binding | diagonal | 0.00000143 | True (3/3 seeds) |
| binding | gru | 0.00000143 | True (3/3 seeds) |
| binding | snn | 0.00000274 | True (3/3 seeds) |
| binding | transformer | 0.00000298 | True (3/3 seeds) |

## Compute and state

Training CPU and total-fit CPU are per-seed mean ± SD, in seconds. Batch latency is the mean of each seed's nine-repeat median; the batch size is recorded per fit in JSON. Amortized latency is a throughput ratio, not single-episode latency.

| Task | Arm | Parameters | State scalars | Training CPU (s) | Total fit CPU (s) | Batch latency (ms) | Amortized ms/episode |
|---|---|---:|---:|---:|---:|---:|---:|
| dynamics | flow | 11332 | 127 | 18.263 ± 0.440 | 19.185 ± 0.416 | 9.393 ± 3.540 | 0.391 ± 0.148 |
| dynamics | diagonal | 11407 | 120 | 6.256 ± 0.505 | 6.483 ± 0.483 | 2.056 ± 0.123 | 0.086 ± 0.005 |
| dynamics | gru | 24500 | 64 | 5.492 ± 0.268 | 5.707 ± 0.263 | 2.067 ± 0.087 | 0.086 ± 0.004 |
| dynamics | snn | 17012 | 128 | 5.402 ± 0.283 | 5.636 ± 0.283 | 2.248 ± 0.131 | 0.094 ± 0.005 |
| dynamics | transformer | 15868 | 1536 | 2.990 ± 0.032 | 3.168 ± 0.032 | 1.014 ± 0.018 | 0.042 ± 0.001 |
| mqar | flow | 11592 | 127 | 14.543 ± 0.881 | 15.622 ± 0.938 | 6.202 ± 0.430 | 0.258 ± 0.018 |
| mqar | diagonal | 11667 | 120 | 5.077 ± 0.301 | 5.451 ± 0.339 | 2.191 ± 0.986 | 0.091 ± 0.041 |
| mqar | gru | 24760 | 64 | 4.728 ± 0.372 | 5.153 ± 0.439 | 2.149 ± 0.792 | 0.090 ± 0.033 |
| mqar | snn | 17272 | 128 | 4.583 ± 0.168 | 4.961 ± 0.142 | 1.626 ± 0.032 | 0.068 ± 0.001 |
| mqar | transformer | 15968 | 1152 | 3.764 ± 0.181 | 4.134 ± 0.182 | 1.244 ± 0.036 | 0.052 ± 0.002 |
| selective | flow | 11592 | 127 | 15.627 ± 0.345 | 16.738 ± 0.446 | 6.591 ± 0.687 | 0.275 ± 0.029 |
| selective | diagonal | 11667 | 120 | 5.927 ± 0.326 | 6.345 ± 0.309 | 1.967 ± 0.308 | 0.082 ± 0.013 |
| selective | gru | 24760 | 64 | 5.556 ± 0.492 | 5.982 ± 0.522 | 1.792 ± 0.089 | 0.075 ± 0.004 |
| selective | snn | 17272 | 128 | 5.731 ± 0.618 | 6.220 ± 0.697 | 2.239 ± 0.371 | 0.093 ± 0.015 |
| selective | transformer | 15968 | 1344 | 4.181 ± 0.384 | 4.659 ± 0.361 | 1.540 ± 0.192 | 0.064 ± 0.008 |
| binding | flow | 11592 | 127 | 19.173 ± 0.736 | 20.453 ± 0.777 | 6.901 ± 0.229 | 0.288 ± 0.010 |
| binding | diagonal | 11667 | 120 | 6.556 ± 0.056 | 7.008 ± 0.043 | 2.033 ± 0.037 | 0.085 ± 0.002 |
| binding | gru | 24760 | 64 | 5.994 ± 0.161 | 6.430 ± 0.149 | 1.883 ± 0.027 | 0.078 ± 0.001 |
| binding | snn | 17272 | 128 | 6.311 ± 0.161 | 6.786 ± 0.153 | 2.256 ± 0.352 | 0.094 ± 0.015 |
| binding | transformer | 15968 | 1536 | 4.429 ± 0.366 | 4.832 ± 0.374 | 1.063 ± 0.062 | 0.044 ± 0.003 |
| avt | flow | 14058 | 127 | 5.457 ± 0.289 | 5.655 ± 0.295 | 3.181 ± 0.290 | 0.133 ± 0.012 |
| avt | diagonal | 14133 | 120 | 1.393 ± 0.085 | 1.423 ± 0.087 | 0.337 ± 0.018 | 0.014 ± 0.001 |
| avt | gru | 27226 | 64 | 1.336 ± 0.046 | 1.367 ± 0.050 | 0.347 ± 0.048 | 0.014 ± 0.002 |
| avt | snn | 19738 | 128 | 1.321 ± 0.037 | 1.352 ± 0.041 | 0.348 ± 0.020 | 0.015 ± 0.001 |
| avt | transformer | 18674 | 192 | 2.181 ± 0.076 | 2.223 ± 0.077 | 0.496 ± 0.018 | 0.021 ± 0.001 |

### Cost accounting

- Completed-fit CPU total, counted once: 518.919 s; summed per-fit wall time: 525.545 s. Summed wall time is not necessarily campaign elapsed time.
- Training CPU subtotal inside those fits: 486.818 s; it is not added again.
- Failure-attempt receipts: CPU 0.000 s, wall 0.000 s. Reported separately: failed evaluation attempts may already include costs represented by retained training receipts. Do not add without checking attempt scopes.
- Feature-preparation receipts available: True; explicit CPU total 112.326 s; wall total 112.197 s.
- Outer-process receipts available: True; explicit CPU total 522.319 s; wall total 528.971 s. These receipts may contain the fit/preparation costs already shown.
- Energy: unmeasured (`null`). Historical media acquisition cost: unknown (`null`). CPU seconds are not converted to joules.
