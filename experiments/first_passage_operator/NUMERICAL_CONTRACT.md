# Regenerative operators and a natural firing free boundary

This module extends the frozen `first_passage_cell` primitives. It does not alter
that package, its source/model freeze, or its maintenance experiment. Its exact
mathematical claims and its finite numerical verification are separate below.

## 1. Augmented state and finite renewal propagation

An active cell has distance `x > 0` and follows

\[
 dX_t=\mu\,dt+\sigma\,dW_t.
\]

Its first hit at zero emits an event, resets distance to `r > 0`, and holds the
state there for a mandatory duration `a > 0`. A refractory state is `(r, eta)`
with remaining duration `eta > 0`; release at `eta = 0` is active. No running
reward or diffusion accrues while refractory. Event reward is paid at its actual
emission time. Parameters are constant within a propagation segment. An input or
parameter change starts a new segment; a missing observation does not condition
on survival. A start at distance zero emits an immediate event even for horizon
zero, and the terminal state is then the reset state with its full refractory
clock. Negative starting distances are rejected.

The extended state is essential. Distance alone cannot distinguish an active
reset state from a reset state that still owes refractory time. Suppressing that
clock loses the Markov property and makes semigroup composition incorrect.

Let `F_d`, `f_d`, and `H_(q,d)` be the existing lower-barrier first-passage CDF,
density, and truncated discounted weight from initial distance `d`. The nth event
has time law

\[
 T_n=(n-1)a+\tau_{x+(n-1)r},\qquad n\geq1.
\]

This follows from independent increments and the first-passage convolution
identity. It holds for positive drift as a defective law, including the atom at
infinity. Only finitely many terms contribute before a finite horizon because
`a > 0`.

The terminal refractory mass is

\[
 \sum_{n\geq1}\{F_{d_n}(t-(n-1)a)-F_{d_n}(t-na)\},
 \quad d_n=x+(n-1)r,
\]

where CDFs at negative time are zero. Active mass is its complement. Active
terminal propagation consists of the killed kernel from the initial state,
plus each possible last event followed by release and a killed kernel from the
reset. Refractory terminal propagation retains the distribution of the remaining
clock, rather than replacing it by a point mass at zero.

For the active payoff `exp(-z*y)`, `z >= 0`, the spatial integration is analytic:

\[
 \int_0^\infty e^{-zy}K_t^{\mu}(x,dy)
 =e^{-zx+(\sigma^2z^2/2-\mu z)t}
 S_t^{\mu-\sigma^2z}(x).
\]

For refractory payoff `exp(-h*eta)`, its nth contribution is a discounted
first-hit interval. Subtracting two saturated `H_h` totals is unstable at high
`h`, because multiplying by the remaining-clock exponential can amplify a lost
small interval. Instead, put `zeta = sqrt(mu^2 + 2*h*sigma^2)` and use

\[
 e^{-hv} f_d^{\mu}(v)
 =e^{-(\mu+\zeta)d/\sigma^2} f_d^{-\zeta}(v).
\]

A stable `F` or `S` interval difference under this tilted drift retains the small
mass before rescaling. `REFRACTORY_INTERVAL_REPAIR.json` and the first extended
validation retain the detected cancellation and its source.

The active renewal convolution also has a closed form. Apply the strong Markov
property at the first hit of level `r` from initial state `d+r`: paths either
have not hit `r` or have hit it and continue with killed propagation from `r`.
Consequently,

\[
 (f_d*K_r)_T(y)=K_T(d+r,y)-\mathbf1_{y>r}K_T(d,y-r).
\]

Writing `L_t(x,z)` for the killed exponential transform above gives the finite
terminal active feature sum

\[
 A_z(t,x)=L_t(x,z)+\sum_{n\geq1:na<t}
 \left[L_{t-na}(x+nr,z)-e^{-zr}L_{t-na}(x+(n-1)r,z)\right].
\]

The implementation computes each nonnegative difference with the smaller of the
`F` and `S` tails after exponential tilting. This avoids the fixed time-quadrature
failure found for initial distances near zero. There is no time quadrature,
spatial truncation, or state-grid approximation in these terminal feature
operators. The original quadrature labels and the failure diagnosis are retained
in `aborted_operator_quadrature_01` and `ANALYTIC_RENEWAL_REPAIR.json`.

`operator_features` returns active and refractory terminal moments, their
actual-time discounted counterparts, event counts, discounted event counts, and
discounted active occupation. `apply_value` contracts these moments with arbitrary
finite positive or negative payoff coefficients. Its gradient with respect to
terminal coefficients is exactly the discounted moment vector. Reward coefficients
multiply occupation and event-count moments. This linear layer can be embedded
in a learned nonlinear map from public dynamics/context to moment vectors.

The constant active payoff is evaluated by that same finite expansion. Its raw
mass identity defect is reported independently; moments are never normalized to
conceal an error. The historical API key `mass_quadrature_defect` now reports
this analytic identity defect. The `quadrature_order` argument is retained for
caller compatibility; it does not tune these analytic paths.

For discount zero, occupation uses the analytic primitive

\[
 J_d(T)=\int_0^T F_d(u)du
       =T F_d(T)+\left.\partial_q H_{q,d}(T)\right|_{q=0}.
\]

The implementation uses the conditional first-passage time already provided by
the frozen kernel gradients. Terms whose upper bound `T*F(T)` is below half the
smallest subnormal return zero before evaluating a conditional derivative; this
avoids an irrelevant far-tail conditioning error. The concrete training-context
failure and this strict underflow bound are retained in
`OCCUPATION_TAIL_REPAIR.json`. For ordinary positive discount,
occupation uses `H_q` and `F`; only the cancellation-prone small-positive-discount
branch uses adaptive integration. Every segment accounts for its remaining time
after an initial refractory delay.

These are fixed-policy propagation operators. Maximization over actions and the
accuracy of an approximating value network require additional evidence. The
operator is positive and contracts bounded terminal payoffs by at most
`exp(-q*t)` in sup norm, up to numerical evaluation error. This alone does not
prove convergence of a sampled nonlinear training algorithm.

## 2. A solved natural firing problem

Here the active physical state is an unrestricted real Brownian diffusion
`dX = mu dt + sigma dW`. A spike is the natural first crossing of an endogenous
upper threshold; emitting earns `X - c`, resets to `r`, and imposes refractory
duration `a`. Rewards during refractoriness are zero. The objective is the
expected discounted sum of actual spike rewards, with `q > 0`. The supported
nondegenerate domain is `sigma > 0`, `a > 0`, `q > 0`, and `c >= r`.

This is a specific optimal recurrent emission problem. It is not the prior
voluntary maintenance gate, and the physical firing threshold is now the unknown
being optimized. It is also not a claim that an arbitrary neuronal objective,
finite deadline, input process, or interacting network has this same solution.

Define

\[
 \lambda={\sqrt{\mu^2+2q\sigma^2}-\mu\over\sigma^2}>0,
 \qquad \beta=e^{-qa}.
\]

For an upper threshold `b > r`, the return from reset follows a regenerative
identity with discounted hitting transform `exp(-lambda*(b-r))`. The optimal
threshold is the unique root

\[
 \lambda(b-c)+\beta e^{-\lambda(b-r)}=1,
 \qquad c<b<c+1/\lambda.
\]

For `c = r` the same open bounds hold because `beta < 1`. On this interval the
left side is strictly increasing; it is below one at `c` and above one at the
upper endpoint. The reset value is

\[
 C={e^{-\lambda(b-r)}\over\lambda}.
\]

The candidate full value is

\[
 V(x)=
 \begin{cases}
 e^{\lambda(x-b)}/\lambda,&x<b,\\
 x-c+\beta C,&x\geq b,
 \end{cases}
 \qquad V_{\rm ref}(\eta)=e^{-q\eta}C.
\]

Both value matching and smooth fit hold:

\[
 V(b)=b-c+\beta V(r),\qquad V'(b-)=1.
\]

### Verification over admissible spike policies

The intervention operator is `M V(x) = x - c + beta V(r)`. The QVI is

\[
 \max\{(\mathcal L-q)V,\;\mathcal M V-V\}=0.
\]

Below the threshold, `(L-q)V = 0` because lambda solves
`0.5*sigma^2*lambda^2 + mu*lambda - q = 0`. The exponential graph is convex and
has the intervention line as its tangent at `b`, so `V >= M V` throughout the
continuation region. In the firing region the intervention gap vanishes and

\[
 (\mathcal L-q)V(x)
 =\mu-q(x-c+\beta C)
 \leq \mu-q/\lambda
 =-\tfrac12\sigma^2\lambda<0.
\]

The candidate is continuously differentiable at the boundary, so the generalized
Ito formula adds no local-time mismatch. Discounted value plus paid rewards is a
supermartingale under any admissible nonanticipating policy. At every spike the
intervention inequality accounts for the immediate reward and exactly the
refractory discount before reset. With this threshold the corresponding
inequalities are equalities until stopping.

Positive refractory time bounds event count on every finite horizon. The
candidate has at most linear positive growth, tends to zero as `x` tends to
negative infinity, and the Brownian expected absolute state grows at most
linearly plus the square root of elapsed time between resets. Exponential
discount therefore gives the required terminal transversality in expectation
for policies with integrable rewards. Optional sampling, localization, and the
limit in time give the upper bound for every such policy and attainment by the
threshold policy. This verifies global optimality in this stated scalar model,
not merely optimality inside a searched grid of thresholds.

`solve_boundary` also returns implicit derivatives with respect to drift,
diffusion, reset, refractory duration, discount, and spike cost. An independent
monotone finite-difference Howard solver includes the same nonlocal reset value
in its stop rows. It does not use the analytic boundary to choose its policy.
Central drift differences are used only when they give nonnegative generator
rates; a monotone upwind fallback covers coarser grids. Grid spacing and
remote-boundary truncation remain disclosed numerical errors. The initial
upwind-only reference failed its relative-value tolerance; that result remains
in `NUMERICAL_VALIDATION_V1.json`. The exact boundary formula was unchanged when
the independent reference was refined.

## 3. Numerical validation and references

`NUMERICAL_PROTOCOL.json` fixes domains, random seed, counts, quadrature orders,
grid refinements, and pass tolerances before the full grid is evaluated.
`validate_operators.py` uses independent SciPy normal and inverse-Gaussian
expressions, adaptive integration, an augmented-state semigroup composition,
and a finite-difference QVI solver. The first validation result is retained;
subsequent repairs require an explicitly versioned record. The additional
`NUMERICAL_DOMAIN_EXTENSION.json` fixes 64 near-boundary/actual-training-domain
checks after discovering the original quadrature problem; it is a numerical
regression check, not a fresh efficacy experiment. Every train/development
context is also checked before optimization; no confirmation context is used
for that preparation sweep. Finite tests do not
constitute a universal floating-point bound.

The first-passage, killed-kernel, renewal, and QVI derivations above are provided
explicitly so that a citation is not used as a substitute for a model proof.
Relevant primary context is He and Xiong, *Rollover Risk and Credit Risk* (2012),
https://www.princeton.edu/~wxiong/papers/rollover.pdf, and Crocce and Mordecki,
*Explicit solutions in one-sided optimal stopping problems for one-dimensional
diffusions* (2013), https://arxiv.org/abs/1302.0712. Qi's *Deep Q-Learning on
Holder Spaces*, https://arxiv.org/html/2606.16846v1, motivates studying operator
regularity. Its hypotheses are not automatically inherited by absorption,
reset, intervention, or refractory state augmentation.
