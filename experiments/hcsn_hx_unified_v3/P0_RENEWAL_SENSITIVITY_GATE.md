# P0 scalar renewal-boundary sensitivity gate (research only)

**DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**
Parent is PR #4435 exact HEAD `8f89b83c0f08d03cdefead83332390cdc0bf1bab`. No change to existing finance HX, `stopping.py`, QVI, learning, Rust, GPU, authority, original evidence or deployment. Added two independent research Python files. This gate does not resolve sibling P0 work based on #4436.

## Mathematical contract

For the **scalar, frozen-coefficient** Brownian regenerative stopping problem, let `k>0` solve

`mu*k + sigma**2*k**2/2 = rho`.

The free-boundary root solves
`k*(b-K) - 1 + exp(-rho*tau - k*(b-reset))=0`.
Set `t=k*(b-K)` and `q=1-t`; in the admitted domain `0<t<1`.
Then `dt/dh=q/t` for `h=k*(K-reset)+rho*tau`, and
`b=K+t/k`. The new module uses these exact identities to calculate six local derivatives: drift, diffusion, discount, cost, reset and refractory.

This is **not** the coupled He--Xiong financial derivative or the neural task-value gradient. Roots near the coalescing branch, tiny boundary separation, unrepresentable discriminant, and nonfinite derivative arithmetic are explicitly refused. The numerical guards are conservative diagnostics, **not interval-certified error bounds**. They do not establish full-domain smooth pasting, an all-network QVI, or gradients at physical event/active-set switches.

## Executed CPU evidence

- Python 3.13.5, SciPy 1.17.0, mpmath local, Linux CPU.
- Exact existing parent `stopping.py` Git blob `b4754eca87ee225d56a110b3408c4047e4f4e66f` was reconstructed and verified using `git hash-object`. Five existing test files used in the combined run were also checked against their upstream Git blobs.
- Six new `unittest` methods, including five fixed regimes × six parameters with independent 90-digit mpmath reference, 128 deterministic seeded parameter-direction probes, f64 central differences, sign conditions, and negative-domain/ill-conditioning refusal.
- The 128 probes produced **121 accepted numeric comparisons and 7 explicit refusals**. These refusals are not counted as successful derivative comparisons or evidence of complete parameter coverage.
- Local selected suite: **28 / 28 PASS, 0 skipped**, consisting of the six new tests plus 22 existing scalar P0 tests; `python -m compileall -q` passed. No full repository checkout, complete HX suite, GPU test or CI result is claimed.

Run from repository root with local `scipy` and `mpmath` available:

```bash
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_renewal_sensitivity \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint \
  experiments.hcsn_hx_unified_v3.test_stop_kappa_scale \
  experiments.hcsn_hx_unified_v3.test_qvi_stability \
  experiments.hcsn_hx_unified_v3.test_qvi_stress \
  experiments.hcsn_hx_unified_v3.test_qvi_sibling_finite
python -m compileall -q experiments/hcsn_hx_unified_v3/renewal_sensitivity.py \
  experiments/hcsn_hx_unified_v3/test_renewal_sensitivity.py
```

New locally executed/remote-verified Git blob identities:
- `renewal_sensitivity.py`: `48ae18f64cf6d7b93227b37f786730be60f161e1`
- `test_renewal_sensitivity.py`: `d507ab43e591359c626975b7d2954ea765425c84`

## Remaining research/production blockers

- **P0:** coupled HX finance global obstacle/fixed-point and entire parameter domain, independent certified intervals/low-precision boundary, event/branch gradients.
- **P1:** matched same-information/slope/active-parameter/complete-budget causal advantage absent (retained historical 0/4 mechanism result).
- **P2:** physical repeated events, Selective Copy, MQAR, overwrite, unseen lengths and recovery.
- **P3:** genuine paired text/image/audio/video holdout and OOD robustness.
- **P4:** native Rust/GPU Cell execution at 64/256/1024/4096, direct joules, p95/p99 and power-loss recovery.
- **P5:** equally tuned external Transformer/SSM controls, quality-conditioned total-cost/net-utility advantage and scaled Encoder+HCSN Head.

Never merge or activate this patch as a production qualification on its own.
