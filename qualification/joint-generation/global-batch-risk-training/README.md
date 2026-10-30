# Global-batch risk: partial recovery, not improvement over A

**globalN−A:0/8; globalN−groupN:0/8. Overall false under the original five gates.**

This new finite-minibatch surrogate adds risk across different content groups,
not just views within each content group. Twelve models share four freshly rebuilt
source-supervised, instruction-masked bases. A/groupN/globalN use the identical
static64-row schedule:8 groups x4 of6 variants x paired full/low,300updates.
Every arm computes all four original utility branches, groupA/groupN and globalN;
only selected utility gradients differ. Ordinary rowmean anchor.2 is never tilted.
The new helper is explicit global64 mode/schema; old helpers/serving guards unchanged.

All4 base and8 historical A/groupN final digests, old complete metrics/profilekeys/
FIT records/datasets reproduced exactly. All12models then24heads froze before the
previously studied heldout noise was regenerated. No TEST, fresh-global-group claim,
model/seed/threshold selection, rerun or deployment. Original mean-row coupled,
FIT-calibrated serving evaluation remains; the independent-training/coupled-serving
mismatch is not repaired. Sampled-batch gradients are not unbiased whole-FIT risk
estimates, and Adam is not unbiased. The free-policy Bayes theorem excludes the
actual anchor and neural parameter restrictions; it does not prove NDU useless.

## Fixed results
Calibrated partial-command macro(full,low) original CE differences:

| Fold | Seed | Noise | globalN−A | globalN−groupN | Five-gate pass vs A / groupN |
|---:|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | -0.000274 | -0.000302 | False / False |
| 0 | 103 | 3702 | -0.000267 | +0.000159 | False / False |
| 0 | 107 | 3701 | +0.000013 | +0.000995 | False / False |
| 0 | 107 | 3702 | -0.000357 | +0.001651 | False / False |
| 1 | 103 | 3711 | -0.000463 | +0.000439 | False / False |
| 1 | 103 | 3712 | +0.000005 | +0.000319 | False / False |
| 1 | 107 | 3711 | -0.000239 | +0.000244 | False / False |
| 1 | 107 | 3712 | -0.000278 | +0.000763 | False / False |

Against A, all8 text-mass and joint-success changes are negative. Against groupN,
all8 improve MSE, text mass and joint success, but the largest CE gain is only
+.001651, below the unchanged+.005 threshold. Recovering some losses relative to
weaker groupN is NOT evidence that globalN beats A. The saved groupN−A boolean is
a descriptive control, not a third primary hypothesis. All72 contrasts and every
metric/channel/population/noise, including pooled descriptions and selfcalibration,
are retained in SUMMARY; none rescue the16 failed primary comparisons.

## Qualification and actual costs
41 literal tests passed before scientific FIT generation: original37 plus4 qualified
global tests. Separate payload-free13-test global qualification cost.247142 CPU s;
its value/chain, two-level aggregation and both-head full-anchor checks were reviewed.
Training child completely waited:17.727167 CPU s,17.805754819 wall s,93384 KiB RSS.
Fixed30CPU/90wall/512MiB/4MiB,CPU0/one numericalthread, existing synthetic lock,
no retry. All new base prep, tests, masks, data generation, schedule creation,
extra aggregation, FIT calibration, serving and SHA work are included. Per-arm,
per-base, fit/data/serving counters and timings, total SHA counts and full wait4
receipt remain in SUMMARY.14856 forwards/1015840 rows;7200 legacy group aggregates
plus3600 global aggregates/230400 row visits. Equal update counts do not establish
equal actual total spend. Historical qualifications/research and source/review/
supervisor tail remain additional; unknown older costs are not zero.

## Portable source and audit boundaries
Only helper, literal test and frozen plan are distributed, not an unrestricted
scientific runner or any weights, examples, private inputs or runtime paths.
Dependencies are the byte-identical published `grouped_risk.py` in grouped-view-risk,
`grouped_training.py`/`test_grouped_training.py` in grouped-view-training, and their
published aligned/transport/control/legacy utility dependencies. Make those modules
available on the Python path to use the helper/tests; no model or dataset is needed
for the literal fixture. Scientific reproduction requires its separately bounded,
reviewed source recipe and shared-resource admission; this package does not launch it.
SUMMARY includes model digests, objective/profile identities, all freeze barriers
and complete scalar aggregates, not model arrays. VALIDATION binds immutable source,
result, receipt and independent reviews. Failed original scientific gates remain false.
