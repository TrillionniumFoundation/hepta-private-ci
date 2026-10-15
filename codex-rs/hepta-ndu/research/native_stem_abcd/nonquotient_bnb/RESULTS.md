# R19 completed: global cost bound for a genuinely non-quotient positive-risk two-step Stem

## Provenance and model
Research-only Draft stacked on R18 #2073 at commit `02c2bd45592dbe4c4156cd08fb52f58811336f1a`. Protocol pushed **before all efficacy fits** at `dfc8a50c329c75266ab3251f6040326f4e68ba62`. The two-step 16-case known stochastic law, two strictly positive entropic risks, preference transitions, discounts, input and terminal target are unchanged. New forward term `q(a)=a/[25(1+a²)]` changes the full objective under parameter sign reversal even at fixed `ab` and `(a-b)²/4`. R18's exact convex *parameter* quotient no longer applies.

## Actual rigorous finding and its limit
The inherited auxiliary function `F(t,u)=C(t,u)+t/2+u` remains globally `m=81/50` strongly convex. The actual objective is `J(a,b)=F(ab,(a-b)²/4+q(a))-q(a)`, not a convex program over independent feasible `(t,u)`. At the frozen rational candidate `a=164044199/100000000, b=42331393/100000000`, an independent outward exact-rational gradient enclosure, globally valid strong-convexity minorant, analytic rational q-bounds, and a full-cover box frontier on `[-3,3]²` establish that **candidate population cost minus the unrestricted global infimum is at most 0.000698987672**. This passed the predeclared 0.001 gate after **16 exact dyadic splits**, versus a 50,000-split cap. A separately disclosed **post-hoc** tighter bound of **0.000097943430** was obtained after **53 splits**, with no fitting/selection changes. All fractions and boxes, including rounding proof and finite-weight-domain exclusion, remain in the conversation packet. No unique global argmin or general nonconvex FBSDE theorem is claimed.

## Executed matched controls and adverse outcomes
**64/64 fresh-process fits, zero execution failures, 60/64 weights changed, 4,298 full optimizer checkpoints.** 8 fixed initializations x4 solver classes x2 forward variants. Both variants share initial bytes, information and population, but DIFFERENT forward objectives, so cross-variant completion counts are not universal method speedups. Per-method success counts at the predeclared after-fit global cost-gap upper <0.001:

| Method | New nonquotient | Eta=0 control |
| --- | ---: | ---: |
| Adam | 3/8 | 0/8 |
| BFGS | 3/8 | 0/8 |
| L-BFGS-B | 4/8 | 0/8 |
| trust-exact | 4/8 | 7/8 |

The eta0 origin is a stationary negative-curvature saddle, whereas the parameter-specific term gives the origin a nonzero derivative in a, approximately 0.06576, so some starts leave it. Generic strong baselines retain other adverse stationary regions. No unique native/explicit NDU optimizer advantage was shown. Full failures and censored cases are present, not selectively removed.

## Independent replay, exceptions, resources
18 new mathematical/mechanism tests +25 unchanged R18 tests +8 actual-data tamper tests under Python -O = **51 distinct checks passed, zero skips**. The read-only audit replays all 4,298 candidate checkpoints with maximum cost difference zero, all 16 independent preference/branch configurations per candidate with max discrepancy `4.44e-16`, seals, law, methods, starts, gradient/Hessian and timing. It rejects missing runs, altered weights/checkpoints/starts, rehashed fake costs, impossible CPU times, forged source, and injected reference labels. A preliminary source-path typo prevented the first attempted sweep from starting ANY efficacy fit; its error log is retained, and the corrected 64 runs were complete, not selectively retried. Separate smoke fit not counted.

Sweep: **77.190765 wall /75.659803 whole-child CPU seconds**, including import/process/serialization. Actual fitting alone uses **15.634257 CPU seconds** inside those totals. Independent audit **7.046775 CPU seconds**. Tamper tests about 8.42 wall seconds and packaging/connector/test costs additional. Peak recorded RSS roughly 125.85MB with allocator overhead. Complete FLOPs, GPU, energy and hardware-attested physical cost unavailable.

## Files, CI, interpretation
Standalone executable source, rational global-bound algorithm, tests, run census and independent audit are in this directory. Remote text source is compared to executed source by exact Git blob SHA; earlier R18 source is untouched. The ZIP archived for the user retains ALL 64 exact final/initial tensors, every checkpoint, full logs, both exact rational box frontiers, original source, seals and negative outcomes, while Git contains a concise result and digest index rather than claiming binary checkpoint ingestion. The exact-head workflow is read-only and replays all trials/tests; global blocking-ci must pass independently and is not waived.

**Research boundary:** restricted two-weight, fully known discrete 16-leaf positive-risk family, no globally unique optimizer theorem, no unknown-state model/LLM generalization, no project cloud/native Neuron deployment, and no main/CURRENT/production merge.