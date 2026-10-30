# Registered v2 development — independent complete-panel analysis

**Both overall development admission gates fail.** The complete four-configuration panel passed byte/provenance/trajectory-row consistency checks. No confirmation source was opened, no training setting or acceptance threshold changed, and these results do not establish lifecycle savings or natural semantic qualification.

Registration: `9a0b16a620b4203093268a2a917f76bb99eb61ef`; [CI run 41055922354](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41055922354).

## Estimand and intervals

Within each training seed, the gamma=2 certainty equivalent is `-log(mean(exp(-2 R)))/2` over the registered sources and actual draws. The reported effect averages these per-seed CE differences; training-seed randomness is not inserted as an extra source of entropic risk. The fixed engine resamples source and seed clusters jointly, with common weights across comparison arms and widths.

All intervals below are the preregistered Bonferroni-adjusted percentile bootstrap intervals, from 4,000 resamples: eight comparison/width endpoints in the mechanism family and six in the distillation family. Familywise coverage is nominal and bootstrap-based, not an exact finite-sample guarantee. Only two training seeds and 32 unique development sources underlie each width. The CE plug-in estimate has finite-sample bias. Every seed must also satisfy the registered effect threshold.

## Mechanism family

| Width | Comparison | Mean seed effect | Adjusted interval | Pass |
| --- | --- | ---: | --- | --- |
| 32 | risk | +0.000556816 | [-0.000645817, +0.002279640] | no |
| 32 | allocation | -0.002132065 | [-0.028571198, +0.017040092] | no |
| 32 | operator | +0.013633493 | [+0.000051060, +0.038668665] | yes |
| 32 | joint_training | +0.000022733 | [-0.000138625, +0.000127001] | no |
| 64 | risk | -0.001324635 | [-0.002801703, -0.000246197] | no |
| 64 | allocation | +0.000806455 | [-0.000919566, +0.002668685] | no |
| 64 | operator | +0.001337530 | [-0.006641842, +0.004211283] | no |
| 64 | joint_training | +0.000825710 | [+0.000015940, +0.002211223] | yes |

Only the width-32 operator and width-64 joint-training endpoints pass. Their adjusted lower bounds are close to zero; neither finding repeats at both registered widths. The width-64 risk-trained arm is worse than the matched mean-trained arm in this development setup. This is an outcome of the declared finite training procedure, not a disproof of the risk-sensitive objective.

The operator/allocation comparisons in v2 keep the risk objective fixed. The old mean-versus-mean mechanism comparisons were already internally matched; the old native teacher-versus-ordinary comparison mixed policy/planner and objective and could not isolate the operator. Joint-versus-actor-only still changes supervised anchoring and critic/generator updates together.

## Distillation family

| Width | Comparison | Mean seed effect | Threshold | Adjusted interval | Pass |
| --- | --- | ---: | ---: | --- | --- |
| 32 | student_quality_noninferiority | -0.000510152 | -0.005 | [-0.001719972, +0.000096372] | yes |
| 32 | student_net_noninferiority | +0.000128270 | -0.005 | [-0.001927308, +0.001361516] | yes |
| 32 | student_cost_saving | +0.000674811 | +0.000 | [-0.001179545, +0.001616040] | no |
| 64 | student_quality_noninferiority | -0.000126761 | -0.005 | [-0.000492353, +0.000261903] | yes |
| 64 | student_net_noninferiority | +0.000634272 | -0.005 | [-0.004421934, +0.005058829] | yes |
| 64 | student_cost_saving | +0.000674819 | +0.000 | [-0.004358748, +0.004874248] | no |

The student meets the declared -0.005 development noninferiority margins for utility CE and audit-inclusive net CE at both widths. These margins are this study’s design choices, not established field standards. Cost-savings intervals cross zero at both widths, so the overall distillation admission gate fails. Width-64 seed 17 is actually more expensive for the student. Positive average savings are insufficient for stable low-cost deployment.

## Verified executed panel

Across the four configurations: 16,384 joint-training trajectories, 2,048 primary mechanism evaluation trajectories, 144 DAgger training trajectories, 512 teacher/student evaluation trajectories, and 576 feedback diagnostic trajectories: **19,664 actual trajectories and 78,656 delivered output files, with zero reported failures.** The raw trajectory members and compact metadata were rehashed; output-byte verification is supported by the original independent archive audits. This analysis did not reopen the omitted media.

All four registered configurations were present exactly once; all required source/draw/arm rows, model/profile/source identities, actual action sequences, named RNG seeds, costs and output digests matched their original trajectory records. Native engineering probes are excluded from this statistical panel because they reuse development sources and do not provide independent quality observations.

## Observed cost reconciliation

Cost units are the registered normalized-utility tariff units, not currency. The encompassing process time meter already includes episode CPU/wall work. Fixed action/encode/delivery service fees are added exactly once. Each action’s original CPU/wall readings were checked against its charged event; terminal delivery exposes only its measured time-tariff total, so no CPU/wall split is invented. Feedback runs after the process meter and is added separately.

| Seed / width | Process time | Fixed service fees inside process | Process + fixed fees | Feedback time + fixed fees | Combined observed cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| 17 / 32 | 5.450610580 | 89.784000000 | 95.234610580 | 2.999259936 | 98.233870516 |
| 17 / 64 | 6.710430314 | 95.241500000 | 101.951930314 | 2.953533812 | 104.905464126 |
| 29 / 32 | 5.837445149 | 93.228500000 | 99.065945149 | 3.103849291 | 102.169794441 |
| 29 / 64 | 8.373762382 | 96.775500000 | 105.149262382 | 3.347635362 | 108.496897744 |
| Total | 26.372248425 | 375.029500000 | 401.401748425 | 12.404278401 | 413.806026826 |

The **413.806026826** observed total adds all recorded costs within those scopes without charging CPU/wall twice. It remains a lower bound for the wider research operation: environment provisioning/package installation, repository/artifact downloads, source/evidence publication, standalone archival/analysis/upload, supervisor startup before its timer, and feedback startup/final-summary serialization are outside the recorded meters. Unmeasured does not mean zero.

No arbitrary per-candidate allocation of shared research, selection, training or distillation costs was made. The frozen deployment volume of 10,000 episodes requires a separate complete lifecycle allocation and confirmation. Both family gates above retain their originally registered audit-inclusive serving-cost scope; this explanatory cost reconciliation changes neither gate.

## Preserved analysis identities

- Analysis source SHA-256: `e7e08e22f04dac0c8d8c7b6e6307c10782d5c3f2024d25c753836d6a8f0b71a3`.
- Statistical engine SHA-256: `552cc7a993e3ab9249bc5cf4b96f8a07307cf7eeac1eaea27b424720473ecf9e`.
- development_plan_distillation_v2.json: `d69b201890c11e0c44e3f7ab4ef345be86a1559ec3abacc7feda2258f110abdd`.
- development_plan_v2.json: `622661ff7b8b2b38d866a96e25b42553d12479579309b6f5fec0e837f2c37653`.

`SUMMARY.json` contains every interval, per-seed effect, phase decomposition, process residual and qualification flag. `MECHANISM_ROWS.json.gz` and `DISTILLATION_ROWS.json.gz` retain the exact compact row values used in the analysis. All are analysis products derived from original preserved bytes; the source run remains unchanged.
