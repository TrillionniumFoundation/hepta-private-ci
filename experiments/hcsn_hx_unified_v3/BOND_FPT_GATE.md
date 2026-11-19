# P0 next-step: independent He–Xiong finite-maturity bond oracle

**Research only, DENY_ALL.** Stack on draft #4380 (`13c4e6aa2de23cb18807af189c12999b8117962e`); keep historical source and evidence unchanged. This test is explicitly not a complete financial default equilibrium, production HCSN computation, or universal scalar-parameter certificate.

## Independent method

For log-distance `x=log(V/b)>0`, log drift `nu=r-delta-sigma^2/2` and first hitting time `T` of zero, the density is `x/(sigma sqrt(2 pi t^3)) exp(-(x+nu*t)^2/(2 sigma^2 t))`. With `u=x/(sigma sqrt(t))`, it becomes the nonsingular integral `sqrt(2/pi) exp[-(u + (nu*x/sigma^2)/u)^2/2] du` on `[x/(sigma sqrt(tau)),infinity)`. Compute `F=P(T<=tau)` and `G=E[exp(-q T) 1(T<=tau)]` by adaptive quadrature with error checks, **independently of the paper's normal-CDF reflection implementation, splitting the near-barrier u=O(x/sigma) boundary layer to avoid false quadrature convergence**. Recover bond PV as coupon paid to `min(T,tau)`, survival principal and default recovery. Compare to the exact-head HX `F`, `G` and bond Eq.(8), including zero-hazard, zero-payout and high-liquidity examples.

`test_bond_fpt_independent.py` validates the two routes over 108 preselected stress parameter points, positivity, discount monotonicity and invalid values, and 5×3×2 exact-upstream HX bond comparisons (90 scalar comparisons across F/G/bond). One test deliberately preserves a float32 barrier quantization counterexample; no low-precision correctness is inferred.

## Run at the stacked repository head

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_bond_fpt_independent
python -m experiments.hcsn_hx_unified_v3.bond_fpt_independent
```

## Explicit unresolved gates

This independently verifies finite-horizon bond and first passage in a *bounded* parameter suite; it does **not** prove full-domain HX default-equilibrium admissibility, self-consistent free-boundary obstacle, interval enclosure, QVI global optimality, stable native fp16/bfloat16 kernels, P1 mechanism gains, P2 memory, P3 four-modal pairing, P4 Rust/GPU joules/4096 Cell, or P5 matched-budget superiority. Preserve all historical negative P1/P2/P5 evidence and keep this branch draft.

## Exact local outcome and unclosed integration

Standalone Python 3.13.5 CPU validation: **6/7 tests passed and the exact-upstream integration test skipped because `hx.py` was not mounted**. A reproducible JSON numerical receipt is in `REFERENCE_ADVERSARIAL.json`. To claim exact-repository integration, run the named test on this PR branch and require the `test_exact_upstream_hx_f_g_and_bond_when_present` case to be **PASS (not skipped)**. The quadrature itself is double precision, and all reported errors are bounded-sample observations, not rigorous interval bounds.
