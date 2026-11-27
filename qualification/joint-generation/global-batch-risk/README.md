# Explicit global64 input/output entropic risk

**Qualification passed, not a scientific benefit result.** This new opt-in objective
uses the uniform whole 64-row minibatch, rather than averaging eight separate
content-group risks. The original grouped helper and old training modes are unchanged.

For row output-law certainty equivalents c_i and fixed rho,

    C_global = -log(mean_i exp(-rho*c_i))/rho
    d_global_i = 64*softmax_i(-rho*c_i)*d_row_i

The supplied d_row already differentiates negative MEAN row CE (includes 1/64).
For equal eight-row groups, the same result is obtained by multiplying each old
group gradient by 8*softmax_group(-rho*C_group). Ordinary .2 row-mean anchor is
added separately, never risk-weighted. At rho=0 the original additive gradients
are preserved exactly. This is a new finite-minibatch surrogate, not an NDU bugfix,
STE, reward change, serving-law change or unbiased full-FIT-gradient estimate.
Adam is not guaranteed unbiased. Hard-content-group weighting can differ from
within-scene view robustness; neither alone guarantees generation improvement.

The explicit profile binds mode `global-batch-input-output-entropic-risk-v1`,
schema `rgb-global64-risk-objective-v1`, exactly64 rows, rho0 or1.5, row-gradient
normalization and anchor exclusion. Old group profiles, other batch sizes,
nonfinite values and wrong shapes reject. No model checkpoint compatibility is
promised. No default or deployed behavior changes.

## What was verified

All13 literal tests passed: nine unchanged group-risk/integration tests and four
new global64 tests. A hand-written heterogeneous64-row fixture verifies direct
flattened input x output expectation, two-level risk and gradient equivalence,
Jensen ordering, both-head finite differences, unweighted-anchor separation,
zero-rho exact parity, constant-row unit scales, permutation covariance, zero-sum
logit gradients, mode/shape/nonfinite refusals and input immutability.

Eight utility-only finite-difference coordinates had maximum error5.89e-11;
eight complete utility+.2ordinary-anchor coordinates had maximum error4.88e-11,
both below the prospective3e-8 bound. These finite tests do not establish universal
floating-point behavior or any science outcome.

Fully waited qualification cost **0.247142 CPU seconds**,0.268822 wall seconds,
30912KiB RSS under5CPU/30wall/512MiB/4MiB, CPU0, one numerical thread and the
existing synthetic-only lock. All imports, tests, checks and output are included;
zero model restores, training updates or scientific dataset rows. Source/review,
shared upstream research and unknown supervisor tails are additional, not zero.

The unrestricted-policy Bayes-action argument in PLAN applies only without the
actual training anchor, finite-softmax/shared-network and optimizer constraints.
It does not prove NDU is useless in this neural task. Independent-output training
versus coupled/calibrated serving mismatch remains. The separately planned science
keeps A/groupN controls, fixed300steps, old FIT calibration and all original five
quality gates; no benefit is assumed and old failed studies remain failed.

## Portable tests

Use the already published sibling helpers and parent utility/control modules:

```sh
PYTHONPATH=../grouped-view-training:../grouped-view-risk:../explicit-semantic-transport:../transport-aligned-training:.. python -B -m unittest -v test_global_risk
```

Only portable source/tests, the executed plan and aggregate validation are public.
No weights, private inputs, per-request predictions, runtime paths or unrestricted
scientific runner; no merge or deployment.
