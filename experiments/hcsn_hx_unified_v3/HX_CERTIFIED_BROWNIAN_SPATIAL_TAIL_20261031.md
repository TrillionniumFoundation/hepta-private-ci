# HCSN P0: exact-rational Brownian spatial-tail component (2026-10-31)

**RESEARCH_ONLY / DENY_ALL / NO_GO**. This increment is stacked on #4508 exact HEAD `be5299fb4c5ae5feaa421d7f49f1ac2402c4fbbd`. It does not modify the financial HX formulas, independent PDE and obstacle solvers, prior data, trained models, or production control.

## Certified statement (fixed-barrier continuous-finance model only)

Let `Y_t=y+mu*t+sigma*W_t`, where `mu=rate-payout-sigma^2/2` and `sigma>0`. For any distance `a>0`, time horizon `T>0` and test `lambda>0`, the exponential martingale stopped on first passage gives

    P(sup_{s<=T}(Y_s-y)>=a) <= exp(-lambda*a+T*max(0,lambda*mu+lambda^2*sigma^2/2)).

For any `x>=0` and positive integer `N`:

    exp(-x) <= [sum_{k=0}^N x^k/k!]^-1.

The source computes every parameter, chosen lambda, Chernoff exponent and finite Taylor sum in exact `fractions.Fraction` arithmetic, interpreting the supplied binary64 values as exact rationals. Displayed decimal *upper* probability/error bounds are rounded outward using integer arithmetic. Displayed exponents are rounded *downward* and are diagnostic only. Unsupported large exact computations refuse rather than silently approximating.

For the HX maturity-`T` representative debt under fixed financial default log barrier `0` and upper log boundary `L`, `q=rate+shock_intensity*sale_fraction>0`, `par=principal/T`, `base=(coupon/T)/q`, and `recovery_b=recovery*b/T`. At any remaining maturity `t`, the no-default bond is `U(t)=base+(par-base)*exp(-q*t)`, hence `U(t)` lies between `par` and `base` and the absolute replacement difference on default is bounded by

    C=max(|recovery_b-par|,|recovery_b-base|).

The strong Markov property then yields an upper-boundary debt truncation error **uniformly** over `0<=y<=L`:

    |B_true(y,T)-B_upper_no_default(y,T)| <= C*P_L(hit lower 0 by T).

A more local bound multiplies the right side by `P_y(hit upper L by T)`; this deliberately ignores competing lower-barrier absorption in that factor, making the result conservative. Both first-hit probabilities use the exact-rational exponential-martingale/Taylor ceilings, not HX Eq.(8)/(12)/(A7), SciPy quadrature, a numerical PDE or its residual.

**This is not a complete PDE bond error bound**. It does not bound finite-difference spatial error, time-stepping error, floating operator rounding, the equity far-field value, the incompatible maturity/default corner, physical parameter uncertainty, or self-consistent financial default equilibrium. Therefore the object explicitly has `debt_error_budget_complete=false`, and trying to convert it to #4508's total debt-error budget always raises `UnresolvedTailCertificate`. It must not be used alone to classify STOP/CONTINUE.

## Executed local verification and numerical examples

From the repository root with SciPy available for test-only independent reflection-law evaluation:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_certified_brownian_tail
```

Python 3.13.5, SciPy 1.17.0, **7/7 test methods PASS**, no skips. The tests include **90 independent drift/volatility/distance/horizon** comparisons to a separately coded normal-tail reflection-law formula, five outward-rounding checks plus zero/tiny cases, exact-zero financial payoff difference, two financial shock regimes, larger-domain monotonicity, invalid parameters, time/distance boundaries, arithmetic-size refusal and production/admission denial. Test-only SciPy is absent from the source certificate's dependency path.

Selected exact-rational **uniform debt spatial truncation upper bounds**, with positive physical parameters otherwise set to `HX()`:

| sale_fraction | supplied candidate barrier b | log upper L | certified uniform upper bound |
|---|---:|---:|---:|
| 0.015 | 64.6251766753 | 2.0 | 1.83215048796e-6 |
| 0.015 | 64.6251766753 | 3.6 | 6.65156320101e-22 |
| 0.015 | 64.6251766753 | 4.5 | 1.69532309705e-34 |
| 0.2 | 101.324028609 | 2.0 | 3.60536095601e-6 |
| 0.2 | 101.324028609 | 3.6 | 1.30891465625e-21 |
| 0.2 | 101.324028609 | 4.5 | 3.33610789184e-34 |

The input barriers are *supplied fixed candidates*, not independently certified equilibrium roots. Numbers are conservative output decimal strings backed by exact rational bounds; they are **not measured PDE errors**. The independent reflection-law comparison uses floating normal CDFs only as a smoke check, not as the mathematical proof.

Exact locally executed Git blobs: source `1160a616eea272e6831e142831f2250c1addf176`, tests `0dd8512e92b976826837cf75000e71d7c9259401`. Repository full CI, native Rust/GPU, actual energy, coupled global financial obstacle, complete financial FP32/BF16 and active-set gradients remain **UNVERIFIED**.

## P0–P5 admission ledger

- P0 **OPEN**. One fixed-barrier continuum debt *upper spatial truncation* subproblem now has a conditional-on-model analytic bound. Missing: independently certified spatial/time/rounding errors, real node-wise complete debt & equity error intervals, self-consistent coupled financial obstacle, global admissible domain and gradients.
- P1 **OPEN**: matched Call/Risk/Margin eight-arm pilot in #4500 retains negative/no-significant mechanisms.
- P2 **OPEN**: #4507 protected new-run provenance but historical mutable record mismatches and no independent matched durable/long-memory win remain.
- P3 **OPEN**: genuine paired text/image/audio/video Encoder OOD.
- P4 **OPEN**: Rust/GPU fused native, 64/256/1024/4096 actual Cell, power/Joules, host crash proofs.
- P5 **BLOCKED**: full fair-baseline quality/total-cost improvement prior to backbone growth.

No previous failures are changed or deleted. `production_activation=false`, `all_scientific_blockers_closed=false`. Keep draft, no merge/deployment.
