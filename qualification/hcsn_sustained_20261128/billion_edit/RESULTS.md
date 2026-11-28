# Seven-matrix editing in a 1,016,475,200-parameter HCSN

This independent CPU study evaluated 27 candidates over three seeds and two nested sample budgets on CREMA-D. All learning arms began from the same seed-specific original initialization. Each arm saw four or sixteen minibatches of sixteen clips. Seven writable matrices totalled 4,980,736 parameters (0.490%); the full encoder contained 1,016,475,200 parameters. The projection-only arm wrote 1,048,576 entries. A single CPU thread ran dense operations with BF16 autocast and FP32 embedding similarity. Every candidate scored every one of 1,147 development clips and 1,311 held clips against all 72 texts. Sixteen held-out actors define the paired resampling units.

| Training rule | Fixed 12× cold NLL | Calibrated dev NLL | Calibrated cold NLL | Calibrated cold top-1 | Seeds reaching 4.1 on both | Both prefixes, seconds |
|---|---:|---:|---:|---:|---:|---:|
| Forward hidden writes + projection | 5.2748 | 4.1430 | 4.1678 | 5.21% | 0/3 | 498.61 |
| Same seven matrices, AdamW BP | 4.2384 | 4.1418 | 4.1522 | 6.28% | 0/3 | 493.29 |
| Projection-only closed-form ridge | 4.8267 | 4.0076 | 4.0649 | 6.38% | 3/3 | 477.29 |
| Shuffled hidden labels + projection | 5.2870 | 4.1336 | 4.1702 | 5.34% | 0/3 | 511.91 |
| Original parent | 4.2772 | 4.2055 | 4.2055 | 3.59% | 0/3 | 226.01 |

Calibration was prespecified for all arms on this panel. It fits one nonnegative score multiplier on development and includes the same fixed training-class log-frequency. The pure training-prior predictor had cold NLL 4.2056. The paired difference (forward minus same-position BP) was +1.0364 [0.9670, 1.1042] with the fixed scale and +0.0157 [0.0007, 0.0288] after calibration. Forward minus projection-only was +0.1029 [0.0617, 0.1449] after calibration. Mixing the hidden target labels produced a difference of −0.0024 [−0.0110, 0.0073] compared with the correctly paired hidden fit (forward minus shuffled). These results support fitting the output projection under the chosen accuracy criterion. They give no evidence that the label-specific six hidden writes added predictive value in this setting.

At 16 updates, the median optimization time was 57.27 s for forward and 71.43 s for same-position BP. Mean charged end-to-end time across development selection on both prefixes and held scoring was 498.61 s vs 493.29 s. Neither reached the prespecified joint NLL gate. The projection-only arm reached it in all three seeds with independently observed charged times 476.84, 447.48 and 504.75 s (common preparation excluded). A matched-quality speed ratio for forward vs BP is unidentifiable here. The small top-1 values and gaps between rescaling behavior and rank accuracy constrain extrapolation to large-scale pretraining or other datasets.

Independent verification re-read all 27 weight patches and 54 complete prediction archives and recomputed all eight paired actor contrasts. Original unrounded results, selected candidates, fixed-prefix scores and timings are in the terminal and its released raw files. A separate post hoc ablation froze the original selected candidates and removed the class prior: held NLL was 4.2299 for forward, 4.2220 for same-site BP and 4.1095 for head-only. The CREMA-D cohort has been explored by earlier studies.

| Evidence | SHA-256 |
|---|---|
| All-candidate development freeze | e1d555769e867824bc958acde45d49a11de2ceb9f38c6da1074a00fd4396f0c1 |
| Original terminal | df1ac77e1d4d5d2af3774443e0947464044bc62e2ed5a67581d22f56db52e160 |
| Independent verification | 6706219e3c28d41a569a860fec2b988dcfe62238f4473d0b2140f62291a5e2f7 |
| Raw-score and fit release manifest | f29168ccf5613455b685ced397b309c57c798f791a938ee2b3cf601948e1e621 |
| 27 actual weight patches, 538,019,840-byte tar | f0c2a7a446e69defe762c5bc54f476c55a7a36cbb6f450eabd762d160418a5c6 |
