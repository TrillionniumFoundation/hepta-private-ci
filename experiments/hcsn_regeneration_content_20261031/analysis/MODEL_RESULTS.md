# Registered model comparison results

All values below are descriptive means and observed min–max ranges across initialization seeds 11, 23 and 37. These ranges are not confidence intervals. No pooled p-value, architecture selection or optimal Pareto claim is made.

## Evidence and fairness

108 frozen fits and all 324 test-condition rows are retained. Recorded training-batch hashes match across all families and widths for each task/seed. Recorded test-batch hashes match across all models for each task/condition. Scores were recomputed from saved predictions; checkpoint, parameter-count, log and source identities were checked.

The primary ordinary/renewal pair has equal parameter counts. The LIF and Transformer baselines have different counts. All fits use the same 300-update data budget; this is not an equal-compute or optimally tuned comparison.

## IID quality, parameter count and fit cost

Accuracy is percent. CPU is total recorded training CPU seconds, including batch generation and per-update evidence writing. Brackets contain the observed seed minimum and maximum.

| Task | Family | Width | Parameters | Accuracy % | Training CPU s |
| --- | --- | ---: | ---: | ---: | ---: |
| associative_recall | ordinary | 16 | 883 | 63.49 [63.13, 63.72] | 0.499 [0.481, 0.533] |
| associative_recall | ordinary | 32 | 2787 | 62.91 [62.40, 63.43] | 0.600 [0.582, 0.625] |
| associative_recall | ordinary | 64 | 9667 | 62.97 [62.35, 63.77] | 0.933 [0.877, 0.974] |
| associative_recall | analytic | 16 | 883 | 63.46 [63.18, 63.72] | 4.482 [4.375, 4.606] |
| associative_recall | analytic | 32 | 2787 | 62.83 [62.45, 63.53] | 6.038 [5.984, 6.101] |
| associative_recall | analytic | 64 | 9667 | 63.02 [62.35, 63.96] | 9.368 [9.040, 9.923] |
| associative_recall | lif_surrogate | 16 | 467 | 37.13 [33.15, 44.29] | 0.463 [0.443, 0.489] |
| associative_recall | lif_surrogate | 32 | 1443 | 38.51 [33.15, 49.07] | 0.525 [0.499, 0.570] |
| associative_recall | lif_surrogate | 64 | 4931 | 43.41 [33.15, 55.42] | 0.565 [0.542, 0.587] |
| associative_recall | transformer | 16 | 2371 | 62.27 [62.06, 62.40] | 0.823 [0.784, 0.869] |
| associative_recall | transformer | 32 | 8835 | 62.43 [62.01, 62.65] | 1.213 [1.182, 1.241] |
| associative_recall | transformer | 64 | 34051 | 61.67 [60.01, 63.23] | 2.363 [2.258, 2.467] |
| multimodal_evidence | ordinary | 16 | 962 | 91.49 [91.31, 91.60] | 1.743 [1.709, 1.768] |
| multimodal_evidence | ordinary | 32 | 2946 | 91.47 [91.41, 91.60] | 1.832 [1.819, 1.842] |
| multimodal_evidence | ordinary | 64 | 9986 | 91.36 [91.31, 91.41] | 2.015 [1.940, 2.080] |
| multimodal_evidence | analytic | 16 | 962 | 91.49 [91.41, 91.55] | 4.298 [4.223, 4.419] |
| multimodal_evidence | analytic | 32 | 2946 | 91.52 [91.41, 91.70] | 5.222 [5.202, 5.253] |
| multimodal_evidence | analytic | 64 | 9986 | 91.36 [91.31, 91.46] | 7.533 [7.395, 7.657] |
| multimodal_evidence | lif_surrogate | 16 | 498 | 90.51 [90.14, 90.77] | 1.743 [1.627, 1.828] |
| multimodal_evidence | lif_surrogate | 32 | 1506 | 90.80 [90.23, 91.21] | 1.774 [1.758, 1.784] |
| multimodal_evidence | lif_surrogate | 64 | 5058 | 90.95 [90.62, 91.55] | 1.848 [1.765, 2.006] |
| multimodal_evidence | transformer | 16 | 2402 | 90.67 [88.87, 91.75] | 1.939 [1.924, 1.966] |
| multimodal_evidence | transformer | 32 | 8898 | 89.76 [88.92, 90.58] | 2.323 [2.273, 2.360] |
| multimodal_evidence | transformer | 64 | 34178 | 90.56 [90.28, 90.97] | 2.946 [2.899, 3.011] |
| digits_rows | ordinary | 16 | 970 | 85.69 [84.24, 87.23] | 0.607 [0.296, 1.204] |
| digits_rows | ordinary | 32 | 2954 | 92.66 [90.76, 94.57] | 0.401 [0.378, 0.429] |
| digits_rows | ordinary | 64 | 9994 | 96.38 [94.57, 97.55] | 0.560 [0.553, 0.568] |
| digits_rows | analytic | 16 | 970 | 84.15 [83.42, 84.78] | 2.822 [2.708, 2.937] |
| digits_rows | analytic | 32 | 2954 | 91.12 [88.59, 92.93] | 3.952 [3.834, 4.090] |
| digits_rows | analytic | 64 | 9994 | 95.92 [95.65, 96.20] | 6.176 [6.051, 6.389] |
| digits_rows | lif_surrogate | 16 | 570 | 31.25 [28.80, 35.33] | 0.266 [0.247, 0.293] |
| digits_rows | lif_surrogate | 32 | 1642 | 43.12 [28.53, 54.62] | 0.306 [0.288, 0.336] |
| digits_rows | lif_surrogate | 64 | 5322 | 69.02 [65.49, 71.74] | 0.339 [0.332, 0.345] |
| digits_rows | transformer | 16 | 2474 | 86.41 [86.14, 86.96] | 0.866 [0.511, 1.526] |
| digits_rows | transformer | 32 | 9034 | 88.32 [86.68, 89.40] | 0.708 [0.684, 0.723] |
| digits_rows | transformer | 64 | 34442 | 86.14 [83.42, 88.32] | 1.539 [1.521, 1.552] |

All IID, longer-sequence/delay and clock-shift rows remain in `model_results.csv` and `summary.json`. The long condition adds distractors for recall, adds blank rows after digit images, and adds informative observations for the synthetic multimodal task; these are different stress conditions.

## Matched primary pairs

Each row summarizes three paired seeds. Accuracy difference is renewal minus ordinary in percentage points. CPU ratios are renewal/ordinary, averaged over the three per-seed ratios. A positive accuracy difference favors renewal; a ratio above one is more CPU cost. All 81 individual paired rows are in `paired_differences.csv`.

| Task | Width | Condition | Accuracy difference pp | Training CPU ratio | Test CPU ratio |
| --- | ---: | --- | ---: | ---: | ---: |
| associative_recall | 16 | iid | -0.03 [-0.54, 0.34] | 9.01 [8.21, 9.54] | 8.24 [7.92, 8.56] |
| associative_recall | 16 | long_delay | 0.07 [-0.24, 0.34] | 9.01 [8.21, 9.54] | 9.71 [9.08, 10.69] |
| associative_recall | 16 | clock_shift | 0.02 [-0.29, 0.20] | 9.01 [8.21, 9.54] | 7.21 [6.46, 8.10] |
| associative_recall | 32 | iid | -0.08 [-0.39, 0.10] | 10.07 [9.65, 10.30] | 9.42 [8.80, 9.94] |
| associative_recall | 32 | long_delay | 0.99 [-0.39, 2.59] | 10.07 [9.65, 10.30] | 12.11 [11.81, 12.50] |
| associative_recall | 32 | clock_shift | -0.08 [-0.44, 0.24] | 10.07 [9.65, 10.30] | 10.42 [10.11, 11.02] |
| associative_recall | 64 | iid | 0.05 [-0.05, 0.20] | 10.08 [9.28, 11.32] | 12.50 [12.18, 12.90] |
| associative_recall | 64 | long_delay | 0.28 [-0.34, 1.07] | 10.08 [9.28, 11.32] | 14.74 [14.23, 15.20] |
| associative_recall | 64 | clock_shift | 0.37 [0.24, 0.54] | 10.08 [9.28, 11.32] | 12.30 [11.68, 12.78] |
| multimodal_evidence | 16 | iid | 0.00 [-0.10, 0.10] | 2.47 [2.39, 2.52] | 1.89 [1.85, 1.94] |
| multimodal_evidence | 16 | long_delay | 0.00 [-0.10, 0.10] | 2.47 [2.39, 2.52] | 1.79 [1.62, 1.99] |
| multimodal_evidence | 16 | clock_shift | 0.24 [0.10, 0.39] | 2.47 [2.39, 2.52] | 1.77 [1.59, 1.97] |
| multimodal_evidence | 32 | iid | 0.05 [0.00, 0.10] | 2.85 [2.83, 2.89] | 2.12 [1.70, 2.45] |
| multimodal_evidence | 32 | long_delay | -0.07 [-0.15, 0.00] | 2.85 [2.83, 2.89] | 2.32 [1.96, 2.51] |
| multimodal_evidence | 32 | clock_shift | 0.37 [0.00, 0.59] | 2.85 [2.83, 2.89] | 2.37 [2.20, 2.62] |
| multimodal_evidence | 64 | iid | 0.00 [-0.05, 0.05] | 3.74 [3.68, 3.81] | 2.90 [2.62, 3.09] |
| multimodal_evidence | 64 | long_delay | 0.08 [0.05, 0.15] | 3.74 [3.68, 3.81] | 2.81 [2.43, 3.11] |
| multimodal_evidence | 64 | clock_shift | 0.21 [0.00, 0.39] | 3.74 [3.68, 3.81] | 2.83 [2.43, 3.20] |
| digits_rows | 16 | iid | -1.54 [-2.99, -0.82] | 6.81 [2.44, 9.52] | 19.42 [16.39, 25.16] |
| digits_rows | 16 | long_delay | 1.36 [-4.35, 9.51] | 6.81 [2.44, 9.52] | 21.28 [17.81, 27.12] |
| digits_rows | 16 | clock_shift | -0.91 [-1.90, 0.54] | 6.81 [2.44, 9.52] | 19.12 [16.20, 24.71] |
| digits_rows | 32 | iid | -1.54 [-2.17, -0.82] | 9.87 [9.18, 10.27] | 20.77 [19.13, 23.51] |
| digits_rows | 32 | long_delay | 0.82 [-1.63, 2.99] | 9.87 [9.18, 10.27] | 21.07 [17.65, 25.51] |
| digits_rows | 32 | clock_shift | -0.09 [-1.36, 1.36] | 9.87 [9.18, 10.27] | 21.53 [15.32, 26.39] |
| digits_rows | 64 | iid | -0.45 [-1.90, 1.36] | 11.04 [10.71, 11.56] | 16.22 [13.06, 20.93] |
| digits_rows | 64 | long_delay | 4.17 [1.63, 7.88] | 11.04 [10.71, 11.56] | 15.55 [13.45, 18.13] |
| digits_rows | 64 | clock_shift | 0.45 [-0.27, 1.63] | 11.04 [10.71, 11.56] | 14.40 [13.58, 14.84] |

## Frozen-content ablations and prefixes

All 54 primary diagnostic reports are present and linked to the frozen checkpoints.

These are interventions on the same frozen models, not separately trained last-observation baselines. Synthetic diagnostics use the first 512 IID examples; digit diagnostics use the full test partition. Their scores must not be substituted for the main synthetic 2048-example scores. Prefix curves and all repeated timing observations are retained in `summary.json`.

| Task | Family | Width | Seeds present | Full history % | Last observation % | Full minus last pp |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| associative_recall | ordinary | 16 | 11,23,37 | 63.80 [62.89, 64.84] | 33.66 [33.59, 33.79] | 30.14 [29.30, 31.05] |
| associative_recall | ordinary | 32 | 11,23,37 | 63.02 [62.30, 63.87] | 32.75 [31.05, 33.59] | 30.27 [28.71, 32.81] |
| associative_recall | ordinary | 64 | 11,23,37 | 62.37 [61.72, 63.09] | 33.85 [32.62, 35.35] | 28.52 [26.37, 30.47] |
| associative_recall | analytic | 16 | 11,23,37 | 63.54 [62.70, 64.06] | 33.66 [33.59, 33.79] | 29.88 [29.10, 30.27] |
| associative_recall | analytic | 32 | 11,23,37 | 63.02 [62.11, 63.67] | 32.75 [31.05, 33.59] | 30.27 [28.52, 32.62] |
| associative_recall | analytic | 64 | 11,23,37 | 62.24 [61.13, 63.09] | 33.85 [32.62, 35.35] | 28.39 [25.78, 30.47] |
| multimodal_evidence | ordinary | 16 | 11,23,37 | 90.95 [90.43, 91.41] | 71.48 [71.48, 71.48] | 19.47 [18.95, 19.92] |
| multimodal_evidence | ordinary | 32 | 11,23,37 | 91.21 [90.43, 91.80] | 71.48 [71.48, 71.48] | 19.73 [18.95, 20.31] |
| multimodal_evidence | ordinary | 64 | 11,23,37 | 91.21 [90.43, 91.60] | 71.48 [71.48, 71.48] | 19.73 [18.95, 20.12] |
| multimodal_evidence | analytic | 16 | 11,23,37 | 91.02 [90.62, 91.41] | 71.48 [71.48, 71.48] | 19.53 [19.14, 19.92] |
| multimodal_evidence | analytic | 32 | 11,23,37 | 91.21 [90.23, 91.80] | 71.48 [71.48, 71.48] | 19.73 [18.75, 20.31] |
| multimodal_evidence | analytic | 64 | 11,23,37 | 91.15 [90.43, 91.60] | 71.48 [71.48, 71.48] | 19.66 [18.95, 20.12] |
| digits_rows | ordinary | 16 | 11,23,37 | 85.69 [84.24, 87.23] | 20.56 [19.84, 21.47] | 65.13 [62.77, 66.85] |
| digits_rows | ordinary | 32 | 11,23,37 | 92.66 [90.76, 94.57] | 18.93 [16.03, 23.10] | 73.73 [67.66, 78.53] |
| digits_rows | ordinary | 64 | 11,23,37 | 96.38 [94.57, 97.55] | 16.12 [10.87, 21.47] | 80.25 [73.10, 86.14] |
| digits_rows | analytic | 16 | 11,23,37 | 84.15 [83.42, 84.78] | 23.73 [22.83, 24.46] | 60.42 [58.97, 61.96] |
| digits_rows | analytic | 32 | 11,23,37 | 91.12 [88.59, 92.93] | 18.21 [16.03, 21.74] | 72.92 [66.85, 76.90] |
| digits_rows | analytic | 64 | 11,23,37 | 95.92 [95.65, 96.20] | 14.95 [11.41, 19.02] | 80.98 [76.90, 84.78] |

## Interpretation limits

- Widths 16/32/64 are small classification models; no large-model scaling or generative-model result is established.
- The renewal distance is a local gate feature of a vector content state. This experiment does not implement the full He–Xiong equity/default endogenous free boundary.
- LIF uses hard forward spikes and surrogate gradients; its upstream surrogate is not the derivative of the hard-forward loss.
- Timings describe these NumPy CPU implementations, including their implementation overhead. They establish neither GPU performance nor energy use, and the Transformer does not use FlashAttention.
- Figure lines connect increasing registered widths within a family. They are not fitted scaling laws or an asserted optimal frontier.
