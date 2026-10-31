# Independent review of the completed bridge experiment

## Conclusion

The completed experiment provides an auditable operational bridge from reduced optimizer observables to local adaptation and from actual Hepta state to selected multimodal actions. It does **not** establish a benefit of the proposed field controller or of the native state over the matched-information history controller. None of the six registered primary gains is accepted. This is a negative decision under the registered development criteria, not proof that all methods are equivalent, a general falsification of parameter-field theory, or a finding of confirmed retention damage.

Scientific source commit: `4a8f284dbf577d0cf4542c1e2c20f7af3b0152a0`. Pretest training freeze: `dec5978ad69f41a34bda631289d3cec3d0bdb5fd`. This review changes neither source nor thresholds.

## Independent numerical verification

I separately loaded all 20,064 completed rows, checked the complete 11-arm/three-model grid and 224 source pairs (448 unique source-image identities), and recomputed all primary and retention means, per-model effects, paired-bootstrap intervals, global certainty equivalents and the registered interaction. I did not call the study's analyzer to do this calculation. Maximum discrepancy from RESULT was 1.91e-16 for intervals and 2.22e-16 for certainty equivalents. The receipt is `RESULTS_REVIEW_CHECKS.json`; the independent arithmetic is `review_complete_results.py`.

Media and native execution are covered by the separate completed `INDEPENDENT_AUDIT.json`: 20,064 rows, 120,384 media files, 20,064 decisions and 35,328 replayed native ticks. All recorded public features and all score components reproduce with zero discrepancy. This establishes internal executable consistency conditional on recorded inputs and pinned assets; it is not external execution attestation, fresh-population validation, or production ownership.

## Six primary contrasts

Effects below are candidate minus control on mean actual hard-output utility minus the declared refinement tariff. Each interval is the registered paired-source bootstrap with six-comparison Bonferroni adjustment **per observer** (nominal individual confidence 99.1667%).

| Contrast | Reward effect | Reward interval | Audit effect | Audit interval |
|---|---:|---|---:|---|
| B − A | 0.001759 | [-0.001128, 0.004623] | 0.001368 | [-0.001714, 0.004212] |
| C − B | -0.000717 | [-0.003321, 0.003059] | -0.000261 | [-0.002952, 0.003906] |
| D − A | 0.002760 | [-0.002459, 0.008005] | 0.000286 | [-0.005308, 0.005308] |
| E − C | 0.000933 | [-0.004307, 0.006540] | -0.001769 | [-0.007832, 0.003629] |
| E − G | -0.001845 | [-0.006344, 0.002416] | -0.002464 | [-0.006716, 0.001408] |
| E − F | -0.003328 | [-0.008319, 0.001431] | -0.000496 | [-0.006169, 0.005395] |

- **B−A:** ordinary adaptation does not establish a gain. Positive pooled effects coexist with a negative seed-29 effect for both observers.
- **C−B:** field adaptation has a negative pooled point estimate for both observers, mixed per-model directions and intervals containing zero. No training-policy superiority is demonstrated.
- **D−A:** native control on frozen models is positive in all three reward-scored models, but the adjusted interval spans zero and the audit observer has a negative seed-43 effect. Reward-only optimism is insufficient.
- **E−C:** adding native control to field-adapted models gives a small positive reward effect and a negative audit effect. Neither is conclusive.
- **E−G:** field adaptation under the same native-control architecture is negative in all three models under both observers. This is the clearest adverse directional finding, but both adjusted intervals include zero; the experiment does not establish a statistically resolved negative effect under its confirmatory criterion.
- **E−F:** field/native is worse in all three reward-scored models than field/history, with pooled reward difference −0.00332773. The primary adjusted interval still contains zero; the audit direction is mixed by model. There is no native-state value advantage or demonstrated equivalence.

All six fail their gain condition even before the retention condition is applied. This is stronger and more precise than saying merely that the global all-six flag is false.

## Retention and interaction require careful wording

The retention gate compares nine arms with A using the separately corrected nine-comparison family, with lower confidence endpoint at least −0.01 under **both** observers. B, C, G, J and K pass; D, E, F and H do not. Reset I is not in this family.

For E, the audit point difference is **+0.00046294**, with interval **[−0.01023178, +0.01139479]**. Its lower endpoint narrowly falls below the −0.01 margin. Thus retention noninferiority is not established. The data do not show a mean loss exceeding the margin. This distinction also matters for D, F and H. G's audit lower endpoint is −0.00945899, so its passing status should not be oversold as wide separation from E.

The predeclared descriptive interaction `(E−C)−(D−A)` is negative in every model for both observers. Reward: −0.00182712, nominal 95% interval [−0.00414235, +0.00029004]. Audit: −0.00205498, nominal 95% interval [−0.00426351, −0.00013093]. The latter is suggestive attenuation, but this was expressly descriptive, without the primary family's multiplicity-controlled interaction claim. It cannot be promoted after observing the result.

Global CE is also secondary and descriptive. E−F reward CE is −0.00872327 with nominal 95% interval [−0.01442234, −0.00331230]; audit CE is −0.00329652 with interval crossing zero. This does not change the registered mean-return decision. Likewise C−B's positive pooled-CE point estimate cannot replace its negative mean-return estimate.

## Native state is active; special value is unproven

Resetting E's native state while reusing its frozen readout changes 1,029/1,536 test actions (66.99%) and 261/288 retention actions (90.63%). Actual native state affects decisions. A frozen readout confronted with reset state also experiences a distribution shift, so this diagnostic is not an information-matched comparison or evidence of memory optimality. E−F is the more relevant comparison: the same two observations, same available actions, same 40-dimensional readout input and same 205 output coefficients, but different state processing.

E averages 1.630859 refinements versus F's 1.803385 and the fixed arms' 2.0. Its tariff advantage over F is +0.00034505, while its raw reward utility is lower by −0.00367278, leaving net difference −0.00332773. Fewer declared refinements therefore do not establish a favorable return/cost tradeoff on this run.

Native E's recorded mean decision wall time is 273.77 microseconds, of which the reported native-kernel metric averages 17.03 microseconds; F's decision time is 9.85 microseconds. The full native path includes bridge/serialization/state/readout work. These are batch-amortized measurements from one process/host, not independent latency samples or causal timing conclusions. Stop still performs the final output decode; it saves a continuation transition, not the entire output path.

## Field-controller training interpretation

The field actively changes optimizer decisions: its sequence differs from ordinary in 84/108 updates and holds the parameters on 58/108 steps. All six adapter factors change, with 3,424 trainable parameters total; the original backbone remains frozen. Field effective-operator displacement is about 29–39% of ordinary displacement across models, so the manipulation is real but more conservative. Equal gradient/probe schedules mean no-op decisions do not demonstrate compute savings.

Held-out field reward RMSE divided by the **training-mean constant** RMSE is **1.584, 1.748 and 25.831** for seeds 17, 29 and 43. Held-out reward standard deviations are only **6.69e-8, 7.84e-8 and 1.98e-7**. Small absolute error for the first two seeds is a consequence of an almost constant measured response, not evidence of strong prediction. The third seed's fit includes a rare high-LR training cliff absent from audit trajectories, and its field RMSE is 3,251 times the frozen-value baseline error. This is an identification/coefficient weakness in the implemented controller, not a successful closure audit.

The generic six-dimensional projection and richer 14-dimensional state do not fix the predictive problem. C's fixed-policy test point mean exceeds J/K here, but there is no registered primary contrast supporting feature-specific superiority, only one frozen generic projection, and different state dimension/parameter counts for the richer predictor. These supplements cannot prove that the named field is sufficient or uniquely useful.

Full training-only details, exact operator norms, action histograms and timings are in `TRAINING_INTERPRETATION.md`.

## What can be falsified, and what remains outside scope

1. The proposition that this exact frozen implementation passes the registered beneficial-bridge gate is rejected by its own six failed primary comparisons. A general statement that the method never helps is unsupported.
2. Strong native-state superiority on this matched-information comparator is unsupported. Actual state dependence is established, but state dependence and beneficial additional information are different properties.
3. Near-zero absolute field prediction error as evidence of predictive skill is contradicted by the constant-predictor audit. Reduction sufficiency is neither demonstrated nor formally disproved by this small audit.
4. The paper's scalar FBSDE identification, common-driver alignment, nonlinear HJB assumptions, large-model claims and endogenous preference learning are not tested. This run uses empirical quadratic-ridge two-step terminal-value MPC and fixed utility, not a Riccati/FBSDE solver.
5. The inference controller receives two self-generated output previews, not fresh external terminal feedback; its kernel is fixed, only the readout is fitted. No Agentd-owner integration or production activation follows.
6. The uncertainty conditions on three fixed historical models and this constructed MNIST task. There are 128 test source-pair units and 96 retention units, not 20,064 independent population observations.

## Development recommendation

Keep the current results and protocol unchanged. Before a new confirmatory run, add a **development-only response-sensitivity and predictive-skill gate**: demonstrate that allowable actions move the actual hard return above constant-baseline/numerical variation, evaluate prediction or action ranking against fixed/no-change baselines on entire held-out trajectories, and inspect effective operator movement alongside output changes. A failing gate should halt claims about field-guided optimization, not trigger post-hoc retuning on this test set.

A new development protocol may consider a wider but bounded local action range, longer adaptation, or a more informative value panel. These are hypotheses, not guaranteed fixes. Once chosen, preregister the next policy and acceptance rules and use new source identities/tasks. Retain ordinary/native and matched-information history controls; improve native integration or reduced-state design only when it delivers a benefit under the same actual-output objective and retention check. Increase native complexity only after beating the lightweight comparator on a fresh evaluation.
