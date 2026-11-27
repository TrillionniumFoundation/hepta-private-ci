# Completed round 2: native NDU Stem structure versus solver

## Result and provenance

All 40 frozen fresh-process runs completed, zero failures: 33 from-scratch fits,
six untrained controls, and one exact D reference. Ten panels per run give 400
panel reports. The main sweep used 346.822915254 seconds wall time and
345.687705 whole-child CPU seconds, including imports, fitting, prediction,
independent Decimal oracle, scoring, serialization and replay. This is local
assistant CPU execution, not a target-device Hepta runtime or user project cloud.

Executed source commit: fdff096954184ab67887e510969d581412549d16, stacked from
PR #1755 source 9631307b604340180b1e706baf96b8ce3aec2f58. The four new Python
files and protocol were refetched and their Git blobs exactly matched the local
executed files. The five original Python files remain byte-for-byte unchanged.
The source-only local slice is not a full Rust/Bazel repository checkout.

48/48 source/math tests passed, zero skips (28 retained and 20 new), on the
frozen source before the sweep. Three further real-artifact tamper tests passed
post hoc: missing census row, altered prediction bytes, and changed score even
when its report hash was recomputed. These are audit checks, not new model tasks.

The post-seal audit reverified all 40 plans, report hashes, prediction seals,
initial/selected weights, exactly matching B/C initializations in 12 paired
comparisons, all raw scores, and ten freshly recomputed independent Decimal
references. It replayed ALL 400 panels (including D) with maximum difference
0.0 over 1,228,800 predicted scalar values. Child runs had separately reloaded
39 stored fitted/initial models over 390 panels. Replays are not independent
learning evidence. The extra full audit cost 3.993796239 CPU seconds; tamper
checks took 10.572 seconds wall time; test/development costs are additional.

## Primary contrast was NOT won by structured C

At nominal 8-second training cap, the mean RMSEs across three initializations are:

| Family / method | New composed terminals | New uniform terminals | Horizon 8 | 192-state world |
| --- | ---: | ---: | ---: | ---: |
| Transformer A / Adam | 0.00544561749 | 0.00773272686 | 0.00556870142 | 0.00615175414 |
| Raw B / Adam | 0.00467999857 | 0.00556191292 | 0.00440704020 | 0.00472542946 |
| Raw C / TRF | 0.000238493865 | 0.000253275577 | 0.000181255400 | 0.00337821507 |
| Raw / L-BFGS | 0.00253886324 | 0.00281508742 | 0.00221825491 | 0.00364043849 |
| Structured B / Adam | 0.000737777435 | 0.000921272446 | 0.000627434943 | 0.000842735971 |
| Structured C / TRF | 0.000760549244 | 0.000931524597 | 0.000632336569 | 0.000864872678 |
| Structured / L-BFGS | 0.000736083886 | 0.000918047030 | 0.000625294691 | 0.000839692355 |
| Untrained structured | 0.00106890891 | 0.00141524351 | 0.000970785467 | 0.00133614308 |
| Direct D | 1.12e-16 | 1.04e-16 | 1.56e-16 | 1.01e-16 |

Raw B/C have the original same 65-parameter class and byte-identical paired
initializations. Structured B/C share the new same 65-parameter class and paired
initializations. Raw and structured are different function classes even though
parameter counts match. A has 665 parameters and is not capacity matched.

The primary frozen metric is NEW COMPOSED terminal RMSE for structured B/C at
the 8-second cap. Structured C is worse in ALL three seeds, by 3.08654% using
the ratio of means. Paired B/C ratios are 0.969708, 0.970666, 0.969802. There is
no primary accuracy superiority claim. Structured L-BFGS also slightly outperforms
structured C on this metric. The 2-second comparison has the same direction.

The raw-family numerical solver advantage replicates on the new families:
raw B/C composed-error ratios are 22.43185, 19.80944, 17.18301; ratio of means
19.62314. This is a small numerical operator experiment, not independent language
or continuous-state generalization. Each family has 32 fixed generated terminal
functions reused across seeds; repeated seeds and panels are not new domains.

## Structural robustness is real, but is largely an encoded prior

All structured models, INCLUDING the three untrained controls, give zero raw
out-of-[0,1] frequency on the joint probability panel and approximately 4e-17
RMSE. No output clipping is used. At rho=0 both entropic experts reduce to the
same exact expectation regardless of network weights. Thus this success MUST NOT
be presented as learned transfer or evidence for a general FBSDE/PMP learner.

Actual learning still occurred on the nonzero-risk task: from the untrained
structured composed mean 0.00106890891, Adam reduced RMSE by 30.9785%, and TRF
by 28.8481%. All 33 fitted runs changed real weights; no frozen expert is called
a trained model. The structured expert temperatures are rho/2 and 3rho/2,
not the exact target rho. Their fixed mixture cannot generally express that
target for all continuations with a task-independent mixing coefficient.

Numerical invariant probes (order, min/max range, translation, constant consistency
and sup stability) had maximum structured discrepancy 6.66e-16, across trained
and untrained models. The analytic real-arithmetic properties are in the protocol;
these finite probes are not interval-certified universal numerical guarantees.

## Single-field tests identify failures beyond the zero-risk condition

Mean RMSE at the 8-second nominal cap; each single-field intervention keeps all
other coefficients and the new uniform terminal bytes unchanged:

| Intervention | Raw B / Adam | Raw C / TRF | Structured B | Structured C |
| --- | ---: | ---: | ---: | ---: |
| Risk zero only | 0.0160518138 | 0.209860474 | 3.79e-17 | 3.94e-17 |
| Discount one only | 0.0120708434 | 0.142904130 | 0.00111234690 | 0.00111769766 |
| Cost zero only | 0.0154239701 | 0.277997456 | 0.000919523570 | 0.000931432154 |
| Indicator terminal only | 0.00533518910 | 0.000205640499 | 0.000844291422 | 0.000850317221 |
| Joint probability profile | 0.0132302315 | 0.214220595 | 3.55e-17 | 4.33e-17 |

Raw C fails badly even if ONLY the running cost is removed, with risk, discount,
kernel and terminal values unchanged. The earlier combined stress failure cannot
be attributed solely to risk=0 or indicator terminals. These are changes outside
the original finite training law, so no original-law guarantee is claimed.
On the new joint probability panel raw C has 49.21875%, 4.6875% and 24.21875%
invalid raw probabilities, while structured models have zero. All raw/clipped
Brier and calibration fields are retained in the reports, without filtering.

## Why tighter solving does not eliminate the new family's bias

A disclosed POST-HOC diagnostic, not used for fit or model selection, relaxes the
new family to one independent mixing coefficient w_s in [0,1] for each state,
constant across the 12 training terminal functions. This is a superset of its
actual shared neural gate. At the first step write d=low-high and y=target-high.
Then the optimal relaxed coefficient is

    w_s = clip(sum_g d_(g,s)*y_(g,s) / sum_g d_(g,s)^2, 0, 1).

This minimizes that state's quadratic error; therefore the full three-step mean
squared defect is at least one third of the first-step relaxed minimum. Numerical
evaluation of this analytic bound gives first-step MSE 1.338082923028301e-6,
and full-objective lower bound 4.460276410094337e-7. Structured C's attained full
training MSE is 5.366313e-7, about 20.3% above this permissive lower bound.
The bound is not interval-certified and does not prove global optimality.

C has LOWER training residual than structured Adam (about 5.528e-7) but slightly
HIGHER new-terminal error. Smaller equation residual alone is not a guarantee
of better unseen-task performance. The positive family-specific floor also shows
why merely running this restricted mixture solver longer cannot arbitrarily
remove its approximation error. It does not establish a limitation of all NDU
architectures, nor a limit for richer monotone operator classes.

## Actual costs and decision consequences

Structured C terminated through its original gradient-tolerance condition after
2.546967, 3.200046 and 2.673334 CPU seconds, below the 8-second cap; structured
Adam used 8.000345--8.003639 seconds. Thus C reaches its lower training residual
faster, although it does not win the primary generalization metric. No dummy
work was added to force identical elapsed time. Raw C used about 8.002--8.007
seconds; all one-operation cap overshoots are recorded.

Raw C's main fits used 445--546 Jacobian evaluations (28,925--35,490 forward-AD
lanes); structured C used 88--117 (5,720--7,605). Peak RSS after the whole run is
about 345--346 MiB for structured Adam and 351--352 MiB for structured C, including
runtime/import allocations. Whole-sweep fitting CPU was 176.541232373 seconds,
independent oracle/scoring/save 74.815744292 seconds and prediction/sealing
1.015705585 seconds; whole-child CPU also includes all remaining phases/imports.
Total FLOPs, GPU peak and energy remain unknown. This is not an equal-FLOP claim.

The fixed 51-price contract-choice grid avoids relying only on the saturated
original binary choice. On composed terminals, mean price-grid decision regret
is raw Adam 7.870214e-6, raw C 2.062755e-8, and structured Adam/C both 2.599564e-7.
Prices were fixed without an oracle. These are correlated numerical decisions,
not natural-language task success rates. Every original and priced metric is saved.

## Next mathematical target, not a claimed new executed model

Keep order/translation/zero-risk structure without forcing a continuation-blind
mixture of two fixed temperatures. One candidate representation is

    CE_theta(a,b;p,rho) = b + integral_(0)^(a-b) q_theta(s,p,rho) ds,
    0 <= q_theta <= 1, q_theta(s,p,0)=p.

The derivative bounds enforce monotonicity in both inputs and sup stability;
the origin condition and integral give constant consistency and translation.
A richer monotone primitive can express dependence on continuation spread.
Its numerical integration must itself preserve the guarantees or carry explicit
error control; a generic quadrature label is insufficient. This is a proposed
next family, not an unreported second sweep or an already-trained model.

## Delivery boundaries

Source, frozen protocol, all results, primary numerical weights, post-seal audit,
complete logs and all raw arrays are retained. This round changes neither main,
CURRENT, native NDU/Q24/Q32 semantics nor deployment authority. The separate
GitHub-head test/CI status must be read on the final composed SHA; parent successes
do not transfer. No whole-repository Rust/Bazel or production acceptance is claimed.
