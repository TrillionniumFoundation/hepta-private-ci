# R16 rigorous global certificate — positive-risk two-step and joint nonconvex weights

**Model.** Known 16-branch law with independent uniform X∈{-1,+1}, P0∈{0,1}, ε1,ε2∈{-1,+1}. Preferences update P1=P0 xor (ε1=+1), P2=P1 xor (ε2=+1); rho0=1/2,rho1=1, gamma=9/10. Forward states H1=aX, H2=bH1+ε2/10; stage cost P1/20 and terminal cost (H2−X)^2+P2/50. The trainable penalty (a²+b²)/4 is *outside* conditional entropic risk. Full nested law J is a bona fide two-step finite-state positive-risk control functional, nonconvex in parameters (a,b), with no oracle target fed to fits.

**Exact quotient.** Let t=ab and u=t−1. Conditional Bernoulli terminal risk at preference p is
Q_p(t,X)=u²+1/50+(1/rho_p) log cosh(rho_p*(uX/5+(1−2p)/100)).
Put A_p=p/20+gamma Q_p, then
C(t)=gamma E_{X,P0} [(1/rho_P0)log((exp(rho_P0 A_0)+exp(rho_P0 A_1))/2)].
Then J(a,b)=C(ab)+(a²+b²)/4. Both risk coefficients are nonzero, both stochastic preference transitions are included; there are 16 exact finite population leaves.

**Strict global reduction.** Q_p''(t)=2+rho_p*(X/5)^2 sech²(rho_p(...))≥2. For rho>0 the Hessian of logsumexp equals the softmax-weighted Hessians plus rho times a nonnegative variance. Applying this at both stages yields **C''(t)≥2 gamma²=81/50 for every real t**. AM–GM gives (a²+b²)/4≥|ab|/2, with equality only when |a|=|b|. Thus global minimization of the jointly nonconvex J reduces *exactly* to scalar strongly convex f(t)=C(t)+|t|/2. A certified negative right derivative at t=0 proves t*>0; opposite rigorous derivative signs at rational endpoints
69594347096172/10^14 < t* < 69594347096175/10^14
isolate its unique minimizer. Therefore the only two **global** minima are a=b=+sqrt(t*) and a=b=−sqrt(t*), over all real a,b, with no box cutoff.

**Rational candidate.** s=834232264397471/10^15 is candidate; its existence was suggested by preliminary float scouting but all proof predicates use only exact integer fractions. Evaluating the fully nested population gradient with directed-rounding 10^65-scale integer intervals bounds |f'(s²)| by g. Strong convexity implies |s−sqrt(t*)|≤g/((81/50)s) and population cost excess J(s,s)−inf J≤g²/(2*(81/50)). The exact certificate output implies **single-component weight error <5.35e−16**, **true population regret <1.62e−31**.

**Strict contrary theorems.** At origin (0,0), gradient J=0 but Hessian [[1/2,C'(0)],[C'(0),1/2]] has one strictly negative eigenvalue (the certified value f'_+(0)<−1.144), making it a false stationary solution. Any one-weight policy with b=0 has t=0, so strong convexity gives regret ≥(81/100)*(lower_product_bound)^2>**0.3923**. The exact zero-risk optimum product is 56/81, while the positive-risk optimum differs by >0.004585; replacing entropic risk with expectation changes learned forward weights.

**Why numerical steps are rigorous.** Every operation is exact integer numerator arithmetic with lower endpoints floored and upper endpoints ceiled on a fixed 10^65 grid. The real exponential is enclosed for |x|≤1 by the degree-36 Taylor polynomial with analytic tail ≤2/37!. The real logarithm is evaluated through 2*atanh((q−1)/(q+1)) with 12 terms and remainder ≤4r^25 where r≤1/2. All necessary domain/positivity checks and root sign inequalities are executable assertions; no SciPy status, stochastic estimate, quadrature or FP64 input is used to prove the bound.

**Scope boundary.** This is an exactly known finite-law, product-separable, two-parameter two-step special case, **not** a global theorem for general deep, unconstrained FBSDE or LLM training. The 32 independent solver outputs are classified numerically against this certified reference, not separately interval-certified. No trained production model or historical gate is changed.

