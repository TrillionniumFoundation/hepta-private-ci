# Variance-aware paid-audit follow-up

**Result: empirical Bernstein changes interval widths but does not change any
adoption decision in this fresh draw.** Both methods adopt 3 of 36 cells: the
three `smooth_positive` direct-sampling cells. All 27 fitted-method cells return
`no-update` under both methods. The original all-fitted-method no-update result
in [paid.json](evidence/paid.json) remains retained and is not replaced.

## Frozen protocol and evidence

This is a declared exploratory follow-up after observing the original
Hoeffding failure. [The protocol](evidence/variance_followup.protocol.json) was
written before the new validation draws. It keeps the saved predictors,
coefficients and MSE-based allocations from [paid.lock.json](evidence/paid.lock.json).
There is no refitting, confidence-driven allocation search, or selection of the
smaller bound. Fresh stream phases are 30 for paid pairs and 31 for resets.

The 36 cells are three tasks, seeds `57101`, `57102`, `57103`, and four methods
(`direct`, `poly1`, `poly3`, `tanh16`). The two fixed confidence methods share
each cell's observations. The family size is **K = 72** at delta = 0.05,
including both confidence methods. This run has one validation sample set per
frozen cell, not repeated draws for estimating power.

[variance_followup.json](evidence/variance_followup.json) retains the paired
candidate/baseline outcomes, predictor values, reset predictions, allocations,
both decisions and intervals, charges, and source hashes. Its SHA-256 is
`2fdc9c1c951ffa210abac5b24151a1696770fbc6fd46ae9f386767ffe4e740c0`.
The parent lock SHA-256 is
`e8502eb1138c056a10779e88495928fa4b1b4199fae9b87a13a8c69e69fe07fb`.

## Exact decisions and interval-width changes

Every row below covers all three listed seeds. Radii are arithmetic means over
those seeds, in exponential-moment-difference units; full interval width is
twice the radius. The percentage is `100 * (mean_EB / mean_H - 1)`.

| Task | Method | Hoeffding adopts / 3 | EB adopts / 3 | Mean H radius | Mean EB radius | Width change |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| smooth_positive | direct | 3 | 3 | 0.162938 | 0.096007 | -41.08% |
| smooth_positive | poly1 | 0 | 0 | 0.415193 | 0.367373 | -11.52% |
| smooth_positive | poly3 | 0 | 0 | 0.431230 | 0.384599 | -10.81% |
| smooth_positive | tanh16 | 0 | 0 | 0.811685 | 0.723011 | -10.92% |
| noisy_candidate | direct | 0 | 0 | 0.162938 | 0.103030 | -36.77% |
| noisy_candidate | poly1 | 0 | 0 | 0.185837 | 0.130993 | -29.51% |
| noisy_candidate | poly3 | 0 | 0 | 0.185837 | 0.130908 | -29.56% |
| noisy_candidate | tanh16 | 0 | 0 | 0.186613 | 0.132033 | -29.25% |
| symmetric_null | direct | 0 | 0 | 0.162938 | 0.117664 | -27.79% |
| symmetric_null | poly1 | 0 | 0 | 0.530195 | 0.609364 | +14.93% |
| symmetric_null | poly3 | 0 | 0 | 0.547131 | 0.629483 | +15.05% |
| symmetric_null | tanh16 | 0 | 0 | 1.228905 | 1.516388 | +23.39% |

EB narrows 27 of 36 intervals and widens nine. All nine wider intervals are
the fitted-method `symmetric_null` cells. Thus a variance-sensitive bound is
not uniformly narrower once its finite-sample support correction is included.
All 27 fitted-method intervals still have nonnegative upper endpoints, so none
certifies even the negative moment-difference sign before the fee subtraction.

The `noisy_candidate` fitted-method allocations have frozen beta = 0 and no
resets: they fall back to direct sampling after paying setup. Their row labels
identify the attempted fitted method, not an active control-variate estimator.
Their width reductions cannot be attributed to predictor variance reduction.

For the three accepted `smooth_positive` direct cells, each uses 1,024 pairs.
The net gain lower bounds after the full declared fee are
0.000872--0.001535 with Hoeffding and 0.045562--0.046225 with EB. These are bounds
for the same fixed simulated comparison, not estimates of learned-policy gain.

## Bound used

The primary result is Maurer and Pontil, *Empirical Bernstein Bounds and Sample
Variance Penalization* (2009), [Theorem 4, PDF page 2](https://arxiv.org/pdf/0907.3740).
For iid Y in a fixed interval of width R, N >= 2, and
`s_Y^2 = sum((Y_i - mean(Y))^2)/(N-1)`, the one-sided radius at failure
probability delta_Y is

\[
r_{\rm EB}(N,\delta_Y)=
\sqrt{\frac{2s_Y^2\log(2/\delta_Y)}{N}}
+\frac{7R\log(2/\delta_Y)}{3(N-1)}.
\]

The implementation applies this to `A = D - beta*H` and to the independent
reset term `W = beta*H'`. It allocates error across all sample-count prefixes:

\[
\alpha_{j,m,n}=\frac{\delta}{K m(m+1)n(n+1)}
\]

when beta is nonzero, and uses the one-dimensional version otherwise. Giving
each of the two streams and two directions alpha/4 yields **log(8/alpha)** in
the radius. The reset radius scales by `abs(beta)`. The support correction
remains even at zero empirical variance. All support bounds are protocol
bounds, not observed sample ranges. Predictors and coefficients stay frozen,
and the main/reset inputs have the same specified predictor marginal law.

The retained gate requires the moment-difference upper endpoint `d_U < 0` and
then tests

\[
-\frac{d_U}{\eta M_{\max}}
-\text{full declared audit charge}-\text{value penalty}>0.
\]

The bound remains a local, frozen-continuation result. Neither the formula nor
these samples establish full-policy improvement or a novel confidence theorem.

## Accounting and limits

The fresh run uses **23,605 pairs and 199,123 resets**, counted once despite
reuse by the two confidence methods. No new fitting or pilot calls occur.
Every standalone certificate still pays the full inherited setup charge;
there is no assumed amortization. Per-cell recorded charges range from
0.010230184 to 0.010240000 synthetic utility units under the declared budget.

The tariff prices simulated sampling, continuation/prediction and fitting
counters. Allocation search, statistical arithmetic, hashing, audit
construction and output are not fully priced. Recorded total CPU time is
1.210114 seconds and wall time is 1.337886 seconds; those measurements include
both bound methods and do not establish a hardware or economic efficiency
advantage for either method. Returned `no-update` preserves the baseline
decision but does not reimburse spent validation charges.

This run supports the specific conclusion that EB alone, with the same frozen
allocation and paid budget, did not rescue adoption for the fitted methods.
It does not estimate long-run acceptance power, false-acceptance frequency,
or a universal ranking of control variates. The original negative result,
the new negative result, and the changed interval widths are all part of the
evidence.
