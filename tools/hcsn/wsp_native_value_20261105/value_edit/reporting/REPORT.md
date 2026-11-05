# Frozen single-run results

Pure-weight efficacy qualified: **False**.

These are conditional results for five existing fits of the finite deadline-six sign task. There are no new base-training fits and no live Trader or full NDU economic claim.

## TEST utility

| Arm | IID | OOD | IID delta vs C | OOD delta vs C |
| --- | ---: | ---: | ---: | ---: |
| C | 0.2265222410 | 0.1275367079 | +0.0000000000 | +0.0000000000 |
| E | 0.2490640804 | 0.1253259548 | +0.0225418394 | -0.0022107532 |
| G | 0.2491925890 | 0.1253259548 | +0.0226703481 | -0.0022107532 |
| EU | 0.2265222410 | 0.1275367079 | +0.0000000000 | +0.0000000000 |
| EA | 0.2392931169 | 0.1282890385 | +0.0127708760 | +0.0007523306 |
| M | 0.1992900979 | 0.0883703817 | -0.0272321431 | -0.0391663262 |
| R | 0.1551832559 | 0.0801422551 | -0.0713389851 | -0.0473944528 |
| P | 0.2280377088 | 0.1419144077 | +0.0015154678 | +0.0143776998 |
| J | 0.3654721430 | 0.3128199855 | +0.1389499020 | +0.1852832776 |
| E_gated | 0.2313598924 | 0.1250529161 | +0.0048376514 | -0.0024837919 |
| G_gated | 0.2313598924 | 0.1250529161 | +0.0048376514 | -0.0024837919 |

## Primary conditional comparisons

| Comparison | Delta | Bonferroni-two 95% conditional interval | Lower bound > .005 |
| --- | ---: | --- | --- |
| E_gated_iid | +0.0048376514 | [-0.0120719041, 0.0217472070] | False |
| E_gated_ood | -0.0024837919 | [-0.0111656527, 0.0061980689] | False |

## Frozen alpha selection and validation

| Fit | E alpha | G alpha | EU alpha | EA alpha | E accepted | G accepted |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 11 | 0.75 | 0.75 | 0.0 | 0.75 | False | False |
| 23 | 0.75 | 0.75 | 0.0 | 0.25 | True | True |
| 37 | 0.25 | 0.25 | 0.0 | 0.25 | False | False |
| 53 | 0.75 | 0.75 | 0.0 | 0.75 | False | False |
| 71 | 0.75 | 0.75 | 0.0 | 0.75 | False | False |

## Why a validation acceptance is not a task-value guarantee

The acceptance rule is a threshold on finite validation means, not a confidence bound or a calibrated false-positive-rate guarantee. Every world is evaluated by full expectation; the remaining validation/TEST variability is over public-world samples. The test outcome does not justify changing the gate or retrospectively selecting another raw arm.

For accepted E fit 23, OOD validation gain was +0.0389743957; OOD TEST gain was -0.0124189593. The accepted model's TEST expected reward changed by -0.0139975802, while fee savings contributed +0.0015786209. The reward loss exceeds the fee saving.

The 16 OOD validation worlds contained 8 positive / 6 zero / 2 negative paired differences; the 32 OOD TEST worlds contained 8 positive / 18 zero / 6 negative differences. These counts describe scenario heterogeneity, not additional independently trained fits, and do not estimate a general gate false-positive rate.


## Measured process cost

| Phase | Child CPU seconds | Wall seconds | Peak RSS bytes |
| --- | ---: | ---: | ---: |
| preparation | 2.003757 | 2.033455 | 43089920 |
| semantic_checks | 0.734467 | 0.736338 | 28495872 |
| protocol_freeze | 0.174421 | 0.177618 | 25079808 |
| execution_r1 | 535.948697 | 537.594690 | 260947968 |
| independent_verification | 332.887897 | 369.168702 | 111558656 |
| posthoc/freeze_receipt | 0.165077 | 0.170285 | 23023616 |
| posthoc/execution_r1 | 3.130104 | 3.270629 | 30871552 |

Measured child CPU sum before this reporting process: 875.044420 seconds. Nested component costs must not be added again.

E/G endpoint solver CPU: 0.216800 / 4.370660 seconds. The matched candidate-construction figures including their common preparation are 167.378052 / 173.693328 seconds, ratio 1.037731. These are restricted construction figures, not full-training speedup.

Cold own-law Bellman preparation for the 480 held-out worlds cost 101.134916 CPU seconds, in addition to J policy lookup/initialization. P/J gains are program gains, never pure-weight gains.

Full historical/editor/agent/controller-startup/energy/economic costs remain unknown where unmeasured. Complete worker and verification receipts remain the authoritative measured process totals.

## Independent execution

All 100 stored path heads and all schedule/selection/gate/rollback/statistical records passed. TRAIN replay: 6400 world/path pairs, maximum absolute utility difference 0.0. Held-out replay: 4960 world/arm pairs, maximum absolute eight-metric difference 0.0, node difference 0.

The verifier uses the original recursive TRAIN executor and a separate held-out literal-head evaluator. It shares the original fixed simulator/core/law definitions and does not count as new statistical evidence.

## Separate post-hoc diagnosis

A separately frozen, approved read-only diagnostic covers all 16 validation and 32 TEST OOD worlds for accepted E fit23. It changes no weights, sample, seed, gate or primary inference. The complete source, input identities, 48 per-world records and process receipt are under `posthoc/`.

| Existing split | Own-law E minus C | Evaluator E minus C | Evaluator contribution from own-target violations | Other contribution |
| --- | ---: | ---: | ---: | ---: |
| test | -0.0139610269 | -0.0124189593 | -0.0463161318 | +0.0338971724 |
| validation | +0.0434261663 | +0.0389743957 | -0.0687144911 | +0.1076888868 |

The TEST loss also occurs under the checkpoint's own law. On these exposed worlds, the failure therefore cannot be explained solely by the difference between the checkpoint law and the evaluator law. The edited head chooses some actions whose own-law one-step advantage over C is negative. This identifies head/target inconsistency on these states; it does not prove a general capacity impossibility or a universal law-error absence.

For each law the diagnostic verifies the unnormalized E-occupancy performance-difference identity, and separately verifies the first-common-prefix partition using complete edited-policy suffix values. Local one-step follow-C counterfactuals are never substituted for those complete suffix values. Coordinate-wise delta-weight times hidden contributions are fixed-representation linear accounting, not independent causal interventions on individual weights.

Maximum stored utility discrepancy: 0.0; own/evaluator performance-difference residuals: 1.1102230246251565e-16 / 1.1102230246251565e-16; first-prefix partition residual: 1.1102230246251565e-16; linear-head margin residual: 2.42861286636753e-16.

The predeclared post-hoc illustration rule selects TEST index 6, with E-minus-C -0.4217498820. Full records remain available, and this worst example is not new confirmation.
