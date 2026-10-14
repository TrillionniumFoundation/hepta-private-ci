# R13 — exact population certificate for a nonzero-risk, two-weight forward Stem

## Scope and law

This is a **one-step, discrete, nonlinear-in-state, two-parameter, nonzero-risk NDU/FBSDE special case**. It is **not** a theorem for unrestricted deep neural networks, multi-step coupled FBSDEs, viscosity solutions, language models or unknown world dynamics. The rational weight candidate was initially proposed using a numerical root; every claimed proof bound below is computed **independently in rational arithmetic**.

Let \(X\sim U[-1,1]\), \(P_0\sim\mathrm{Bernoulli}(1/2)\), \(\varepsilon\in\{-1,+1\}\) equiprobable, all independent. The two shared forward-Stem weights are \(\theta=(a,b)\). Define

\[
H_1=X+aX^2+bX^3+\varepsilon/5,\qquad
P_1=P_0\oplus\mathbf1\{\varepsilon=+1\},\qquad
T(X)=X^2+X^4/2.
\]

Terminal cost \(L=(H_1-T(X))^2+P_1/20\). Preference-specific risk sensitivity \(\rho_0=1/2,\rho_1=1\), with discount \(\gamma=9/10\). The backward recursive cost is

\[
Y_0(X,p)=\frac{\gamma}{\rho_p}
\log\mathbb E\big[e^{\rho_p L}\mid X,P_0=p\big],
\qquad J(a,b)=\mathbb E_{X,P_0}[Y_0(X,P_0)].
\]

This is a known finite-branch entropic BSDE. With \(m=\mathbf1\{\varepsilon=+1\}-1/2\), the terminal martingale difference is \(L-\mathbb E[L\mid X,p]=Z m\) with **\(Z=L_+-L_-\)**. This \(Z\) is not a weight gradient. Preference updates change the terminal payoff state even as risk is determined by the initial preference state.

## Explicit smooth population objective and Hessian

Put \(z=X+(a-1)X^2+bX^3-X^4/2\), \(\delta=1/5\), \(\bar c=1/40\), and \(\Delta_p=(1-2p)/40\). For branch outcomes \(L_\pm=(z\pm\delta)^2+P_{1,\pm}/20\), direct algebra gives

\[
\frac{1}{\rho_p}\log\frac{e^{\rho_p L_+}+e^{\rho_p L_-}}2
=z^2+\delta^2+\bar c+
\frac{1}{\rho_p}\log\cosh\big(\rho_p(2\delta z+\Delta_p)\big).
\]

Let \(\phi(X)=(X^2,X^3)^\top\). Differentiating *the population objective* yields

\[
\nabla J(a,b)=\gamma\mathbb E_X\left[
\Big(2z+\delta\big(\tanh(z/5+1/80)+\tanh(2z/5-1/40)\big)\Big)\phi(X)\right].
\]

Because the derivative of each risk aggregator in \(z\) has second derivative
\(2+4\rho_p\delta^2\operatorname{sech}^2(\rho_p(2\delta z+\Delta_p))\ge2\), for **all real \((a,b)\)**,

\[
\nabla^2J\succeq2\gamma\mathbb E[\phi\phi^\top]
=\begin{pmatrix}9/25&0\\0&9/35\end{pmatrix}
\succeq mI,\qquad m=9/35>0.
\]

Thus \(J\) is globally strongly convex and coercive in its two coefficients. Its unique global minimizer exists, without needing a nonconvex neural-network optimizer's stopping flag.

## Candidate and certified gradient residual

Choose fixed rational candidate

\[
\widehat a=1359072658021/10^{12},\qquad
\widehat b=-1400028626085/10^{12}.
\]

The source partitions the *entire* interval [-1,1] into 16 segments and computes exact Bernstein coefficients for the fourth-degree polynomial \(z(x;\widehat a,\widehat b)\). The coefficient convex-hull property proves

\[
-\frac{8452437001}{15625000000}\le z(x)\le
\frac{49326071793141}{128000000000000},
\quad x\in[-1,1].
\]

Consequently both actual tanh arguments satisfy \(|t_p(x)|\le 9428999501/39062500000<1/2\), uniformly over the full distribution.

For complex \(|u|\le1\), elementary series majorants give \(|\sinh u|<4/3\) and \(|\cosh u|>1/3\). The latter follows from \(|\cosh u|\ge2-\cosh1>1/3\). Hence \(\tanh u\) is analytic in this disk and bounded there in modulus by 4. Cauchy's coefficient estimate and a geometric series imply for its Taylor polynomial \(T_N\):

\[
|\tanh(t)-T_N(t)|\le\frac{8}{2^{N+1}},\quad |t|\le1/2.
\]

Coefficients of \(T_{64}\) are obtained *exactly* from \((\tanh u)'=1-\tanh^2u\); substituting the rational polynomials \(t_0(x),t_1(x)\) and integrating polynomial powers with \(\mathbb E[X^{2k}]=1/(2k+1)\) evaluates both surrogate gradient coordinates as exact fractions. Each true gradient coordinate differs from its rational surrogate by at most

\[
e=\gamma(2\delta)\frac8{2^{65}}=
\frac{72}{25\,2^{65}}.
\]

Set \(G=|g_{64,a}|+|g_{64,b}|+2e\). Then \(\|\nabla J(\widehat\theta)\|_2\le G\). Strong convexity yields global certificates

\[
\boxed{\|\widehat\theta-\theta^*\|_2\le G/m},\qquad
\boxed{0\le J(\widehat\theta)-J(\theta^*)\le G^2/(2m)}.
\]

The exact rational output of `certificate.py`, not rounded decimals, is the authoritative proof object. Decimal *presentations* of the rational bounds are approximately **2.954176e-13** for parameter error and **1.122063e-26** for population-cost suboptimality. These are not statistical confidence intervals, approximation between CC rules, or claims about arbitrary models.

## Why two shared weights are actually needed in this family

Let the restricted comparator force \(b=0\) and freely optimize \(a\). Any such parameter has Euclidean distance at least \(|b^*|\) from the certified unconstrained minimizer; furthermore \(|b^*|\ge|\widehat b|-G/m\). Strong convexity therefore establishes, for *all* real \(a\),

\[
\boxed{J(a,0)-J(\theta^*)\ge\frac m2\big(|\widehat b|-G/m\big)^2>0.252.}
\]

This is a global function-class separation, not a single unsuccessful scalar fit. The zero-risk optimum, derived by projection of \(z\) onto \(X^2,X^3\), is exactly \((19/14,-7/5)\); the risk-sensitive optimum is provably different since \(|\widehat a-19/14|-G/m>1/1000\). Thus the nonzero recursive-risk model genuinely changes the recovered forward weight.

## Independent diagnostics and limitations

Separate *floating-point only* SciPy/NumPy scripts solve the Gauss–Legendre population gradient, verify the Bernoulli martingale identity, and compare the CC5, GL5, GL17 trained surrogates on high-order integration. Their results do not enter the proof. On the chosen task the CC5 numerical solution's observed population regret is about 0.00147543, versus GL5 about 5.18e-10. This is a **numerical observation**, not a rigorous certificate for these separately fitted quadrature solutions.

The global certificate relies crucially on the exactly known bounded continuous input law, finitely many preference and noise states, a forward family *affine in two parameters*, and convex entropic terminal costs. It does not establish global optimization of a general multi-layer Stem or prove transfer to unknown distributions, higher-dimensional LLMs or nonlinear unrestricted FBSDE viscosity solutions. Historical R10/R11 model gates and all production contracts remain unchanged.