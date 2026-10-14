# R17 exact global population certificate — a nonproduct two-step entropic forward Stem

## The mathematical object

Take independent equiprobable `X∈{-1,+1}`, `P0∈{0,1}`, `eps1,eps2∈{-1,+1}`. Both stochastic preference transitions are `P1=P0 xor I[eps1=+1]`, `P2=P1 xor I[eps2=+1]`. The learned forward weights `a,b∈R` enter both stages:

\[
H_1=aX,\qquad H_2=bH_1+\tfrac14(a-b)^2+\tfrac1{10}\varepsilon_2X.
\]

Stage loss is `P1/20`, terminal loss is `(H2-X)^2+P2/50`; the two nested conditional entropic certainty equivalents use risk attitudes `rho0=1/2`, `rho1=1`, each transition discounted `gamma=9/10`. Parameter penalty `(a²+b²)/4` is **outside** risk. Every one of the 16 terminal configurations is enumerated, not sampled. Known stochastic dynamics and preferences, no pretrained Encoder, action labels or unknown-world fitting.

Put `t=ab` and `d=(a-b)²/4`. Define the exactly specified population recursion `C(t,d)` from the full conditional risk tree. Then

\[
J(a,b)=C(ab,(a-b)^2/4)+\frac{a^2+b^2}{4}.
\]

**This is not a function of product alone**: at fixed `t=1`, the independent full-tree costs `C(1,0)=0.03894148549459679` and `C(1,9/16)=0.2990933482248869` differ; the latter is a numerical illustration, while the inequalities below are global proofs.

## Global nonproduct offset inequality

For each fixed (X,P0,eps1,eps2), terminal residual is
`X*(t-1+eps2/10)+d`.

Under the transformation `X→-X`, `d→-d` with eps1,eps2 and preferences fixed, the residual changes sign, its square does not. The input law is symmetric in X. Therefore **exactly** `C(t,d)=C(t,-d)`.

Terminal cost has Hessian 2 in d. Conditional entropic certainty equivalent for strictly positive risk is log-sum-exp, which is convex and nondecreasing in its two branch costs; its Hessian is the weighted branch Hessian plus the risk times a gradient covariance. Every stage therefore preserves positive semidefiniteness and the two discount factors yield

\[
\partial^2_d C(t,d)\ge 2\gamma^2=\frac{81}{50}
\]

**for all real t and d**, with the same bound for `C_tt` on `d=0`. Evenness forces `C_d(t,0)=0`, so by strong convexity

\[
C(t,d)\ge C(t,0)+\gamma^2 d^2.
\]

Substituting `d=(a-b)²/4` and using AM–GM yields the quantitative global lower bound

\[
J(a,b)\ge C(t,0)+\tfrac12|t|
+\tfrac14\big(|a|-|b|\big)^2
+\tfrac{81}{1600}(a-b)^4,\quad t=ab.
\]

Thus, although the *full* objective has a genuinely second nonlinear parameter channel, its *global minimum* can be certified through the 1D lower envelope `f(t)=C(t,0)+|t|/2`. Equality at a positive minimizer of f requires `a=b=±sqrt(t)` (same sign). **This symmetry-supported lower envelope is a strong restriction; it is not a generic 2D interval branch-and-bound algorithm or general deep FBSDE theorem.**

## Directed exact rational isolation of the only global minima

For `t>0`, the derivative of `f` is expressed using only exact rationals, tanh and logcosh with arguments `rho_p*((t-1)/5+(1-2p)/100)`. Exact 10^65-denominator integer intervals, outward rounding on every operation, a 36-term exponential expansion with a rational tail bound, and a 12-term log/atanh expansion with a rational tail bound enclose the two nested risk derivatives. Code rejects terms outside each certified Taylor domain.

Since `f''(t)≥81/50`, f is globally strictly convex. The exact interval sign tests prove `f'_+(0)<0` and opposite signs at

\[
\ell=0.69620266886932,\qquad u=0.69620266886935.
\]

The unique positive minimizer lies in `(ell,u)`. Negative `t` cannot minimize f because its derivative stays negative to 0. There are precisely two sign-related global optima of the original nonconvex objective.

The rational candidate is `s=834387601099952/10^15`, `a=b=s`; its product is between ell,u. The exact rational interval gradient bound `E` and strict scalar convexity `m=81/50` imply `|s-sqrt(t*)|≤E/(m*s)` and `J(s,s)-J*≤E²/(2m)`.

The checked **rational** output yields per-coordinate distance bound `8.35160641501e-16` and population excess `3.93333322925e-31`; these decimal forms are rounded up for legibility, not used in the proof. For any `b=0`, the global excess is rigorously greater than `0.392605506474` (the stored exact rational bound is authoritative). The nonzero-risk optimum product differs from the zero-risk solution `56/81` by more than `0.00484464417796`.

At `(a,b)=(0,0)`, the gradient vanishes, but the Hessian along the positive `(1,1)` direction has eigenvalue `f'_+(0)<0`: a certified strict saddle. Numerical solver success/gradient root is never used to establish the theorem.

## What fails after breaking the *symmetry* itself

The separate counterfactual replaces correlated noise `eps2*X/10` by `eps2/10`, with all other terms fixed. Then the exact `X→-X,d→-d` symmetry no longer applies; the same frozen rational candidate has a nonzero floating gradient of roughly `3.5563e-4` per component. This is a **changed stochastic problem** and diagnostic evidence only. No theorem, root bracket or global certificate is transported to it.

## Boundaries and reproducibility

The mathematical theorem is for a finite-state, two-step, positive-entropic-risk, nonproduct-but-symmetry-reducible two-parameter model. No continuous uniform law, arbitrary nonlinear deep network, unobserved environment, general multiperiod stochastic control FBSDE, viscosity PDE, LLM/world model capability, or deployment qualification is certified. Local executable proofs use `fractions.Fraction` plus outward integer arithmetic and do not depend on floating optimization outcomes. Independent direct leaf scoring and derivative/curvature tests are implementation diagnostics; they are not substitutes for the exact proof.
