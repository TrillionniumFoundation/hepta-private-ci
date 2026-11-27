# Stable HX reference mathematics

Source: Zhiguo He and Wei Xiong, *Rollover Risk and Credit Risk*, Journal of Finance 67(2), 2012, DOI 10.1111/j.1540-6261.2012.01721.x. Equations (8), (9), (12), (A5), (A7).

Author-hosted published paper: https://zhiguohe.net/wp-content/uploads/2023/12/The-Journal-of-Finance-2012-HE-Rollover-Risk-and-Credit-Risk.pdf

Use `q=r+ell`, `mu=r-delta-sigma**2/2`, `a=mu/sigma**2`, `z=sqrt(a*a+2*r/sigma**2)`, `zq=sqrt(a*a+2*q/sigma**2)`, `eta=z-a`, `gamma=z+a`, `s=sigma*sqrt(maturity)`. Rationalize the small root when subtraction would cancel. In particular, `delta/(eta-1)=r/eta+sigma**2/2`; the latter avoids a removable singularity as payout tends to zero.

The positive normal-tail integral is

    H(lam,u,s) = integral_0^inf exp(-lam*y) Phi(u*s-y/s) dy
               = [Phi(u*s)-exp((lam**2/2-lam*u)*s**2)*Phi((u-lam)*s)]/lam.

`lam` may be negative. At zero its exact limit is

    H(0,u,s) = s * [phi(u*s)+u*s*Phi(u*s)].

Near zero, expand using `H=sum_n (-lam)**n/n! * M_n`, where `M_n=s**(n+1)/(n+1)*J_(n+1)(u*s)` and `J_k(w)=E[(w+Z)_+**k]`. The truncated normal moments obey `J0=Phi(w)`, `J1=w*Phi(w)+phi(w)`, `Jk=w*J_(k-1)+(k-1)*J_(k-2)`. In negative tails use a positive integral or a special function instead of this cancelling recurrence. For nonzero lam evaluate the numerator with log-CDF and expm1/log-difference.

Define

    I_F = H(z+a,a,s)+H(z-a,-a,s)
    I_G = H(z+zq,zq,s)+H(z-zq,-zq,s)
    A = (1-tax)*coupon + (1-exp(-q*maturity))*(p-c/q)
    B = exp(-q*maturity)*(p-c/q)
    b = (A/eta + B*I_F + c/q*I_G)
        / (r/eta+sigma**2/2 + recovery/maturity*I_G).

Compute `z-zq=-2*ell/(sigma**2*(z+zq))`, making ell=0 an exact H-limit. Thus ell=0 is a supported liquidity limit. It does **not** remove rollover: the equity equation still contains `d(x,m)-p`.

The equity equation in log distance is `(r-L)E=g`, with `L=mu*d_x+sigma**2/2*d_xx`, `g=delta*b*exp(x)-A-B*F(x,m)+D*G(x,m)`, `D=recovery*b/m-c/q`. For a fixed b the Dirichlet resolvent is

    Rg(x) = [exp(-gamma*x) integral_0^x (exp(gamma*y)-exp(-eta*y))*g(y)dy
             +(exp(eta*x)-exp(-gamma*x)) integral_x^inf exp(-eta*y)*g(y)dy]
            /(sigma**2*z).

For the elementary normal term `Q_u(x)=exp(-(a+u)*x)*Phi(u*s-x/s)`, its closed resolvent is

    RQ_u(x) = {exp(-gamma*x)*[H(u-z,u,s)-H(z+u,u,s)]
               +exp(-(a+u)*x)*[H(z+u,u-x/s**2,s)-H(u-z,u-x/s**2,s)]}
              /(sigma**2*z).

Then `RF=RQ_a+RQ_-a`, `RG=RQ_zq+RQ_-zq` and

    E=b*(exp(x)-exp(-gamma*x))-A*(1-exp(-gamma*x))/r-B*RF+D*RG.

This formula is algebraically equivalent to A7. At small x it subtracts first-order terms to obtain a second-order result; at large maturity its H terms can cancel badly. The FP64 reference also supplies independently integrated killed-resolvent equity as an oracle. For small x at the optimal boundary, an especially stable representation is

    E(x)=-integral_0^x exp(eta*(x-y))*(-expm1(-2*z*(x-y)))*g(y)dy/(sigma**2*z).

For x→0, `E=-g(0)/sigma**2*x**2+O(x**3)`. When callers provide a nonoptimal b, the small-x expression additionally needs `E'(0)*(exp(eta*x)-exp(-gamma*x))/(2*z)`.

At x=0 the hitting time is an atom at zero: F=G=1 for T>=0. The regular density f is zero for t>0 and carries no representation of that atom. At x>0,T=0, F=G=f=0. For debt, default at x=0 dominates the terminal corner; d(0,0)=recovery*b/m, whereas d(x,0)=p for x>0. Negative x, negative T, sigma<=0 are rejected, rather than silently reinterpreted.

Domain: r>0, delta>0, sigma>0, m>0, ell>=0, coupon>=0, principal>0, 0<=tax<1, 0<=recovery<=1. Strict sigma=0/r=0/delta=0 cases are not the same well-posed original diffusion problem and are not hidden behind epsilons. Homogeneity: multiplying coupon, principal and V by a positive factor multiplies b, E and d by that factor, while F,G,f are unchanged. F,G are dimensionless; f has inverse-time units; ell,r,delta have inverse-time units and sigma has inverse-square-root-time units.

## Tensor H tail recommendation

For `w=-a<-1`, evaluate Taylor moments through the positive Laguerre integral

    J_n(-a)=exp(-a*a/2)/(sqrt(2*pi)*a**(n+1))
            * integral_0^inf v**n*exp(-v)*exp(-v*v/(2*a*a)) dv.

A 64-node fixed Gauss--Laguerre rule for n=1..6 gave maximum relative error
`1.43e-10` at a=1 and below `7.2e-13` at a=2,3,4,5,8,10,20 against SciPy's
parabolic-cylinder special function (FP64 evaluation). This is far below FP32
roundoff. A 32-node rule has ~`9.8e-6` maximum relative error at a=1 but below
`3.6e-10` at a>=2. The ordinary FP32 forward recurrence already loses ~0.8% at
a=4 and ~7% at a=5 for the sixth moment; do not extend it deep into negative
arguments. Use recurrence only for w>=-1, and the positive Laguerre expression
for w<-1. Evaluate log moments when a*a/2 is near underflow if later coefficients
can rescale them. In the six-term H Taylor branch higher moments are multiplied
by small powers of lam, so their contribution error is additionally suppressed.

The reference's default `hx_equity` is deliberately an independently integrated
oracle. `hx_equity_closed` is the closed A7-equivalent expression tested against
it. Reporting this distinction is required; numerical quadrature is not claimed
to be an exact symbolic evaluation or a production fast path.

## Formal roots versus economic feasibility

Positive primitive parameters and small equation residuals do not establish an
admissible equity value. Define the running cashflow at the root as

    g0 = delta*b-(1-tax)*coupon+recovery*b/maturity-principal/maturity.

The ODE and E(0)=E'(0)=0 give `E''(0+)=-2*g0/sigma**2`. Therefore `g0<=0` is a
necessary local condition for limited-liability equity. A root with g0>0 has
negative continuation equity immediately above it even if every algebraic
identity passes. For example, sigma=0.2, maturity=0.05, ell=0.3 with the other
default parameters produces b≈198.12124, g0≈377.667, and E(0.01)≈-0.8769.
This is an inadmissible financial equity root, useful only as a formal ODE test.

An additional sufficient monotonic-cashflow subdomain follows from the debt
representation. With R=recovery*b/maturity and S=P(tau>t),

    d(x,m)-R = (p-R)*exp(-q*m)*S(x,m)
               +(c-q*R)*integral_0^m exp(-q*t)*S(x,t) dt.

If `R<=min(p,c/q)`, both coefficients are nonnegative, so d is increasing in x;
the positive asset cashflow then makes g increasing. This is a deliberately
stronger, sufficient monotonicity screen, not a necessary condition for every
admissible model. The reference exposes both `local_admissible` and
`sufficient_monotone_subdomain` rather than equating their scope.

Published Eq.6 specifies uncapped recovery alpha*b/m. The condition alpha*b<=P
is not asserted here as a universally proved assumption of the paper. Its
violation is a separate `uncapped_recovery_exceeds_face` diagnostic. A model that
requires debt recovery capped by face value must explicitly change the boundary
payoff and rederive the coupled equations; silently clamping R is incorrect.

The 144-point numerical scan includes formal inadmissible parameters on purpose
and labels each point accordingly. Its small closed-versus-oracle error measures
agreement of equation solutions; it does not assert financial admissibility of
all points, neuron stability, or task/NDU global optimality.

## Change of time unit

Under T'=k*T and m'=k*m, use r'=r/k, delta'=delta/k, ell'=ell/k,
C'=C/k, sigma'=sigma/sqrt(k), with P, tax and recovery unchanged. Then
b and E are unchanged; F and G are unchanged; f'=f/k. Because the paper
normalizes the maturity ladder to one unit of debt maturing per time unit,
p=P/m and d are values per maturity-ladder unit and transform as p'=p/k,
d'=d/k; the coupon density c=C/m transforms as c'=c/k**2. Multiplying d by
an unchanged time step after changing time units would therefore be incorrect.
The full HX covariance, including the boundary and rollover term, is tested.
