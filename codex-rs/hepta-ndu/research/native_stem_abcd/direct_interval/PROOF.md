# R20 — certified cost bounds by direct interval enclosure of nested entropic NDU

## 1. Population and parameter dependence

The known law enumerates exactly 16 equally likely branches \((X,P_0,\varepsilon_1,\varepsilon_2)\), with \(X,\varepsilon_1,\varepsilon_2\in\{-1,1\}\) and \(P_0\in\{0,1\}\). At stage \(i\), the preference state flips when \(\varepsilon_i=+1\). With \(\gamma=9/10\), \(\rho_0=1/2\), \(\rho_1=1\), define the positive-risk conditional certainty equivalent

\[
\operatorname{CE}_{\rho}(v_-,v_+)=\frac1\rho \log\left(\frac{e^{\rho v_-}+e^{\rho v_+}}2\right).
\]

Stage loss is \(P_1/20\); terminal loss is \((H_2-X-1)^2+P_2/50\), where

\[
H_1=aX,\quad H_2=abX+\frac{(a-b)^2}4+\frac{\varepsilon_2}{10}
+\frac{a}{25(1+a^2)}+\lambda\frac{a-b}{1+(a-b)^2},\quad \lambda\in\{0,1/8\}.
\]

The outer and inner CEs are both risk-sensitive with the regime-specific \(\rho_{P_0},\rho_{P_1}\), and each layer is discounted by \(\gamma\). Finally add \((a^2+b^2)/4\) *outside* the risk recursion. The extra signed-difference path is genuinely parameter-specific: the original R18 quotient \((ab,(a-b)^2/4)\) does not determine \(H_2\) under \(\lambda=1/8\). Both variants use the **same exact known population**, objective family, starting parameters and evaluation limits; they have distinct forward model families and distinct finite-dimensional global optima.

## 2. Elementary rigorously valid risk function inequalities

For arbitrary real \(z\), the identity

\[
\log\cosh z=\int_0^{|z|}\tanh s\,ds
\]

and \(0\le\tanh s\le s\) for \(s\ge0\) imply \(\log\cosh z\le z^2/2\). For the lower bound, differentiation gives

\[
\frac{d}{ds}\left[\tanh s-s+\frac{s^3}3\right]
= s^2-\tanh^2 s\ge0,
\]

and the bracket vanishes at zero. Thus for **all** real \(z\),

\[
\boxed{\max\left(0,\frac{z^2}2-\frac{z^4}{12}\right)
\le \log\cosh z\le\frac{z^2}2.}
\]

Writing \(m=(v_-+v_+)/2\), \(z=\rho(v_+-v_-)/2\),

\[
\operatorname{CE}_{\rho}(v_-,v_+)=m+\frac{\log\cosh z}{\rho}.
\]

For \(\rho>0\), each CE is monotone in **both** input costs (softmax derivatives are nonnegative). Therefore it is safe to compute a rational lower CE bound at the lower endpoints of two certified loss intervals and a rational upper CE bound at the upper endpoints. The same monotone operation is applied at both entropic recursion levels. There is no floating transcendental evaluation in any asserted mathematical bound. Unlike R19, the proof **does not use strong convexity of any auxiliary \(C(t,d)\)**.

## 3. Rational box arithmetic and global coverage

For a dyadic box \(B=[a_l,a_h]\times[b_l,b_h]\), product \(ab\) lies between the min/max of four endpoint products. \((a-b)^2\) is bounded using the exact interval square minimum (zero if the difference interval crosses zero). The extrema of \(c v/(1+v^2)\) for positive \(c\) are attained at the interval endpoints and the interior critical points \(v=\pm1\), if present. Thus all forward terms have exact rational interval enclosures. Terminal squared residuals have exact interval enclosures, and the monotonicity/\(\log\cosh\) formulas yield a certified lower bound \(L(B)\) for the **original** full stochastic objective, not a surrogate approximation.

Outside \([-3,3]^2\), parameter penalty \((a^2+b^2)/4\ge9/4\). Since stage/terminal costs are nonnegative and positive-risk CE is at least the mean and hence nonnegative, the global objective is at least \(9/4\) there. For each selected *rational*, pre-frozen candidate, the same exact interval rules give a cost upper bound \(U_c<9/4\), so an exterior solution cannot improve it.

Start with the full square, recursively split the longer edge into two **dyadic rational** halves, and maintain a priority queue of active boxes. A box can only be discarded if \(L(B)\ge U_c\). Thus the union of active and proven-discarded boxes covers the original square inductively. Float heap priorities determine only which box to inspect next; all comparisons involving proof bounds use Python \`Fraction\` exact arithmetic. If the smallest active lower bound is \(L_*\), then

\[
\boxed{0\le J(\hat\theta)-J^*\le U_c-\min(L_*,L_c),}
\]

where \(L_c\) is the exact lower enclosure at the candidate itself. Stop once the gap is at most \(1/100\) or **50,000** splits, never changing those thresholds based on efficacy outcomes. All final active-frontier boxes, their exact rational lower bounds, original protocol and candidate cost enclosure are saved; an independent audit reruns the algorithm and compares the frontier hash.

For a **frozen trained endpoint** \(\theta_f\), first convert its two float64 values to exact rational values via \`Fraction.from_float\`. Bound \(J(\theta_f)\) again using the *same two-sided risk enclosure*, and combine its rational upper with the common rational global lower. Only if this entirely rational inequality is \(\le1/100\) is it called a **certified global-cost qualified model**. Saved floating model costs, gradient residuals or Hessian signs alone cannot grant this classification.

## 4. What is and is not proved

For the pre-frozen signed candidate \((154696889/10^8,44887401/10^8)\), the proof stops after 2,985 splits; for the control candidate \((164044199/10^8,42331392/10^8)\), 4,890 splits. In both cases \(U_c-L_*<1/100\), so the frozen target succeeds. The computed gap is conservative and not the actual unknown regret. The certified statement is global **cost** proximity; there is **no certified unique global parameter minimizer**, no guarantee a solver converges from arbitrary starts, and no full nonconvex 3+-parameter branch-and-bound result. Continuous input laws, unmodeled environment dynamics, generic multi-layer FBSDE and language/world-model performance are outside this theorem.
