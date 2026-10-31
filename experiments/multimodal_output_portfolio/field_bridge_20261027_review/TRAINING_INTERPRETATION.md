# Independent interpretation of the frozen training evidence

**Scope:** training and the two held-out optimizer trajectories only. This note does not read incomplete or completed test/retention output rows and does not refit a controller. It is an interpretation of the already frozen run, not a change to its acceptance criteria.

- Scientific source commit: `4a8f284dbf577d0cf4542c1e2c20f7af3b0152a0`.
- Pretest training-artifact commit: `dec5978ad69f41a34bda631289d3cec3d0bdb5fd`.
- Evidence: `bridge_run/training/{17,29,43}/EXPLORATION.json` and `{ordinary,field,generic,richer}.json`.

## Main finding

The parameter-field controller actually intervenes in local adapter training, and its saved optimizer/parameter identities make the intervention inspectable. The available training evidence does **not** demonstrate superior reward prediction, sufficient reduced state, or a useful causal advantage of the proposed field. In particular, very small absolute reward errors for seeds 17 and 29 arise in a response whose entire held-out variation is of the same tiny order. Constant predictors are more accurate. Seed 43 exhibits a much larger field prediction error after a rare training-panel discontinuity that does not occur on its two held-out trajectories.

## 1. Prediction error must be compared with response variation

Each learned controller fits 216 rows from six 36-step optimizer trajectories. Its audit has 72 rows from two additional trajectories. These are two trajectory units, not 72 independent experiments. The normalization and predictor fit use the six training trajectories only.

The training-mean baseline predicts the mean hard value over the 216 fitting rows. The frozen-value baseline predicts the recorded endpoint of the all-no-update trajectory, which is the unchanged original-model value. Neither baseline uses held-out labels to fit its prediction. Reported errors below are recomputed directly from the stored values; the learned field error is the frozen controller audit.

| Seed | Held-out hard-value SD | Held-out range | Field RMSE | Training-mean RMSE | Frozen-value RMSE | Field / training-mean RMSE |
|---|---:|---:|---:|---:|---:|---:|
| 17 | 6.69011e-08 | 2.87709e-07 | 1.90064e-07 | 1.19982e-07 | 1.09605e-07 | 1.584 |
| 29 | 7.83641e-08 | 3.69188e-07 | 1.51736e-07 | 8.68273e-08 | 8.33765e-08 | 1.748 |
| 43 | 1.98212e-07 | 7.46408e-07 | 0.000742512 | 2.87452e-05 | 2.28418e-07 | 25.831 |

For seeds 17 and 29, the field RMSE is approximately 1.58 and 1.75 times the training-mean baseline error. Its apparent seven-decimal absolute accuracy therefore does not establish useful predictive skill. For seed 43 the field RMSE is approximately 25.83 times the training-mean baseline and 3,251 times the frozen-value baseline. The latter comparison shows how much larger the model error is than the almost unchanged audit response.

Seed 43 has a training hard-value range of about 0.00624987: fixed high-learning-rate trajectory 3 ends at 0.8944423087, while the no-update value is 0.9006901864. The two held-out trajectories instead occupy a range of only about 7.46e-7. This is evidence of an adverse nonlinear/quantized response encountered in fitting and a poor transferred predictor on this audit; the saved aggregate hard values do not by themselves identify which semantic or pixel component caused the discontinuity. No such component-level causal explanation is asserted here.

| Seed | Field reward RMSE | Generic-summary reward RMSE | Richer-state reward RMSE | Field next-state RMSE |
|---|---:|---:|---:|---:|
| 17 | 1.90064e-07 | 1.72442e-07 | 2.74043e-07 | 0.410254 |
| 29 | 1.51736e-07 | 1.77173e-07 | 3.40676e-07 | 0.533294 |
| 43 | 0.000742512 | 0.000791197 | 0.00091034 | 0.244709 |

The generic and richer models do not consistently solve the reward-prediction problem either. Field next-state error is in its training-standardized six-dimensional coordinates; generic and richer models use different projected coordinate spaces, so their raw next-state RMSEs should not be ranked as if they measured the same Euclidean error. These are regression diagnostics, not the R45 reachable-error or Bellman-regret certificates.

## 2. The training intervention is real but modest in effective operator space

All twelve final adaptations train 3,424 parameters in six low-rank tensors; all six tensors change for every seed and mode. The original generator parameters remain frozen. Within each seed, ordinary, field, generic, and richer variants share the same initial adapter identity and final minibatch/noise schedule digest. Their final adapter identities differ. This establishes actual parameter learning and different controlled trajectories. It does not establish whole-generator joint learning.

Action indices 0, 1, 2, 3 mean learning-rate multipliers 0, 0.25, 1, 2, corresponding to step sizes 0, 0.0125, 0.05, 0.10. Action 0 holds both parameters and momentum, although its registered gradient/probe computation is still performed.

| Seed | Ordinary fixed action | Field counts [0,1,2,3] | Field choices differing from ordinary | Generic counts [0,1,2,3] | Richer counts [0,1,2,3] |
|---|---:|---|---:|---|---|
| 17 | 3 | [14, 0, 13, 9] | 27/36 | [1, 0, 6, 29] | [31, 4, 0, 1] |
| 29 | 2 | [18, 0, 15, 3] | 21/36 | [1, 0, 21, 14] | [17, 0, 3, 16] |
| 43 | 2 | [26, 5, 0, 5] | 36/36 | [34, 1, 0, 1] | [28, 7, 0, 1] |

The field controller takes 58 no-update actions across 108 decision steps, and its choices differ from ordinary training on 84/108 steps. It is not a recorded field that never changes the optimizer action.

Effective displacement is the RMS, across the three adapted modules, of `||up @ down||_F / ||base.weight||_F`. It is not the norm of all original model parameters. The effective product avoids treating a pure low-rank factor rescaling as an operator change; the momentum statistic remains a declared training-coordinate quantity.

| Seed | Ordinary effective displacement | Field effective displacement | Field / ordinary | Field image-module displacement | Field text-module RMS displacement |
|---|---:|---:|---:|---:|---:|
| 17 | 1.26576% | 0.47468% | 0.37502 | 0.04500% | 0.58049% |
| 29 | 0.58301% | 0.22670% | 0.38884 | 0.03106% | 0.27678% |
| 43 | 1.33972% | 0.38232% | 0.28537 | 0.02835% | 0.46781% |

Field adaptation therefore produces approximately 61–71% less effective operator displacement than ordinary training in this run. Smaller movement is a manipulation-strength observation, not automatically an efficiency or quality advantage. The digit-head loss is unchanged because these local adapters do not alter that frozen head or the upstream latent representation.

| Seed | Ordinary endpoint minus frozen training value | Field endpoint minus frozen training value | Field minus ordinary endpoint |
|---|---:|---:|---:|
| 17 | -1.39605e-07 | -2.81539e-07 | -1.41934e-07 |
| 29 | -4.79387e-07 | -2.11527e-08 | +4.58234e-07 |
| 43 | +1.09954e-06 | +3.29083e-07 | -7.7046e-07 |

These are values on the repeatedly observed training-value panel, not test gains. Their mixed signs and tiny scale do not support a uniform training-value improvement. Teacher-forced probe losses can move more visibly while the actual hard-output panel value remains nearly constant; that distinction was a reason to keep the executed hard objective separate from the differentiable training proxy.

## 3. Cost accounting

Every final adaptation performs 36 gradient computations on 1,728 examples, 1,776 probe examples, and 1,152 hard-value examples. A field no-update action does not avoid that registered computation. The shared exploratory bank has 288 optimizer decision steps per model seed. Its measured wall cost must be reported as shared study/search overhead rather than charged anew to each arm or ignored.

| Seed | Shared bank seconds | Ordinary final-adaptation seconds | Field final-adaptation seconds | Field predictor fit/audit milliseconds |
|---|---:|---:|---:|---:|
| 17 | 12.8430 | 1.3618 | 1.5810 | 7.5307 |
| 29 | 11.4824 | 1.6429 | 1.6298 | 7.4168 |
| 43 | 11.8907 | 1.3100 | 1.3612 | 5.7177 |

Total shared bank time is 36.2161 seconds. Final ordinary adaptations total 4.3147 seconds and final field adaptations 4.5721 seconds, a descriptive ratio of 1.0596. Controller fitting is included in the latter. These are single-host measurements in a fixed experimental process, not a causal or repeated performance benchmark. No wall-time saving should be inferred from the smaller number of nonzero parameter updates.

## 4. What this establishes about the paper/Hepta relationship

1. **Operational bridge:** a frozen observable map of a real optimizer state affects real training interventions, and resulting saved adapters are available for independent selected-action deployment. This is a concrete empirical instance of the paper's optimizer/field/control separation.
2. **Objective boundary:** the differentiable supervised/anchor objective proposes changes; the controller's target is a fixed deployable policy's hard-output value. The source and smoke test make their relationship explicit without calling the proxy an exact hard-reward gradient.
3. **Reduction and coefficient uncertainty remain open:** the controller audits show substantial relative predictive error, especially for seed 43. They do not establish a Markov sufficient statistic, a uniform error budget, or optimality.
4. **Local actuation boundary:** only 3,424 adapter parameters change. This does not demonstrate full encoder/transition/backbone joint training, unrestricted action sufficiency, or LLM-scale effectiveness.
5. **Inference is a separate experimental factor:** training evidence cannot establish native-state runtime value. That requires the frozen test contrasts, especially E versus F for the matched-information history comparator, and E versus G for field training under native control.
6. **No scalar FBSDE identification:** common martingale alignment, specific coefficient identities, endogenous NDU preference efficacy, and the paper's nonlinear HJB hypotheses are not tested by these regressions or optimizer traces.

The appropriate pretest interpretation is therefore: **the empirical bridge is implemented and instrumented, but the training audit does not yet show a predictive or value advantage of the proposed field.** Test/retention conclusions must come from the unchanged registered analysis after the entire evaluation is complete.
