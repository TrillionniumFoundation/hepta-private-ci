# Independent financial-construction review

Reviewed source: `aebb58339dda8010888569d78d29cfdb226bb712`, checked locally
against all four frozen hashes. The three inherited R11/R12 source identities
also match, and the six fixed R12 parameters are exactly r=.08, delta=.02,
alpha=.60, tax=.27, coupon=6.39 and principal=61.68. No frozen source, protocol
or original formal result was modified by this review.

The new reviewer does not import the project verifier, its high-precision
quotient helper, or R11/R12 numerical classes. At 90 decimal digits it evaluates
Gaussian densities by adaptive integration and B by adaptive derivative
integration, independently of the native fixed 16-point panels. It recalculates
all eight formal corners plus four formal interior cases. The maximum native
boundary discrepancy is `1.7539e-14`, below the original `2e-11` threshold.
The maximum difference from the original 80-digit reference rounded to float
is `6.4979e-15`.

For `N(y)=Phi(ys)-exp((z²-y²)s²/2)Phi(-zs)`, direct differentiation gives

`N'(y)=s phi(ys)+ys² exp((z²-y²)s²/2)Phi(-zs)`.

Since `N(-z)=0`, the native derivative integral equals `N(y)/(z+y)` and extends
continuously to `N'(-z)`. The audit checks the four actual B arguments, both
sides at distance `1e-20` from the removable point, and the point itself in
each selected parameter case. Maximum identity discrepancy is `7.1379e-72`.
The rationalized eta/gamma expressions follow from
`(z-a)(z+a)=2r/sigma²` and match the inherited boundary formula.

The truncated shifted normal integral omits **exactly** `Phi(-(u+12))`, hence
at most `Phi(-12)` for u>=0. This proves only the real-arithmetic tail
truncation statement, not uniform quadrature or floating-point accuracy.
Nine independently integrated formal CDF points have maximum relative error
`1.9032e-15`. At x=12 the native CDF is 1 while the true complement is
`1.776482112077679e-33`, confirming the already-disclosed complement limitation.

The review independently checks structural rates, allowed edges, row mass,
nonnegative off-diagonals, reset prior barycenter, four-content recovery
factorization, fixed READ and REFRESH likelihoods across all 72 native arrays.
Maximum structural discrepancy is `7.1055e-15`. This is the declared synthetic
eight-active/two-recovery-phase, four-content law; its emissions are fixed,
not the original R12 learned emission model. It does not establish financial
regeneration as a property of the original He–Xiong model.

Five actual CDF out-of-profile calls reject with exit 2 and empty stdout.
An additional bisection reaches an interior reset knot at sigma=.15,
liquidity=.002, maturity=1.0602625344670003; the actual frozen binary rejects
with `reset interpolation knot`. The 44-call trace and binary identity are
retained. This exercises a guard not covered by the original seven box/NaN
negative cases.

All review gates pass within this finite scope. Complete audit process-family
CPU, including imports, adaptive calculations, native calls and serialization,
is **10.188088 seconds**, with **23.222374 seconds** wall time. The internally
reported CPU is nested and is not added again. This is additional peer-review
cost, not part of the original formal verifier's budget.

No all-box FP64/quadrature proof, full equity/debt implementation, continuous
financial/neural free boundary, complete gradients, production admission or
model-utility gain follows from these finite checks. The independent evidence
is `INDEPENDENT_REVIEW.json`, with executable audit source and complete process
receipt alongside it.
