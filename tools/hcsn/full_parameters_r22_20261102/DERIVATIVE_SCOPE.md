# Differentiated object and admission boundary

The candidate is a new native implementation with nine independent physical
coordinates `(r, delta, alpha, tax, coupon, principal, sigma, liquidity,
maturity)`. R20 and its executed sources remain unchanged. The six newly free
coordinates have a deliberately local explicit box; sigma/liquidity/maturity
retain the earlier broad ranges. No conclusion extends beyond that box merely
because all corner cases pass.

The 2,001-word output is the static boundary followed by the declared synthetic
40-state Q, fixed READ/REFRESH emissions and reset prior. Each word carries all
nine first derivatives. The rates use the free drift `r-delta-sigma²/2`; the
reset weights use `log(90/boundary)`, so all physical coordinates can change
the reset and prior. Recovery mean, reset asset, retention and emission values
remain constants, and their learning derivatives are outside this contract.

Forward dual arithmetic applies the ordinary product, quotient and elementary
chain rules. The candidate normal tail is a composite Gauss-Legendre evaluation
of a positive shifted integral on `[0,12]`. Before quadrature, its mathematical
value is `Phi(x)-Phi(x-12)` for `x<0`; omitted value and x-derivative terms are
bounded respectively by `Phi(-12)` and `phi(12)`. This does not prove a uniform
floating-point or Gauss-Legendre error bound. The independent high-precision
path uses the exact erfc divided difference and mpmath differentiation, not
candidate quadrature or dual code. The additional selected auditor is authored
separately and uses another integral representation plus complex-step
derivatives.

The B divided difference is evaluated by integrating its smooth derivative on
the fixed unit interval. Consequently the removable `y=-z` denominator is not
present in candidate arithmetic. The two rationalized eta branches represent
the same smooth positive function in real arithmetic; the branch avoids
subtraction cancellation. All final values and sensitivities must be finite.

Within a fixed reset interpolation interval the prior and completion/reset
rates are affine in the reset log-distance. Their derivatives follow by the
chain rule. At a reset knot the left and right ordinary derivatives need not
agree. Inputs within 32 machine epsilons of a knot are explicitly rejected;
this is a domain boundary, not a zero derivative or an arbitrary tie choice.
Finite-difference stencil halving depends only on this admission/regime
condition, never on whether its derivative error would pass a tolerance.
Failure to obtain an admitted stencil within the fixed cap fails the run.

Conservation is structural: each edge adds a rate to one off-diagonal entry
and subtracts the same dual rate from its row diagonal; reset weights sum to
one and their derivatives sum to zero. Floating-point row and prior sums are
still measured independently at all registered points.

Successful registered checks qualify the bounded nine-coordinate constructor
and its finite arrays at those points. They do not qualify a learned nonlinear
boundary, continuum PDE/obstacle limit, full equity/debt channels, complete
neural training/control gradients, an updated nine-parameter runtime profile,
exclusive core utility or production use. The original native runtime remains
the separately qualified three-parameter profile.
