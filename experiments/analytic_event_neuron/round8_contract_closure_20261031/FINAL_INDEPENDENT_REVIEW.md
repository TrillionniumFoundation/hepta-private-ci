# Final independent statistical and execution review

## Finding

The recorded experiment is internally consistent. Full raw-record replay,
independent aggregate arithmetic, a separate reconstruction of the registered
bootstrap, and a direct policy/DP timing check all pass. The fresh registered
comparisons do **not** establish a positive first-passage-cell advantage.

One empirical heldout contrast has a wholly negative registered bootstrap
interval, but its exact finite-law expectation has the opposite sign. The
discrepancy is compatible with the limited paired-world sample and the fragility
of a percentile bootstrap over only five realized blocks. It must not be
reported as a proven architectural disadvantage. The exact full stage matrix
also contains an ordinary readout-only controller with higher expected utility
than the final first-passage controller. Both facts matter; neither permits
selecting a new checkpoint from these heldout outcomes.

This review adds post-freeze diagnostics only. It changes no registered primary
analysis, candidate, source input, or selection decision.

## Identities and sample size

- Frozen commit: `96270fb1c3d153f0fe48c996d6f7b0b4cede34ef`.
- Freeze SHA256: `f4edffc4451697fd543bdf0e10dc7242297c13f38f8c96d21bc8d7c68355988e`.
- Raw trajectory archive SHA256: `e7ca54d67dbab68c9ad765b1959d815d322882027717a9f9ef52f557c33f882b`.
- 46,080 complete trajectory records, 36 arms, two regimes, five original fits.
- Each regime has **640 distinct external worlds**, comprising 128 worlds per
  fit, balanced as 16 worlds in each of eight configurations. The arms reuse
  those worlds. The record count is not a count of independent worlds or fits.
- The registered sampling unit is one original fit and its complete paired
  world block. There remain five independent fit units, not 46,080.

All 123 frozen inputs were verified before and after the independent audits.

## What was independently checked

`posthoc/independent_confirmation_audit.py` checked every raw identity, world,
configuration and latent seed; complete coverage of all 360 fit/arm/regime
blocks; and all 2,880 configuration strata. It regenerated the actual external
worlds and replayed **159,462 external transitions**, including legal greedy
actions, STOP timing, revealed observations, terminal answers and outcomes.

Task costs, event charges, decision charges, per-step timing/packet counters,
episode totals, analysis means and every one of the 28 reported contrasts were
recomputed. The maximum discrepancy in registered utility arithmetic was zero;
summation-order discrepancies in fit totals were at most `1.99e-13`.

The bootstrap was independently reconstructed from the 126 compositions of
five draws among five fits, weighted by their multinomial multiplicities. This
produces the same 3,125 draws as the registered ordered-index enumeration.
Maximum interval-endpoint discrepancy was `9.54e-16`. The six primary tests use
the frozen 99.166667% intervals; secondary intervals remain descriptive.

All **2,560 paired Gaussian/probit trajectories** have exactly identical
actions, Q values, state moments, endpoint partitions, task outcomes and packet
lengths. They are the same policy expressed through equivalent operators, not
additional independent evidence.

The exact expectations were separately connected to actual hard deployment by
`posthoc/policy_dp_parity.py`:

- All 60 candidate models and all **7,680 heldout calibrated-hard trajectories**
  were covered, comprising 25,877 incoming internal transitions.
- Each transition was resampled from the DP's matrix using an independently
  reconstructed SHA key and categorical inverse CDF. Every sampled latent state
  and selected action matched the recorded deployment.
- The maximum batched-DP versus per-episode Q difference was `8.05e-16`; the
  corresponding expected-event difference was `2.11e-15`.
- The nearest draw was `1.52e-5` from a cumulative-probability boundary, excluding
  a floating-point boundary flip as the explanation of the observed discrepancy.
- A separately written finite recursion reproduced all 60 heldout expected
  utilities with zero difference. The order was: incoming internal transition,
  observed latent state, greedy action, public successor; current event fees
  were charged once, and future reset/recovery remained in the continuation.

The discrepancy below is therefore not a hard/mean policy mismatch, stale
transition encoder, missing successor branch, or one-tick ordering error in the
checked finite implementation. This does not certify a continuous OU model or
its numerical approximation.

## Registered primary results

`Final` denotes the predeclared `content_readout` stage; all comparisons below
use hard deployment. Intervals are the unchanged registered fit-block bootstrap
intervals. They describe these five realized blocks and have no guaranteed
small-sample coverage.

| Regime | Comparison | Observed paired mean | Registered 99.166667% interval | Positive fits |
| --- | --- | ---: | ---: | ---: |
| Nominal | FPT final − direct final | −0.008063 | [−0.029669, +0.000405] | 1/5 |
| Nominal | FPT final − clocked final | −0.008598 | [−0.025602, +0.002218] | 3/5 |
| Nominal | FPT final − FPT baseline | +0.021965 | [−0.007886, +0.059850] | 3/5 |
| Heldout | FPT final − direct final | −0.015766 | [−0.026354, −0.004580] | 0/5 |
| Heldout | FPT final − clocked final | −0.004867 | [−0.038747, +0.020229] | 3/5 |
| Heldout | FPT final − FPT baseline | −0.011853 | [−0.035961, +0.018777] | 2/5 |

None of the six primary intervals establishes a positive effect. The heldout
FPT/direct empirical result is unfavorable, including all five observed fit
differences. That observation must be presented together with the expectation
and sampling analysis, not elevated into an intrinsic architecture ranking.

## Why the Monte Carlo and exact results disagree

The exact numbers integrate all public successor branches and finite latent
states under each fixed candidate. The Monte Carlo numbers average 128 sampled
worlds per fit. They estimate the same hard-policy quantity, as verified above.

For each fit `f`, configuration `c` and paired world `i`, let `d_fci` be the
left-minus-right utility. Each configuration has 16 worlds and weight 1/8.
The additional, conditional Monte Carlo variance estimate is

\[
\widehat{\mathrm{Var}}(\bar d_f)
=\sum_{c=1}^{8}\frac{s^2_{fc}}{16\,8^2},\qquad
\widehat{\mathrm{Var}}(\bar d)
=\frac{1}{5^2}\sum_{f=1}^{5}\widehat{\mathrm{Var}}(\bar d_f).
\]

This uses paired differences within each world, retaining the benefit of common
worlds and latent uniforms. It conditions on the five frozen models and does
not estimate training-seed uncertainty. `final_mc_decomposition.json` retains
all 30 fit comparisons and all 240 fit/configuration strata, including every
paired-world difference.

| Regime | Comparison | Exact mean | MC minus exact | Conditional paired MC SE | Deviation / SE |
| --- | --- | ---: | ---: | ---: | ---: |
| Nominal | FPT final − direct final | −0.001856 | −0.006207 | 0.004548 | −1.36 |
| Nominal | FPT final − clocked final | +0.002314 | −0.010911 | 0.005469 | −2.00 |
| Nominal | FPT final − FPT baseline | +0.015702 | +0.006263 | 0.012609 | +0.50 |
| Heldout | FPT final − direct final | +0.002278 | −0.018044 | 0.011338 | −1.59 |
| Heldout | FPT final − clocked final | +0.002421 | −0.007288 | 0.014449 | −0.50 |
| Heldout | FPT final − FPT baseline | +0.021451 | −0.033304 | 0.016398 | −2.03 |

These are realized sampling deviations, not demonstrated systematic biases.
Deviations of roughly 0.5–2 conditional standard errors are compatible with
finite sampling. The ratio is a diagnostic, not an additional hypothesis test
or proof that every implementation bias is absent.

The heldout FPT/direct comparison is especially instructive:

| Original fit seed | Observed paired difference | Exact finite-law difference |
| --- | ---: | ---: |
| 11 | −0.018877 | +0.007011 |
| 12 | −0.001005 | +0.000306 |
| 13 | −0.029600 | −0.001192 |
| 14 | −0.013370 | +0.000194 |
| 15 | −0.015978 | +0.005073 |

The standard error estimated from the five realized block means is only
0.004608, while the within-configuration paired-world calculation gives
0.011338. Since every observed block difference is negative, every bootstrap
mean formed exclusively from those five numbers is also negative. More
bootstrap resamples cannot repair that restriction. The published negative
interval is correctly computed, but it cannot justify a claim contradicting
the already enumerated expectation of these same finite models.

The appropriate conclusion is that this confirmation is too noisy and contains
too few fit units to establish a broad architecture ranking. The original
registered result remains unchanged; the post-freeze diagnostic explains its
scope instead of replacing it with a favorable reanalysis.

## Complete heldout stage matrix

The exact expectation columns below contain no trajectory sampling noise. They
retain all predeclared stages; no row has been selected for deployment after
observing heldout performance.

| Family | Stage | Exact expected utility | Observed utility |
| --- | --- | ---: | ---: |
| Direct Q | Baseline | 0.637882 | 0.642041 |
| Direct Q | Readout only | **0.653249** | 0.629353 |
| Direct Q | Content/readout | 0.649370 | 0.635329 |
| Projected continuous | Baseline | 0.628843 | 0.616398 |
| Projected continuous | Readout only | 0.647687 | 0.624719 |
| Projected continuous | Content/readout | 0.649304 | 0.626105 |
| Clocked | Baseline | 0.640963 | 0.641988 |
| Clocked | Readout only | 0.651860 | 0.647843 |
| Clocked | Content/readout | 0.649227 | 0.624430 |
| First passage, R7 CTMC | Baseline | 0.630198 | 0.631416 |
| First passage, R7 CTMC | Readout only | 0.651187 | 0.629910 |
| First passage, R7 CTMC | Content/readout | 0.651648 | 0.619563 |

Although FPT's final exact expectation exceeds direct's final expectation by
0.002278, the direct readout-only stage is higher than FPT's final stage by
0.001601. Clocked readout-only is also slightly higher. These are descriptive
full-matrix comparisons, not newly declared primary tests. They prevent a
selective “beat ordinary control” interpretation of the final-stage comparison.

The direct second stage loses about 0.003879 in heldout expected utility; the
clocked second stage loses about 0.002632. More content/readout fitting did not
monotonically improve generalization. The FPT final stage does improve its own
exact baseline by 0.021451, with positive exact improvements for all five fits,
but the ordinary controller improves under the same repair as well. These
results identify controller approximation and optimization effects, not newly
acquired content information from cell dynamics.

Measured Python episode CPU for final FPT is 5.399 ms nominal and 5.265 ms
heldout, compared with direct's 3.040 and 3.049 ms. Those measurements are
shared-host process costs, not physical energy or native/artifact end-to-end
costs. They give no basis for claiming a demonstrated cost advantage here.

## Ninety fixed-encoder/readout kernel exchanges

All 90 raw occupancy/regret tables were recomputed. Their sums match the
reported optimality gaps within `1.01e-16`. Event-free optimal values agree
across all cases within `5.44e-15`.

The following differences average the five seeds **within each anchor family**.
The three anchor families are not pooled into 15 independent fit units.

| Process law | Frozen anchor family | FPT − clocked | Positive fits | Clocked − projected continuous |
| --- | --- | ---: | ---: | ---: |
| R7 finite OU/CTMC | Continuous | −0.000454 | 2/5 | −0.001791 |
| R7 finite OU/CTMC | Clocked | −0.000204 | 0/5 | +0.005614 |
| R7 finite OU/CTMC | First passage | +0.000158 | 3/5 | +0.002075 |
| Common Brownian, leak zero | Continuous | −0.000158 | 1/5 | −0.001956 |
| Common Brownian, leak zero | Clocked | +0.000023 | 4/5 | +0.005762 |
| Common Brownian, leak zero | First passage | −0.000035 | 3/5 | +0.002019 |

The FPT-versus-clocked effect is small and changes sign with the frozen anchor.
The larger clocked-versus-continuous differences also depend on which mechanism
trained that readout. This is evidence of readout/mechanism compatibility. It
does not support a universal first-passage gain, and a favorable single anchor
would be insufficient evidence.

## Interpretation and remaining scope

The public state remains a sufficient statistic. With zero event price, the
optimal value is independent of the internal stochastic cell; positive event
fees bound the cell-specific optimum shift by at most 0.0012 in this task.
Consequently, meaningful learned-policy differences mostly concern fitting,
state representation and costs within an already sufficient control input.
They do not answer the broader raw-content-addressing question for Hepta.

The new Brownian local kernel, the R7 CTMC calibration/native family, hard versus
mean deployment, and the true unbounded Gaussian comparator remain distinct
contracts. Results should retain those labels. Full finite-law agreement does
not remove R7's numerical-diffusion limitations or certify multiple firings
within a tick. The unbounded comparator is a frozen-readout intervention, not
a separately optimized architecture.

No additional fitting, candidate selection, enlarged confirmation sample or
redefinition of a primary endpoint was performed for this review.

## Reproducible post-freeze receipts

- `evidence/final_independent_audit.json`: all-record replay, fit-block balance,
  costs, arithmetic, bootstrap, identity pairs, MC/exact and exchange checks.
- `evidence/final_policy_dp_parity.json`: all heldout hard traces versus the DP
  kernel, action stage, fees and independent finite recursion.
- `evidence/final_mc_decomposition.json`: all per-fit/per-configuration paired
  world differences and conditional variance components.
- Corresponding source files are in `posthoc/`; each receipt records its source
  hash. These sources were added after the frozen candidate experiment and do
  not modify any frozen dependency.
