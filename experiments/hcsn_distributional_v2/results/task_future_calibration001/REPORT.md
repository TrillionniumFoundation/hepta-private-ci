# Stored first-FIRE future value: post-panel calibration

This separate analysis reads only already sealed per-stream records. It does not refit a teacher, rerun a neural model, solve another Bellman table, select a policy, or change any original result. The larger policy outcomes were already known when this analysis was specified.

The forecast is the value assigned at the first FIRE to tasks after reset/refractory. The outcome is that same policy's subsequent actual classification correctness minus every subsequent READ charge. The first task reward and first task reads are excluded from both sides. The registered discount is one, so no additional temporal discount is applied here.

Positive bias means overprediction: forecast minus actual. For each source stream, predictions and outcomes are first averaged over the three registered prices. Bias and the principal MAE then use this stream-level macro error. A second MAE averages absolute error before price averaging, exposing cancellation across prices. The two definitions are separately named.

| Panel | Streams | Mean forecast | Actual later net reward | Bias | Nominal 95% bias interval | Macro-error MAE | Nominal 95% MAE interval | Pricewise MAE average |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |
| v1_cached128 | 128 | 0.423024 | 0.373510 | 0.049514 | [-0.024212, 0.120927] | 0.336804 | [0.292988, 0.382332] | 0.405477 |
| v1_native16 | 16 | 0.425930 | 0.659875 | -0.233945 | [-0.446183, -0.031731] | 0.346480 | [0.188794, 0.520527] | 0.448570 |
| v2_engineering2 | 2 | 0.475480 | -0.120833 | 0.596314 | Not estimated | 0.596314 | Not estimated | 0.596314 |

## Per-price descriptions

| Panel | Price | Forecast | Actual later net reward | Bias | MAE | Mean first FIRE clock |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| v1_cached128 | 0.001 | 0.586520 | 0.497211 | 0.089310 | 0.455651 | 12.211 |
| v1_cached128 | 0.005 | 0.517474 | 0.460195 | 0.057279 | 0.432685 | 8.570 |
| v1_cached128 | 0.02 | 0.165077 | 0.163125 | 0.001952 | 0.328094 | 1.000 |
| v1_native16 | 0.001 | 0.550334 | 0.788375 | -0.238041 | 0.494000 | 14.188 |
| v1_native16 | 0.005 | 0.562378 | 0.856250 | -0.293872 | 0.425442 | 5.250 |
| v1_native16 | 0.02 | 0.165077 | 0.335000 | -0.169923 | 0.426269 | 1.000 |
| v2_engineering2 | 0.001 | 0.617937 | -0.027500 | 0.645437 | 0.645437 | 16.000 |
| v2_engineering2 | 0.005 | 0.525321 | -0.135000 | 0.660321 | 0.660321 | 16.000 |
| v2_engineering2 | 0.02 | 0.283183 | -0.200000 | 0.483183 | 0.483183 | 2.500 |

## Interpretation and limits

A value formula can correctly include post-reset future tasks while its fitted probabilities, transition model or sufficient-state assumption are wrong. This audit checks marginal forecast errors under the realized policy, not the algebraic inclusion of the future term. The four-bin neural observation state discards hidden state, predicted class and much of the history. TRAIN-fitted Bellman predictions must not be treated as an exact neural belief-state oracle.

A nonzero outcome-level MAE alone is not proof of miscalibration: random classification rewards retain irreducible dispersion even under a correct conditional expectation. The signed mean discrepancy and its descriptive interval are the relevant marginal calibration diagnostic here. An interval containing zero also does not establish conditional calibration or the Markov assumption.

The bootstrap uses 19,999 whole-stream resamples after the three-price macro, with no independent resampling of prices or individual tasks. Intervals are nominal, descriptive, post-panel and unadjusted for multiple descriptions. Source queues are drawn without replacement from a finite data cohort. The native16 panel is exactly a subset of cached128; their matching pairs are audited but are not independent replications and must not be pooled.

The v2 engineering panel uses only two three-image streams from six reused validation images. It receives no confidence interval or population significance claim. Its forecast comes from its own 64-TRAIN-image observation model and differs from the old frozen-v1 planner.

PAIRED_ROWS.json and the *_pairs.npz files retain each original forecast/outcome pair, first-FIRE time and image source identity. Bootstrap sample statistics, registration hashes and complete analysis-process costs are retained. No calibration adjustment or policy reselection is performed.
