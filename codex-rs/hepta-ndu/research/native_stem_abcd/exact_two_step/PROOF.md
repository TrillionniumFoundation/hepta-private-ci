# R14 mathematical certificate — two-step, two-weight, nonzero-risk forward/backward Stem

## Scope: complete five-atom input law, not continuous X

This proof concerns the exactly specified **finite support** law
\(X\in\{-1,-\tfrac12,0,\tfrac12,1\}\) (weight \(1/5\) each), independent \(P_0\in\{0,1\}\) (weight \(1/2\)), and independent \(\varepsilon_1,\varepsilon_2\in\{-1,1\}\), with weights \(1/2\) each. Thus **all 40 terminal configurations** are explicitly enumerated. A different continuous uniform initial law is evaluated separately and **is not covered** by the certificate.

With two shared weights \(\theta=(a,b)\), define the genuinely evolving forward state
\[
H_1=X+aX^2+bX^3+\varepsilon_1/5,
\qquad P_1=P_0\oplus 1_{\{\varepsilon_1=1\}},
\]
\[
H_2=(1+\varepsilon_1 X/10)H_1+\varepsilon_2/10,
\qquad P_2=P_1\oplus 1_{\{\varepsilon_2=1\}}.
\]
Let \(T_1=X^2+X^4/2\), \(T_2=(1+\varepsilon_1X/10)T_1+X/8\), and
\[
\ell_1=(H_1-T_1)^2+P_1/20,\quad
\ell_2=(H_2-T_2)^2+P_2/25.
\]
Both preference states use nonzero risks \(\rho_0=1/2,\rho_1=1\), and \(\gamma=9/10\). Conditional entropic certainty equivalence is
\[
C_\rho(U_+,U_-)=\rho^{-1}\log\big[(e^{\rho U_+}+e^{\rho U_-})/2\big].
\]
Backward recursion and population target are
\[
Y_1=\ell_1+\gamma C_{\rho_{P_1}}(\ell_{2,+},\ell_{2,-}),
\quad Y_0=\gamma C_{\rho_{P_0}}(Y_{1,+},Y_{1,-}),
\quad J(\theta)=E_{X,P_0}[Y_0].
\]
For each binary branch, the martingale representation coefficient is the successor-value *difference*, e.g. \(Z_2=\ell_{2,+}-\ell_{2,-}\), not the gradient with respect to \(\theta\).

## Global strong convexity — this exact parameter family only

For fixed \(X,\varepsilon_1\), both forward states are *affine in* \(\theta\) despite being nonlinear in \(X\); \(\ell_1\) and each \(\ell_2\) are convex quadratic in \(\theta\). Since \(\rho>0\), \(C_\rho\) is coordinatewise nondecreasing and jointly convex in the two scalar arguments. For twice differentiable inputs its Hessian is the softmax-weighted average of their Hessians plus the nonnegative risk-weighted covariance of their gradients. These facts establish convexity of the nested recursion, **with no restriction on the numerical values of** \((a,b)\).

Let \(\phi=(X^2,X^3)^T\). The \(\ell_1\) Hessian is exactly \(2\phi\phi^T\) at *every* first-stage branch. Hence the outer positive-risk CE and discount imply
\[
\nabla^2 J(\theta)\succeq 2\gamma E_X[\phi\phi^T]
=\begin{pmatrix}153/200&0\\0&117/160\end{pmatrix}
\succeq m I,\qquad m=117/160>0.
\]
Exact five-atom moments are \(E[X^4]=17/40\), \(E[X^5]=0\), \(E[X^6]=13/32\). Thus \(J\) is globally strongly convex and coercive, with **one unique global minimizer** in the specified two-parameter family. This does *not* prove global optimality for unrestricted nonlinear recurrent networks.

## Independently verified exact rational gradient enclosure

A preliminary high-precision numerical root proposed, but does not certify, the fixed rational pair
\[
\widehat a=14790233104650800/10^{16},\quad
\widehat b=-10033907548161366/10^{16}.
\]
The actual certificate recomputes the entire two-step branch-gradient using only \(\mathbb Q\) and outward intervals on a dyadic grid of denominator \(2^{160}\). Every elementary operation is rounded *outward*. Neither a floating-point optimum nor a generic optimizer success flag is a proof assumption.

For \(x\ge0\), the exponential on a scaled argument \(y=x/2^k\in[0,1/2]\) is bracketed by the first 30 positive Maclaurin terms and the remainder
\[
0\le R_{30}(y)\le
\frac{y^{31}/31!}{1-y/32}.
\]
The enclosure is squared \(k\) times. Negative arguments use \(e^{-x}=1/e^x\) with reversed interval reciprocals. For positive logarithm arguments, exact power-of-two normalization gives \(v=2^k m\) with \(m\in[1,2]\). Then \(u=(m-1)/(m+1)\in[0,1/3]\) and
\[
\log m=2\sum_{j=0}^{35}\frac{u^{2j+1}}{2j+1}+R,
\quad0\le R\le\frac{2u^{73}}{73(1-u^2)}.
\]
\(\log 2\) has the same formula at \(u=1/3\); interval arithmetic with exact rational powers and outward dyadic rounding encloses the true value of every log, exp, risk weight, stage cost and gradient.

Let \(g=(g_a,g_b)\) be the true 40-outcome population gradient. For each coordinate the code independently returns rational enclosure \([g_{i,-},g_{i,+}]\). Put
\[
G=\max(|g_{a,-}|,|g_{a,+}|)+\max(|g_{b,-}|,|g_{b,+}|).
\]
Because \(\|g\|_2\le G\) and \(m\)-strong convexity is **global**, for the unique full-population optimum \(\theta^*\):
\[
\boxed{\|\widehat\theta-\theta^*\|_2\le G/m},\quad
\boxed{0\le J(\widehat\theta)-J(\theta^*)\le G^2/(2m)}.
\]
The machine-readable *exact rational fractions* in `CERTIFICATE.json` are authoritative. In decimal presentation these bounds are about \(1.5814\times10^{-16}\) for parameter error and \(9.1437\times10^{-33}\) for true finite-law cost excess.

## Necessity of two weights, and actual risk dependence

For all restricted weights \((a,0)\), Euclidean distance to the unique optimizer is at least \(|b^*|\). The previous bound establishes \(|b^*|\ge|\widehat b|-G/m\). Therefore **over the entire one-weight family**, not just a failed run:
\[
J(a,0)-J(\theta^*)\ge \frac m2\big(|\widehat b|-G/m\big)^2>0.36810869.
\]

At \(\rho=0\), direct exact rational expectation of the same two-stage paths produces a quadratic population objective. Solving its two normal equations gives a reference around \((1.478014601071002,-1.004067997412923)\). Its first coordinate differs from the nonzero-risk certified optimum by at least \(0.00100870939\). Thus **nonzero risk genuinely affects the recovered forward parameters** in this example. The risk-neutral comparator is NOT used as a training label.

## Scope limits and independent checks

An 85-digit independent `mpmath` implementation recomputes the two-stage gradient and falls inside each directed interval. Independently differentiated NumPy Hessians agree with finite differences and the exact global strong-convexity bound. The 15 matched fresh-process optimizer cases compare analytic-adjoint Newton, Adam and L-BFGS-B without oracle supervision, using the same exact full support and initial weights per seed; the external certified candidate enters **only the monitoring predicate**, not parameter updates.

Changing X to a *different* continuous uniform [-1,1] distribution produces a different optimum. A separate floating-only GL stress test sees a cost penalty about 0.0378899 for directly transplanting the five-atom certified candidate. **The discrete-law certificate cannot be reused for that continuous law.** Likewise it is not a theorem on unknown plant coefficients, multistage unrestricted neural feedback, general continuous-time FBSDEs, or LLM/world-model scaling. Historical research gates, deployment contracts and production selection remain unchanged.