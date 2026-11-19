# Study002: all CPU-budget training comparisons

Status: **complete**. Completed **215/215** searches and **430** LR candidates.

Each search uses two prespecified learning rates and the same 12 process-CPU-second allowance per candidate. The final indivisible update can overshoot; a 4,096-update safeguard can leave allowance unused. Both are recorded. Validation/checkpoint/setup costs are additional and included in full search CPU. All means/SDs use training seeds; partial groups retain their actual n.

## Mechanism

| Task | Architecture | n | Accuracy % | CE | Parameters | All-LR updates, mean | Training CPU, mean s | Full search CPU, mean s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| multimodal_select | hcsn | 5 | 18.828 ± 3.985 | 2.217 ± 0.046 | 11146 | 206.6 | 24.144 | 32.087 |
| multimodal_select | single | 5 | 22.070 ± 3.835 | 2.167 ± 0.044 | 9034 | 300.4 | 24.104 | 30.010 |
| multimodal_select | no_adaptation | 5 | 18.984 ± 2.801 | 2.204 ± 0.038 | 11082 | 264.2 | 24.165 | 29.574 |
| multimodal_select | ordinary | 5 | 25.312 ± 2.836 | 2.129 ± 0.061 | 11146 | 495.0 | 24.102 | 29.414 |
| multimodal_select | continuous_rnn | 5 | 31.719 ± 3.864 | 1.796 ± 0.088 | 11189 | 1495.6 | 24.032 | 29.306 |
| synthetic | hcsn | 5 | 48.867 ± 3.284 | 1.114 ± 0.056 | 10948 | 249.4 | 24.136 | 34.330 |
| synthetic | single | 5 | 48.359 ± 1.329 | 1.107 ± 0.029 | 8836 | 255.6 | 24.241 | 32.068 |
| synthetic | no_adaptation | 5 | 48.555 ± 2.442 | 1.140 ± 0.035 | 10884 | 214.6 | 24.438 | 33.019 |
| synthetic | ordinary | 5 | 51.250 ± 2.065 | 1.049 ± 0.043 | 10948 | 486.6 | 24.198 | 30.682 |
| synthetic | continuous_rnn | 5 | 50.898 ± 0.836 | 1.056 ± 0.020 | 10991 | 1666.2 | 24.027 | 32.073 |

### All prespecified mechanism contrasts

HCSN minus control, percentage points. 98.75% intervals adjust four contrasts within each task. The one-percentage-point reference is not converted into a new Boolean success rule.

| Task | Control | Paired n | Difference, pp | 98.75% CI, pp |
|---|---|---:|---:|---:|
| multimodal_select | single | 5 | -3.242 | [-11.625, 5.141] |
| multimodal_select | no_adaptation | 5 | -0.156 | [-11.051, 10.738] |
| multimodal_select | ordinary | 5 | -6.484 | [-12.146, -0.823] |
| multimodal_select | continuous_rnn | 5 | -12.891 | [-23.345, -2.436] |
| synthetic | single | 5 | 0.508 | [-6.890, 7.905] |
| synthetic | no_adaptation | 5 | 0.312 | [-4.577, 5.202] |
| synthetic | ordinary | 5 | -2.383 | [-7.421, 2.655] |
| synthetic | continuous_rnn | 5 | -2.031 | [-9.180, 5.117] |

## Representation

Same frontend/data/head and width; parameter counts need not match. Accuracy is percent, with sample SD. Each task uses the common two-LR CPU allowance, not architecture-specific optimal tuning.

| Architecture | MNIST | FSDD | Multimodal query | Long memory |
|---|---:|---:|---:|---:|
| hcsn | 56.120 ± 5.094 | 13.607 ± 6.146 | 20.443 ± 2.070 | 24.544 ± 2.511 |
| lif_snn | 31.576 ± 4.540 | 10.482 ± 0.739 | 18.424 ± 3.157 | 24.674 ± 1.329 |
| continuous_rnn | 67.513 ± 10.009 | 12.565 ± 0.628 | 34.505 ± 1.846 | 25.911 ± 1.300 |
| two_gates | 84.375 ± 3.389 | 10.547 ± 0.851 | 44.206 ± 1.413 | 23.242 ± 1.033 |
| cfc | 36.198 ± 3.452 | 10.156 ± 0.517 | 21.354 ± 2.221 | 24.674 ± 2.426 |
| mamba1 | 82.292 ± 1.897 | 13.021 ± 5.300 | 40.951 ± 4.523 | 25.781 ± 1.475 |
| transformer | 86.458 ± 2.033 | 27.279 ± 6.823 | 43.750 ± 4.310 | 100.000 ± 0.000 |

### Representation cross-entropy and actual cost

| Task | Architecture | n | CE | Parameters | All-LR examples, mean | Full search CPU, mean s |
|---|---|---:|---:|---:|---:|---:|
| fsdd | hcsn | 3 | 2.182 ± 0.213 | 11146 | 8757.3 | 28.595 |
| fsdd | lif_snn | 3 | 2.305 ± 0.003 | 4682 | 36522.7 | 28.315 |
| fsdd | continuous_rnn | 3 | 2.383 ± 0.141 | 4650 | 70645.3 | 28.265 |
| fsdd | two_gates | 3 | 2.303 ± 0.001 | 8778 | 37546.7 | 28.563 |
| fsdd | cfc | 3 | 2.307 ± 0.002 | 8842 | 36650.7 | 29.143 |
| fsdd | mamba1 | 3 | 2.283 ± 0.039 | 12490 | 19466.7 | 28.694 |
| fsdd | transformer | 3 | 2.026 ± 0.104 | 15242 | 94336.0 | 30.774 |
| long_memory | hcsn | 3 | 1.394 ± 0.009 | 10948 | 8064.0 | 30.206 |
| long_memory | lif_snn | 3 | 1.389 ± 0.002 | 4484 | 38272.0 | 28.905 |
| long_memory | continuous_rnn | 3 | 1.395 ± 0.007 | 4452 | 56586.7 | 28.552 |
| long_memory | two_gates | 3 | 1.391 ± 0.002 | 8580 | 42048.0 | 30.347 |
| long_memory | cfc | 3 | 1.400 ± 0.005 | 8644 | 34421.3 | 28.644 |
| long_memory | mamba1 | 3 | 1.388 ± 0.002 | 12292 | 14837.3 | 28.894 |
| long_memory | transformer | 3 | 0.000 ± 0.000 | 15044 | 101546.7 | 28.242 |
| mnist | hcsn | 3 | 1.236 ± 0.209 | 11146 | 7968.0 | 31.764 |
| mnist | lif_snn | 3 | 1.778 ± 0.087 | 4682 | 39626.7 | 28.204 |
| mnist | continuous_rnn | 3 | 0.983 ± 0.296 | 4650 | 57301.3 | 28.234 |
| mnist | two_gates | 3 | 0.512 ± 0.104 | 8778 | 38048.0 | 29.130 |
| mnist | cfc | 3 | 1.679 ± 0.088 | 8842 | 30837.3 | 29.829 |
| mnist | mamba1 | 3 | 0.604 ± 0.041 | 12490 | 20181.3 | 28.465 |
| mnist | transformer | 3 | 0.483 ± 0.038 | 15242 | 82997.3 | 28.847 |
| multimodal_select | hcsn | 3 | 2.176 ± 0.043 | 11146 | 9312.0 | 29.174 |
| multimodal_select | lif_snn | 3 | 2.123 ± 0.087 | 4682 | 43701.3 | 29.416 |
| multimodal_select | continuous_rnn | 3 | 1.821 ± 0.018 | 4650 | 66730.7 | 27.994 |
| multimodal_select | two_gates | 3 | 1.475 ± 0.020 | 8778 | 51189.3 | 27.640 |
| multimodal_select | cfc | 3 | 2.028 ± 0.052 | 8842 | 39114.7 | 27.955 |
| multimodal_select | mamba1 | 3 | 1.573 ± 0.129 | 12490 | 20864.0 | 28.055 |
| multimodal_select | transformer | 3 | 1.592 ± 0.122 | 15242 | 97568.0 | 30.831 |

### Modality query subsets

These are test subsets, not independently trained encoders or input-masking interventions.

| Architecture | Image-query accuracy % | Spoken-query accuracy % | Conflicting-class accuracy % |
|---|---:|---:|---:|
| hcsn | 30.588 ± 4.523 | 10.376 ± 1.919 | 19.742 ± 2.261 |
| lif_snn | 26.405 ± 5.887 | 10.506 ± 0.778 | 18.383 ± 3.871 |
| continuous_rnn | 58.170 ± 2.611 | 11.025 ± 1.123 | 32.690 ± 1.721 |
| two_gates | 79.477 ± 2.995 | 9.209 ± 2.213 | 43.848 ± 1.363 |
| cfc | 33.333 ± 2.745 | 9.468 ± 1.755 | 20.815 ± 2.240 |
| mamba1 | 71.765 ± 9.898 | 10.376 ± 0.810 | 40.129 ± 3.610 |
| transformer | 68.627 ± 5.007 | 19.066 ± 3.712 | 42.561 ± 4.467 |

## Scaling

Accuracy %, mean ± sample SD across three seeds when complete. Capacity/data/history axes are separate. The joint multimodal configuration uses null-step length stress; long_memory adds genuine distractors.

| Config | Axis | Task | W/D/N/T | HCSN | Mamba-1 | Transformer |
|---:|---|---|---|---:|---:|---:|
| 0 | center | long_memory | 32/1/1024/32 | 21.289 ± 1.087 | 23.633 ± 1.475 | 100.000 ± 0.000 |
| 1 | capacity | long_memory | 16/1/1024/32 | 22.591 ± 2.160 | 24.414 ± 1.703 | 99.870 ± 0.226 |
| 2 | capacity | long_memory | 64/2/1024/32 | 24.154 ± 1.927 | 24.544 ± 2.778 | 100.000 ± 0.000 |
| 3 | capacity | long_memory | 128/2/1024/32 | 24.023 ± 1.703 | 23.828 ± 3.051 | 99.544 ± 0.789 |
| 4 | data | long_memory | 32/1/256/32 | 24.414 ± 2.058 | 24.479 ± 0.739 | 33.529 ± 2.792 |
| 5 | data | long_memory | 32/1/4096/32 | 22.917 ± 1.638 | 27.018 ± 3.322 | 100.000 ± 0.000 |
| 6 | context | long_memory | 32/1/1024/64 | 25.000 ± 1.669 | 23.958 ± 0.983 | 99.935 ± 0.113 |
| 7 | context | long_memory | 32/1/1024/128 | 24.609 ± 0.338 | 24.219 ± 1.015 | 27.539 ± 4.772 |
| 8 | joint | multimodal_select | 64/2/4096/128 | 10.221 ± 0.451 | 9.961 ± 0.000 | 34.440 ± 11.555 |

### Scaling CE, parameters and exposure

| Config | Architecture | n | CE | Parameters | All-LR updates, mean | All-LR examples, mean | Full search CPU, mean s |
|---:|---|---:|---:|---:|---:|---:|---:|
| 0 | hcsn | 3 | 1.406 ± 0.004 | 10948 | 303.7 | 9717.3 | 29.501 |
| 0 | mamba1 | 3 | 1.400 ± 0.011 | 12292 | 441.3 | 14122.7 | 28.986 |
| 0 | transformer | 3 | 0.000 ± 0.000 | 15044 | 2664.3 | 85258.7 | 28.797 |
| 1 | hcsn | 3 | 1.404 ± 0.013 | 3428 | 243.7 | 7797.3 | 29.790 |
| 1 | mamba1 | 3 | 1.394 ± 0.005 | 4548 | 945.7 | 30261.3 | 27.621 |
| 1 | transformer | 3 | 0.003 ± 0.005 | 4452 | 4040.0 | 129280.0 | 29.516 |
| 2 | hcsn | 3 | 1.409 ± 0.003 | 71876 | 105.3 | 3370.7 | 32.440 |
| 2 | mamba1 | 3 | 1.399 ± 0.011 | 70084 | 141.3 | 4522.7 | 29.769 |
| 2 | transformer | 3 | 0.000 ± 0.000 | 104644 | 1097.7 | 35125.3 | 30.773 |
| 3 | hcsn | 3 | 1.408 ± 0.015 | 274820 | 64.0 | 2048.0 | 36.730 |
| 3 | mamba1 | 3 | 1.410 ± 0.018 | 242564 | 73.0 | 2336.0 | 34.333 |
| 3 | transformer | 3 | 0.011 ± 0.019 | 405892 | 506.3 | 16202.7 | 30.692 |
| 4 | hcsn | 3 | 1.398 ± 0.003 | 10948 | 247.7 | 7925.3 | 30.407 |
| 4 | mamba1 | 3 | 1.440 ± 0.062 | 12292 | 668.0 | 21376.0 | 27.690 |
| 4 | transformer | 3 | 2.542 ± 0.998 | 15044 | 2936.0 | 93952.0 | 28.454 |
| 5 | hcsn | 3 | 1.400 ± 0.014 | 10948 | 267.0 | 8544.0 | 29.862 |
| 5 | mamba1 | 3 | 1.387 ± 0.004 | 12292 | 545.7 | 17461.3 | 29.929 |
| 5 | transformer | 3 | 0.000 ± 0.000 | 15044 | 3494.0 | 111808.0 | 28.960 |
| 6 | hcsn | 3 | 1.402 ± 0.014 | 10948 | 81.0 | 2592.0 | 36.727 |
| 6 | mamba1 | 3 | 1.396 ± 0.009 | 12292 | 235.7 | 7541.3 | 32.793 |
| 6 | transformer | 3 | 0.001 ± 0.001 | 15044 | 1742.7 | 55765.3 | 29.485 |
| 7 | hcsn | 3 | 1.398 ± 0.011 | 10948 | 42.7 | 1365.3 | 37.325 |
| 7 | mamba1 | 3 | 1.396 ± 0.005 | 12292 | 76.3 | 2442.7 | 31.302 |
| 7 | transformer | 3 | 1.387 ± 0.017 | 15044 | 593.0 | 18976.0 | 32.423 |
| 8 | hcsn | 3 | 2.334 ± 0.007 | 72266 | 18.3 | 586.7 | 49.551 |
| 8 | mamba1 | 3 | 2.323 ± 0.009 | 70474 | 21.0 | 672.0 | 37.664 |
| 8 | transformer | 3 | 1.896 ± 0.255 | 105034 | 304.3 | 9738.7 | 30.356 |

## Learning-rate choices and allowance exhaustion

| Stage | Group | Architecture | Selected LR counts | Exhausted candidate allowances | Total candidate count | Mean final-step overshoot s |
|---|---|---|---|---:|---:|---:|
| mechanism | multimodal_select | hcsn | 0.003: 5 | 10 | 10 | 0.072 |
| mechanism | multimodal_select | single | 0.001: 1, 0.003: 4 | 10 | 10 | 0.052 |
| mechanism | multimodal_select | no_adaptation | 0.001: 1, 0.003: 4 | 10 | 10 | 0.083 |
| mechanism | multimodal_select | ordinary | 0.003: 5 | 10 | 10 | 0.051 |
| mechanism | multimodal_select | continuous_rnn | 0.003: 5 | 10 | 10 | 0.016 |
| mechanism | synthetic | hcsn | 0.001: 1, 0.003: 4 | 10 | 10 | 0.068 |
| mechanism | synthetic | single | 0.001: 1, 0.003: 4 | 10 | 10 | 0.120 |
| mechanism | synthetic | no_adaptation | 0.001: 2, 0.003: 3 | 10 | 10 | 0.219 |
| mechanism | synthetic | ordinary | 0.001: 1, 0.003: 4 | 10 | 10 | 0.099 |
| mechanism | synthetic | continuous_rnn | 0.001: 3, 0.003: 2 | 10 | 10 | 0.013 |
| representation | fsdd | hcsn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.038 |
| representation | fsdd | lif_snn | 0.003: 3 | 6 | 6 | 0.020 |
| representation | fsdd | continuous_rnn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.005 |
| representation | fsdd | two_gates | 0.001: 3 | 6 | 6 | 0.039 |
| representation | fsdd | cfc | 0.001: 2, 0.003: 1 | 6 | 6 | 0.011 |
| representation | fsdd | mamba1 | 0.001: 2, 0.003: 1 | 6 | 6 | 0.045 |
| representation | fsdd | transformer | 0.001: 3 | 6 | 6 | 0.003 |
| representation | long_memory | hcsn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.105 |
| representation | long_memory | lif_snn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.009 |
| representation | long_memory | continuous_rnn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.007 |
| representation | long_memory | two_gates | 0.001: 3 | 6 | 6 | 0.007 |
| representation | long_memory | cfc | 0.001: 3 | 6 | 6 | 0.008 |
| representation | long_memory | mamba1 | 0.001: 1, 0.003: 2 | 6 | 6 | 0.031 |
| representation | long_memory | transformer | 0.003: 3 | 6 | 6 | 0.006 |
| representation | mnist | hcsn | 0.003: 3 | 6 | 6 | 0.045 |
| representation | mnist | lif_snn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.042 |
| representation | mnist | continuous_rnn | 0.001: 1, 0.003: 2 | 6 | 6 | 0.016 |
| representation | mnist | two_gates | 0.003: 3 | 6 | 6 | 0.016 |
| representation | mnist | cfc | 0.001: 2, 0.003: 1 | 6 | 6 | 0.011 |
| representation | mnist | mamba1 | 0.001: 1, 0.003: 2 | 6 | 6 | 0.013 |
| representation | mnist | transformer | 0.001: 3 | 6 | 6 | 0.045 |
| representation | multimodal_select | hcsn | 0.003: 3 | 6 | 6 | 0.035 |
| representation | multimodal_select | lif_snn | 0.001: 1, 0.003: 2 | 6 | 6 | 0.006 |
| representation | multimodal_select | continuous_rnn | 0.003: 3 | 6 | 6 | 0.007 |
| representation | multimodal_select | two_gates | 0.003: 3 | 6 | 6 | 0.097 |
| representation | multimodal_select | cfc | 0.001: 2, 0.003: 1 | 6 | 6 | 0.006 |
| representation | multimodal_select | mamba1 | 0.003: 3 | 6 | 6 | 0.022 |
| representation | multimodal_select | transformer | 0.001: 1, 0.003: 2 | 6 | 6 | 0.004 |
| scaling | 0 | hcsn | 0.001: 3 | 6 | 6 | 0.043 |
| scaling | 0 | mamba1 | 0.001: 3 | 6 | 6 | 0.072 |
| scaling | 0 | transformer | 0.003: 3 | 6 | 6 | 0.026 |
| scaling | 1 | hcsn | 0.001: 1, 0.003: 2 | 6 | 6 | 0.051 |
| scaling | 1 | mamba1 | 0.001: 2, 0.003: 1 | 6 | 6 | 0.014 |
| scaling | 1 | transformer | 0.003: 3 | 6 | 6 | 0.003 |
| scaling | 2 | hcsn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.085 |
| scaling | 2 | mamba1 | 0.001: 2, 0.003: 1 | 6 | 6 | 0.110 |
| scaling | 2 | transformer | 0.001: 1, 0.003: 2 | 6 | 6 | 0.008 |
| scaling | 3 | hcsn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.438 |
| scaling | 3 | mamba1 | 0.001: 2, 0.003: 1 | 6 | 6 | 0.173 |
| scaling | 3 | transformer | 0.001: 2, 0.003: 1 | 6 | 6 | 0.023 |
| scaling | 4 | hcsn | 0.001: 3 | 6 | 6 | 0.128 |
| scaling | 4 | mamba1 | 0.001: 3 | 6 | 6 | 0.019 |
| scaling | 4 | transformer | 0.001: 2, 0.003: 1 | 6 | 6 | 0.058 |
| scaling | 5 | hcsn | 0.001: 2, 0.003: 1 | 6 | 6 | 0.030 |
| scaling | 5 | mamba1 | 0.001: 2, 0.003: 1 | 6 | 6 | 0.042 |
| scaling | 5 | transformer | 0.003: 3 | 6 | 6 | 0.005 |
| scaling | 6 | hcsn | 0.001: 1, 0.003: 2 | 6 | 6 | 1.095 |
| scaling | 6 | mamba1 | 0.001: 2, 0.003: 1 | 6 | 6 | 0.156 |
| scaling | 6 | transformer | 0.001: 1, 0.003: 2 | 6 | 6 | 0.004 |
| scaling | 7 | hcsn | 0.001: 3 | 6 | 6 | 0.203 |
| scaling | 7 | mamba1 | 0.001: 2, 0.003: 1 | 6 | 6 | 0.103 |
| scaling | 7 | transformer | 0.001: 1, 0.003: 2 | 6 | 6 | 0.407 |
| scaling | 8 | hcsn | 0.001: 3 | 6 | 6 | 0.994 |
| scaling | 8 | mamba1 | 0.001: 3 | 6 | 6 | 0.565 |
| scaling | 8 | transformer | 0.003: 3 | 6 | 6 | 0.082 |

## Cost ledger

Training CPU is a subset of full search CPU. Discarded LR candidates and later updates beyond the selected checkpoint are fully charged. Per-job wall totals can overlap and are not calendar elapsed.

| Stage | Searches | LR candidates | Training CPU s | Full search CPU s | Updates | Examples | Candidates capped by max_updates |
|---|---:|---:|---:|---:|---:|---:|---:|
| mechanism | 50 | 100 | 1207.932 | 1562.810 | 28171 | 901472 | 0 |
| representation | 84 | 168 | 2020.179 | 2435.026 | 112982 | 3615424 | 0 |
| scaling | 81 | 162 | 1973.616 | 2585.635 | 65699 | 2102368 | 0 |
| TOTAL | 215 | 430 | 5201.727 | 6583.471 | 206852 | 6619264 | 0 |

External executions: 215 attempts, 215 successful, 0 failed. Known child CPU: 7475.860 s; unknown-CPU attempts: 0. Failed job wall: 0.000 s.

External worker CPU includes full search CPU and interpreter/import/setup overhead, so these columns must not be added together. Controller self-CPU remains unmeasured. Controller pauses are lifecycle events and do not themselves count as failed scientific jobs.

| Controller | Lifecycle status | Worker receipts | Known worker CPU s |
|---|---|---:|---:|
| 1 | prestart_resource_wait_without_normal_result | 0 | 0.000 |
| 2 | paused_between_scientific_jobs | 8 | 268.636 |
| 3 | completed_controller_invocation | 207 | 7207.224 |

## Serial full-batch versus incremental measurements

Audit status: passed; 55/55 cases, 54 parity passes, 7 exact separate-process replays.

Batch=16, two warmups, seven alternating timed repeats. Latencies exclude reset/model hashing, which have separate receipts. Persistent state bytes are not RSS or peak allocations. Measurement is shared-host CPU, not GPU/energy evidence.

| Job | Batch median ms | Stream median ms | Batch p95 ms | Stream p95 ms | Stream/batch median | Persistent state bytes | Parity |
|---|---:|---:|---:|---:|---:|---:|---|
| representation/mnist/hcsn/seed6201 | 37.937 | 54.268 | 70.387 | 77.010 | 1.430 | 8320 | True |
| representation/mnist/lif_snn/seed6201 | 8.029 | 45.092 | 15.386 | 63.155 | 5.616 | 4224 | True |
| representation/mnist/continuous_rnn/seed6201 | 1.247 | 5.937 | 1.499 | 13.133 | 4.760 | 2176 | True |
| representation/mnist/two_gates/seed6201 | 2.112 | 10.958 | 4.505 | 14.790 | 5.189 | 2176 | True |
| representation/mnist/cfc/seed6201 | 4.200 | 10.400 | 4.970 | 13.488 | 2.476 | 2176 | True |
| representation/mnist/mamba1/seed6201 | 5.881 | 49.318 | 13.196 | 66.369 | 8.385 | 77952 | True |
| representation/mnist/transformer/seed6201 | 1.423 | 27.637 | 3.402 | 41.032 | 19.424 | 131200 | True |
| representation/fsdd/hcsn/seed6201 | 20.558 | 37.553 | 28.474 | 46.198 | 1.827 | 8320 | True |
| representation/fsdd/lif_snn/seed6201 | 2.732 | 12.887 | 6.144 | 20.367 | 4.718 | 4224 | True |
| representation/fsdd/continuous_rnn/seed6201 | 1.730 | 8.964 | 2.999 | 15.719 | 5.181 | 2176 | True |
| representation/fsdd/two_gates/seed6201 | 3.640 | 12.280 | 6.551 | 14.202 | 3.374 | 2176 | True |
| representation/fsdd/cfc/seed6201 | 3.529 | 8.620 | 4.833 | 10.034 | 2.443 | 2176 | True |
| representation/fsdd/mamba1/seed6201 | 4.535 | 35.099 | 6.742 | 45.284 | 7.740 | 77952 | True |
| representation/fsdd/transformer/seed6201 | 1.090 | 14.918 | 3.654 | 23.054 | 13.689 | 131200 | True |
| representation/multimodal_select/hcsn/seed6201 | 15.697 | 21.296 | 21.682 | 22.111 | 1.357 | 8320 | True |
| representation/multimodal_select/lif_snn/seed6201 | 2.653 | 9.240 | 3.137 | 16.841 | 3.483 | 4224 | True |
| representation/multimodal_select/continuous_rnn/seed6201 | 1.361 | 5.852 | 1.810 | 9.486 | 4.298 | 2176 | True |
| representation/multimodal_select/two_gates/seed6201 | 3.085 | 9.902 | 4.191 | 13.168 | 3.210 | 2176 | True |
| representation/multimodal_select/cfc/seed6201 | 3.862 | 10.847 | 4.613 | 17.646 | 2.808 | 2176 | True |
| representation/multimodal_select/mamba1/seed6201 | 3.234 | 26.764 | 4.934 | 31.158 | 8.275 | 77952 | True |
| representation/multimodal_select/transformer/seed6201 | 1.370 | 17.041 | 4.974 | 36.597 | 12.442 | 131200 | True |
| representation/long_memory/hcsn/seed6201 | 19.822 | 27.378 | 28.457 | 35.456 | 1.381 | 8320 | True |
| representation/long_memory/lif_snn/seed6201 | 3.110 | 11.356 | 5.242 | 19.691 | 3.651 | 4224 | True |
| representation/long_memory/continuous_rnn/seed6201 | 1.453 | 7.073 | 4.862 | 11.601 | 4.869 | 2176 | True |
| representation/long_memory/two_gates/seed6201 | 2.446 | 8.782 | 72.323 | 12.958 | 3.591 | 2176 | True |
| representation/long_memory/cfc/seed6201 | 3.497 | 11.823 | 9.036 | 126.051 | 3.381 | 2176 | True |
| representation/long_memory/mamba1/seed6201 | 3.014 | 26.776 | 5.073 | 31.534 | 8.884 | 77952 | True |
| representation/long_memory/transformer/seed6201 | 0.856 | 20.898 | 1.362 | 25.946 | 24.406 | 131200 | True |
| scaling/config00/hcsn/seed7301 | 20.088 | 25.281 | 102.886 | 40.084 | 1.258 | 8320 | True |
| scaling/config00/mamba1/seed7301 | 9.257 | 32.893 | 32.889 | 120.403 | 3.553 | 77952 | True |
| scaling/config00/transformer/seed7301 | 1.048 | 20.811 | 1.558 | 24.133 | 19.863 | 131200 | False |
| scaling/config01/hcsn/seed7301 | 40.782 | 37.488 | 134.679 | 106.039 | 0.919 | 4224 | True |
| scaling/config01/mamba1/seed7301 | 3.868 | 31.395 | 4.160 | 38.342 | 8.116 | 39040 | True |
| scaling/config01/transformer/seed7301 | 3.793 | 72.568 | 7.893 | 105.999 | 19.131 | 65664 | True |
| scaling/config02/hcsn/seed7301 | 49.743 | 77.065 | 57.300 | 114.837 | 1.549 | 32896 | True |
| scaling/config02/mamba1/seed7301 | 10.706 | 51.892 | 13.655 | 74.684 | 4.847 | 311424 | True |
| scaling/config02/transformer/seed7301 | 2.596 | 29.069 | 4.395 | 34.234 | 11.197 | 524416 | True |
| scaling/config03/hcsn/seed7301 | 81.024 | 99.380 | 93.325 | 113.114 | 1.227 | 65664 | True |
| scaling/config03/mamba1/seed7301 | 22.390 | 72.731 | 39.014 | 90.637 | 3.248 | 622720 | True |
| scaling/config03/transformer/seed7301 | 6.169 | 46.157 | 8.329 | 53.430 | 7.482 | 1048704 | True |
| scaling/config04/hcsn/seed7301 | 14.323 | 33.326 | 18.174 | 35.113 | 2.327 | 8320 | True |
| scaling/config04/mamba1/seed7301 | 3.458 | 25.959 | 4.272 | 33.413 | 7.508 | 77952 | True |
| scaling/config04/transformer/seed7301 | 1.016 | 19.666 | 1.492 | 20.036 | 19.352 | 131200 | True |
| scaling/config05/hcsn/seed7301 | 39.684 | 47.447 | 50.689 | 78.643 | 1.196 | 8320 | True |
| scaling/config05/mamba1/seed7301 | 3.623 | 33.643 | 11.885 | 84.061 | 9.285 | 77952 | True |
| scaling/config05/transformer/seed7301 | 1.730 | 23.681 | 2.860 | 30.332 | 13.687 | 131200 | True |
| scaling/config06/hcsn/seed7301 | 42.794 | 46.944 | 59.682 | 75.350 | 1.097 | 8320 | True |
| scaling/config06/mamba1/seed7301 | 12.609 | 78.639 | 161.671 | 168.263 | 6.237 | 77952 | True |
| scaling/config06/transformer/seed7301 | 2.262 | 34.794 | 3.306 | 51.894 | 15.380 | 262272 | True |
| scaling/config07/hcsn/seed7301 | 72.400 | 140.013 | 218.257 | 155.576 | 1.934 | 8320 | True |
| scaling/config07/mamba1/seed7301 | 10.824 | 106.600 | 14.205 | 118.232 | 9.848 | 77952 | True |
| scaling/config07/transformer/seed7301 | 5.218 | 88.915 | 7.542 | 108.594 | 17.041 | 524416 | True |
| scaling/config08/hcsn/seed7301 | 172.276 | 212.983 | 281.862 | 391.099 | 1.236 | 32896 | True |
| scaling/config08/mamba1/seed7301 | 47.459 | 218.416 | 147.502 | 416.360 | 4.602 | 311424 | True |
| scaling/config08/transformer/seed7301 | 17.720 | 167.779 | 28.127 | 235.875 | 9.468 | 2097280 | True |

## Interpretation boundaries

- paired training seeds; 98.75% Student-t interval per task's four controls; fixed dataset and search recipe
- descriptive seed mean and sample SD; no architecture-optimal tuning claim
- both prespecified learning rates and all recorded CPU milestones; validation CE only; all candidate costs charged
- validation CE at actual measured training CPU, with both LR searches charged; unrecorded overhead timing cannot be interpolated to individual checkpoints
- episode seed8123; raw MNIST/FSDD populations may overlap study001; no source-population independence claim
- study001-to-study002 differences are not controlled causal effects because data episodes, budget and selection recipe changed
- shared-host single-thread CPU; no GPU, energy or universal scaling-law conclusion
- 215 classification/search jobs; boundary/native task studies are reported separately
