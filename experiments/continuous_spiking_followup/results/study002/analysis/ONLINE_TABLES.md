# Study002 online stopping and incremental inference

Scientific source seal: `52ce70744a2659e6f2690fc24e68f651d48f57d4a5064680e71d2694b0a2f673`.

Evidence audit: `28b5288ee617fb62c090af145d780e4edf4271711b9e5f6e4ece13886370f017`. Audit success establishes internal evidence consistency; numerical parity failures, if present, are retained separately.

## Causal paid-observation task

All four arms share each frozen study001 actor, the new episode arrays and the same observation charge. One temperature is fitted on training prefixes; direct thresholds use 100 training updates and fixed thresholds use validation utility. The value policy uses a finite-grid Gaussian transition model informed by the supplied SNR. The actor's natural threshold remains distinct from this task-level stopping rule.

The table reports mean ± sample SD across five actor seeds. Accuracy is percent; utility is correctness reward minus every purchased observation cost, including the first read.

| Split | Policy | Accuracy | Reads / episode | Charge / episode | Net utility | Executed model steps | Avoided model steps |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ID | fixed | 86.88 ± 3.05% | 3.016 ± 0.489 | 0.1083 ± 0.0244 | 0.7605 ± 0.0255 | 965 | 4155 |
| ID | direct | 90.31 ± 4.47% | 4.606 ± 0.759 | 0.1024 ± 0.0097 | 0.8007 ± 0.0391 | 1474 | 3646 |
| ID | value | 88.44 ± 5.48% | 4.853 ± 0.248 | 0.0976 ± 0.0051 | 0.7868 ± 0.0536 | 1553 | 3567 |
| ID | full | 94.69 ± 3.60% | 16.000 ± 0.000 | 0.5787 ± 0.0000 | 0.3681 ± 0.0360 | 5120 | 0 |
| OOD | fixed | 82.19 ± 3.92% | 3.619 ± 0.502 | 0.2003 ± 0.0218 | 0.6216 ± 0.0556 | 1158 | 6522 |
| OOD | direct | 78.44 ± 4.04% | 3.278 ± 0.611 | 0.1149 ± 0.0187 | 0.6694 ± 0.0364 | 1049 | 6631 |
| OOD | value | 80.00 ± 4.34% | 4.219 ± 0.416 | 0.1294 ± 0.0209 | 0.6706 ± 0.0382 | 1350 | 6330 |
| OOD | full | 90.31 ± 3.56% | 24.000 ± 0.000 | 1.3425 ± 0.0000 | -0.4394 ± 0.0356 | 7680 | 0 |

Avoided work is measured by actual RAM-source iterator reads and incremental model updates ending at STOP. It does not measure sensor, network or energy savings.

### Prespecified paired utility contrasts

| Value minus comparator | Mean difference | 98.75% paired Student-t interval | Paired SD |
| --- | --- | --- | --- |
| id/value-minus-fixed | +0.026359 | [-0.047839, +0.100558] | 0.038453 |
| id/value-minus-direct | -0.013922 | [-0.057458, +0.029614] | 0.022562 |
| ood/value-minus-fixed | +0.049062 | [-0.039090, +0.137215] | 0.045685 |
| ood/value-minus-direct | +0.001188 | [-0.085356, +0.087731] | 0.044851 |

These are four Bonferroni-adjusted intervals using the five seed means (df = 4). Episodes and time steps are not counted as independent optimization seeds.

### Shared temperature calibration

| Split | Odds | Prefix cross entropy | Prefix Brier score |
| --- | --- | --- | --- |
| ID | raw | 0.2570 ± 0.0295 | 0.0819 ± 0.0108 |
| ID | shared_temperature | 0.2568 ± 0.0285 | 0.0820 ± 0.0107 |
| OOD | raw | 0.3003 ± 0.0348 | 0.0993 ± 0.0124 |
| OOD | shared_temperature | 0.3001 ± 0.0359 | 0.0993 ± 0.0127 |

A fitted temperature changes confidence calibration. It does not establish that neural log-odds follow the transition model used by the Bellman table.

### Fitting and inherited actor cost

| Actor seed | Shared temperature | Fixed threshold | Policy fitting CPU s | Bellman table CPU s | New study parent CPU s | Historical actor training CPU s |
| --- | --- | --- | --- | --- | --- | --- |
| 4401 | 0.916887 | 0.7000 | 2.6990 | 0.1460 | 7.3034 | 9.0615 |
| 4402 | 0.962551 | 0.7500 | 3.3011 | 0.1641 | 9.0346 | 15.6726 |
| 4403 | 1.007010 | 0.7500 | 2.8108 | 0.1528 | 11.2556 | 8.9188 |
| 4404 | 1.035828 | 0.7000 | 5.2010 | 0.4405 | 11.8387 | 11.5331 |
| 4405 | 0.940356 | 0.7500 | 3.0256 | 0.2401 | 11.7296 | 8.7671 |

Historical actor training is explicitly retained, although these actors are reused. Fitting and table time are nested in the new-study parent total; native child CPU is separate.

## Original native owner and NDU

The audited subset contains **96 actual native episodes**, **370 paid reads**, **102 native processes** and **6 cold native recoveries**. The consumed native and Python policies have 0 step-level action differences; 96 / 96 episodes stop at the same step.

| Split | Policy | Accuracy | Reads / episode | Net utility | Same stopping step / 16 | Cold recoveries |
| --- | --- | --- | --- | --- | --- | --- |
| ID | direct | 100.00% | 6.0625 | 0.893438 | 16 | 1 |
| ID | fixed | 87.50% | 2.7500 | 0.783125 | 16 | 1 |
| ID | value | 100.00% | 6.5625 | 0.894375 | 16 | 1 |
| OOD | direct | 62.50% | 1.8125 | 0.510000 | 16 | 1 |
| OOD | fixed | 68.75% | 3.3125 | 0.420625 | 16 | 1 |
| OOD | value | 68.75% | 2.6250 | 0.571250 | 16 | 1 |

| Actual native counter | Total |
| --- | --- |
| owner_ticks | 370 |
| actual_kernel_calls | 370 |
| actual_ndu_calls | 370 |
| original_journal_replay_steps | 6 |
| event_validation_kernel_steps | 6 |
| event_validation_ndu_calls | 6 |
| total_native_kernel_calls | 382 |
| total_native_ndu_calls | 376 |
| rpc_calls | 1078 |
| request_bytes | 251517 |
| response_bytes | 774152 |
| native_errors | 96 |

The exact-child wait4 CPU total is **0.590080 s**. The native-error count includes the deliberately rejected post-STOP probe for each episode. Archival integrity covers every original owner file, durable event, checkpoint witness, signal packet and native receipt.

Each cold recovery starts a new native process and restores the serialized neural state and task cursor in the existing Python process. The seven standalone neural replays below separately test a fresh Python interpreter. The native profile compiles the signed decision score into the original sparse head/NDU; these runs do not establish an advantage from learning a native sparse head. Natural margin, risk and interval activity enter typed native inputs, but their independent causal benefit is not established. Q24 discrepancies remain in the evidence and are not overridden with Python actions.

## Full-sequence and incremental CPU inference

Single-thread CPU float32, B16, same selected model and inputs. Full-sequence final-logit forward versus all T true incremental steps. Seven serial repeats are descriptive host samples, not confidence intervals; no GPU/optimized-kernel, FLOP, RSS or energy equivalence.

All latencies below are for the same B16 inputs and selected checkpoint. Batch is one complete-sequence final-logit forward; stream is the sum of genuine one-token forwards over the full sequence, excluding reset. Reset, data loading, output comparisons and recovery are retained separately. No complete-prefix recomputation is used to implement the stream.

There are **55 preselected cases**, each with two warmups and seven measured repeats per mode. The largest observed logit difference is **3.76701355e-05**; there are **0 prefix** and **0 final** predicted-class changes. The declared test uses rtol = 3e-05 and atol = 3e-06.

**Retained numerical parity failures:** scaling/config00/transformer/seed7301

### Representation

| Task / scale configuration | Model | W × D × T | Batch median ms | Stream median ms | Stream p95 ms | Stream / batch | State KiB | Max logit error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fsdd | cfc | 32 × 1 × 32 | 3.529 | 8.620 | 10.034 | 2.443 | 2.125 | 0 |
| fsdd | continuous_rnn | 32 × 1 × 32 | 1.730 | 8.964 | 15.719 | 5.181 | 2.125 | 0 |
| fsdd | hcsn | 32 × 1 × 32 | 20.558 | 37.553 | 46.198 | 1.827 | 8.125 | 0 |
| fsdd | lif_snn | 32 × 1 × 32 | 2.732 | 12.887 | 20.367 | 4.718 | 4.125 | 0 |
| fsdd | mamba1 | 32 × 1 × 32 | 4.535 | 35.099 | 45.284 | 7.740 | 76.125 | 0 |
| fsdd | transformer | 32 × 1 × 32 | 1.090 | 14.918 | 23.054 | 13.689 | 128.125 | 1.19e-06 |
| fsdd | two_gates | 32 × 1 × 32 | 3.640 | 12.280 | 14.202 | 3.374 | 2.125 | 0 |
| long_memory | cfc | 32 × 1 × 32 | 3.497 | 11.823 | 126.051 | 3.381 | 2.125 | 0 |
| long_memory | continuous_rnn | 32 × 1 × 32 | 1.453 | 7.073 | 11.601 | 4.869 | 2.125 | 0 |
| long_memory | hcsn | 32 × 1 × 32 | 19.822 | 27.378 | 35.456 | 1.381 | 8.125 | 0 |
| long_memory | lif_snn | 32 × 1 × 32 | 3.110 | 11.356 | 19.691 | 3.651 | 4.125 | 0 |
| long_memory | mamba1 | 32 × 1 × 32 | 3.014 | 26.776 | 31.534 | 8.884 | 76.125 | 0 |
| long_memory | transformer | 32 × 1 × 32 | 0.856 | 20.898 | 25.946 | 24.406 | 128.125 | 9.54e-06 |
| long_memory | two_gates | 32 × 1 × 32 | 2.446 | 8.782 | 12.958 | 3.591 | 2.125 | 0 |
| mnist | cfc | 32 × 1 × 32 | 4.200 | 10.400 | 13.488 | 2.476 | 2.125 | 0 |
| mnist | continuous_rnn | 32 × 1 × 32 | 1.247 | 5.937 | 13.133 | 4.760 | 2.125 | 0 |
| mnist | hcsn | 32 × 1 × 32 | 37.937 | 54.268 | 77.010 | 1.430 | 8.125 | 0 |
| mnist | lif_snn | 32 × 1 × 32 | 8.029 | 45.092 | 63.155 | 5.616 | 4.125 | 0 |
| mnist | mamba1 | 32 × 1 × 32 | 5.881 | 49.318 | 66.369 | 8.385 | 76.125 | 0 |
| mnist | transformer | 32 × 1 × 32 | 1.423 | 27.637 | 41.032 | 19.424 | 128.125 | 3.81e-06 |
| mnist | two_gates | 32 × 1 × 32 | 2.112 | 10.958 | 14.790 | 5.189 | 2.125 | 0 |
| multimodal_select | cfc | 32 × 1 × 32 | 3.862 | 10.847 | 17.646 | 2.808 | 2.125 | 0 |
| multimodal_select | continuous_rnn | 32 × 1 × 32 | 1.361 | 5.852 | 9.486 | 4.298 | 2.125 | 0 |
| multimodal_select | hcsn | 32 × 1 × 32 | 15.697 | 21.296 | 22.111 | 1.357 | 8.125 | 0 |
| multimodal_select | lif_snn | 32 × 1 × 32 | 2.653 | 9.240 | 16.841 | 3.483 | 4.125 | 0 |
| multimodal_select | mamba1 | 32 × 1 × 32 | 3.234 | 26.764 | 31.158 | 8.275 | 76.125 | 0 |
| multimodal_select | transformer | 32 × 1 × 32 | 1.370 | 17.041 | 36.597 | 12.442 | 128.125 | 2.86e-06 |
| multimodal_select | two_gates | 32 × 1 × 32 | 3.085 | 9.902 | 13.168 | 3.210 | 2.125 | 0 |

### Scaling

| Task / scale configuration | Model | W × D × T | Batch median ms | Stream median ms | Stream p95 ms | Stream / batch | State KiB | Max logit error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 00 / center | hcsn | 32 × 1 × 32 | 20.088 | 25.281 | 40.084 | 1.258 | 8.125 | 0 |
| 00 / center | mamba1 | 32 × 1 × 32 | 9.257 | 32.893 | 120.403 | 3.553 | 76.125 | 0 |
| 00 / center | transformer | 32 × 1 × 32 | 1.048 | 20.811 | 24.133 | 19.863 | 128.125 | 1.6e-05 |
| 01 / capacity | hcsn | 16 × 1 × 32 | 40.782 | 37.488 | 106.039 | 0.919 | 4.125 | 0 |
| 01 / capacity | mamba1 | 16 × 1 × 32 | 3.868 | 31.395 | 38.342 | 8.116 | 38.125 | 0 |
| 01 / capacity | transformer | 16 × 1 × 32 | 3.793 | 72.568 | 105.999 | 19.131 | 64.125 | 6.44e-06 |
| 02 / capacity | hcsn | 64 × 2 × 32 | 49.743 | 77.065 | 114.837 | 1.549 | 32.125 | 0 |
| 02 / capacity | mamba1 | 64 × 2 × 32 | 10.706 | 51.892 | 74.684 | 4.847 | 304.125 | 0 |
| 02 / capacity | transformer | 64 × 2 × 32 | 2.596 | 29.069 | 34.234 | 11.197 | 512.125 | 1.41e-05 |
| 03 / capacity | hcsn | 128 × 2 × 32 | 81.024 | 99.380 | 113.114 | 1.227 | 64.125 | 0 |
| 03 / capacity | mamba1 | 128 × 2 × 32 | 22.390 | 72.731 | 90.637 | 3.248 | 608.125 | 0 |
| 03 / capacity | transformer | 128 × 2 × 32 | 6.169 | 46.157 | 53.430 | 7.482 | 1024.125 | 3.77e-05 |
| 04 / data | hcsn | 32 × 1 × 32 | 14.323 | 33.326 | 35.113 | 2.327 | 8.125 | 0 |
| 04 / data | mamba1 | 32 × 1 × 32 | 3.458 | 25.959 | 33.413 | 7.508 | 76.125 | 0 |
| 04 / data | transformer | 32 × 1 × 32 | 1.016 | 19.666 | 20.036 | 19.352 | 128.125 | 2.62e-06 |
| 05 / data | hcsn | 32 × 1 × 32 | 39.684 | 47.447 | 78.643 | 1.196 | 8.125 | 0 |
| 05 / data | mamba1 | 32 × 1 × 32 | 3.623 | 33.643 | 84.061 | 9.285 | 76.125 | 0 |
| 05 / data | transformer | 32 × 1 × 32 | 1.730 | 23.681 | 30.332 | 13.687 | 128.125 | 9.54e-06 |
| 06 / context | hcsn | 32 × 1 × 64 | 42.794 | 46.944 | 75.350 | 1.097 | 8.125 | 0 |
| 06 / context | mamba1 | 32 × 1 × 64 | 12.609 | 78.639 | 168.263 | 6.237 | 76.125 | 0 |
| 06 / context | transformer | 32 × 1 × 64 | 2.262 | 34.794 | 51.894 | 15.380 | 256.125 | 6.2e-06 |
| 07 / context | hcsn | 32 × 1 × 128 | 72.400 | 140.013 | 155.576 | 1.934 | 8.125 | 0 |
| 07 / context | mamba1 | 32 × 1 × 128 | 10.824 | 106.600 | 118.232 | 9.848 | 76.125 | 0 |
| 07 / context | transformer | 32 × 1 × 128 | 5.218 | 88.915 | 108.594 | 17.041 | 512.125 | 1.04e-06 |
| 08 / joint | hcsn | 64 × 2 × 128 | 172.276 | 212.983 | 391.099 | 1.236 | 32.125 | 0 |
| 08 / joint | mamba1 | 64 × 2 × 128 | 47.459 | 218.416 | 416.360 | 4.602 | 304.125 | 0 |
| 08 / joint | transformer | 64 × 2 × 128 | 17.720 | 167.779 | 235.875 | 9.468 | 2048.125 | 2.38e-06 |

Persistent state is tensor payload only: weights, Python objects and transient allocations are excluded. The Transformer adapter retains the causal KV cache; the recurrent models retain their causal state. These CPU measurements do not compare fused GPU kernels, long-context generative quality or full multimodal pretraining.

### Seven standalone neural recoveries

| Model | Exact logits and final state | External process wall s | Model reload wall s | Stream restore wall s | Remainder wall s | Snapshot bytes |
| --- | --- | --- | --- | --- | --- | --- |
| cfc | True | 4.954615 | 0.050074 | 0.118139 | 0.015916 | 3418 |
| continuous_rnn | True | 1.824469 | 0.004610 | 0.004191 | 0.004376 | 3434 |
| hcsn | True | 5.122751 | 0.011945 | 0.009844 | 0.019628 | 10570 |
| lif_snn | True | 3.889546 | 0.013509 | 0.008972 | 0.008535 | 4049 |
| mamba1 | True | 2.280463 | 0.008620 | 0.008119 | 0.015696 | 75492 |
| transformer | True | 3.198457 | 0.016590 | 0.006181 | 0.010731 | 62821 |
| two_gates | True | 1.887996 | 0.006700 | 0.005229 | 0.005124 | 3442 |

The external process interval includes interpreter startup and shutdown. Child phase times are nested and cannot be added to that total. Expected logits are retained by the parent; the child receives only model identity, checkpoint, bound stream snapshot and remaining inputs. Both the parent expected final-state digest and the child final-state digest are retained and compared.

## External execution accounting

The ledger contains 60 direct child attempts for 60 completed continuation cases, including 0 retained failed attempts. All-attempt child CPU is 460.727359 s; summed launch-to-reap wall is 462.255244 s. All continuation children ran serially after all training children exited.

POSIX wait4 direct-child CPU may include descendants that child reaped; do not add nested native or replay child CPU again. All attempts are retained; launch-to-reap wall includes startup/shutdown.
