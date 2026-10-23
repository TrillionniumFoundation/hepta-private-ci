# Completed one-shot TRAIN reconstruction, gradient and service diagnostic

This is the single reconstruction authorized after `34b16fc7d7`. It finished
with exit 0. No parameter was updated, no training was repeated and no
validation/formal source was constructed. This new inference identity does not
turn the original missing row logs into historical observations.

Source/protocol/sample/order were committed at `214fd56bec`, frozen in
`ndu_training/reinfer_d1/frozen-d1.json`, and the freeze plus successful real-entry
zero-prediction smoke committed at `5e34db9e54` before execution. The exclusive
TRAIN marker and first-model-result marker remain. The two handmade entry tests
passed in 0.098 seconds; the smoke forbade dataset construction/model forwards.
Previously closed parameter-delta and test-log audits were not repeated.

## Budget, denominators and preservation

Exactly 12 saved final models × 48 four-source cohorts × 4 Williams waves × 64
rows = **147,456 actual native/PNG service requests**: 73,728 per A/N system,
12,288 per model. All 192 physical sources and 3,072 requests remain in each
readout. The separately priced three-base CE reference and final-model gradient
forwards give 227,328 total encoder/head forward-row evaluations. Service p/q
from wave 0 supplied the readout; subsequent waves matched at frozen tolerance.

| Full system | Declared operator units | CPU seconds after final write |
|---|---:|---:|
| A, all six final models and all shared work | 3,517,800,846 | 8.250158328 |
| N, all six final models and all shared work | 3,519,254,214 | 8.297947620 |
| Common work, fully included in **each** row above | 1,437,213,192 | included |

Actual physical process CPU was **15.665678455 seconds**, below the 30-second
cap. Each complete system remained below 15 CPU seconds and 4B units, rather
than receiving that allowance per model. The pre-result admission quotes were
A3,523,681,368/N3,525,020,760 units; service reservations were 9.5 seconds each.
No unused work was executed to equalize the totals. Raw retained output was
51,573,297 bytes before its final receipt, below 64 MiB.

The supplementary `read_saved.py` uses only these saved arrays and performs no
forward or training call. Its useful numerical work adds 2,034,102 declared units
in full to **both** systems: A3,519,834,948/N3,521,288,316. Its process, including
imports and array/JSON I/O, took 0.220680851 CPU seconds after receipt writing,
also fully shared. Entry plus this readout is therefore 15.886359306 physical
seconds and A8.470839179/N8.518628471 attributed seconds. These are measured
process scopes; exploratory shell inspection, source editing and repository
delivery are not latency measurements and are not silently folded into them.
`delivery-receipt.json` records the separate archive verification/writing CPU.

Arrays are lossless float64/ZIP_STORED; no source was removed for storage.
`TRAIN-inputs.npz` and `TRAIN-map.json` preserve labels, views, instructions,
physical source identities/attributes, cohorts and all minibatch draws.
`requests-*.npz` retains p/q, each true-class probability, margins, per-request
Z and entropic value, reward components, greedy codes/reward and attribute errors.
`base-reference-*.npz`, `gradient-*.npz`, all 32 gradient hashes and original
model hash references permit reconstruction of the gradient evidence. The
service arrays retain all choices/payload hashes/byte counts; unique complete
payloads are deduplicated in `output-payloads.json`. Models and native binary
reference the original immutable artifacts instead of duplicating them.

## Fixed CE control variate

The only candidate is
`g'_B = g_B + 0.2 (H_CE(base) − h_CE,B(base))` with rho=1.5, the existing CE
anchor/utility, and the original paired sampler/view/importance law. Both A and
N receive the same correction. Full TRAIN/full-low reference means independently
matched the dense public backward route (maximum absolute error
6.94e-18, predeclared rtol1e-10/atol1e-12). Population-weight checks passed.

| Sampler | Seed | N original variance | N CV variance | N reduction | A reduction |
|---|---:|---:|---:|---:|---:|
| IID | 11 | 0.02800384 | 0.01628831 | 41.84% | 40.60% |
| IID | 23 | 0.02767151 | 0.01605714 | 41.97% | 38.66% |
| IID | 47 | 0.03069005 | 0.01959226 | 36.16% | 34.21% |
| Stratified | 11 | 0.03021669 | 0.01957029 | 35.23% | 33.97% |
| Stratified | 23 | 0.02714097 | 0.01744408 | 35.73% | 33.38% |
| Stratified | 47 | 0.02905428 | 0.01873860 | 35.50% | 35.18% |

All six N points met the predeclared strict-reduction rule. Retain the candidate
for review, without a coefficient search or a training-benefit claim. These are
32 paired minibatches at fixed saved parameters, with one new sampler panel
shared across model seeds. They are not six independent replications and do
not estimate variation across new complete training blocks. The noisy 32-batch
reference sample mean differs from its full mean (norm 0.0384–0.0538); this is
not the deterministic full-reference mean check and is not relabeled a failure
or erased. Pre-clip unbiasedness does not imply unbiased Adam updates. Total
variance may increase at other training states, and cache preparation consumes
budget otherwise usable for updates.

## Continuous gains and localized greedy losses

All numbers below compare N to A **within the same sampler and seed**. Source
counts use every source; the complete 192-source tables are in `result.json`.

| Sampler/seed | Δ raw utility | Δ text true p | Δ image true p | Sources with positive/negative utility | Greedy joint lost/rescued |
|---|---:|---:|---:|---:|---:|
| IID11 | .0030371 | .0011957 | .0011043 | 167/25 | 6/1 |
| IID23 | .0054302 | .0029234 | .0028564 | 176/16 | 1/0 |
| IID47 | .0029200 | .0011150 | .0011091 | 176/16 | 5/0 |
| Stratified11 | .0030077 | .0015243 | .0015078 | 167/25 | 3/2 |
| Stratified23 | .0047098 | .0022354 | .0022368 | 168/24 | 2/0 |
| Stratified47 | .0043059 | .0021695 | .0022012 | 172/20 | 1/2 |

Continuous gains are spread across many sources and both heads. Joint correct
probability, consistency and mean entropic value improve in all six comparisons;
negative-reward mass and pixel MSE fall. This supports the earlier aggregate
finding that gains include real true-class probability increases. It does not
identify one unique causal effect of curvature versus gradient scale.

Greedy errors are concentrated on the **shape** attribute (square/cross). All
listed lost/rescued joint-correct rows change shape only; the saved complete
attribute-error means have zero color/position difference. This is not merely
tiny argmax jitter: stratified seed11 row225 (source scene0, brightness .787,
vertical shift+1, target8) goes [8,8]→[10,10], with text true margin
.718943→−.213341 and image +.740847→−.234347. Other transitions are small-margin:
stratified seed47 row337 has image margin +.000372→−.071944. Both cases remain.

For stratified seed11, losses are rows225/1334/1596 and rescues739/1540; seed23
loses2654/3054 with no rescue; seed47 loses337 and rescues1596/1607. Row1596
changes in opposite directions for seeds11 and47, so a single source/brightness
rule is unsupported. IID losses span source scenes0/2/5/6/7/10 and also show
large margin reversals. All source IDs, commands, severities and margins for
joint-correctness transitions are in `saved-array-readout.json` under the field
`all_changed_greedy_rows` (that field means changed **joint correctness**, not
every change between already-incorrect codes). Full p/q and greedy codes retain
the latter changes too; the 4×4 head-transition matrices include them.

The mean fixed greedy reward falls in five comparisons and rises only for
stratified47. Same-sampler stratified N changes joint correct counts by −1/−2/+1;
against the endpointwise better of effective A_iid and A_stratified it is
**−2/−2/−1 of3072**. No greedy improvement is claimed. Losing both heads to a
shared wrong shape can preserve cross-head consistency while changing decoded
reward from about1 to about.092; a one-head mistake can yield about.042–.050.
Those are the unchanged utility's semantics, not a newly selected scorer.

## Four service waves

Primary paired CPU differences use **all48 timing cohorts** in each wave,
including actual native generation and PNG/JSON/ledger output. The table gives
N−A microseconds/request; all four waves remain.

| Sampler/seed | Wave0 | Wave1 | Wave2 | Wave3 |
|---|---:|---:|---:|---:|
| IID11 | 5.066 | −5.017 | 2.864 | −3.418 |
| IID23 | 6.762 | 1.716 | 5.739 | −2.174 |
| IID47 | −7.243 | −2.501 | −3.653 | 7.755 |
| Stratified11 | 1.303 | 24.090 | −3.671 | −7.951 |
| Stratified23 | −2.142 | −11.545 | 4.680 | −5.376 |
| Stratified47 | −2.386 | 10.484 | 8.167 | −.824 |

Every seed/sampler changes sign across waves. Identical-output cohort strata
also have nonzero/noisy differences and are retained as descriptive checks,
not selected to replace the primary denominator. Williams order cannot remove
arbitrary host drift. Differences in actual outputs and execution conditions
remain possible contributors; this run establishes no stable N service-speed
advantage and supplies no independent training-block variance estimate.

## Next candidate and preserved boundary

The minimal next candidate remains the single fixed-base CE control variate,
equally available to strong A and N. Any subsequent training study must charge
the full reference/correction/cache cost inside the original complete-system
10-second/12B caps, reduce useful updates as necessary, freeze the same effective
A comparators, and retain all seeds. Lower measured gradient variance alone
is insufficient: the candidate is falsified as an improvement if its complete
budget N−A external utility gain does not survive its predeclared comparison or
its fixed greedy preservation rule. No such new training is authorized or run
by this diagnostic, and no further CV coefficient or scorer is selected here.

The large multi-block confirmation remains an unexecuted proposal. It requires
parent integration of the three contributions/claims, physical-source and
timing-cohort inference, training-seed estimand and honest forward error budget.
The original r1 caveat, r2 non-superiority and failed consumed CORE c1 remain;
this TRAIN diagnostic does not reopen or reinterpret them. This is a controlled
text/image task with a12-code decoder, not an open-world multimodal result.

No runtime permission/resource blocker remains. A later saved-array report
launch without PYTHONPATH failed at import before loading data; the successful
launch sets PYTHONPATH=.; both launch identities are recorded separately and the
model diagnostic was not repeated.
