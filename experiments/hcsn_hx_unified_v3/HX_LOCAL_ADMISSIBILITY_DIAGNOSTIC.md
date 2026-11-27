# One-sided local HX admissibility diagnostic

This research-only helper does not change `HX`, `boundary`, `equity_closed`,
the default model, or any production/admission gate. It never clamps equity.

## Derivation and interpretation

He–Xiong, *Rollover Risk and Credit Risk* (2012), printed p395 Eqs2–4,
p399 Eq6 and p400 Eq11 supply the debt scaling, recovery and equity ODE.
The smooth-fit candidate is Eq12 (p401); the equity formula is A7 (p422).
The p423 proof explicitly invokes nonnegative equity for every V >= B.
Source: https://www.princeton.edu/~wxiong/papers/rollover.pdf

Writing B for the computed smooth-fit boundary and

    f(B) = (delta + alpha/m) B - (1-pi) C - P/m,

value matching and smooth fit in the ODE imply

    E_VV(B+) = -2 f(B)/(sigma^2 B^2).

Thus a strictly positive f(B) analytically forces negative equity immediately
above B. A floating-point sign diagnostic is not a formal sign certificate.
A finite near-boundary sampling grid can miss that negative interval.

The helper returns:

- `POSITIVE_CASHFLOW_NEGATIVE_CURVATURE`: numerical local failure witness.
- `NO_LOCAL_REJECTION`: this necessary-condition test did not reject; **not PASS**.
- `ROUNDING_UNRESOLVED`: too close to zero at the heuristic roundoff scale.

The margin is 64 machine epsilons times the absolute cashflow-term sum.
It is heuristic, not an interval enclosure or a bound on boundary-solver error.
Global status is always `NOT_CERTIFIED`; `numerical_certificate` is always false.
Neither f(B) <= 0 nor alpha B/P <= 1 establishes global admissibility.

## Independently rechecked witnesses

All unspecified parameters below use `HX()` defaults.

1. `sale_fraction=.2`: B=101.3240286090781,
   f(B)=0.4369294409957731,
   E_VV(B+)=-0.001361872309916986.
   Equity at V/B=1.01 is approximately -0.00048928557185,
   consistent between A7 and an independent Green integral.
2. `payout=.08, maturity=3.5, coupon=4, recovery=.7, sale_fraction=.28`:
   B=73.55452669008902, alpha B/P=0.8581361447177052 < 1,
   f(B)=0.4524103303677798 and E(1.001 B) approximately -7.1374181e-6.
   This refutes using recovery-below-principal alone as an admissibility test.

Five focused tests cover both witnesses, default non-certification, the
near-zero unresolved branch, and nonfinite scale rejection. Independent review
also recalculated the boundary from a separate Green-integral slope root.
The base is commit `97ef824020c4416a02332b2a8216956b1d6ca209`;
existing `hx.py` SHA256 is
`6722d2d5d9070452779252508fc1dbbffa8b65e22e619aa5845353e092561423`.
These results establish local rejection examples, not global-domain coverage.
