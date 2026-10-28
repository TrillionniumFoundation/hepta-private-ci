# Study001 comparison tables

**Status: complete**. No winner is assigned.

Valid results: 229/229; preselected performance records: 58/58.

Accuracy tables use percent; paired differences use percentage points. SD is across training seeds.

## Mechanism

| Configuration / task | Architecture | Seeds | Accuracy % mean ± SD | CE mean ± SD | Parameters | Train CPU s mean ± SD | Train wall s mean ± SD |
|---|---|---:|---:|---:|---:|---:|---:|
| synthetic | hcsn | 5/5 | 49.082 ± 0.997 | 1.086 ± 0.019 | 10948 | 17.217 ± 3.517 | 17.551 ± 3.428 |
| synthetic | single | 5/5 | 49.473 ± 0.836 | 1.090 ± 0.029 | 8836 | 22.617 ± 2.928 | 23.162 ± 2.959 |
| synthetic | no_adaptation | 5/5 | 49.434 ± 0.994 | 1.094 ± 0.028 | 10884 | 15.242 ± 1.716 | 15.686 ± 1.994 |
| synthetic | ordinary | 5/5 | 48.691 ± 1.273 | 1.099 ± 0.027 | 10948 | 8.895 ± 0.646 | 9.023 ± 0.522 |
| synthetic | continuous_rnn | 5/5 | 41.348 ± 4.033 | 1.231 ± 0.045 | 10991 | 2.742 ± 1.235 | 2.857 ± 1.394 |
| multimodal_select | hcsn | 5/5 | 23.125 ± 3.474 | 2.168 ± 0.047 | 11146 | 21.639 ± 6.266 | 21.878 ± 6.378 |
| multimodal_select | single | 5/5 | 23.516 ± 1.870 | 2.161 ± 0.026 | 9034 | 15.081 ± 2.896 | 15.746 ± 3.056 |
| multimodal_select | no_adaptation | 5/5 | 22.285 ± 2.916 | 2.171 ± 0.022 | 11082 | 16.548 ± 2.749 | 16.894 ± 2.932 |
| multimodal_select | ordinary | 5/5 | 22.832 ± 3.623 | 2.164 ± 0.062 | 11146 | 11.252 ± 1.369 | 11.745 ± 1.585 |
| multimodal_select | continuous_rnn | 5/5 | 16.992 ± 2.113 | 2.246 ± 0.028 | 11189 | 3.198 ± 1.601 | 3.301 ± 1.658 |

## Representation

| Configuration / task | Architecture | Seeds | Accuracy % mean ± SD | CE mean ± SD | Parameters | Train CPU s mean ± SD | Train wall s mean ± SD |
|---|---|---:|---:|---:|---:|---:|---:|
| mnist | hcsn | 3/3 | 66.406 ± 3.472 | 0.989 ± 0.068 | 11146 | 23.909 ± 8.743 | 25.022 ± 9.881 |
| mnist | lif_snn | 3/3 | 27.148 ± 0.763 | 1.876 ± 0.053 | 4682 | 4.904 ± 0.760 | 4.906 ± 0.761 |
| mnist | continuous_rnn | 3/3 | 46.517 ± 16.729 | 1.447 ± 0.350 | 4650 | 2.706 ± 0.566 | 2.790 ± 0.617 |
| mnist | two_gates | 3/3 | 56.380 ± 9.114 | 1.199 ± 0.230 | 8778 | 4.797 ± 0.644 | 4.832 ± 0.677 |
| mnist | cfc | 3/3 | 28.060 ± 4.203 | 1.921 ± 0.129 | 8842 | 5.083 ± 0.701 | 5.203 ± 0.720 |
| mnist | mamba1 | 3/3 | 83.301 ± 0.962 | 0.536 ± 0.040 | 12490 | 10.294 ± 2.378 | 10.325 ± 2.372 |
| mnist | transformer | 3/3 | 80.859 ± 1.572 | 0.573 ± 0.063 | 15242 | 1.652 ± 0.387 | 1.689 ± 0.394 |
| fsdd | hcsn | 3/3 | 11.914 ± 1.367 | 2.312 ± 0.006 | 11146 | 25.993 ± 6.145 | 26.750 ± 6.315 |
| fsdd | lif_snn | 3/3 | 9.863 ± 0.352 | 2.306 ± 0.003 | 4682 | 5.174 ± 2.627 | 5.259 ± 2.692 |
| fsdd | continuous_rnn | 3/3 | 9.961 ± 0.098 | 2.306 ± 0.000 | 4650 | 2.854 ± 0.971 | 3.025 ± 1.213 |
| fsdd | two_gates | 3/3 | 10.938 ± 1.608 | 2.305 ± 0.001 | 8778 | 4.723 ± 1.092 | 4.956 ± 0.946 |
| fsdd | cfc | 3/3 | 10.091 ± 0.314 | 2.307 ± 0.002 | 8842 | 4.594 ± 0.946 | 4.628 ± 0.984 |
| fsdd | mamba1 | 3/3 | 9.993 ± 0.056 | 2.313 ± 0.006 | 12490 | 12.276 ± 2.863 | 12.430 ± 2.898 |
| fsdd | transformer | 3/3 | 25.488 ± 6.475 | 1.932 ± 0.128 | 15242 | 1.767 ± 0.379 | 1.809 ± 0.343 |
| multimodal_select | hcsn | 3/3 | 25.716 ± 2.728 | 2.069 ± 0.090 | 11146 | 28.084 ± 8.204 | 28.878 ± 8.801 |
| multimodal_select | lif_snn | 3/3 | 10.677 ± 0.620 | 2.304 ± 0.001 | 4682 | 4.746 ± 0.957 | 4.855 ± 0.907 |
| multimodal_select | continuous_rnn | 3/3 | 18.815 ± 2.100 | 2.185 ± 0.006 | 4650 | 2.988 ± 0.091 | 3.268 ± 0.485 |
| multimodal_select | two_gates | 3/3 | 24.902 ± 2.882 | 1.950 ± 0.077 | 8778 | 4.458 ± 1.416 | 4.468 ± 1.418 |
| multimodal_select | cfc | 3/3 | 15.202 ± 2.932 | 2.219 ± 0.073 | 8842 | 6.228 ± 0.377 | 6.359 ± 0.514 |
| multimodal_select | mamba1 | 3/3 | 38.053 ± 5.602 | 1.712 ± 0.191 | 12490 | 10.119 ± 2.019 | 10.416 ± 1.999 |
| multimodal_select | transformer | 3/3 | 36.686 ± 2.594 | 1.827 ± 0.121 | 15242 | 2.068 ± 0.548 | 2.218 ± 0.760 |
| long_memory | hcsn | 3/3 | 24.023 ± 2.658 | 1.401 ± 0.003 | 10948 | 33.685 ± 5.595 | 34.988 ± 6.623 |
| long_memory | lif_snn | 3/3 | 24.902 ± 0.544 | 1.390 ± 0.001 | 4484 | 4.698 ± 1.645 | 4.746 ± 1.714 |
| long_memory | continuous_rnn | 3/3 | 25.358 ± 0.746 | 1.393 ± 0.010 | 4452 | 5.269 ± 2.354 | 5.390 ± 2.429 |
| long_memory | two_gates | 3/3 | 24.870 ± 2.652 | 1.396 ± 0.007 | 8580 | 3.908 ± 0.950 | 4.195 ± 1.175 |
| long_memory | cfc | 3/3 | 25.521 ± 0.886 | 1.398 ± 0.009 | 8644 | 6.653 ± 1.077 | 6.859 ± 1.212 |
| long_memory | mamba1 | 3/3 | 24.121 ± 1.599 | 1.403 ± 0.012 | 12292 | 10.865 ± 4.159 | 11.028 ± 4.146 |
| long_memory | transformer | 3/3 | 26.237 ± 3.677 | 1.391 ± 0.015 | 15044 | 1.857 ± 0.456 | 1.870 ± 0.455 |

## Scaling

| Configuration / task | Architecture | Seeds | Accuracy % mean ± SD | CE mean ± SD | Parameters | Train CPU s mean ± SD | Train wall s mean ± SD |
|---|---|---:|---:|---:|---:|---:|---:|
| config00 center W32 D1 N1024 T32 long_memory | hcsn | 3/3 | 26.432 ± 0.149 | 1.398 ± 0.004 | 10948 | 19.430 ± 0.642 | 19.816 ± 0.598 |
| config00 center W32 D1 N1024 T32 long_memory | mamba1 | 3/3 | 26.823 ± 1.053 | 1.396 ± 0.003 | 12292 | 7.926 ± 1.487 | 8.029 ± 1.572 |
| config00 center W32 D1 N1024 T32 long_memory | transformer | 3/3 | 27.181 ± 2.344 | 1.395 ± 0.020 | 15044 | 1.084 ± 0.273 | 1.098 ± 0.290 |
| config01 capacity W16 D1 N1024 T32 long_memory | hcsn | 3/3 | 26.335 ± 1.869 | 1.394 ± 0.008 | 3428 | 13.480 ± 3.547 | 13.592 ± 3.643 |
| config01 capacity W16 D1 N1024 T32 long_memory | mamba1 | 3/3 | 25.358 ± 0.720 | 1.396 ± 0.004 | 4548 | 4.243 ± 1.194 | 4.314 ± 1.167 |
| config01 capacity W16 D1 N1024 T32 long_memory | transformer | 3/3 | 25.911 ± 0.948 | 1.399 ± 0.012 | 4452 | 1.016 ± 0.209 | 1.042 ± 0.224 |
| config02 capacity W64 D2 N1024 T32 long_memory | hcsn | 3/3 | 25.358 ± 1.080 | 1.403 ± 0.005 | 71876 | 39.586 ± 0.626 | 40.108 ± 0.753 |
| config02 capacity W64 D2 N1024 T32 long_memory | mamba1 | 3/3 | 26.660 ± 0.258 | 1.409 ± 0.005 | 70084 | 31.173 ± 2.266 | 32.470 ± 3.231 |
| config02 capacity W64 D2 N1024 T32 long_memory | transformer | 3/3 | 55.371 ± 39.504 | 0.844 ± 0.733 | 104644 | 3.217 ± 0.514 | 3.221 ± 0.508 |
| config03 capacity W128 D2 N1024 T32 long_memory | hcsn | 3/3 | 25.781 ± 0.737 | 1.412 ± 0.010 | 274820 | 66.209 ± 9.010 | 69.101 ± 9.569 |
| config03 capacity W128 D2 N1024 T32 long_memory | mamba1 | 3/3 | 25.488 ± 2.233 | 1.446 ± 0.060 | 242564 | 58.939 ± 8.620 | 60.570 ± 9.439 |
| config03 capacity W128 D2 N1024 T32 long_memory | transformer | 3/3 | 76.725 ± 28.375 | 0.492 ± 0.569 | 405892 | 10.121 ± 6.142 | 10.387 ± 6.512 |
| config04 capacity W256 D3 N1024 T32 long_memory | hcsn | 3/3 | 24.577 ± 0.997 | 1.444 ± 0.032 | 1601540 | 167.241 ± 26.441 | 173.739 ± 32.182 |
| config04 capacity W256 D3 N1024 T32 long_memory | mamba1 | 3/3 | 25.651 ± 0.907 | 1.518 ± 0.074 | 1332740 | 155.587 ± 14.538 | 157.325 ± 17.064 |
| config04 capacity W256 D3 N1024 T32 long_memory | transformer | 3/3 | 26.725 ± 1.545 | 1.472 ± 0.127 | 2387972 | 34.678 ± 2.913 | 35.065 ± 2.759 |
| config05 data W32 D1 N256 T32 long_memory | hcsn | 3/3 | 24.056 ± 0.819 | 1.426 ± 0.015 | 10948 | 17.598 ± 2.630 | 18.273 ± 3.075 |
| config05 data W32 D1 N256 T32 long_memory | mamba1 | 3/3 | 25.391 ± 1.378 | 1.466 ± 0.051 | 12292 | 9.483 ± 3.912 | 9.848 ± 4.331 |
| config05 data W32 D1 N256 T32 long_memory | transformer | 3/3 | 32.520 ± 14.971 | 1.357 ± 0.131 | 15044 | 1.358 ± 0.353 | 1.416 ± 0.427 |
| config06 data W32 D1 N4096 T32 long_memory | hcsn | 3/3 | 25.033 ± 0.923 | 1.398 ± 0.009 | 10948 | 26.121 ± 9.062 | 29.091 ± 12.673 |
| config06 data W32 D1 N4096 T32 long_memory | mamba1 | 3/3 | 25.326 ± 2.643 | 1.399 ± 0.007 | 12292 | 7.051 ± 2.691 | 7.702 ± 2.645 |
| config06 data W32 D1 N4096 T32 long_memory | transformer | 3/3 | 26.400 ± 1.300 | 1.403 ± 0.023 | 15044 | 1.454 ± 0.166 | 1.501 ± 0.119 |
| config07 context W32 D1 N1024 T64 long_memory | hcsn | 3/3 | 25.033 ± 0.440 | 1.399 ± 0.006 | 10948 | 41.331 ± 4.759 | 42.536 ± 5.617 |
| config07 context W32 D1 N1024 T64 long_memory | mamba1 | 3/3 | 26.497 ± 0.988 | 1.394 ± 0.005 | 12292 | 22.156 ± 6.466 | 23.220 ± 7.376 |
| config07 context W32 D1 N1024 T64 long_memory | transformer | 3/3 | 25.163 ± 2.059 | 1.402 ± 0.007 | 15044 | 2.565 ± 0.171 | 2.578 ± 0.167 |
| config08 context W32 D1 N1024 T128 long_memory | hcsn | 3/3 | 25.033 ± 0.298 | 1.395 ± 0.002 | 10948 | 127.672 ± 35.674 | 137.142 ± 48.534 |
| config08 context W32 D1 N1024 T128 long_memory | mamba1 | 3/3 | 25.098 ± 0.000 | 1.400 ± 0.006 | 12292 | 50.098 ± 4.485 | 51.849 ± 5.519 |
| config08 context W32 D1 N1024 T128 long_memory | transformer | 3/3 | 26.237 ± 0.948 | 1.401 ± 0.002 | 15044 | 4.023 ± 0.374 | 4.079 ± 0.336 |
| config09 joint W64 D2 N4096 T128 multimodal_select | hcsn | 3/3 | 16.048 ± 0.451 | 2.238 ± 0.019 | 72266 | 295.001 ± 48.958 | 314.580 ± 64.593 |
| config09 joint W64 D2 N4096 T128 multimodal_select | mamba1 | 3/3 | 11.230 ± 2.201 | 2.295 ± 0.022 | 70474 | 190.290 ± 63.144 | 203.505 ± 85.792 |
| config09 joint W64 D2 N4096 T128 multimodal_select | transformer | 3/3 | 36.361 ± 6.392 | 1.881 ± 0.169 | 105034 | 13.077 ± 3.166 | 13.386 ± 3.416 |

## Multimodal query and conflicting-label subsets

These are target accuracies conditional on the requested modality, not separate frozen-encoder probes. Conflict cases have different image and spoken digits. Mean ± sample SD is across training seeds.

| Stage | Architecture | Seeds | Overall % | Image-query % | Spoken-query % | Conflicting-label % |
|---|---|---:|---:|---:|---:|---:|
| mechanism | hcsn | 5/5 | 23.125 ± 3.474 | 33.793 ± 7.101 | 12.032 ± 1.318 | 20.556 ± 2.647 |
| mechanism | single | 5/5 | 23.516 ± 1.870 | 34.636 ± 4.540 | 11.952 ± 1.587 | 21.267 ± 1.543 |
| mechanism | no_adaptation | 5/5 | 22.285 ± 2.916 | 31.954 ± 5.597 | 12.231 ± 0.362 | 20.356 ± 2.367 |
| mechanism | ordinary | 5/5 | 22.832 ± 3.623 | 33.180 ± 7.103 | 12.072 ± 0.519 | 20.578 ± 3.184 |
| mechanism | continuous_rnn | 5/5 | 16.992 ± 2.113 | 22.184 ± 4.485 | 11.594 ± 1.122 | 15.867 ± 2.040 |
| representation | hcsn | 3/3 | 25.716 ± 2.728 | 38.697 ± 5.757 | 12.218 ± 0.941 | 23.593 ± 2.667 |
| representation | lif_snn | 3/3 | 10.677 ± 0.620 | 11.175 ± 0.553 | 10.159 ± 1.631 | 10.778 ± 0.770 |
| representation | continuous_rnn | 3/3 | 18.815 ± 2.100 | 27.650 ± 3.450 | 9.628 ± 1.003 | 17.037 ± 1.561 |
| representation | two_gates | 3/3 | 24.902 ± 2.882 | 38.953 ± 5.102 | 10.292 ± 1.201 | 23.704 ± 2.885 |
| representation | cfc | 3/3 | 15.202 ± 2.932 | 19.604 ± 6.194 | 10.624 ± 0.460 | 14.926 ± 2.924 |
| representation | mamba1 | 3/3 | 38.053 ± 5.602 | 63.857 ± 11.276 | 11.222 ± 0.304 | 36.889 ± 6.093 |
| representation | transformer | 3/3 | 36.686 ± 2.594 | 57.280 ± 4.000 | 15.272 ± 1.217 | 34.148 ± 3.518 |

## All four prespecified mechanism contrasts per task

The protocol contains no Boolean success formula. The 1 pp practical-effect value is a reference, not a newly imposed pass/fail rule.

| Task | Contrast | Paired seeds | Accuracy difference pp | 98.75% CI pp | Practical reference pp | Status |
|---|---|---:|---:|---:|---:|---|
| synthetic | hcsn-minus-single | 5/5 | -0.391 | [-3.748, 2.967] | 1.00 | complete |
| synthetic | hcsn-minus-no_adaptation | 5/5 | -0.352 | [-2.954, 2.251] | 1.00 | complete |
| synthetic | hcsn-minus-ordinary | 5/5 | 0.391 | [-2.186, 2.967] | 1.00 | complete |
| synthetic | hcsn-minus-continuous_rnn | 5/5 | 7.734 | [0.975, 14.494] | 1.00 | complete |
| multimodal_select | hcsn-minus-single | 5/5 | -0.391 | [-4.997, 4.215] | 1.00 | complete |
| multimodal_select | hcsn-minus-no_adaptation | 5/5 | 0.840 | [-1.683, 3.363] | 1.00 | complete |
| multimodal_select | hcsn-minus-ordinary | 5/5 | 0.293 | [-1.758, 2.344] | 1.00 | complete |
| multimodal_select | hcsn-minus-continuous_rnn | 5/5 | 6.133 | [-2.975, 15.241] | 1.00 | complete |

## Every scaling seed: validation versus cumulative training CPU

Each point is `update: CPU seconds / validation CE / validation accuracy %`; these are the three registered checkpoints, not interpolated convergence curves.

| Configuration | Architecture | Seed | Points |
|---|---|---:|---|
| config00 | hcsn | 3301 | 40: 3.869s / 1.4062 / 24.80%; 80: 7.811s / 1.4066 / 24.80%; 160: 19.526s / 1.4171 / 29.30% |
| config00 | hcsn | 3302 | 40: 3.204s / 1.3963 / 25.20%; 80: 7.709s / 1.3874 / 26.95%; 160: 18.746s / 1.4064 / 27.15% |
| config00 | hcsn | 3303 | 40: 5.999s / 1.3880 / 25.20%; 80: 10.955s / 1.3975 / 25.00%; 160: 20.018s / 1.4151 / 26.95% |
| config00 | mamba1 | 3301 | 40: 2.412s / 1.4153 / 24.61%; 80: 4.356s / 1.4091 / 24.02%; 160: 9.537s / 1.4791 / 25.98% |
| config00 | mamba1 | 3302 | 40: 1.940s / 1.3907 / 26.76%; 80: 3.905s / 1.4151 / 24.61%; 160: 7.635s / 1.4603 / 26.17% |
| config00 | mamba1 | 3303 | 40: 1.585s / 1.3938 / 23.83%; 80: 3.205s / 1.4010 / 26.56%; 160: 6.607s / 1.5279 / 25.39% |
| config00 | transformer | 3301 | 40: 0.231s / 1.4281 / 24.02%; 80: 0.452s / 1.4175 / 22.85%; 160: 0.900s / 1.4025 / 28.71% |
| config00 | transformer | 3302 | 40: 0.411s / 1.4000 / 24.22%; 80: 0.726s / 1.4016 / 26.17%; 160: 1.398s / 1.4096 / 26.17% |
| config00 | transformer | 3303 | 40: 0.251s / 1.3966 / 24.61%; 80: 0.487s / 1.4110 / 26.37%; 160: 0.955s / 1.4295 / 24.61% |
| config01 | hcsn | 3301 | 40: 2.449s / 1.4091 / 24.61%; 80: 4.899s / 1.4031 / 24.80%; 160: 10.520s / 1.4228 / 26.37% |
| config01 | hcsn | 3302 | 40: 5.005s / 1.3916 / 26.76%; 80: 9.376s / 1.3980 / 27.15%; 160: 17.412s / 1.4066 / 26.56% |
| config01 | hcsn | 3303 | 40: 4.339s / 1.3874 / 24.41%; 80: 7.538s / 1.4020 / 25.39%; 160: 12.507s / 1.3962 / 25.98% |
| config01 | mamba1 | 3301 | 40: 0.813s / 1.4022 / 24.61%; 80: 1.601s / 1.4090 / 23.05%; 160: 3.819s / 1.4414 / 24.41% |
| config01 | mamba1 | 3302 | 40: 0.856s / 1.3884 / 26.37%; 80: 1.682s / 1.3992 / 24.61%; 160: 3.318s / 1.4093 / 26.56% |
| config01 | mamba1 | 3303 | 40: 1.194s / 1.3887 / 25.59%; 80: 2.517s / 1.4032 / 24.61%; 160: 5.590s / 1.4328 / 29.10% |
| config01 | transformer | 3301 | 40: 0.318s / 1.4208 / 24.80%; 80: 0.635s / 1.4014 / 23.05%; 160: 1.193s / 1.4096 / 25.20% |
| config01 | transformer | 3302 | 40: 0.192s / 1.4016 / 24.61%; 80: 0.387s / 1.4001 / 25.20%; 160: 1.070s / 1.4021 / 24.80% |
| config01 | transformer | 3303 | 40: 0.217s / 1.3958 / 24.61%; 80: 0.407s / 1.4119 / 25.59%; 160: 0.785s / 1.4087 / 25.20% |
| config02 | hcsn | 3301 | 40: 11.228s / 1.3954 / 24.61%; 80: 19.450s / 1.4344 / 25.98%; 160: 39.690s / 1.4702 / 29.69% |
| config02 | hcsn | 3302 | 40: 10.159s / 1.4048 / 28.52%; 80: 16.910s / 1.4146 / 27.15%; 160: 38.915s / 1.4604 / 26.95% |
| config02 | hcsn | 3303 | 40: 9.140s / 1.4572 / 25.20%; 80: 20.941s / 1.4122 / 25.98%; 160: 40.153s / 1.4968 / 28.12% |
| config02 | mamba1 | 3301 | 40: 7.838s / 1.4196 / 25.59%; 80: 18.399s / 1.4860 / 24.22%; 160: 33.576s / 1.5917 / 27.54% |
| config02 | mamba1 | 3302 | 40: 11.941s / 1.4033 / 26.37%; 80: 18.115s / 1.4182 / 27.15%; 160: 30.867s / 1.6256 / 27.73% |
| config02 | mamba1 | 3303 | 40: 8.943s / 1.3898 / 29.10%; 80: 15.682s / 1.4488 / 24.80%; 160: 29.075s / 1.6914 / 28.32% |
| config02 | transformer | 3301 | 40: 0.842s / 1.4125 / 24.80%; 80: 1.658s / 1.3999 / 25.00%; 160: 3.523s / 1.0697 / 47.46% |
| config02 | transformer | 3302 | 40: 0.636s / 1.3861 / 27.73%; 80: 1.299s / 1.3907 / 25.78%; 160: 2.624s / 0.0197 / 99.80% |
| config02 | transformer | 3303 | 40: 0.864s / 1.4132 / 26.37%; 80: 1.716s / 1.3949 / 27.54%; 160: 3.505s / 1.4158 / 25.78% |
| config03 | hcsn | 3301 | 40: 13.454s / 1.4166 / 23.63%; 80: 25.609s / 1.4112 / 27.93%; 160: 56.144s / 1.6051 / 26.56% |
| config03 | hcsn | 3302 | 40: 19.134s / 1.3925 / 25.39%; 80: 35.328s / 1.4153 / 22.66%; 160: 68.960s / 1.4137 / 31.05% |
| config03 | hcsn | 3303 | 40: 13.241s / 1.4398 / 26.56%; 80: 32.290s / 1.4260 / 25.39%; 160: 73.522s / 1.5265 / 25.78% |
| config03 | mamba1 | 3301 | 40: 15.503s / 1.4061 / 24.61%; 80: 40.372s / 1.4863 / 25.20%; 160: 67.491s / 1.7576 / 28.91% |
| config03 | mamba1 | 3302 | 40: 20.751s / 1.4113 / 26.37%; 80: 31.089s / 1.4813 / 28.32%; 160: 59.075s / 1.7271 / 28.12% |
| config03 | mamba1 | 3303 | 40: 9.646s / 1.4553 / 29.88%; 80: 24.737s / 1.5734 / 26.95%; 160: 50.253s / 1.8343 / 24.41% |
| config03 | transformer | 3301 | 40: 3.620s / 1.5016 / 23.05%; 80: 7.392s / 1.4315 / 26.95%; 160: 17.213s / 1.1427 / 44.34% |
| config03 | transformer | 3302 | 40: 1.388s / 1.3904 / 30.47%; 80: 2.836s / 0.0004 / 100.00%; 160: 6.594s / 0.0045 / 99.80% |
| config03 | transformer | 3303 | 40: 1.809s / 1.4323 / 28.32%; 80: 3.433s / 1.2641 / 41.21%; 160: 6.556s / 0.4475 / 81.25% |
| config04 | hcsn | 3301 | 40: 35.942s / 1.3959 / 26.56%; 80: 70.929s / 1.4623 / 24.61%; 160: 142.748s / 1.5872 / 26.17% |
| config04 | hcsn | 3302 | 40: 57.415s / 1.4353 / 26.76%; 80: 115.822s / 1.4420 / 22.46%; 160: 195.273s / 1.4779 / 25.78% |
| config04 | hcsn | 3303 | 40: 39.075s / 1.5320 / 24.61%; 80: 80.273s / 1.4228 / 23.83%; 160: 163.702s / 1.5265 / 26.37% |
| config04 | mamba1 | 3301 | 40: 44.547s / 1.4902 / 26.56%; 80: 90.142s / 1.5353 / 24.80%; 160: 171.952s / 1.5774 / 27.54% |
| config04 | mamba1 | 3302 | 40: 36.341s / 1.4326 / 26.76%; 80: 74.582s / 1.4633 / 24.61%; 160: 144.166s / 1.5810 / 25.78% |
| config04 | mamba1 | 3303 | 40: 41.496s / 1.7028 / 24.41%; 80: 77.831s / 1.6343 / 27.34%; 160: 150.644s / 1.7495 / 24.02% |
| config04 | transformer | 3301 | 40: 8.094s / 2.1743 / 24.61%; 80: 16.195s / 1.6093 / 24.61%; 160: 37.825s / 1.3937 / 27.93% |
| config04 | transformer | 3302 | 40: 8.205s / 1.5640 / 27.15%; 80: 16.977s / 1.6080 / 24.61%; 160: 34.134s / 1.6376 / 24.80% |
| config04 | transformer | 3303 | 40: 9.690s / 2.1946 / 25.20%; 80: 16.833s / 1.7309 / 22.46%; 160: 32.076s / 1.4507 / 23.83% |
| config05 | hcsn | 3301 | 40: 3.164s / 1.4092 / 22.27%; 80: 6.806s / 1.5575 / 24.61%; 160: 15.470s / 1.8536 / 23.83% |
| config05 | hcsn | 3302 | 40: 5.959s / 1.4166 / 25.00%; 80: 10.856s / 1.6121 / 27.54%; 160: 20.539s / 1.9276 / 25.20% |
| config05 | hcsn | 3303 | 40: 3.737s / 1.4124 / 24.80%; 80: 8.218s / 1.4981 / 25.00%; 160: 16.785s / 1.9691 / 24.41% |
| config05 | mamba1 | 3301 | 40: 3.018s / 1.4316 / 23.24%; 80: 5.722s / 1.7444 / 23.24%; 160: 10.536s / 5.3352 / 23.83% |
| config05 | mamba1 | 3302 | 40: 1.293s / 1.4573 / 23.83%; 80: 2.568s / 1.7208 / 25.78%; 160: 5.152s / 3.6313 / 23.83% |
| config05 | mamba1 | 3303 | 40: 3.863s / 1.4890 / 23.44%; 80: 6.634s / 1.7854 / 26.37%; 160: 12.760s / 6.0654 / 26.95% |
| config05 | transformer | 3301 | 40: 0.366s / 1.3960 / 25.78%; 80: 0.688s / 1.4516 / 26.56%; 160: 1.359s / 1.2051 / 50.98% |
| config05 | transformer | 3302 | 40: 0.630s / 1.4187 / 24.80%; 80: 0.995s / 1.4369 / 25.59%; 160: 1.711s / 2.1309 / 24.41% |
| config05 | transformer | 3303 | 40: 0.299s / 1.3920 / 25.59%; 80: 0.544s / 1.4475 / 23.63%; 160: 1.005s / 1.5990 / 30.08% |
| config06 | hcsn | 3301 | 40: 5.495s / 1.3999 / 25.20%; 80: 9.687s / 1.3942 / 25.98%; 160: 23.111s / 1.3915 / 25.20% |
| config06 | hcsn | 3302 | 40: 4.562s / 1.3974 / 24.41%; 80: 7.873s / 1.4020 / 24.61%; 160: 18.946s / 1.3938 / 25.39% |
| config06 | hcsn | 3303 | 40: 7.458s / 1.3938 / 26.17%; 80: 13.715s / 1.3984 / 26.17%; 160: 36.305s / 1.3883 / 24.61% |
| config06 | mamba1 | 3301 | 40: 1.247s / 1.4077 / 25.20%; 80: 3.126s / 1.3921 / 25.59%; 160: 5.796s / 1.3927 / 26.17% |
| config06 | mamba1 | 3302 | 40: 4.027s / 1.3922 / 24.22%; 80: 6.079s / 1.3910 / 24.80%; 160: 10.140s / 1.3933 / 26.37% |
| config06 | mamba1 | 3303 | 40: 1.552s / 1.3919 / 24.02%; 80: 2.822s / 1.3881 / 26.56%; 160: 5.216s / 1.4031 / 24.02% |
| config06 | transformer | 3301 | 40: 0.323s / 1.4060 / 23.63%; 80: 0.645s / 1.3990 / 25.39%; 160: 1.264s / 1.3879 / 27.73% |
| config06 | transformer | 3302 | 40: 0.455s / 1.4096 / 25.78%; 80: 0.890s / 1.4059 / 25.00%; 160: 1.527s / 1.4070 / 25.98% |
| config06 | transformer | 3303 | 40: 0.398s / 1.4105 / 25.78%; 80: 0.787s / 1.4104 / 23.05%; 160: 1.571s / 1.3920 / 24.61% |
| config07 | hcsn | 3301 | 40: 7.307s / 1.4076 / 24.80%; 80: 20.771s / 1.4123 / 22.46%; 160: 36.024s / 1.4263 / 22.66% |
| config07 | hcsn | 3302 | 40: 9.232s / 1.3991 / 25.00%; 80: 19.150s / 1.3954 / 27.34%; 160: 42.754s / 1.4294 / 26.17% |
| config07 | hcsn | 3303 | 40: 9.307s / 1.3874 / 26.37%; 80: 19.213s / 1.3983 / 25.20%; 160: 45.217s / 1.4252 / 26.95% |
| config07 | mamba1 | 3301 | 40: 4.359s / 1.4098 / 24.61%; 80: 8.326s / 1.4097 / 21.29%; 160: 16.408s / 1.4446 / 24.61% |
| config07 | mamba1 | 3302 | 40: 7.854s / 1.3908 / 26.17%; 80: 12.389s / 1.4028 / 25.78%; 160: 20.904s / 1.4361 / 24.61% |
| config07 | mamba1 | 3303 | 40: 10.029s / 1.3940 / 23.44%; 80: 20.518s / 1.4045 / 22.27%; 160: 29.157s / 1.4556 / 24.80% |
| config07 | transformer | 3301 | 40: 0.690s / 1.4274 / 22.46%; 80: 1.335s / 1.4185 / 24.22%; 160: 2.753s / 1.4215 / 24.41% |
| config07 | transformer | 3302 | 40: 0.646s / 1.3987 / 25.00%; 80: 1.294s / 1.4025 / 25.98%; 160: 2.521s / 1.4226 / 24.22% |
| config07 | transformer | 3303 | 40: 0.637s / 1.4032 / 23.83%; 80: 1.242s / 1.4182 / 26.37%; 160: 2.421s / 1.4378 / 23.05% |
| config08 | hcsn | 3301 | 40: 26.283s / 1.4101 / 24.61%; 80: 61.960s / 1.4113 / 22.66%; 160: 110.122s / 1.4125 / 24.22% |
| config08 | hcsn | 3302 | 40: 24.274s / 1.3996 / 24.61%; 80: 51.812s / 1.3870 / 26.56%; 160: 168.722s / 1.4241 / 25.20% |
| config08 | hcsn | 3303 | 40: 33.797s / 1.3858 / 25.20%; 80: 54.532s / 1.4011 / 24.22%; 160: 104.173s / 1.4205 / 25.00% |
| config08 | mamba1 | 3301 | 40: 13.042s / 1.4103 / 24.61%; 80: 25.689s / 1.4365 / 23.05%; 160: 49.191s / 1.4203 / 22.27% |
| config08 | mamba1 | 3302 | 40: 13.662s / 1.3929 / 24.61%; 80: 24.193s / 1.3949 / 23.83%; 160: 46.136s / 1.4132 / 26.37% |
| config08 | mamba1 | 3303 | 40: 15.259s / 1.3937 / 24.61%; 80: 29.328s / 1.4116 / 25.00%; 160: 54.968s / 1.4364 / 27.15% |
| config08 | transformer | 3301 | 40: 1.018s / 1.4207 / 23.44%; 80: 1.893s / 1.4279 / 22.27%; 160: 3.688s / 1.4447 / 23.24% |
| config08 | transformer | 3302 | 40: 1.109s / 1.4095 / 24.41%; 80: 2.224s / 1.4173 / 25.78%; 160: 3.954s / 1.4300 / 24.80% |
| config08 | transformer | 3303 | 40: 1.176s / 1.3995 / 23.24%; 80: 2.220s / 1.4057 / 23.05%; 160: 4.427s / 1.4301 / 25.39% |
| config09 | hcsn | 3301 | 40: 65.674s / 2.3488 / 9.96%; 80: 132.209s / 2.3212 / 9.96%; 160: 269.258s / 2.2597 / 14.26% |
| config09 | hcsn | 3302 | 40: 90.167s / 2.3341 / 9.96%; 80: 156.105s / 2.2758 / 11.72%; 160: 351.460s / 2.2578 / 14.45% |
| config09 | hcsn | 3303 | 40: 57.906s / 2.3189 / 9.96%; 80: 124.850s / 2.2957 / 14.65%; 160: 264.287s / 2.2633 / 13.67% |
| config09 | mamba1 | 3301 | 40: 36.373s / 2.3279 / 9.96%; 80: 78.901s / 2.3163 / 9.96%; 160: 149.957s / 2.3080 / 9.77% |
| config09 | mamba1 | 3302 | 40: 40.849s / 2.3209 / 9.96%; 80: 82.090s / 2.3279 / 9.96%; 160: 157.854s / 2.2654 / 14.84% |
| config09 | mamba1 | 3303 | 40: 97.757s / 2.3191 / 9.96%; 80: 150.486s / 2.3121 / 9.96%; 160: 263.059s / 2.3072 / 9.96% |
| config09 | transformer | 3301 | 40: 2.842s / 2.3088 / 14.65%; 80: 5.123s / 2.0844 / 30.47%; 160: 10.297s / 1.7808 / 40.23% |
| config09 | transformer | 3302 | 40: 2.625s / 2.2856 / 19.53%; 80: 5.041s / 2.1532 / 28.91%; 160: 12.412s / 2.1130 / 29.49% |
| config09 | transformer | 3303 | 40: 4.181s / 2.3030 / 15.43%; 80: 7.740s / 2.1919 / 23.44%; 160: 16.523s / 2.0425 / 34.96% |

## Every preselected inference measurement

Batch 16, CPU-only; warmup and profiler are outside latency samples. FLOPs below are **partial**, and allocations are **not RSS**.

| Run | Status | Wall median / p95 ms | CPU median ms | Examples/s median / p95 | Partial MFLOPs | Created / peak additional MiB |
|---|---|---:|---:|---:|---:|---:|
| representation/mnist/hcsn/seed2201 | complete | 16.596 / 18.370 | 16.601 | 964.1 / 1099.7 | 11.328 | 6.768 / 1.334 |
| representation/mnist/lif_snn/seed2201 | complete | 2.606 / 3.463 | 2.609 | 6139.9 / 7626.8 | 4.672 | 1.261 / 0.320 |
| representation/mnist/continuous_rnn/seed2201 | complete | 1.424 / 2.028 | 1.427 | 11236.4 / 13165.2 | 4.622 | 1.047 / 0.318 |
| representation/mnist/two_gates/seed2201 | complete | 2.354 / 2.780 | 2.357 | 6798.1 / 8041.4 | 8.848 | 1.416 / 0.318 |
| representation/mnist/cfc/seed2201 | complete | 3.007 / 4.682 | 3.010 | 5320.9 / 5801.0 | 8.897 | 1.603 / 0.318 |
| representation/mnist/mamba1/seed2201 | complete | 3.120 / 3.655 | 3.123 | 5128.9 / 5813.4 | 13.485 | 16.952 / 1.639 |
| representation/mnist/transformer/seed2201 | complete | 0.984 / 1.139 | 0.987 | 16265.5 / 19184.2 | 15.123 | 1.716 / 1.131 |
| representation/fsdd/hcsn/seed2201 | complete | 16.784 / 22.000 | 16.788 | 953.3 / 1083.2 | 11.328 | 6.768 / 1.334 |
| representation/fsdd/lif_snn/seed2201 | complete | 2.772 / 3.353 | 2.775 | 5771.7 / 7253.3 | 4.672 | 1.261 / 0.320 |
| representation/fsdd/continuous_rnn/seed2201 | complete | 1.357 / 1.729 | 1.360 | 11793.6 / 13329.2 | 4.622 | 1.047 / 0.318 |
| representation/fsdd/two_gates/seed2201 | complete | 2.163 / 2.805 | 2.166 | 7396.7 / 8509.3 | 8.848 | 1.416 / 0.318 |
| representation/fsdd/cfc/seed2201 | complete | 3.075 / 4.116 | 3.078 | 5202.7 / 6100.4 | 8.897 | 1.603 / 0.318 |
| representation/fsdd/mamba1/seed2201 | complete | 3.600 / 4.000 | 3.603 | 4444.9 / 5026.5 | 13.485 | 16.952 / 1.639 |
| representation/fsdd/transformer/seed2201 | complete | 1.091 / 1.325 | 1.094 | 14669.3 / 19886.8 | 15.123 | 1.716 / 1.131 |
| representation/multimodal_select/hcsn/seed2201 | complete | 16.342 / 22.418 | 16.346 | 979.1 / 1327.5 | 11.328 | 6.768 / 1.334 |
| representation/multimodal_select/lif_snn/seed2201 | complete | 2.428 / 2.786 | 2.432 | 6588.6 / 7364.6 | 4.672 | 1.261 / 0.320 |
| representation/multimodal_select/continuous_rnn/seed2201 | complete | 2.058 / 2.328 | 2.062 | 7774.1 / 12452.6 | 4.622 | 1.047 / 0.318 |
| representation/multimodal_select/two_gates/seed2201 | complete | 1.963 / 2.397 | 1.966 | 8152.0 / 8708.3 | 8.848 | 1.416 / 0.318 |
| representation/multimodal_select/cfc/seed2201 | complete | 3.024 / 4.367 | 3.027 | 5291.2 / 5579.3 | 8.897 | 1.603 / 0.318 |
| representation/multimodal_select/mamba1/seed2201 | complete | 2.898 / 3.183 | 2.901 | 5521.9 / 5694.5 | 13.485 | 16.952 / 1.639 |
| representation/multimodal_select/transformer/seed2201 | complete | 0.835 / 0.918 | 0.838 | 19154.1 / 21536.6 | 15.123 | 1.716 / 1.131 |
| representation/long_memory/hcsn/seed2201 | complete | 17.456 / 18.731 | 17.461 | 916.6 / 1092.5 | 11.131 | 6.756 / 1.334 |
| representation/long_memory/lif_snn/seed2201 | complete | 12.004 / 14.821 | 12.008 | 1332.9 / 3835.2 | 4.475 | 1.249 / 0.320 |
| representation/long_memory/continuous_rnn/seed2201 | complete | 1.163 / 1.524 | 1.166 | 13753.5 / 14813.3 | 4.425 | 1.035 / 0.318 |
| representation/long_memory/two_gates/seed2201 | complete | 1.969 / 2.779 | 1.972 | 8126.2 / 8543.6 | 8.652 | 1.405 / 0.318 |
| representation/long_memory/cfc/seed2201 | complete | 4.104 / 8.738 | 4.107 | 3898.8 / 5088.7 | 8.700 | 1.591 / 0.318 |
| representation/long_memory/mamba1/seed2201 | complete | 3.759 / 4.875 | 3.762 | 4257.0 / 5738.7 | 13.288 | 16.941 / 1.639 |
| representation/long_memory/transformer/seed2201 | complete | 0.905 / 1.549 | 0.908 | 17682.6 / 18514.8 | 14.927 | 1.705 / 1.131 |
| scaling/config00/hcsn/seed3301 | complete | 19.692 / 23.354 | 19.697 | 812.5 / 958.2 | 11.131 | 6.756 / 1.334 |
| scaling/config00/mamba1/seed3301 | complete | 4.989 / 6.583 | 4.993 | 3207.2 / 3794.8 | 13.288 | 16.941 / 1.639 |
| scaling/config00/transformer/seed3301 | complete | 0.924 / 1.262 | 0.928 | 17312.0 / 22690.1 | 14.927 | 1.705 / 1.131 |
| scaling/config01/hcsn/seed3301 | complete | 12.264 / 15.197 | 12.268 | 1304.7 / 1477.9 | 3.469 | 3.457 / 0.733 |
| scaling/config01/mamba1/seed3301 | complete | 2.311 / 4.000 | 2.314 | 6924.0 / 7807.2 | 5.006 | 8.579 / 0.916 |
| scaling/config01/transformer/seed3301 | complete | 0.650 / 1.028 | 0.653 | 24610.5 / 28014.3 | 4.318 | 0.938 / 0.631 |
| scaling/config02/hcsn/seed3301 | complete | 50.037 / 52.930 | 50.043 | 319.8 / 335.5 | 73.492 | 26.186 / 3.663 |
| scaling/config02/mamba1/seed3301 | complete | 8.929 / 10.237 | 8.933 | 1792.0 / 1990.4 | 74.777 | 66.803 / 3.209 |
| scaling/config02/transformer/seed3301 | complete | 3.175 / 3.913 | 3.179 | 5039.1 / 7652.0 | 105.416 | 5.509 / 2.131 |
| scaling/config03/hcsn/seed3301 | complete | 51.708 / 58.507 | 51.715 | 309.4 / 343.6 | 281.200 | 52.204 / 7.195 |
| scaling/config03/mamba1/seed3301 | complete | 16.177 / 25.621 | 16.182 | 989.0 / 1091.6 | 254.411 | 133.322 / 6.225 |
| scaling/config03/transformer/seed3301 | complete | 4.955 / 9.588 | 4.958 | 3229.0 / 3484.7 | 412.157 | 10.826 / 4.131 |
| scaling/config04/hcsn/seed3301 | complete | 139.498 / 141.489 | 138.641 | 114.7 / 116.2 | 1639.730 | 155.535 / 14.260 |
| scaling/config04/mamba1/seed3301 | complete | 58.979 / 61.412 | 58.986 | 271.3 / 306.9 | 1383.203 | 398.717 / 12.256 |
| scaling/config04/transformer/seed3301 | complete | 24.250 / 27.914 | 24.255 | 659.8 / 754.4 | 2435.188 | 30.487 / 8.131 |
| scaling/config05/hcsn/seed3301 | complete | 20.650 / 35.845 | 20.654 | 774.8 / 1038.1 | 11.131 | 6.756 / 1.334 |
| scaling/config05/mamba1/seed3301 | complete | 5.869 / 6.930 | 5.874 | 2726.2 / 3348.1 | 13.288 | 16.941 / 1.639 |
| scaling/config05/transformer/seed3301 | complete | 1.058 / 1.364 | 1.061 | 15129.1 / 20087.6 | 14.927 | 1.705 / 1.131 |
| scaling/config06/hcsn/seed3301 | complete | 39.985 / 45.660 | 40.063 | 400.2 / 487.3 | 11.131 | 6.756 / 1.334 |
| scaling/config06/mamba1/seed3301 | complete | 7.458 / 12.016 | 7.463 | 2145.2 / 2660.9 | 13.288 | 16.941 / 1.639 |
| scaling/config06/transformer/seed3301 | complete | 1.112 / 1.360 | 1.115 | 14388.0 / 15950.1 | 14.927 | 1.705 / 1.131 |
| scaling/config07/hcsn/seed3301 | complete | 42.196 / 53.335 | 42.201 | 379.2 / 466.9 | 22.263 | 13.503 / 2.653 |
| scaling/config07/mamba1/seed3301 | complete | 5.872 / 7.068 | 5.876 | 2724.6 / 3266.1 | 26.576 | 33.786 / 3.086 |
| scaling/config07/transformer/seed3301 | complete | 4.815 / 6.722 | 4.820 | 3322.6 / 6092.1 | 29.854 | 3.408 / 2.262 |
| scaling/config08/hcsn/seed3301 | complete | 72.010 / 88.118 | 72.018 | 222.2 / 261.4 | 44.526 | 26.998 / 5.289 |
| scaling/config08/mamba1/seed3301 | complete | 9.619 / 14.694 | 9.623 | 1663.4 / 1799.0 | 53.152 | 67.478 / 5.980 |
| scaling/config08/transformer/seed3301 | complete | 3.177 / 6.705 | 3.180 | 5037.0 / 5457.8 | 59.707 | 6.814 / 4.523 |
| scaling/config09/hcsn/seed3301 | complete | 205.558 / 265.638 | 205.566 | 77.8 / 83.5 | 295.539 | 104.691 / 14.556 |
| scaling/config09/mamba1/seed3301 | complete | 39.854 / 43.681 | 39.860 | 401.5 / 464.0 | 300.681 | 266.121 / 11.688 |
| scaling/config09/transformer/seed3301 | complete | 13.735 / 15.287 | 13.739 | 1164.9 / 1397.7 | 423.236 | 22.067 / 8.523 |

## Cost ledger

| Completed stage | Runs | Recorded training CPU s | Total RESULT CPU s | Summed RESULT job-wall s |
|---|---:|---:|---:|---:|
| mechanism | 50 | 672.158 | 916.857 | 949.436 |
| representation | 84 | 709.059 | 967.463 | 1014.482 |
| scaling | 90 | 4269.634 | 4950.324 | 5198.769 |
| boundary | 5 | 53.953 | 71.000 | 72.553 |

### Representation costs by architecture

Each complete architecture total covers the same four tasks × three seeds × 240 updates; sums are recorded job costs, not calendar elapsed time or inference latency.

| Architecture | Completed runs | Summed training CPU s | Summed training job-wall s | Summed RESULT CPU s |
|---|---:|---:|---:|---:|
| hcsn | 12/12 | 335.015 | 346.918 | 384.066 |
| lif_snn | 12/12 | 58.566 | 59.296 | 91.154 |
| continuous_rnn | 12/12 | 41.450 | 43.416 | 83.864 |
| two_gates | 12/12 | 53.661 | 55.354 | 89.487 |
| cfc | 12/12 | 67.673 | 69.148 | 101.019 |
| mamba1 | 12/12 | 130.663 | 132.597 | 165.707 |
| transformer | 12/12 | 22.031 | 22.758 | 52.167 |

All external training/study attempts: 232. Successful attempts: 229; accumulated job-wall 7991.759s.

Failed attempts: 3; accumulated job-wall 399.874s. Failed attempts with unknown process-CPU: 3.

Inference measurement arithmetic audits passed: 58/58; recorded whole-profile work: 356.006 CPU seconds, 357.169 wall seconds. This includes data, warmup and profiler overhead, unlike the latency samples.

These overlapping job-wall sums are not calendar elapsed time. Failed resource attempts are retained and charged separately.

| Failed run | Attempt | Exit | Wall s |
|---|---|---:|---:|
| scaling/config04/mamba1/seed3302 | EXECUTION_01.json | -9 | 22.074 |
| scaling/config09/mamba1/seed3301 | EXECUTION_01.json | -9 | 127.066 |
| scaling/config09/mamba1/seed3302 | EXECUTION_01.json | -9 | 250.733 |

## Scope and limitations

- No winner or post-hoc configuration selection is assigned by this analysis.
- Accuracy is primary; CE and Brier are lower-is-better. Mean and sample SD describe training-seed variation conditional on fixed heldout sources.
- Mechanism accuracy contrasts use paired seeds and 98.75% two-sided Student-t intervals (four comparisons per task). PROTOCOL records 0.01 minimum practical effect but no Boolean success rule; 0.01 is displayed as a reference line, not a retrospectively registered verdict.
- Representation/scaling have three seeds and are descriptive; common learning rate/updates do not establish each architecture's tuned optimum.
- Scaling uses fixed 160x32 sample presentations; capacity configurations change width/depth jointly. Long-memory adds real distractors but retains four early associations; multimodal length stress adds null steps.
- CPU-only results do not establish GPU or neuromorphic energy advantages. Mamba is an equation-verified serial CPU reference; actual SDPA operators are reported.
- Inference times cover the delivered full-sequence forward, including auxiliary tensors; they are not optimized-kernel lower bounds or fixed-memory streaming measurements.
- Profiler FLOPs are partial supported-operator formulas. Special/fused operators without counts remain explicit. Tensor allocations, including UNKNOWN categories, are not RSS.
- Inference uses a preregistered single seed and first 16 heldout samples; repeat quantiles are descriptive, not confidence intervals over samples or hardware.
- Measurements ran serially on a shared host; serial execution does not establish dedicated-machine isolation. Nonmonotonic small-repeat latency changes do not establish complexity exponents.
- Successful RESULT process-CPU excludes interpreter/import and pre-timer startup. EXECUTION wall includes job startup/scheduling. Summed overlapping job-wall is not study calendar time.
- Failed-attempt wall is charged separately. Failed process-CPU is unknown unless recorded, and is never imputed as zero.

All planned rows are retained; pending/invalid entries are not zero scores. Detailed unsupported operator lists, allocation categories, matching receipts, and seed curves are in COMPARISON_SUMMARY.json.
