# Fixed-zero exponential score: mathematical qualification

**17 literal tests passed; no scientific benefit evaluated.** This explicit opt-in
surrogate removes the random whole-batch risk denominator while retaining rho1.5,
the original reward units/zero and an ordinary, unweighted supervised anchor.
It is not the original logarithmic NDU objective or a bug repair.

    s(R) = (1-exp(-rho*R))/rho
    mean_score = mean_i[-expm1(-rho*c_i)/rho]
    d_score_i = exp(-rho*c_i)*d_row_i = Z_batch*d_global_i

Here c_i is output-law CE at the same rho, d_row differentiates negative MEAN row
CE and already includes1/64, and Z_batch=mean_i exp(-rho*c_i). The helper computes
this exact analytic composition, not a detached-weight approximation. The ordinary
.2 anchor is added separately. Its relative strength therefore differs from global
risk; these regularized objectives and Adam trajectories are not equivalent.
Reward translation multiplies utility gradients by exp(-rho*b) but leaves anchor
unchanged: this surrogate loses that anchor-relative shift invariance. Reward zero
is fixed prospectively, never optimized. At rho0 the additive mean/gradients are
returned exactly for finite outputs.

For fixed parameters and dataset, a plain mean gradient has the correct sampling
expectation under equal inclusion probabilities (the fixed group/view sampler).
This is not an unbiased logarithmic-risk gradient or a claim about Adam updates.
The independent-training/coupled-calibrated-serving mismatch also remains.

## Qualification and boundaries

Thirteen prior tests/helpers are unchanged; four new tests cover a hand-written
heterogeneous64-row fixture, direct transformed-reward expectation and gradients,
Z_batch times global-risk identity, both-head utility/full-anchor finite differences,
rho0, constant-row scaling, reward-shift/anchor invariance, identity separation,
128-row/shape/nonfinite/overflow refusals and input immutability. Transformed scores
can fall below the original RGB reward bound and are not sent through that bounded
reward wrapper. The profile fixes64 rows, rho0 or1.5, reward zero/units and separate
anchor; it rejects old global/group modes. Upstream same-rho array provenance is
an explicit caller contract, not inferable from bare arrays.

Maximum errors were2.19e-11 for eight utility coordinates and2.81e-11 for eight
complete ordinary-anchor coordinates, versus the fixed3e-8 bound. V1/v2 were never
executed. Independent source review found rho0 finite-input mean overflow; v3
added rejection plus its literal case before the first numerical run. Expected
RuntimeWarnings occur only in deliberate refusal fixtures; no floor/epsilon repair.

Fully waited cost: **0.256208 CPU seconds**,0.266841 wall seconds,30952KiB RSS,
under5CPU/30wall/512MiB/4MiB,CPU0,one numerical thread,existing synthetic lock,
no retry. Zero models restored, training updates or scientific dataset rows.
Tests/imports/checks/output are included; earlier research, source/review and
unknown supervisor tails are additional, not zero.

The separately proposed A/globalN/score experiment retains original rewards at
serving and original five quality gates. Even a future score improvement would
not establish that original NDU beats A. Current negative studies remain negative.

## Portable tests

```sh
PYTHONPATH=../global-batch-risk:../grouped-view-training:../grouped-view-risk:../explicit-semantic-transport:../transport-aligned-training:.. python -B -m unittest -v test_exponential_score
```

Only portable helper/tests, executed plan and aggregate validation are public;
no model weights, private inputs, per-request predictions, runtime paths or
unrestricted scientific runner. No default change, merge or deployment.
