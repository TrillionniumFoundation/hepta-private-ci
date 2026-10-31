# Mechanism follow-up: split forecasts, fresh worlds, full-process costs

**63/63 formal workers succeeded.** The main D−B utility contrast remains inconclusive. Current-only and hypothetical-READ forecast interventions now locate distinct causes of decision changes. D used 37.3761% less complete-worker CPU than B in this controlled assay, with no preregistered quality-noninferiority claim.

Protocol SHA-256: `fd463d4055f79d064f62f4bdfa0586b1e39f895b31c1ce6303c093d854d4ae41`. Sources and seeds were frozen before three new ordinary fits and 768 newly generated worlds. Each condition has three independent fitted groups ×128 paired episodes. Four mandatory outputs and at most three READs per episode; utility is accuracy minus 0.04×READ count. CPU is reported separately.

## 2×2 means

| Condition | Arm | Accuracy | READs | Utility | NLL | Brier |
|---|---|---:|---:|---:|---:|---:|
| hidden_refractory_mismatch | A | 0.837240 | 2.875000 | 0.722240 | 0.413677 | 0.221576 |
| hidden_refractory_mismatch | B | 0.882812 | 2.833333 | 0.769479 | 0.283360 | 0.153043 |
| hidden_refractory_mismatch | C | 0.850260 | 2.869792 | 0.735469 | 0.392135 | 0.208101 |
| hidden_refractory_mismatch | D | 0.884115 | 2.807292 | 0.771823 | 0.280747 | 0.150982 |
| matched | A | 0.837891 | 2.856771 | 0.723620 | 0.400764 | 0.215663 |
| matched | B | 0.873698 | 2.755208 | 0.763490 | 0.282398 | 0.153276 |
| matched | C | 0.842448 | 2.867188 | 0.727760 | 0.391409 | 0.208759 |
| matched | D | 0.882812 | 2.736979 | 0.773333 | 0.279126 | 0.149840 |

A=ordinary/lightweight; B=ordinary/task-value; C=analytic/lightweight; D=analytic/task-value. The ordinary core is the inherited 23,712-parameter gated feedforward, not an SSM; the analytic core has known renewal structure and zero fitted core parameters. Both use the same observed packet, calibration estimates, budgets, task and controller code.

## All registered utility contrasts

Intervals are descriptive 95% hierarchical paired bootstrap intervals: 10,000 resamples, fitted-seed groups first and paired episodes within groups. Only three independent fits; auxiliary contrasts are descriptive, with no architecture-wide or familywise significance claim. The single main comparison is matched D−B.

| Condition | Contrast | Mean utility difference | Descriptive95% interval |
|---|---|---:|---|
| hidden_refractory_mismatch | B-A | +0.047240 | [+0.026301, +0.069610] |
| hidden_refractory_mismatch | B_on_D-D | -0.001302 | [-0.006510, +0.003255] |
| hidden_refractory_mismatch | C-A | +0.013229 | [-0.002604, +0.028620] |
| hidden_refractory_mismatch | D-B | +0.002344 | [-0.007370, +0.011459] |
| hidden_refractory_mismatch | D-C | +0.036354 | [+0.017448, +0.055417] |
| hidden_refractory_mismatch | D_both-D | -0.332005 | [-0.368126, -0.298410] |
| hidden_refractory_mismatch | D_current-D | -0.215469 | [-0.246225, -0.185703] |
| hidden_refractory_mismatch | D_hypothetical-D | -0.358620 | [-0.385184, -0.331952] |
| hidden_refractory_mismatch | hold_on_D-D | -0.004557 | [-0.016927, +0.007812] |
| hidden_refractory_mismatch | interaction | -0.010885 | [-0.029115, +0.007448] |
| matched | B-A | +0.039870 | [+0.020833, +0.059037] |
| matched | B_on_D-D | -0.002604 | [-0.006510, +0.000651] |
| matched | C-A | +0.004141 | [-0.006484, +0.015625] |
| matched | D-B | +0.009844 | [-0.004245, +0.025573] |
| matched | D-C | +0.045573 | [+0.023620, +0.068308] |
| matched | D_both-D | -0.313333 | [-0.344167, -0.283255] |
| matched | D_current-D | -0.220234 | [-0.244558, -0.195859] |
| matched | D_hypothetical-D | -0.351016 | [-0.383204, -0.320520] |
| matched | hold_on_D-D | -0.013021 | [-0.026042, +0.000651] |
| matched | interaction | +0.005703 | [-0.014740, +0.025859] |

The interaction is(D−C)−(B−A). Complete accuracy, NLL, Brier and READ contrasts with their intervals are in[RESULTS.json](results/mechanism/formal001/RESULTS.json). All NLL values use the inherited 1e−12 floor; hold-last-content can assign zero mass and is not a calibrated probabilistic baseline.

## Attribution after separating the intervention

`D_current` holds only real-observation future content forecasts fixed in the policy. `D_hypothetical` holds only hypothetical future-READ continuations fixed. `D_both` reproduces the inherited joint suppression exactly. Actual scored output propagation is unchanged. These are joint event/content forecast interventions, not isolated risk-feature or financial Put-channel ablations.

| Condition | Compared with D | Episodes with action change | First action changes at tick0 | Content-probability changes |
|---|---|---:|---:|---:|
| hidden_refractory_mismatch | B | 115/384 | 8 | 368/384 |
| hidden_refractory_mismatch | B_on_D | 0/384 | 0 | 361/384 |
| hidden_refractory_mismatch | D_both | 384/384 | 358 | 384/384 |
| hidden_refractory_mismatch | D_current | 384/384 | 0 | 384/384 |
| hidden_refractory_mismatch | D_hypothetical | 384/384 | 358 | 384/384 |
| hidden_refractory_mismatch | hold_on_D | 0/384 | 0 | 361/384 |
| matched | B | 115/384 | 10 | 371/384 |
| matched | B_on_D | 0/384 | 0 | 361/384 |
| matched | D_both | 384/384 | 356 | 384/384 |
| matched | D_current | 383/384 | 0 | 383/384 |
| matched | D_hypothetical | 384/384 | 356 | 384/384 |
| matched | hold_on_D | 0/384 | 0 | 361/384 |

Every current-only trajectory matches D before the first real READ (768/768). The old tick0 effect therefore comes from hypothetical future-READ valuation. Fixed D schedules are replayed exactly by ordinary and hold-last-content cores(1,536/1,536 checks); generic forecasting necessity does not establish that an analytic formula is uniquely necessary.

## Complete per-arm worker costs

Each arm×fit×condition has its own fresh process and 128 episodes; the table aggregates 768 episodes per arm. Parent `wait4` measures interpreter/imports/loading/execution/evidence serialization/exit. Cold startup is therefore amortized over 128 episodes per worker, not a separate cold start per request. Study workers were serial, but the shared host was not isolated.

| Arm | Full worker CPU seconds | Full worker wall seconds | Maximum one-worker RSS KiB | Standalone CPU including its own fits |
|---|---:|---:|---:|---:|
| A | 25.412007 | 25.443209 | 241772 | 47.452925 |
| B | 136.850036 | 136.889880 | 242232 | 158.890954 |
| B_on_D | 15.920339 | 15.938176 | 250796 | 37.961257 |
| C | 17.719693 | 17.764117 | 232604 | 17.719693 |
| D | 85.700836 | 85.741396 | 232604 | 85.700836 |
| D_both | 12.190250 | 12.203174 | 232604 | 12.190250 |
| D_current | 48.795176 | 48.829298 | 232604 | 48.795176 |
| D_hypothetical | 14.075154 | 14.104558 | 232604 | 14.075154 |
| hold_on_D | 11.590674 | 11.614483 | 242216 | 11.590674 |

The three ordinary fits cost 22.040918 CPU seconds and are charged once in the actual study. World generation/calibration is separately charged 9.328698 CPU seconds. All 63 workers total 399.623781 CPU seconds; study wall time 400.065061 seconds; maximum one-worker RSS 340,708KiB. Coordinator CPU 0.161934 seconds is separate, as are later analysis/audit/reporting. Per-arm standalone rows are hypothetical independent deployments and must not be summed as the actual research bill.

B cost 136.850036 worker CPU seconds; D 85.700836, a 37.3761% reduction. Matched quality D−B is +0.00984375 with interval [−0.00424544,+0.02557292]. No noninferiority tolerance was preregistered, so the CPU observation is not a same-quality economic certification. Energy remains null; no physical sensor, codec or network measurement is implied.

## Verification and evidence

[RAW_AUDIT.json](results/mechanism/formal001/RAW_AUDIT.json) independently recomputes 27,648 output scores across 6,912 arm-episodes, checks 16,777 READ events, 63 process receipts, 6 frozen project source files, 768 unique world seeds, paired world identity, 1,536 forced replays and 768 causal prefixes. It passes with no findings. Frozen analysis and audit CLIs both exited 0. A later inline console-display syntax error is retained in `POSTPROCESS_DISPLAY_FAILURE.json`; it changed no candidate or result and required no scientific rerun.

Four development behavior tests passed, including exact v2 rollout parity for unmodified and both-suppression modes. Raw per-episode traces, observations, predictions, worlds, fitted checkpoints, training data, source identities and complete receipts are retained under[formal001](results/mechanism/formal001/). Detailed Chinese explanation:[REPORT_ZH.md](results/mechanism/formal001/REPORT_ZH.md).

This assay still uses a perfect synthetic sensor, known renewal structure, an unequal-capacity ordinary core and a one-planned-read receding heuristic. It does not establish raw audio/video content learning, strong-SSM superiority, globally optimal task boundaries, real device energy savings or production readiness. Production activation remains false.
