# Fixed-zero exponential score: original scientific gates failed

**Score−A:0/8; score−globalN:0/8. All16 primary five-gate comparisons fail.**

The new score s(R)=(1-exp(-rho R))/rho fixes rho1.5 and the original reward zero
and units. Its utility gradient is exp(-rho rowCE) times the already-rowmean
negative CE gradient. This equals Zbatch times globalN's utility gradient, but
ordinary aligned anchor.2 stays unscaled: regularized objectives differ. Adam
history/epsilon also preclude general update-scaling equivalence. No reward shift,
scale, rho, temperature, seed or threshold tuning follows these results.

A/globalN/score share4 fresh source-supervised instruction-masked bases, folds0/1,
seeds103/107, and the exact static grouped64 sampler/300updates. Every arm computes
all original raw/aligned A/N terms, groupA/groupN, globalN AND score; only chosen
utility gradients differ. All4 bases and8 A/globalN final digests plus completeold
metrics, FIT records/profilekeys and datasets reproduced exactly. All12models then
24calibrated heads froze before previously studied heldout noise regeneration.
No TEST or globallynewgroup/noise claim; no outcome-based selection or rerun.

## Fixed results
Original calibrated partial-command full/low macro CE differences:

| Fold | Seed | Noise | Score−A | Score−globalN | Five-gate pass vs A / globalN |
|---:|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | +0.000103930 | +0.000378284 | False / False |
| 0 | 103 | 3702 | +0.000144013 | +0.000410801 | False / False |
| 0 | 107 | 3701 | +0.000006669 | -0.000006125 | False / False |
| 0 | 107 | 3702 | -0.000194492 | +0.000162751 | False / False |
| 1 | 103 | 3711 | +0.000134143 | +0.000597312 | False / False |
| 1 | 103 | 3712 | +0.000048369 | +0.000043796 | False / False |
| 1 | 107 | 3711 | +0.000041487 | +0.000280398 | False / False |
| 1 | 107 | 3712 | +0.000051532 | +0.000329246 | False / False |

Seven of eight CE changes are positive against each control, but maximum gains
are only+.000144013 versus A and+.000597312 versus globalN, far below the fixed
+.005 requirement. Versus A,3 strata regress MSE and2 regress text mass. Small
positive changes and recovery against a weaker control do not rescue the gates.
This fixed-scale score is a different surrogate, not evidence original NDU beats A.
The recorded globalN−A gate is descriptive, not a third primary. SUMMARY preserves
all72 contrasts, all11 metrics/full-low-macro/all-partial/noises and pooled/selfcal
controls; every failure remains. The aggregation/normalizer family is closed here
without parameter or threshold rescue; this does not prove all risk methods useless.

## Estimand and limitations
At fixed parameters and fixedFIT data, the uniform8of130 contentgroups/4of6variants/
pairedchannels design has equalrow inclusion, giving an unbiased plainmean SCORE
gradient. It does NOT give an unbiased log-risk estimator or Adam updates. Reward
translation scales utility but not anchor; fixing originalzero is essential.
Originalmean-row coupled/FIT-calibrated serving evaluation is unchanged. Training
uses independent output expectation; its mismatch with serving is not repaired.
Free-policy deterministic-Bayes arguments exclude this actualanchor/neuralmodel.

## Full costs and validation
All45 literal tests passed before FIT generation. Separate17-test scorequalification
fully waited.256208 CPU seconds; earlier13-test globalqualification.247142 CPU seconds.
Scientific child fully waited17.090139 CPU seconds/17.167466741 wall seconds,
94148 KiB RSS. Fixed30CPU/90wall/512MiB/4MiB,CPU0/singlethread/shared synthetic lock,
no retries. All newprep/tests/data/schedules/masks/extraaggregation/FIT/serving/SHA
inside child; perarm/base/fit/serving/data costs and complete wait4 are preserved.
14856forwardbatches/1015840rows;7200groupaggregations+3600globalaggregations+
3600scorecalls/230400scorerows/3600scorebatchvalues. Wholechild SHA instrumentation
recorded11608 constructions and33024158 inputbytes; full exact counters retained.
Equal updates are not equal actualspend; all prior research/prep/review/supervisor
costs are additional and unknown older costs are notzero.

## Portable package
Sixfiles only: qualifiedscorehelper/test, frozenPLAN, README and complete scalar
SUMMARY/VALIDATION. No unrestrictedrunner, weights, privateinputs, runtimepaths,
merge or deployment. Source/test/PLAN are byte-exact candidatecopies. Tests use
manual64row fixtures, not scientificdataset/model payloads.
Dependencies: published global-batch-risk `global_risk.py`/`test_global_risk.py`,
grouped-view-risk `grouped_risk.py`, grouped-view-training integration fixture,
and their aligned/transport/control/legacyutility dependencies. Place these modules
on Pythonpath; actual science reproduction requires separately reviewed bounded
admission, not a command hidden in this package. Validation binds exact result,
receipt and reviews; metadata retains modeldigests, objectiveidentities and barriers.
