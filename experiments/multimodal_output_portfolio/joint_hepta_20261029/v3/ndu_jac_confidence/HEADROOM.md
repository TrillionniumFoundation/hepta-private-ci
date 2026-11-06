# Oracle headroom rules out the old paid gate on this fixed task

**The old task has too little remaining utility above the strong actor to pay
its declared `.01` audit fee, even with the true model already known.** This is
stronger than observing wide confidence intervals. Acquiring more samples only
to tighten those intervals cannot make this frozen paid endpoint positive.
It does not rule out other tasks, information/action contracts, or separately
declared cost accounting, and does not establish a new algorithmic advantage.

This appendix adds a diagnostic; it does not change the corrected 20-bank
results, their protocol, fees or source identities. There are zero new samples,
fits, task draws or model invocations.

## Actual known-law comparison

The original finite task has 52 states and 124 legal rows. Its Bellman optimum
under the unchanged `eta=2`, `rho=.17`, complete external reward/cost model is

\[
 V^*=0.25274721905017294\quad\text{(source DP point value).}
\]

The strong baseline is the retained original actor's deterministic
probability-argmax extraction, separately fitted in each old bank. All 20
baseline policies and per-bank results are retained in [headroom.json](headroom.json).

| Banks | Count | Strong baseline value | Remaining point headroom `V* - Vbaseline` |
| --- | ---: | ---: | ---: |
| Seeds 1701, 1703, 2716 | 3 | 0.2515709321087354 | 0.0011762869414375654 |
| Every other retained seed | 17 | 0.25274721905017294 | 0 |
| Arithmetic mean across all retained banks | 20 | 0.25257077600895733 | 0.0001764430412156348 |

For any replacement policy in this same finite information/action class,

\[
 V(\pi)-V(\pi_{\rm strong})-0.01
 \le V^*-V(\pi_{\rm strong})-0.01.
\]

The largest oracle headroom is only about `.001176287`. The independent rational
upper enclosure is strictly below `1177/1000000=.001177`, so every bank's paid
oracle ceiling is strictly less than `-.008823`. Its tighter recorded value is
about **`-.008823713058562412`**. The mean paid oracle ceiling is about
**`-.009823556958784362`**.

Even a deliberately generous arithmetic aggregation cannot pay one shared
`.01` charge: adding the separate headrooms for one scored episode from each
of all 20 banks gives an upper bound about **`.0035288608243127613`**. Charging
only once against that sum still leaves about **`-.006471139175687239`**.
This aggregate means a sum of the 20 separately defined episode CE values; it
is not a new joint 20-episode entropic objective or a claim about shared hidden
labels. The actual per-update fee rule is unchanged.

This does not exclude a separately frozen long-run reuse contract for one
policy. For a baseline with positive headroom Delta, a one-time audit followed
by M scored deployments has the oracle upper expression M*Delta-.01. Here that
expression becomes positive at M=9, before other costs. It is only an upper
possibility bound, not achieved learned-policy gain or a full lifecycle result.

## Independent numerical enclosure

`headroom.py` first runs the existing known-law DP and evaluates every saved
strong baseline. It also independently recurses over the same graph using
rational interval arithmetic, rather than treating a floating solver tolerance
as a proof. Finite source-float metadata are interpreted as exact binary
rationals; each outcome row is normalized in exact rational arithmetic. This
explicit real-valued interpretation of the frozen artifact is the scope of the
enclosure. Source point values agree with it to the stated `1e-12` comparison
check; the exact fractions are retained, not inferred from those point checks.

All arithmetic is rounded outward to a dyadic grid with 80 fractional bits.
For nonnegative `x`, the degree-40 exponential sum is a lower bound, and its
remainder is bounded by the first omitted term divided by
`1-x/(40+2)`; the checked domain is `|x|<=8`. Negative arguments use reciprocal
bounds. Logarithms use

\[
 \log x=2\operatorname{atanh}\!\left(\frac{x-1}{x+1}\right),
\]

with 80 odd-power terms and the geometric remainder bound
`2*z^(161)/(161*(1-z^2))`, restoring the sign when necessary. Rounding each
operation outward retains both series truncation and arithmetic uncertainty.
Monotone CE recursion and row maxima then enclose the optimal value; selected
baseline actions are evaluated by the same independent interval recursion.
Randomized policies cannot improve the Bellman optimum here because action
mixing is outside CE and is linear at each state.

The oracle value interval has width about `1.51374e-22`. The 17 point-optimal
banks have headroom upper enclosures no larger than that width. The maximum
headroom upper enclosure across all banks is the exact fraction

\[
 \frac{1422043654779420360097}{1208925819614629174706176}
 <\frac{1177}{1000000}<\frac{1}{100}.
\]

This narrow arithmetic certificate does not convert the separate confidence
adapter's SciPy quantiles and floating-point propagation into a formal interval
implementation. It certifies only the known-law headroom diagnostic.

## Consequence for further work

Do not spend new calibration budget merely to rescue the old `.01` gate by
narrowing its confidence intervals. The strong baseline has already consumed
nearly all the task's attainable utility. Any new study needs a prospectively
specified task, information contract, or lifecycle/deployment-volume contract
with actual decision-relevant headroom,
then its own complete-cost comparison. The existing negative endpoint remains
unchanged; this appendix supplies a reason for it.

## Replay and identities

From the repository root:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_jac_confidence.headroom \
  --evidence experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac/evidence/gap_study.json \
  --corrected-result experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_jac_confidence/result.corrected.json \
  --output /tmp/ndu-jac-headroom-new.json
```

The runner checks the historical bank input and accepted source identities and
refuses to overwrite output. Its receipt contains the full model fingerprint,
source hashes and exact per-bank enclosures.

- Historical bank artifact:
  `56ad5d043a2ac661b3d0155747851a67e282d7faa42e7fa463ef5b581ca765dd`.
- Corrected result, unchanged:
  `6e0638e3fe9b6003b42aee826dd40cc653e8ac25d87a712dabdd01642444d58d`.
- New headroom result:
  `4952e8f736caf1e5e46d0365ab519ff638faaba9bd3f8bbb01f49f3b62d49133`.
- New headroom source:
  `64ce7d4d9100939a6d86793df7b6888044f559f668203edc69a9d5430090fc2f`.
