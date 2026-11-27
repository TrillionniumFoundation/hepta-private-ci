# R12 — exact population and nonlinear NDU recursion certificate

Parent R11 #1935 at `6b0f8a5cdaf79e3bf4e50fb75dbeda837825caad`. Additive research-only, separate from the R10 model and historical qualification.

## Purpose and crucial scope

Develop and **actually test** a nontrivial provable integration/error certificate, rather than reclassify the historical 33 R10 rejected candidates. The exact-rational research submodel keeps a **trainable forward shared Stem**, two-step Bernoulli forward transitions with two observed preference regimes, a four-dimensional known uniform input law, quartic terminal service cost and nonadditive entropic recursive utility. It uses a 32-coefficient **affine policy Stem**, not the 498/1842-parameter tanh Stem, and uses the **linear** target subfamily (R10's sine/bilinear corrections are excluded). No original R10 weight is promoted or assigned a proof it does not have.

Initial and terminal laws, shocks, dynamics, preference transitions and risk settings are exact decimal rational parameters documented in `rational_ndu.py`. Controls, weights, polynomial expansions and expected moments use Python Fraction. The normalized four-dimensional input is independent uniform [-1,1], with physical scales [.25,.25,.8,.8].

## Mathematical construction

For two child continuation costs `a,b`, probability p, risk η>0, define

`CE_eta(a,b)=log(p*exp(eta*a)+(1-p)*exp(eta*b))/eta`.

Use polynomial second-order recursion

`CE2(a,b)=m+(eta/2)*p*(1-p)*(a-b)^2` with `m=pa+(1-p)b`.

The cumulant third derivative satisfies
`|d³/dt³ log(p exp(t a)+(1-p) exp(t b))| <= |a-b|³/(6 sqrt(3))`.
Because `36sqrt(3)>60`, the *exact* bound

`|CE_eta(a,b)-CE2(a,b)| <= eta² |a-b|³/60`

holds for any reals a,b and p in [0,1]. True CE is 1-Lipschitz in sup norm. Let D1 and D0 be **rigorously computed** uniform bounds on sibling differences in the polynomial surrogate, using the sum of absolute monomial coefficients on the normalized input cube. For two backward steps,

`|J_true - J_poly| <= gamma² eta² D1³/60 + gamma eta² D0³/60`.

All coefficients and the integrated polynomial value are exact Fraction quantities. Terminal quartic, affine controls, and two polynomial CE2 steps yield coordinatewise degree at most 16. Nine-node tensor Gauss–Legendre exactly integrates degree <=17 in each coordinate in real arithmetic. Here the implementation integrates polynomial moments exactly as Fractions, not by trusting numerical GL9 output. Thus the polynomial-population integration error is zero for this subfamily; the nonzero certified error is the explicitly bounded entropic Taylor remainder.

## Arms / honesty

Exploratory development (not independent preregistration) already tested four scalar-multiplier policies (zero, half-tracking, full-tracking, numerically fitted multiplier 60871/100000) at eta=.4, and a from-scratch full 32-weight numerical search; these **preliminary results preceded this protocol**. The remaining recorded checks are confirmatory only in the sense of code-verification, NOT blind evidence.

Evaluate all five frozen policies across eta in {1/5,2/5,3/4}, preserve every exact lower/upper bound, and include the historical candidate comparison without retroactively modifying R10. Train full 32 weights from scratch for seeds11/23/47 with:
- complete-population Gaussian9 polynomial-surrogate L-BFGS;
- explicit finite-tree BSDE adjoint root solve with complex-step Hessian;
- ordinary automatic differentiation L-BFGS;
- an Adam budget/step control.

Each method sees the **same known distribution** and polynomial surrogate only, no true entropic oracle labels or held-out score in optimization. Save all unrounded numerical weights, then quantize to denominators 10000 for exact rational certification, even if several initializations quantize identically. Report root residual, Hessian eigenvalue at the recovered solution, actual CPU/wall time and all competing methods, including failures.

A high-precision interval pilot on the original R10 tanh model is a separately labelled **nonqualifying diagnostic**. Wide interval bounds are not replaced by numerical agreement. No uniform R10 derivative or quadrature certificate, no true-model global optimum, no general LLM/world-model conclusion is claimed.

## Verification and delivery

Cross-check with an independently implemented vectorized exact-entropic evaluator at GL9 and GL17, including all three risk settings, as a *numerical sanity check*, not the proof. The proof follows from exact rational moments, the analytic Taylor bound, and sup-norm propagation. Test failure modes, parameter shapes, exact moment identities, and strict interval separation. Preserve exact rational numerators/denominators, selected full coefficient tensors, all baselines, source hashes, timings and tests; do not conceal poor arms.

Git stores code, protocol, positive and negative readout, receipt and JSON tensor bytes/decimal rational coefficients, with no native semantic changes. The conversation archive retains all raw data. Run read-only GitHub CI tests; do not claim hosted CI passed until observed. No main merge, CURRENT update or production authorization.

**Next mathematical obstacle:** controlled error bounds over the actual R10 nonlinear tanh family, including arithmetic rounding and space-time recursion, not just this tractable affine polynomial submodel.
