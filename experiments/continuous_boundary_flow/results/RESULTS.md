# Continuous-boundary confirmation results

**The unchanged scientific auditor passed the explicit cost-roundoff-normalized input view. The original strict audit rejected the original ledger at its child-CPU nonnegativity check.** Exactly 153 negative `completed_child_cpu_seconds` tokens in the allowed [-1e-12, 0) second range became `0.0`; the maximum absolute correction was 1.7763568394002505E-15 seconds and their sum was 8.2822203956167681423E-14 seconds. Fresh byte-level validation verified that only those cost tokens and the manifest's cost digest changed. Primary/task records, model profiles, protocol, seeds, scientific source and historical costs are unchanged. The original rejection and both manifest identities are preserved; engineering remains bound to the original manifest.

Run `study-002`: **0/3 registered primary benefit gates passed**. There are 8 independent training seeds and 26,624 audited episodes across all arms.

## Pre-confirmation amendment

Before confirmation data existed, the common deadline input changed from per-episode remaining fraction to `remaining_windows/16`, so every arm could recover the absolute remaining duration with `dt`. The interrupted training-only `study-001` was retained. This report uses the new sealed run; it does not use the old run's training effects as evidence.

## Registered paired comparisons

Differences are in mean message-priced net utility, paired by independent seed. Intervals use the registered two-sided Bonferroni Student-t procedure: 95% simultaneous family coverage across three comparisons. A gate requires the lower interval endpoint to exceed 0.005 and no recorded stability failure in either arm.

| Comparison | Pair | Δ net | Simultaneous interval | Minimum effect | Stability | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| boundary | `value_margin` − `learned_margin` | -0.0720 | [-0.3701, 0.2261] | no | yes | NOT ESTABLISHED |
| dual | `value_dual` − `value_call` | 0.0485 | [-0.0313, 0.1282] | no | yes | NOT ESTABLISHED |
| flow | `value_dual` − `event_reset` | -0.0211 | [-0.1006, 0.0584] | no | yes | NOT ESTABLISHED |

## ID

Utilities and event counts are per episode. Stop is the percentage of episodes that stop. Brier/ECE pool non-stopped visited windows and are descriptive.

| Arm | Gross | Net | Failures | Repairs | Stop % | Brier | ECE | Risk windows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fixed_margin` | 4.3430 | 4.3411 | 0.094 | 2.031 | 0.6 | 0.0065 | 0.0011 | 12,271 |
| `learned_margin` | 4.3443 | 4.3424 | 0.119 | 1.928 | 2.1 | 0.0076 | 0.0012 | 12,255 |
| `value_margin` | 4.3471 | 4.3452 | 0.114 | 1.912 | 1.5 | 0.0079 | 0.0012 | 12,257 |
| `value_call` | 4.3647 | 4.3628 | 0.115 | 1.827 | 2.3 | 0.0076 | 0.0015 | 12,248 |
| `value_dual` | 4.3327 | 4.3308 | 0.118 | 1.877 | 3.6 | 0.0075 | 0.0022 | 12,219 |
| `generic_gate` | 4.3060 | 4.3041 | 0.129 | 1.921 | 3.3 | 0.0088 | 0.0013 | 12,229 |
| `native_sparse` | 4.2685 | 4.2666 | 0.169 | 1.800 | 1.3 | 0.0114 | 0.0014 | 12,269 |
| `event_reset` | 4.3562 | 4.3543 | 0.107 | 1.890 | 2.9 | 0.0073 | 0.0019 | 12,241 |
| `dense_recurrent` | 4.3156 | 4.3137 | 0.131 | 1.865 | 4.2 | 0.0089 | 0.0016 | 12,201 |
| `dp` | 4.5251 | 4.5251 | 0.063 | 1.635 | 0.0 | 0.0051 | 0.0004 | 12,288 |
| `always_keep` | 2.5266 | 2.5266 | 1.167 | 0.000 | 0.0 | 0.0521 | 0.0052 | 12,288 |
| `always_repair` | 1.6504 | 1.6504 | 0.007 | 12.000 | 0.0 | 0.0006 | 0.0003 | 12,288 |
| `always_stop` | 0.0000 | 0.0000 | 0.000 | 0.000 | 100.0 | — | — | 0 |

## OOD

Utilities and event counts are per episode. Stop is the percentage of episodes that stop. Brier/ECE pool non-stopped visited windows and are descriptive.

| Arm | Gross | Net | Failures | Repairs | Stop % | Brier | ECE | Risk windows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fixed_margin` | 1.7186 | 1.7170 | 0.361 | 2.527 | 22.2 | 0.0252 | 0.0050 | 10,394 |
| `learned_margin` | 1.6202 | 1.6186 | 0.377 | 3.051 | 21.7 | 0.0265 | 0.0032 | 10,432 |
| `value_margin` | 1.4735 | 1.4718 | 0.390 | 2.875 | 22.4 | 0.0251 | 0.0039 | 10,377 |
| `value_call` | 1.6367 | 1.6350 | 0.430 | 2.259 | 25.6 | 0.0277 | 0.0033 | 10,269 |
| `value_dual` | 1.7657 | 1.7641 | 0.400 | 2.352 | 24.4 | 0.0268 | 0.0034 | 10,297 |
| `generic_gate` | 1.6947 | 1.6931 | 0.467 | 2.062 | 25.4 | 0.0290 | 0.0022 | 10,308 |
| `native_sparse` | 1.9235 | 1.9219 | 0.391 | 2.158 | 23.4 | 0.0265 | 0.0036 | 10,361 |
| `event_reset` | 1.7843 | 1.7827 | 0.418 | 2.286 | 21.6 | 0.0278 | 0.0035 | 10,428 |
| `dense_recurrent` | 1.8680 | 1.8664 | 0.362 | 2.058 | 28.0 | 0.0254 | 0.0017 | 9,993 |
| `dp` | 2.8189 | 2.8189 | 0.199 | 1.630 | 19.6 | 0.0165 | 0.0010 | 10,773 |
| `always_keep` | 0.1838 | 0.1838 | 1.493 | 0.000 | 0.0 | 0.0664 | 0.0069 | 11,648 |
| `always_repair` | -1.4110 | -1.4110 | 0.195 | 11.375 | 0.0 | 0.0159 | 0.0017 | 11,648 |
| `always_stop` | 0.0000 | 0.0000 | 0.000 | 0.000 | 100.0 | — | — | 0 |

## Combined, equal ID/OOD weights

Utilities and event counts are per episode. Stop is the percentage of episodes that stop. Brier/ECE pool non-stopped visited windows and are descriptive.

| Arm | Gross | Net | Failures | Repairs | Stop % | Brier | ECE | Risk windows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fixed_margin` | 3.0308 | 3.0290 | 0.228 | 2.279 | 11.4 | 0.0151 | 0.0024 | 22,665 |
| `learned_margin` | 2.9823 | 2.9805 | 0.248 | 2.489 | 11.9 | 0.0163 | 0.0017 | 22,687 |
| `value_margin` | 2.9103 | 2.9085 | 0.252 | 2.394 | 11.9 | 0.0158 | 0.0022 | 22,634 |
| `value_call` | 3.0007 | 2.9989 | 0.272 | 2.043 | 14.0 | 0.0168 | 0.0021 | 22,517 |
| `value_dual` | 3.0492 | 3.0474 | 0.259 | 2.114 | 14.0 | 0.0164 | 0.0024 | 22,516 |
| `generic_gate` | 3.0004 | 2.9986 | 0.298 | 1.991 | 14.4 | 0.0180 | 0.0016 | 22,537 |
| `native_sparse` | 3.0960 | 3.0942 | 0.280 | 1.979 | 12.4 | 0.0183 | 0.0022 | 22,630 |
| `event_reset` | 3.0703 | 3.0685 | 0.263 | 2.088 | 12.3 | 0.0167 | 0.0025 | 22,669 |
| `dense_recurrent` | 3.0918 | 3.0901 | 0.247 | 1.961 | 16.1 | 0.0163 | 0.0012 | 22,194 |
| `dp` | 3.6720 | 3.6720 | 0.131 | 1.632 | 9.8 | 0.0104 | 0.0003 | 23,061 |
| `always_keep` | 1.3552 | 1.3552 | 1.330 | 0.000 | 0.0 | 0.0591 | 0.0057 | 23,936 |
| `always_repair` | 0.1197 | 0.1197 | 0.101 | 11.688 | 0.0 | 0.0081 | 0.0010 | 23,936 |
| `always_stop` | 0.0000 | 0.0000 | 0.000 | 0.000 | 100.0 | — | — | 0 |

## Measured computation and communication

Logged scientific phases total **551.94 CPU seconds** and **569.47 summed wall seconds**. They executed 1,861,776 native kernel calls and 866,448 NDU calls; full process JSON wire traffic was 1,675,421,482 bytes (454,053,006 request + 1,221,368,476 response). Wall sums are logged phase windows, not an uninstrumented end-to-end elapsed clock; CPU is not converted to energy.

| Actual phase | CPU s | Wall s | Kernel calls | NDU calls | Wire bytes |
| --- | --- | --- | --- | --- | --- |
| evaluation | 95.93 | 98.92 | 205,470 | 205,470 | 235,598,380 |
| serialization | 19.25 | 19.34 | 0 | 0 | 0 |
| solver_setup_confirmation | 3.20 | 3.21 | 0 | 0 | 0 |
| solver_setup_training | 9.54 | 10.70 | 0 | 0 | 0 |
| training_and_development | 424.02 | 437.30 | 1,656,306 | 660,978 | 1,439,823,102 |

The 128 confirmation contexts used 3.042 CPU seconds for model construction and 0.144 for DP. These are included subtimers of the shared setup row, never extra additions to the actual total. The following per-arm planning column is an alternative standalone attribution: value arms and DP receive one model build plus one solve per context; fixed/direct policies receive no inference DP charge.

| Arm | Train/dev CPU s | Rollout CPU s | Standalone setup s | Rollout + setup s | Eval wire bytes |
| --- | --- | --- | --- | --- | --- |
| `fixed_margin` | 43.79 | 9.76 | 0.000 | 9.76 | 25,994,007 |
| `learned_margin` | 37.17 | 9.38 | 0.000 | 9.38 | 26,023,656 |
| `value_margin` | 36.27 | 8.42 | 3.185 | 11.60 | 25,967,698 |
| `value_call` | 42.64 | 9.56 | 3.185 | 12.75 | 26,026,428 |
| `value_dual` | 51.81 | 8.67 | 3.185 | 11.86 | 26,283,155 |
| `generic_gate` | 55.96 | 8.93 | 3.185 | 12.11 | 26,464,820 |
| `native_sparse` | 52.21 | 9.23 | 3.185 | 12.41 | 26,343,386 |
| `event_reset` | 53.48 | 8.38 | 3.185 | 11.57 | 26,351,878 |
| `dense_recurrent` | 50.70 | 8.04 | 3.185 | 11.22 | 26,143,352 |
| `dp` | 0.00 | 2.46 | 3.185 | 5.64 | 0 |
| `always_keep` | 0.00 | 11.40 | 0.000 | 11.40 | 0 |
| `always_repair` | 0.00 | 1.61 | 0.000 | 1.61 | 0 |
| `always_stop` | 0.00 | 0.08 | 0.000 | 0.08 | 0 |

Rollout costs include the environment sampler and adapter. Shared environment/model overhead must not be added again. Standalone columns must not be summed across arms or into measured totals. The net-utility price applies only to 160-byte numerical feature payloads at the registered rate, not JSON framing, CPU or power.

## Parameter and comparison scope

Each neural arm fits 42 wait/repair-head scalars; stop is literal zero. `learned_margin` adds 20 fitted boundary coefficients (62 trained scalars total). The common encoder has 420 frozen coefficients. `generic_gate` and `dense_recurrent` add 42 and 78 frozen seeded mixing coefficients respectively. These controls are fixed reservoirs plus learned readouts; the results do not establish superiority over fully trained GRUs or end-to-end BPTT.

Risk uses the same analytic conditional first-hit formula on each policy's visited states. Brier/ECE differences are not risk-learning gains; zero-exposure STOP windows are excluded, not scored as perfect predictions.

## Durable owner study

Engineering parity passed for 96 reused episodes; 96 cold resumes, 96 episodes with subsequent execution, 0 terminal-only resumes, and 10 post-STOP rejection checks. It adds zero independent scientific samples and 8.65 separately measured CPU seconds. Native logical ticks are 10 ms; physical task windows use their separate `dt`.

## Interrupted preconfirmation work: separately recorded lower bound

Retained `study-001` contains 32 completed cost receipts: 129.34 CPU seconds and 130.71 logged wall seconds. This is a lower bound because the interrupted arm's unfinished cost window has no complete receipt. These costs are excluded from the valid study's totals. Valid science + engineering + known abandoned receipts record at least 689.93 CPU seconds and 711.70 summed wall-window seconds. This excludes unlogged R&D, compilation, audit and the unfinished window; it is not complete total elapsed time. Only old cost receipts were read, never old development returns or selection results.

## Evidence

The JSON summary preserves split and seed metrics, all primary intervals and gates, parameter budgets, cost attribution, source hashes, and the amendment record. The audit is bound to the trusted manifest and raw records; it is not a cryptographic signature against wholesale replacement of the bundle.
