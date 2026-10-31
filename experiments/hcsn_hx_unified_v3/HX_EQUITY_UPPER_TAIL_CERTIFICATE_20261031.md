# P0: exact-rational HX financial equity upper Dirichlet bound — 2026-10-31

Status: **RESEARCH_ONLY / DENY_ALL / NO_GO**. Stacked on #4512 exact parent HEAD 99fa3ad1f75eb021fc95fd2b6cd5dbda37898e2c. Previous mathematical/negative results and all production controls remain unchanged.

## Correction inherited from #4498

The correct never-default maturity-T representative bond includes the surviving principal:
B_inf = (coupon/T)/q + exp(-q*T)*(principal/T-(coupon/T)/q), q=rate+shock_intensity*sale_fraction.

The old #4496 extra STOP end near 112 was **retracted** after the earlier far-field principal omission was discovered; the current project must use the corrected bond tail.

## Exact fixed-barrier analytic derivation

Let X=log(A/b) for an **arbitrary fixed positive financial default barrier** b, drift mu=r-delta-sigma^2/2, sigma>0, r>0, T>0, and delta=payout>0. Define C=(1-tax)*coupon+principal/T and H(A)=A+(B_inf-C)/r. This is a financial cashflow model, NOT a neuronal Call or Put operator.

Its killed expected discounted equity value obeys:
V(b*exp(x))-H(b*exp(x)) =
  -H(b)*exp(-k_r*x)
  + E_x[ integral_0^tau0 exp(-r*t)*(B(b*exp(X_t);b,T)-B_inf) dt ],
where k_lambda=(mu+sqrt(mu^2+2*lambda*sigma^2))/sigma^2 and tau0 is first hitting time of X=0.

With D=exp(-qT)*abs(principal/T-coupon/(T*q)) + abs(recovery*b/T-coupon/(T*q)), the finite-maturity first-hit inequality is:
abs(B(b*exp(y);b,T)-B_inf) <= D*exp(lambda*T-k_lambda*y).

For any lambda>0, lambda!=r, the killed exponential resolvent is exactly:
E_x[integral_0^tau0 exp(-r*t-k_lambda*X_t) dt]
    =(exp(-k_lambda*x)-exp(-k_r*x))/(r-lambda) >= 0.

Therefore the conservative finite exact-model upper equity boundary budget is:
abs(H(b))*exp(-k_r*L)
  + D*exp(lambda*T)*(exp(-k_lambda*L)-exp(-k_r*L))/(r-lambda).

The source minimizes this bound over nine *prespecified valid lambda choices*, without importing/calling the HX closed bond/boundary/equity formulas or finite-grid solver.

## Exact arithmetic and local execution

The module interprets physical Python binary64 parameters as exact rational numbers; integer square roots enclose kappa; the exponential is enclosed by positive Taylor sum and a geometric-remainder upper bound; decimal error amounts round outwards using exact integer operations. Invalid domains, delta=0, unsupported resource limits, and precision failures REFUSE. This is a mathematically bounded ONE-COMPONENT oracle, not a GPU/f64 solver-wide roundoff or continuum equilibrium certification.

Run from repo root:
    python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_equity_upper_tail_certificate

**5/5 targeted test methods PASS, zero skips**, locally executed in a package-shaped Python 3.13.5/SciPy 1.17.0/mpmath 1.3.0 CPU environment. 12 bounded financial comparisons used an independently coded reflected Green-resolvent integral with normal-CDF debt plus rational sqrt/exponential enclosures, refused physical/precision domains, and a prohibition on full-P0 promotion. Not full-repository CI.

Exact locally tested and remotely read-back Git blob IDs:
- Source 11fa4aa0a5d596d05c4ec5c925bb767d4a37772f
- Tests 7d8a9fd14d3bfc81cfde18df92294c03b9ba3067

## Numerical cross-checks (independent floating check, NOT source of mathematical guarantee)

| Financial fixed-barrier case | log upper L | Outward analytical bound | Observed reflected-resolvent discrepancy |
| --- | ---: | ---: | ---: |
| Standard HX; b=64.62518 | 3.6 | 2.044511 | 0.528781 |
| Standard | 6 | 0.146729 | 0.037948 |
| Standard | 10 | 0.001819 | 0.000471 |
| sale_fraction=0.2; b=101.32403 | 3.6 | 16.945402 | 2.704057 |
| High liquidity | 6 | 1.216090 | 0.194055 |
| High liquidity | 10 | 0.015072 | 0.002405 |
| Alternative moderate HX; b=54.3 | 3.6 | 0.001384 | 0.000061 |
| Alternative | 6 | 1.869714e-7 | 8.143637e-9 |
| Alternative | 10 | 6.652703e-14 | 2.897620e-15 |

A later 16-seed × two-domain exploratory random-panel run exceeded its execution timeout, and yielded **no completed report**. This is not a passing stress panel or a native performance measure.

## Strict compositional limitations and remaining work

This result supplies **only the mathematical fixed-barrier financial EQUITY far-field Dirichlet discrepancy** missing from #4508. To use it with that conditional Bellman classifier one must separately enclose floating-point evaluation of the actual implemented upper condition, complete debt/PDE cashflow error, space/time discretization, and value-model input uncertainty. This result cannot be promoted to a verified total debt error or global equilibrium.

P0 OPEN: full debt PDE error, global coupled obstacle existence/self-consistency, certified mesh and low-precision financial gradients. P1 OPEN: eight-arm matched causal gain remains unproved. P2 OPEN: full long-memory and native restore net benefit. P3 OPEN: real four-modal paired/OOD validation. P4 OPEN: native GPU and 64/256/1024/4096 Cell/Joules. P5 BLOCKED by no equal-budget backbone net advantage.

The output explicitly asserts input_debt_error_verified=false, entire_P0_certified=false, all_scientific_blockers_closed=false, production_activation=false. Keep Draft/unmerged.


## Bounded-seed follow-up with explicit resource accounting

A subsequent new test file, test_hx_equity_upper_tail_stress.py, fixes RNG seed 20261031 and loops through **16 financial regimes × 2 declared log-domain lengths = 32 independent physical numerical cross-checks**, with no data omission or outcome-dependent filtering. Both tests use the exact same rational bound; the stress panel explicitly selects a 64-term (rather than 160-term) **still mathematically valid positive Taylor enclosure** to cap exact-Fraction CPU cost. The independent SciPy reflected-Green value remains a numerical comparison, not a rigorous interval proof.

- Local **stress file alone: 1/1 method PASS, 32/32 subcases, 0 skipped**, approximately 8 seconds on the research container. Exact locally tested remote Git blob: bd8c4b258960c20dccb62f192dbcbf4e360f1030.
- Original five-test file alone: **5/5 PASS**, zero skipped, approximately 28 seconds.
- One later attempt to execute both files **in the same Python process did not finish before an execution timeout** (it reached the stress test). It must NOT be reported as a combined 6/6 PASS or whole-repository CI. The original 160-term broader exploratory panel likewise timed out. These are explicit runtime/resource limitations of the reference calculation, not scientific successes.
- Reproduce as **separate processes** with:
  python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_equity_upper_tail_certificate
  python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_equity_upper_tail_stress

No P0–P5 gate changes and no production admission.
