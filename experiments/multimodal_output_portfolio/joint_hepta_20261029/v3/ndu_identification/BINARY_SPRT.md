# Exact binary SPRT: a cost lower-bound reference

**A separate fixed-confidence experiment, 2026-11-05.** This is a numerical
connection to the companion decision-relevant identification theorem. It is a
classical known-law binary sequential test, not a new NDU algorithm. Its
objective is uniformly small identification error with low expected sampling
cost; the adjacent 18-case experiment instead maximizes Bayesian discounted
net utility. Neither objective can be substituted for the other.

The [protocol](binary_sprt.protocol.json) was written before execution. It fixes
p=7/10, per-query fee c=1/200, deterministic duration tau=1, nine error targets,
and nine deadline caps. The choice p=.7 follows the preceding theory instance;
it was not selected by these results. Likelihoods are known, query observations
are IID under each hypothesis, and query costs and durations are constant. The
time unit is a declared model unit, not a measured tool latency.

## Exact formula and information denominator

Under H=+, a query returns Y=1 with probability p and Y=0 with probability q=1-p;
under H=- these probabilities swap. The log likelihood increment is +a or -a,
where a=log(p/q), and the directed KL in either direction is D=(2p-1)a.
For a requested 0<delta<1/2, use the theorem's conservative Ville threshold
b=log(1/delta). The integer walk stops at +/-m, where

\[
m=\min\{j\ge1:(q/p)^j\le\delta\}
  =\lceil b/a\rceil.
\]

The code finds m with exact rational comparisons, avoiding a floating-point
ceiling error at lattice boundaries. Put r=q/p. Gambler's ruin gives the exact
error and expected sample count under either hypothesis:

\[
\epsilon_m=\frac{r^m}{1+r^m},\qquad
E N=\frac{m}{2p-1}\frac{1-r^m}{1+r^m}.
\]

For completeness, the hitting probability solves h(s)=p h(s+1)+q h(s-1),
h(-m)=1, h(m)=0. Its solution at s=0 is epsilon_m. Absorption has finite mean
because, from every transient state, a run of 2m equal increments exits with
uniformly positive probability. Wald's identity therefore applies. Since the
terminal walk equals +m with probability 1-epsilon_m and -m otherwise,
(2p-1)E N=m(1-2epsilon_m), proving the second formula. The implementation also
solves both transient recurrences by an independent rational tridiagonal
method: all nine closed-form pairs match that solver **exactly**.

The stopped change-of-measure lower bound for any uniformly delta-correct rule
in this model, and the theorem's bounded-increment upper bound, are

\[
L_\delta=\frac{\operatorname{kl}(1-\delta,\delta)}D
\le E N\le
U_\delta=\frac{\log(1/\delta)+a}D.
\]

Expected cost lies in [c L_delta, c U_delta], and expected model time in
[tau L_delta, tau U_delta]. These are undiscounted resource statements.
At the **achieved** error epsilon_m, the identity
D E N=kl(1-epsilon_m,epsilon_m) is exact. Relative to the requested delta, the
integer threshold can be conservative; the ratio tends to one as delta tends
to zero, but need not decrease monotonically on a finite grid. This is an
explicitly narrow classical benchmark, not a neural or unknown-law guarantee.

## All nine unlimited-time cells

Exact rational values are retained in
[evidence/binary_sprt_reviewed/results.json](evidence/binary_sprt_reviewed/results.json).
The table rounds for readability; no simulation, standard error, or Monte Carlo
confidence interval is involved.

| Requested delta | m | Actual error | Exact E N | KL lower L | Upper U | E N / L |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| .2 | 2 | .155172414 | 3.448275862 | 2.454203697 | 7.248737096 | 1.405048760 |
| .1 | 3 | .072972973 | 6.405405405 | 5.186427773 | 9.293906844 | 1.235032220 |
| .05 | 4 | .032634972 | 9.347300564 | 7.818959557 | 11.339076592 | 1.195466033 |
| .02 | 5 | .014252199 | 12.143695015 | 11.023713327 | 14.042643940 | 1.101597498 |
| .01 | 6 | .006158239 | 14.815252834 | 13.286996414 | 16.087813688 | 1.115018953 |
| .005 | 7 | .002648566 | 17.407300207 | 15.462011712 | 18.132983435 | 1.125810828 |
| .001 | 9 | .000487525 | 22.478061362 | 20.338010962 | 22.881720532 | 1.105224174 |
| .0001 | 11 | .000089581 | 27.495073039 | 27.169897239 | 29.675627376 | 1.011968238 |
| .000001 | 17 | .000000555 | 42.499952814 | 40.763356586 | 43.263441063 | 1.042601895 |

For delta=.05, expected query cost is .0467365028, versus the information cost
lower bound .0390947978; expected elapsed model time is 9.3473005641. That
19.55% cost gap is proved/computed for this one known-law model. It says nothing
by itself about whether buying the observations is worth their external payoff.
The delta=.0001 and .000001 ratios, 1.01197 and 1.04260, also demonstrate why a
finite-grid statement of monotonically improving ratios would be incorrect.

## Hard deadlines invalidate automatic reuse of the guarantee

The second block retains all **81** (delta, query-cap) cells. It propagates
rational transient and absorbed mass for at most n observations. At the cap,
unabsorbed paths are forced to decide by sign of the sufficient statistic;
a zero tie is resolved by a fair independent coin. The reported error is
**unconditional**, including these forced decisions. The unresolved mass is
reported separately; discarding it would misrepresent accuracy.

For delta=.05:

| Query cap | Unresolved at cap | Forced-decision error | Exact E min(N,cap) | Full-cap optimal error | KL obstruction |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 1.000000 | .500000000 | 0.000000000 | .500000000 | Yes |
| 5 | .751800 | .163080000 | 4.751800000 | .163080000 | Yes |
| 8 | .390073 | .126036000 | 6.590224000 | .126036000 | No |
| 10 | .279741 | .099586584 | 7.370370640 | .098808660 | No |
| 20 | .053006 | .045319961 | 8.972717715 | .032553357 | No |
| 50 | .000361 | .032721258 | 9.344752575 | .001651364 | No |

`KL obstruction` means nD < kl(1-delta,delta), a sufficient certificate that no
uniformly delta-correct policy can meet the cap in this single-query model.
Its absence is **not sufficient** for feasibility: at cap 8 the inequality
passes, but even the optimal full-eight-observation rule has error .126036.

The stronger `optimal_full_cap_error` is computed exactly from the binomial
majority rule, with fair ties. The full n-observation experiment can simulate
any stopped rule using at most n observations. Its likelihood-ratio rule
minimizes equal-prior Bayes error and has symmetric conditional errors. Hence,
if its error exceeds delta, no cap-n rule can satisfy both conditional error
limits. A truncated SPRT can also be worse than this full-cap rule, as cap 10
shows. At cap 20 the particular truncated SPRT happens to meet .05, by the new
exact enumeration, not by importing the unlimited-time theorem.

## Verification and reproduction

Six new behavioral tests passed: independent formula/chain agreement,
one-step absorption, the invalid five-step transfer, zero deadline, and exact
lattice-boundary selection, and rejection of the reversed-success parameterization. The 18-case model/study code and original result
files were unchanged. New module and tests total 171 lines.

```bash
python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_identification.test_binary_sprt -v
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_identification.binary_sprt --output /tmp/ndu-binary-sprt-new
```

The result SHA-256 is
`c69fdfe6fb3233cdcb06b70969e581d870f22d79a3e5def75077b488bef37dd9`.
Protocol and source hashes are inside that result. Rational fractions are
serialized as exact strings; only natural logarithms in the information bounds
use floating point. The experiment does not cover learned likelihoods,
state-changing/nonresetting interventions, random informative durations,
parallel scheduling, or the economic optimum for a discounted external task.

A separate internal code review found that the deadline helper initially accepted p<1/2,
where calling an ordinary success-majority error optimal would be incorrect.
Its domain is now explicitly p>1/2, matching the registered model and main
SPRT function. The original run/source snapshot is retained in
`evidence/binary_sprt`; all 90 registered numerical rows are identical in the
reviewed result. Only source identity and validation coverage changed.
