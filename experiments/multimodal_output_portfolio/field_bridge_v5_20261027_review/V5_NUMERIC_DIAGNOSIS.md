# V5 numeric development diagnosis

## Status and scope

**Within-run integrity passed; overall and historical exact-regression status remain FAIL; numeric development entry also failed.** This report summarizes already sealed development outputs under diagnostic registration `f0897403189e866ffaa16c186fdb4ded2d3b5341`. It introduces no threshold, changes no gate, performs no model call, and grants no holdout access or admission.

The precise inputs, trace hashes, paired checks, per-seed resource totals and original seven comparisons are in `V5_NUMERIC_DIAGNOSIS.json`. The original frozen `AUDIT.json` and separate `WITHIN_RUN_AUDIT.json` are preserved.

## Same-guard methods are exactly identical in their realized outputs

Across all three seeds, four schedules and two transaction grains, there are **48 field/richer-versus-ordinary path pairs**. Every pair has the same independently verified terminal parameter hash and complete optimizer hash. All task/clean utility arrays match bit for bit, and **all 96 corresponding raw endpoint NPZ file pairs have identical SHA256 hashes**. Thus this is stronger than equality of reported means: retained pixels, captions and scores are byte-identical too.

All four predeclared same-guard comparisons—field_48−ordinary_48, field_48−richer_48, field_8−ordinary_8 and field_8−richer_8—are exactly zero for task and clean, reward and audit, both pooled and for each seed.

This identity follows from the observed policy: all 288 adaptive macro decisions kept the fixed ordinary baseline. It does not mean the two regressors have identical predictions.

## The empirical gate never opened

There were **zero nonbaseline overrides out of 288 adaptive decisions**, with no greedy ties. Without the gate, the unique greedy prediction would have chosen a nonbaseline action on **121 decisions: field 53/144 and richer 68/144**. Every predicted margin was below its fixed seed threshold. The maximum margin/threshold ratio was **0.7182597844**.

Field and richer observed bitwise-identical raw30 and mapped30 states at all 144 paired decision times. Their predicted values and some unconstrained greedy choices differ; the gate prevents those differences from affecting the executed trajectory.

| Seed | Transaction grain | Head | Empirical τ | Maximum predicted margin | Maximum margin/τ | Greedy nonbaseline | Actual override |
|---|---:|---|---:|---:|---:|---:|---:|
| 17 | 48 | field | 0.01948005 | 0.00543969 | 0.27924 | 9/24 | 0/24 |
| 17 | 48 | richer | 0.01948005 | 0.00637595 | 0.32731 | 12/24 | 0/24 |
| 17 | 8 | field | 0.01948005 | 0.00665726 | 0.34175 | 12/24 | 0/24 |
| 17 | 8 | richer | 0.01948005 | 0.00770792 | 0.39568 | 13/24 | 0/24 |
| 29 | 48 | field | 0.02710728 | 0.01153141 | 0.42540 | 14/24 | 0/24 |
| 29 | 48 | richer | 0.02710728 | 0.00952588 | 0.35141 | 13/24 | 0/24 |
| 29 | 8 | field | 0.02710728 | 0.00415666 | 0.15334 | 15/24 | 0/24 |
| 29 | 8 | richer | 0.02710728 | 0.00812432 | 0.29971 | 19/24 | 0/24 |
| 43 | 48 | field | 0.02463359 | 0.01671025 | 0.67835 | 3/24 | 0/24 |
| 43 | 48 | richer | 0.02463359 | 0.01769332 | 0.71826 | 11/24 | 0/24 |
| 43 | 8 | field | 0.02463359 | 0.00000000 | 0.00000 | 0/24 | 0/24 |
| 43 | 8 | richer | 0.02463359 | 0.00000000 | 0.00000 | 0/24 | 0/24 |

The seed thresholds span 0.01948005–0.02710728; the observed margins span 0–0.01769332. These are empirical old-fit maxima, not calibrated coverage guarantees. The current gate has demonstrated conservative fallback to baseline on these paths. The result supplies no active-control advantage for field and no general refutation of parameter-field theory. Lowering τ after seeing this result would define a new candidate, not repair the present result.

## Eight-step transactions underperformed the 48-step treatment

Because all three policy methods coincide within a grain, ordinary_8−ordinary_48 equals field_8−field_48 and richer_8−richer_48 in endpoint outcomes. Every seed has a negative mean task delta under both observers.

| Seed | Task Δ reward | Task Δ audit | Clean Δ reward | Clean Δ audit | Retained nonzero microsteps across four paths,48→8 |
|---|---:|---:|---:|---:|---:|
| 17 | -0.0013355072 | -0.0007983978 | +0.0011479925 | -0.0022211481 | 816 → 872 |
| 29 | -0.0074305365 | -0.0044337104 | -0.0040451684 | -0.0008957544 | 240 → 32 |
| 43 | -0.0302207565 | -0.0216636276 | -0.0044107272 | +0.0000326322 | 672 → 8 |

Pooled task differences are **−0.0129956001 reward** and **−0.0089652453 audit**. Pooled clean differences are **−0.0024359677 reward** and **−0.0010280901 audit**. These are descriptive means on disclosed development data, with no p-values or confidence claims.

Per method across 12 paths, the 48-step treatment accepted 36/72 transactions and retained 1728/3456 scheduled microsteps. The8-step treatment accepted 114/432 transactions and retained 912/3456 microsteps. Discarded work increased from 1728 to 2544 microsteps. The acceptance rates are 50% and 26.3889%, respectively. Counting 114 accepted short transactions as more learning than 36 long transactions would be misleading.

The short treatment increased retained steps for seed 17 (816→872) but decreased them sharply for seed 29 (240→32) and seed 43 (672→8). There were no zero-action transactions: each path attempted all 288 optimizer steps, and rejected transactions were restored. Attempted optimizer steps and retained updates are different quantities.

## Measured cost

Changing ordinary_48 to ordinary_8 keeps scheduled gradient backwards at 288 per path but adds **30 snapshots, 60 guard generator calls, 7680 guard generator examples, 120 observer calls and 15360 observer digit examples per path**. Guard work increases sixfold. Rejected work remains charged.

Field/richer instrumentation adds the same measured operations to ordinary at either grain: 6 directional backwards, 18 feature reverse calls, 96 generator/probe forwards, 12 teacher forwards and 96 reward-observer calls per path. Both heads measure common 30 for the comparison. These extra measurements did not alter an executed action in this run.

The actual path timing averages were:

| Method | CPU seconds/path | Wall seconds/path | Guard generator calls/path | Guard observer calls/path | Gradient backwards/path | Directional backwards/path | Feature reverse calls/path |
|---|---:|---:|---:|---:|---:|---:|---:|
| ordinary_48 | 27.115198 | 15.710932 | 12 | 24 | 288 | 0 | 0 |
| field_48 | 32.179918 | 16.640695 | 12 | 24 | 288 | 6 | 18 |
| richer_48 | 30.737521 | 15.584913 | 12 | 24 | 288 | 6 | 18 |
| ordinary_8 | 32.169479 | 16.503608 | 72 | 144 | 288 | 0 | 0 |
| field_8 | 50.617148 | 26.764847 | 72 | 144 | 288 | 6 | 18 |
| richer_8 | 46.114421 | 27.267281 | 72 | 144 | 288 | 6 | 18 |

ordinary_8 therefore recorded an additional 5.054281 CPU seconds and 0.792676 wall seconds per path on average. These are observations from a single census with a fixed method order and concurrent workload, not randomized latency estimates. Invocation/example counters are not FLOPs. Summed per-path wall times are not the total experiment elapsed time.

## Why numeric admission failed independently of the historical audit

Both observers passed the frozen-baseline task-gain checks and the each-model clean threshold. Both observers failed the two strict pooled field-increment conditions:

- field_8−ordinary_8 is 0, while the original rule requires greater than 0.001.
- field_8−richer_8 is 0, while the original rule requires greater than 0.

Thus numeric admission fails even if the separate historical portability issue were eventually explained. The original historical exact-regression FAIL remains a distinct unresolved result.

## Interpretation

This experiment established that the implementation executes complete real parameter-update transactions, preserves its recorded rollback invariants, and pays the measured feature and guard costs. The candidate nevertheless reverted to baseline everywhere and supplied no same-guard field increment. The8-step transaction choice made mean task outcomes worse on each of the three fixed models.

These findings concern this frozen bank, selected heads, empirical threshold, original model trio and already disclosed development roles. They do not establish that the field is a sufficient state, prove a policy-improvement bound, or falsify parameter-field theory. The old labels encode fixed Qref continuation and 48-step transactions; using them under the 8-step treatment remains an empirical surrogate. No gate is adjusted, no new outcome is declared independent, and no holdout or production admission follows from this diagnostic report.
