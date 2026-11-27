# R13 protocol: nonzero-risk two-weight forward Stem, exact rational certificate

Parent R12 exact-moment PR #1959 commit `6026b1664a369d26e90b9cb81fb787898ad9d410`. This exploratory follow-on is frozen before the complete rational certificate calculation. The numerical root used to select a candidate was preliminarily inspected; therefore this is not a blind efficacy preregistration. The **proof** must not use solver success or floating-point integration as a premise.

Distribution: X uniform on [-1,1], initial P0 uniform in {0,1}, independent equiprobable epsilon in {-1,+1}. Forward Stem:
H1=X+a X^2+b X^3+epsilon/5. Target T=X^2+X^4/2. P1=P0 xor 1_{epsilon=+1}. Terminal cost L=(H1-T)^2+P1/20. Subject risk rho_0=1/2, rho_1=1; discount gamma=9/10. Backward recursion is conditional entropic certainty equivalent, NOT a zero-risk substitute:
Y0=gamma/rho_P0 log(E[exp(rho_P0 L)|X,P0]).
The two shared coefficients a,b change the forward state itself. Nonlinear polynomial state evolution, not Transformer, pretrained representation or an end-to-end language/world-model model. The Bernoulli martingale coefficient is Z=L_plus-L_minus.

Certification method:
- propose a decimal rational candidate using independent Gauss–Legendre numerical root; candidate selection is NOT proof;
- prove a uniform bound for |rho_p(2z/5+/-1/40)|<=1/2 over the whole input domain using exact rational Bernstein coefficient hulls on fixed subintervals;
- evaluate the gradient's tanh Taylor polynomial using exact Fraction arithmetic and exact uniform moments E[X^(2k)]=1/(2k+1);
- use Cauchy coefficient bound |tanh Taylor coefficient|<=4 on |z|=1 and a geometric tail to rigorously enclose each full-population gradient;
- show global strong convexity H >= (9/35)I for the two coefficients, hence bound distance to the unique global optimum and true population suboptimality. Do not claim a global optimum for an arbitrary multi-layer network.
- compare to the one-weight b=0 family with a proven positive population regret lower bound, and independently check forward/Bernoulli and preference-state bookkeeping.
- keep the previous R10 historic 35/96 and R11 corroborated 68/96 unchanged.

All computed rational objects, test logs, candidate, precision, and SHA hashes must be retained. Any failing assertion or interval-bound violation blocks claims. Report runtime and limitations transparently. This exact polynomial/one-step entropic FBSDE special case does NOT demonstrate general NDU/viscosity PDEs, learning unknown dynamics, or LLM generalization. No production admission, main merge, or historical rewrite. A new read-only CI workflow may check this certificate at the PR head; hosted result cannot be asserted before observation.
