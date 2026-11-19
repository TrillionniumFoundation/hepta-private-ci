# Explicit grouped input-view and output entropic risk

This is a new opt-in training objective, not a reward change, serving change, STE,
clip-derivative replacement or unbiased-Adam claim. Previous per-input NDU profiles
remain unchanged. Existing scientific NDU failures remain failures; this package
currently qualifies the analytic chain only, not generation benefit.

For equal groups of K input views, let CE_i be the original output-law entropic
certainty equivalent at fixed rho. Define

    group_CE_g = -log(mean_i exp(-rho * CE_i)) / rho
    loss = -mean_g group_CE_g

The unchanged utility helper returns logit gradients d_i of negative MEAN row CE,
including 1/n. Therefore the exact new chain is

    d_group_i = K * softmax_within_group(-rho * CE_i) * d_i

This equals entropic risk of the joint uniform-view / generated-output law at
fixed rho by expanding the expectation. At rho=0, the group mean and gradient
reduce to the ordinary mean-row additive objective. K=1 preserves the original
row objective exactly. The supervised anchor is **excluded**: if used, its ordinary
row-mean gradient must be added separately, never multiplied by these risk weights.

`GroupRiskProfile` explicitly binds mode `equal-group-input-output-entropic-risk-v1`,
rho (0 or 1.5), K, contiguous canonical equal-size groups, normalization convention
and anchor exclusion under a distinct schema/key. Rewards and group membership
are constant inputs. The RGB reference wrapper uses twelve classes per head and
reward bounds [-.35,1]. Empty, heterogeneous/interleaved/noninteger groups, mixed
modes, nonfinite inputs and out-of-profile rewards reject without epsilon repair.
No model checkpoint compatibility is promised.

## Qualification, not a science result

Six handmade tests passed. Eight central finite-difference coordinates cover both
heads and both groups, with maximum absolute error **5.73e-11** versus the fixed
2e-8 bound. An independently flattened view/output expectation and tilted-logit
gradient agree with the chain. Other cases cover rho=0/K=1 exact gradient parity,
identical rows, constant reward, group/view permutation, zero-sum logit gradients
and explicit identity/input refusals. The qualified literal fixture uses K=2;
future K=8 sampler and transported-anchor integration need separate qualification.
The mathematical chain applies to arbitrary supported equal K, but these finite
tests are not a claim over all floating-point inputs.

Whole waited qualification: **0.144417 CPU seconds**, 0.165322 wall seconds,
27812 KiB RSS under 5 CPU / 30 wall / 512 MiB / 4 MiB, CPU 0, one numerical thread,
existing shared synthetic lock, no retry. All fixtures/imports/checks are included.
No model restore, training update or dataset row. Earlier research, source/review
and unknown supervisor tails are additional, not zero.

The planned next comparison is additive / row-NDU / group-NDU using identical
source-masked models, grouped minibatches, update counts and FIT calibration.
Risk over a sampled subset of views must not be called an unbiased estimate of
full-group risk. Actual coupled/calibrated serving, original rewards and original
quality gates remain the evaluation target. No positive benefit is assumed.

## Portable tests

The unchanged published parent `utility.py` is required:

```sh
PYTHONPATH=.. python -B -m unittest -v test_grouped_risk
```

Only portable helper, tests, fixed plan and aggregate receipts are public. No
weights, private inputs, runtime paths or per-request model outputs; no default
change, deployment or unrestricted scientific runner.
