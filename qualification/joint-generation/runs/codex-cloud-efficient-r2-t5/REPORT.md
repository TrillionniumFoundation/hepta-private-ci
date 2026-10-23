# Exact-output r2 training/validation: failed readiness

Source `10f1b8045ce8b864f21bcd7e49db59234d4f2bdf`; freeze `independent/frozen-r2-output-vectorized.json`; execution `4b8f02665c14112f8bef28eb35400d1f89373c8d`.

Actual command exited **2**, all complete build caps held, and the independent test stayed unconstructed/unopened. r1 remains sealed.

Validation mean contrasts (not held-out estimates or confidence intervals):

- `additive-anchor:joint_success`: +0.015352750151
- `additive-anchor:task_utility`: +0.014986449012
- `ndu-additive:joint_success`: +0.013232917271
- `ndu-additive:task_utility`: +0.012583652991
- `ndu_control-ndu:cpu_net_utility`: -0.002427032664
- `ndu_control-random:joint_success`: -0.000927330141
- `ndu_control-random:task_utility`: -0.000780176007

Maximum greedy drop: 0.006944444444.

| System | CPU seconds | Operator units | Updates by seed 11/23/47 | Residual rounds |
|---|---:|---:|---|---:|
| supervised | 8.234296685 | 11969183073 | 396 / 396 / 396 | 0 |
| anchor | 8.289063170 | 11969183073 | 396 / 396 / 396 | 0 |
| additive | 8.421352453 | 11997029145 | 356 / 391 / 391 | 4 |
| ndu | 8.853006965 | 11998238105 | 388 / 431 / 431 | 45 |
| ndu_control | 9.375876280 | 11979848714 | 389 / 450 / 450 | 84 |

NC full-content utility minus NDU/full: -0.001265116703; control routing relative to its own full view: -0.000780176007 (random full probability was 1 for all seeds). Remaining net difference includes real runtime, preparation and build CPU.

Output-path savings really funded 84 residual NC rounds versus 45 NDU rounds, so the remaining content gap is not explained by fewer final updates alone. Extra stochastic optimization steps do not guarantee a better decoded raw utility. All 15 selected encoders and both content heads changed, while adaptation decoder weights remained fixed.

The core claim (content control and NDU training improve generation under complete budgets) and the stronger adaptive-continuation claim must remain separate. Positive core validation means are not an independent held-out proof. The stronger frozen dynamic gates remain failed and have not been deleted or relabeled as an overall pass.

The nested `random_validation.cpu_net_utility` is a runtime-only diagnostic (build_cpu_ns=0); compare raw gates or equally attributed runtime/build terms. Main selected-system J_H includes complete build. Formal evaluator supplies identical NC build to both laws.

The actual calibrated v2 external-RGB smoke generated `blue cross right`, a real PNG, a restorable checkpoint and exact output replay after reload. No serving labels/observer were used; selection_ready=false.

Next: bounded TRAIN-only physical-source grouped decision-regret diagnostics before choosing a minimal controller repair. Do not assume more model complexity is necessary, retune validation thresholds, suppress large losses or open the formal fold. AV generation, long interactions and production remain unrun.
