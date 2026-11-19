# HX analytic / scalar stopping / regenerative QVI: separated P0 reference

**Research-only, DENY_ALL for production.** This directory is additive to the
existing `hcsn_free_boundary_v1` and `hcsn_distributional_v2` studies. It does
not change their frozen source, evidence, benchmarks, native owner or training.

## Scientific contracts: three distinct value problems

1. **He–Xiong finance (`hx.py`)**: the 2012 *Journal of Finance* model,
   [He and Xiong, *Rollover Risk and Credit Risk*](https://www.princeton.edu/~wxiong/papers/rollover.pdf),
   Eq. (8) (finite-maturity bond), Eq. (12) (endogenous stationary default
   threshold), and Eq. (A5)/(A7) (equity). Assumptions: risk-neutral geometric
   Brownian assets, stationary continuum of bonds, proportional liquidity
   selling costs, limited liability and financial smooth pasting. Variables
   `rate,payout,volatility,maturity,principal,coupon,tax_shield,recovery,`
   `shock_intensity,sale_fraction` retain their **financial** meanings.
   The `mechanism_channels` *accounting readout* provides equity, first-passage
   default probability, discounted first-hit factor and bond rollover margin.
   These are **not** two European Call/Put prices; renaming them does not
   establish a neural mechanism or causal advantage.
2. **Simplified neural stopping (`stopping.py`)**: arithmetic Brownian membrane
   state, linear fire payoff `x-cost`, discount, no competing inputs, and an
   analytically optimal infinite-horizon *one-shot* boundary `cost+1/kappa`.
   Its dynamics and units are different from finance.
3. **Regenerative neural QVI (`stopping.py`)**: the same scalar dynamics with
   deterministic mandatory refractory duration and reset `reset<cost`.
   Discounted recurrent pulse reward for a fixed boundary is a geometric
   renewal series. The unique scalar stationary optimum follows the principal
   Lambert-W branch; an independent Brent root checks its smooth fit. For
   the optimal value, `max{(L-rho)V, x-cost+D*V(reset)-V}=0` is sampled on
   both sides of the boundary. This is *not* proof of a coupled network QVI,
   time-varying state, finite deadline, or finite-grid optimal policy.

## Numeric details and rejection behavior

- The bond uses the reflected first-passage normal-CDF formula. Exponential
  CDF products use `log_ndtr`; zero-maturity and default states have explicit
  payoffs. The equity implements the paper's Laplace-inverted A7 expression.
- The `zhat -> z` (`shock_intensity*sale_fraction -> 0`) singularity in A7 and
  (12) is removable. Analytic numerator derivatives are integrated over a
  *short parameter interval* (3-node Gauss-Legendre), including the exact
  coalescent case. This is not an epsilon perturbation of financial parameters.
- A separate Feynman–Kac killed-diffusion Green resolvent evaluates the same
  fixed-boundary equity cash flow. For `payout=0` it includes the correct
  `payout -> 0+` limiting terminal value, rather than discarding the asset.
  A separate discounted running-cashflow integration and Brent solve check
  boundary (12); four-point finite differences check the equity ODE.
- Financial smooth pasting alone does **not** certify global limited liability
  or intervention optimality. A deliberately retained counterexample with
  `sale_fraction=0.2` has a negative equity value near the algebraic boundary.
  **Do not clamp negative values to zero or classify this as an admissible
  global stopping policy.** This blocker requires an obstacle solution / domain
  classification, not parameter tuning to remove a failed test.
- Any finite-input-parameter checks cover the declared structural domain,
  not all mathematically legal parameter combinations. A positive algebraic
  boundary is not sufficient to certify global economic viability. The Green
  resolvent has finite tail controls suitable for audited reference ranges;
  not all extreme f64 states and tiny discount gaps are yet certified.
- `float32` *input quantization* tests do not claim native fp32/fp16 arithmetic,
  stable backpropagation or GPU execution. No training in this package.

## Reproduce

From repository root, with NumPy and SciPy installed:

```bash
python -m unittest -v experiments.hcsn_hx_unified_v3.test_oracles
python -m experiments.hcsn_hx_unified_v3.audit \
  --output /tmp/hcsn_hx_p0_reference_audit.json
```

The tests include: two boundary conditions, probability and discounted-hit
bounds, A7 versus independent resolvent, closed financial boundary versus
independent integrated smooth fit, finite-difference equity PDE, no-hazard
and zero-payout limits, seeded 48-case parameter sweep, input rejection,
explicit counterexample, one-shot and renewal boundary comparisons, scalar
QVI complementarity, reset/refractory limiting conditions. Each test only
certifies its specified parameter ranges.

## P0–P5 admission tracker

| Stage | Current result | Remaining blocking evidence |
| --- | --- | --- |
| P0 | Reference implementation and independent tests; **partial** | All-domain viability and independent grid convergence, native low-precision and derivative certification |
| P1 | Financial proxy channels named only; **not started** | Registered paired ordinary-gate, same-slope/same-parameter/training-budget ablations; channel attribution |
| P2 | Exact scalar renewal only; **not complete** | Selective Copy/MQAR, overwrite, long recall, irregular clocks, repeated physical firing |
| P3 | **Not complete** | Actual paired text/image/audio/video, OOD robustness, alignment |
| P4 | **Not complete** | Native Rust/GPU, 64/256/1024/4096 Cell and energy/recovery |
| P5 | **Blocked** | Same-data/tokens/FLOPs stable superiority before scaling |

No established result in existing studies is silently reclassified as a new
training outcome, and nothing here grants production authority or registers a
Hepta Cell.
