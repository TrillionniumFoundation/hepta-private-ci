# A verifiable regenerative free-boundary oracle

## Scope and relation to the motivating paper

This is a new, deliberately tractable **scalar impulse-control model**. It is
not an implementation of the debt/equity model in He and Xiong, *Rollover Risk
and Credit Risk* (2012), https://www.princeton.edu/~wxiong/papers/rollover.pdf.
That paper motivates endogenous value-based boundaries; its risk-neutral
financing equations and lower default boundary are not asserted to hold for
neural states. Here the boundary is an upper firing boundary. The theorem
below concerns an infinite-horizon stationary scalar process, not a learned
multilayer network, input-dependent coefficients, or a finite remaining budget.

## 1. State, action, and objective

During an active interval, the observable state follows

\[
 dX_t=\mu\,dt+\sigma\,dW_t,\qquad
 \mu\in\mathbb R,\quad\sigma>0.
\]

At an admissible stopping time an agent can fire, receive **the immediate
reward** \(X_{t^-}-K\), reset the state to \(r<K\), and enter a mandatory
refractory interval of duration \(\tau\ge0\). The state is frozen at \(r\)
during that interval. No reward, state noise, or new action is allowed during
refractoriness. Afterward, the same active diffusion resumes. Discount is
\(\rho>0\). A control is an adapted, nonaccumulating sequence of firing times;
infinite waiting is permitted. The objective is

\[
 J(x)=\sup_\pi\mathbb E_x\sum_n
 e^{-\rho T_n}(X_{T_n^-}-K).
\]

The usual integrability condition on discounted rewards is imposed; controls
with a negative-infinite objective cannot improve the supremum. The active
generator and intervention operator are

\[
 \mathcal L=\mu\partial_x+\tfrac12\sigma^2\partial_{xx},\qquad
 \mathcal M U(x)=x-K+e^{-\rho\tau}U(r).
\]

The stationary QVI is

\[
 \max\{\mathcal LJ-\rho J,\mathcal MJ-J\}=0.
\]

The value with \(a\) units of refractory time still remaining is
\(e^{-\rho a}J(r)\). This supplementary state makes the time convention
explicit; refractory time is not free computation or a second immediate reset.

## 2. Fixed-threshold renewal value

Let \(T_b\) be the first upper hit of \(b>x\). The positive characteristic root
is

\[
 \kappa=\frac{\sqrt{\mu^2+2\rho\sigma^2}-\mu}{\sigma^2}>0,
 \qquad \mathbb E_x[e^{-\rho T_b};T_b<\infty]=e^{-\kappa(b-x)}.
\]

For a threshold \(b>\max(K,r)\), the first reward and all subsequent cycles give

\[
 J_b(x)=e^{-\kappa(b-x)}\{b-K+e^{-\rho\tau}J_b(r)\},\qquad x<b.
\]

Solving this renewal equation yields

\[
 q_b=e^{-\rho\tau-\kappa(b-r)}\in(0,1),\qquad
 J_b(x)=\frac{e^{-\kappa(b-x)}(b-K)}{1-q_b}.
\]

For \(x\ge b\), immediate firing gives
\(J_b(x)=x-K+q_b(b-K)/(1-q_b)\). Thus reset and refractory continuation
contribute to the value; this is not a first-event-only payoff.

## 3. Existence and uniqueness of the optimal boundary

Smooth fit at the firing boundary requires \(J_b'(b^-)=1\), hence

\[
 H(b)=\kappa(b-K)-1+e^{-\rho\tau-\kappa(b-r)}=0. \tag{1}
\]

At \(b=K\), \(H<0\); at \(b=K+1/\kappa\), \(H>0\).
Throughout that interval,

\[
 H_b=\kappa(1-q_b)>0.
\]

There is exactly one root \(b_*\in(K,K+1/\kappa)\). The implementation solves
the dimensionless, cancellation-resistant equation

\[
 y+\operatorname{expm1}(-a-y)=0,\quad
 a=\rho\tau+\kappa(K-r)>0,\quad
 y=\kappa(b_*-K)\in(0,1).
\]

The resulting candidate value is

\[
 J_*(x)=\begin{cases}
  e^{\kappa(x-b_*)}/\kappa,&x<b_*,\\
  x-b_*+1/\kappa,&x\ge b_*.
 \end{cases} \tag{2}
\]

It is \(C^1\), and is piecewise \(C^2\). The second derivative jumps at the
boundary: the theorem does not claim global analytic smoothness.

## 4. Global verification, beyond matching two boundary conditions

Equation (1) implies
\(\mathcal MJ_*(x)=x-b_*+1/\kappa\). For \(x<b_*\), writing
\(z=\kappa(x-b_*)\),

\[
 J_*(x)-\mathcal MJ_*(x)=\frac{e^z-1-z}{\kappa}\ge0.
\]

For \(x\ge b_*\), equality holds. On the continuation region,
\((\mathcal L-\rho)J_*=0\), by the characteristic equation. On the action region,

\[
 (\mathcal L-\rho)J_*(x)
 =\mu-\rho(x-b_*+1/\kappa)
 =-\tfrac12\sigma^2\kappa-\rho(x-b_*)\le0.
\]

Thus **both QVI inequalities hold globally**, not only at the proposed root.
Generalized Ito's formula has no boundary local-time term because the two
first derivatives agree. Discounted value is a supermartingale under waiting;
the intervention inequality bounds every allowed firing reward plus its
refractory continuation by the pre-action value. Stopping/localization and
then taking expectations therefore bound every admissible policy by \(J_*\).
The candidate has at most linear growth. Discount kills the first moment of
the arithmetic Brownian state; fixed resets do not invalidate that bound.
During refractory intervals the augmented-state discounted value is constant
in expectation. These facts supply the transversality needed for the limit.

The threshold policy waits only where the generator equality holds and fires
only where the intervention equality holds, so it attains the bound. Its
successive active hitting times are positive and independent after reset by
the strong Markov property; they cannot accumulate in finite time, even when
\(\tau=0\). A path may never hit again when \(\mu<0\); that possibility is already
included in the discounted hitting transform. This verifies global optimality
for the stated admissible control problem.

## 5. Joint boundary derivatives and conditioning

Put \(\omega=\sqrt{\mu^2+2\rho\sigma^2}\), \(q=q_{b_*}\),
\(A=b_*-K-q(b_*-r)\), and \(D=\kappa(1-q)>0\). Then

\[
 \kappa_\mu=-\kappa/\omega,\qquad
 \kappa_\sigma=-\sigma\kappa^2/\omega,\qquad
 \kappa_\rho=1/\omega,
\]

\[
 b_\mu=-A\kappa_\mu/D,\quad
 b_\sigma=-A\kappa_\sigma/D,\quad
 b_\rho=(-A\kappa_\rho+\tau q)/D,
\]

\[
 b_K=\kappa/D,\qquad b_r=-\kappa q/D,\qquad
 b_\tau=\rho q/D.
\]

These are partial derivatives with the other physical parameters fixed. A
learned constrained parameterization, such as \(r=K-\operatorname{softplus}(g)\),
must apply its full chain rule; varying \(K\) then also varies \(r\).
The custom Torch backward implements these six first derivatives and supports
broadcast reduction. Higher-order derivatives through the detached root have
not been implemented or certified.

Near \(r\uparrow K,\tau\downarrow0\), \(1-q\) approaches zero and conditioning
deteriorates. A unique root is not a guarantee of a small derivative. The
validation records this behavior rather than clipping the gradient and calling
the clipped result exact. Differentiating the **value-matching** equation alone
would be inappropriate here: the boundary is identified by the smooth-fit
residual (1), whose total root derivative is nonzero in the stated domain.

## 6. First passage, interval survival, and regeneration are different objects

For \(d=b-x>0\), constant coefficients, and \(t>0\),

\[
 F(t)=\Phi\!\left(\frac{\mu t-d}{\sigma\sqrt t}\right)
 +e^{2\mu d/\sigma^2}\Phi\!\left(\frac{-\mu t-d}{\sigma\sqrt t}\right),
\]

\[
 f(t)=\frac{d}{\sigma\sqrt{2\pi t^3}}
 \exp\!\left[-\frac{(d-\mu t)^2}{2\sigma^2t}\right],\qquad S(t)=1-F(t).
\]

The second, reflected term distinguishes first passage from endpoint
exceedance. Log-CDF and expm1 forms preserve small survival probabilities.
Discounted first-hit mass is obtained by a density tilt:

\[
 H_\rho(t)=\mathbb E[e^{-\rho T_b}\mathbf1_{T_b\le t}]
 =e^{-\kappa d}F_{\omega,\sigma}(t;d).
\]

The killed first moment is

\[
 \mathbb E[X_t\mathbf1_{T_b>t}]
 =(x+\mu t)S(t)-2d\,e^{2\mu d/\sigma^2}
 \Phi\!\left(\frac{-\mu t-d}{\sigma\sqrt t}\right).
\]

Adding \(rF(t)\) resets every hit at the interval end. That **does not** account
for the random time remaining after the actual hit, further firings, or the
refractory-age distribution. It is a declared neural mean-state approximation,
not the exact regenerative propagator. Neither a mean state nor a first-hit
CDF is a sample trajectory of a spiking neuron.

There is also an exact repeated-event series for the **fixed threshold**.
Let \(d_0=b-x\) and \(d_r=b-r\). Strong Markov independence of successive active
intervals implies that the sum of their first-hit times has the first-hit law
for their summed distances. Equivalently, their Laplace transforms multiply.
Thus the nth firing time has the law

\[
 T_n\overset{d}{=}T_{\mathrm{hit}}(d_0+(n-1)d_r)+(n-1)\tau.
\]

The finite-time expected discounted reward is therefore

\[
 J_{b,T}(x)=(b-K)\sum_{n\ge1}e^{-\rho(n-1)\tau}
 H_\rho\!\left(T-(n-1)\tau;d_0+(n-1)d_r\right),
\]

where terms with nonpositive remaining time vanish for a subthreshold start.
For \(\tau>0\) only finitely many terms remain. For \(\tau=0\), the remainder
after N terms is bounded by \(J_b(x)q_b^N\). This is a real-arithmetic series
truncation bound, not a floating-point interval-arithmetic certificate.
`finite_time_threshold_value` implements this expression. It accounts for
repeated firings and the actual refractory shift within the finite interval;
it does **not** optimize a terminal deadline-dependent boundary or propagate a
coupled neural content state.

Separately, `renewal_reference` implements numerical renewal quadrature. It
uses exact discounted first-hit bin masses and rounds continuation time to a
grid, with refractory duration aligned to that grid. `oracle_tests.py` refines
this independent recurrence against the exact finite-time series and also
checks density integrals and a killed-kernel semigroup. A finite horizon is not
silently identified with the infinite-horizon value.

## 7. Degenerate regimes and exclusions

- **Zero noise, positive drift:** \(\kappa=\rho/\mu\); the same renewal equation
  and boundary formula apply, with deterministic hitting time \((b-x)/\mu\).
- **Zero noise, nonpositive drift:** \(J(x)=\max(x-K,0)\). Fire immediately when
  profitable and otherwise never fire. Reset has no profitable future. The
  positive-root diffusion formula and its boundary derivatives are not used.
- **No further usable cycle:** as \(\tau\to\infty\), \(q\to0\) and
  \(b_*\to K+1/\kappa\), the single-firing threshold.
- **Zero refractory duration:** permitted because \(r<K<b_*\); the positive
  active hitting duration prevents accumulation for the optimal policy.
- **Reset at/above cost:** excluded by the implementation contract. In
  particular \(r=K,\tau=0\) can destroy root conditioning and admits chattering
  limits; the theorem is not extended to that boundary by silent clipping.
- **Zero discount:** excluded. With nonnegative drift the repeated positive
  undiscounted reward may diverge. A formal small-discount limit is not a new
  certified finite-valued objective.
- **Finite remaining time, moving boundary, changing coefficients, correlated
  neural states, or content-dependent rewards:** outside this theorem. A local
  frozen-coefficient approximation can be trained and measured, but inherits
  no global optimality certificate from (1)--(2).

## 8. Independent validation

The executable validation records global obstacle/generator inequalities,
matching/smooth-fit errors, all six derivative checks, a separate scalar
threshold optimizer, and a monotone finite-difference QVI solver with policy
iteration. The latter uses no analytic root or value in its solver and is
checked on three refined grids. It also records integral, killed-semigroup,
renewal-refinement, deterministic-limit, near-chattering, and Torch gradchecks.
The JSON contains source hashes and runtime versions. These checks certify the
implemented scalar contract only; they are not benchmark superiority evidence
for a neural architecture.
