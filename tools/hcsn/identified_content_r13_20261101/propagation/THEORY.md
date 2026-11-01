# R13 propagation: proved properties, conditional certificates, and remaining gaps

## 1. Executable model and continuous comparison process

The executable cell is the finite continuous-time Markov chain built in
`finite_volume.py` and exposed by `api.py`. Its state is `(content, phase)`, with
two content classes and, within each class, `N` active location cells followed
by recovery stages `R1` and `R2`. The full state has `2(N+2)` coordinates. Row
probabilities propagate as `p exp(tQ)`.

The continuous comparison process has active coordinate

\[
 dX_t=\mu\,dt+\sigma\,dW_t,\qquad X_t>0.
\]

At first arrival at zero, it enters R1, then R2, with independent exponential
holding times of rate \(\kappa=2/\rho\). Completion of R2 samples a new location
from a Gaussian of physical standard deviation `.1`, conditioned to `[0,.8]`.
It changes content through

\[
 C=\eta I+(1-\eta)\mathbf1\mathbf1^\top/2.
\]

Thus `retention=.75` means same-content probability `.875`, not `.75`.
Recovery has Erlang shape two and mean \(\rho=.35\). These recovery/content
rules are declared extensions; they are not properties proved by the original
He–Xiong financial model. The full financial calculation supplies the boundary,
reset location and task reward/cost functions. It does not give a closed-form
regenerative transition kernel for this extended process.

The finite model uses a reflecting upper endpoint. The continuous reference
used below has **no upper endpoint**. Matrix exponentiation solves the finite
model; it does not remove its spatial approximation. The frozen R13 mesh has
56 active cells, 116 total states and upper endpoint `13.064376419678013`.

## 2. Positive fitted flux and the lower half cell

Let cell widths be \(w_i\), centers \(c_i\), distances
\(d_i=c_{i+1}-c_i\), and \(D=\sigma^2/2\). Define the positive analytic
Bernoulli function

\[
 B(z)=\frac{z}{e^z-1},\quad B(0)=1.
\]

Solving the constant-flux equation \(J=\mu u-Du_x\) between two centers gives

\[
 J_{i+1/2}=\frac D{d_i}
 \left[B(-\mu d_i/D)u_i-B(\mu d_i/D)u_{i+1}\right].
\]

Writing cell mass as \(p_i=w_i u_i\) gives the row-generator rates

\[
 q_{i,i+1}=\frac D{w_i d_i}B(-\mu d_i/D),\qquad
 q_{i+1,i}=\frac D{w_{i+1}d_i}B(\mu d_i/D).
\]

The absorbing boundary value is at **zero**, a distance \(c_0\) from the first
center, rather than one full center spacing away. Its outgoing rate is

\[
 q_{0,R1}=\frac D{w_0 c_0}B(\mu c_0/D).
\]

On a uniform mesh of width \(h\), this becomes
\(2D h^{-2}B(\mu h/(2D))\), and equals \(2D/h^2\) at zero drift. The R12
uniform-grid generator used a full-spacing down rate at this boundary. R13
repairs that geometric inconsistency.

These are exponentially fitted, Scharfetter–Gummel-type fluxes. The displayed
formula and half-cell specialization follow from the elementary flux ODE above;
no external convergence theorem is assumed for the graded mesh. The original
method is associated with [Scharfetter and Gummel (1969)](https://doi.org/10.1109/T-ED.1969.16566).

All off-diagonal rates are nonnegative, and assigning the negative outgoing sum
to the diagonal gives \(Q\mathbf1=0\). Redirecting the killing flux to R1,
adding R1→R2 at rate \(\kappa\), and adding R2→active at rate
\(\kappa C_{bb'}\rho_i\) preserve these properties. The bin masses \(\rho_i\)
are exact normal-CDF differences for a fixed physical reset support; increasing
the computational upper endpoint does not redefine the reset law.

**Semigroup and state sufficiency.** With \(\nu\ge\max_i(-q_{ii})\),
\(A=I+Q/\nu\) is stochastic and

\[
 e^{tQ}=e^{-\nu t}\sum_{k=0}^\infty\frac{(\nu t)^k}{k!}A^k.
\]

Consequently the finite propagation is positive and mass preserving, and
\(P_{s+t}=P_sP_t\). It includes arbitrarily many cycles and uses the remaining
time after each transition. Collapsing R1/R2 to one recovery flag loses the
Markov property in general: the remaining duration from R1 is an Erlang-two
law, while from R2 it is exponential. Dropping content–phase dependence likewise
changes future observations and values.

**Smooth drift and gradients.** The target function \(B\) is analytic across
zero, eliminating the `relu(mu)` split. The implementation evaluates a Taylor
series near zero and `expm1` elsewhere; this is an accurate floating-point
evaluation of an analytic target, not a claim that the piecewise floating-point
program is an exact symbolic function. For a fixed grid and a smooth parameter
map,

\[
 \partial_\theta e^{tQ}
 =\int_0^t e^{sQ}(\partial_\theta Q)e^{(t-s)Q}\,ds,
 \qquad
 \|\partial_\theta P_t\|_\infty\le t\|\partial_\theta Q\|_\infty.
\]

Reset normalization must stay positive, and the financial boundary map must be
differentiable in the parameter region. The inherited financial bridge supports
first-order differentiation; it does not supply a certified higher-order AD
path. Mesh shape and support are frozen before optimization.

## 3. An upper-domain bound including every renewal excursion

Assume all initial active positions and all reset positions are at most
\(a\), \(\sigma\le\bar\sigma\), \(\mu\le\bar\mu\), and
\(\rho\ge\rho_{\min}>0\). Let total elapsed time be at most \(T\), and let
\(L>a+\bar\mu_+T\). For any single active excursion, reaching \(L\) before
its remaining time expires requires

\[
 \sup_{s\le T}W_s\ge
 \frac{L-a-\bar\mu_+T}{\bar\sigma}.
\]

The reflection principle therefore bounds that excursion's probability by

\[
 p_L=2\Phi\!\left(-\frac{L-a-\bar\mu_+T}{\bar\sigma\sqrt T}\right).
\]

The [MIT Brownian-motion notes, Theorem 1](https://www.ocw.mit.edu/courses/15-070j-advanced-stochastic-processes-fall-2013/aca1518a09539a09ddd37428ab0d0268_MIT15_070JF13_Lec7.pdf)
give the reflection-principle identity used in this step. Recovery completions
are no more numerous than recovery phase jumps, whose predictable intensity is
bounded by \(2/\rho_{\min}\). Hence their expected count by \(T\) is at most
\(2T/\rho_{\min}\). Apply the strong Markov property at each new excursion
and a union bound over the expected number of starts to obtain

\[
 \Pr(\text{ever reach }L\text{ by }T)
 \le \epsilon_L
 :=\min\{1,(1+2T/\rho_{\min})p_L\}. \tag{1}
\]

The argument counts all cycles, including a potentially incomplete final
cycle. It also covers initial recovery states, using the conservative `1+`
term. Coupling two continuous models until they first reach \(L\) bounds their
path-law TV distance by \(\epsilon_L\), regardless of how the upper boundary
is handled afterward. This bound controls an upper-domain modification of the
continuous process, **not the difference between the FV chain and a diffusion**.

Solving (1) for a requested tail budget \(\epsilon\) gives the implemented rule

\[
 L=a+\bar\mu_+T+\bar\sigma\sqrt T\,
 \Phi^{-1}\!\left(1-\frac{\epsilon}{2(1+2T/\rho_{\min})}\right).
\]

R13 uses \(T=29.4\), \(a=.8\), \(\bar\sigma=.4\),
\(\bar\mu=.04875\), \(\rho_{\min}=.35\), giving
\(L=13.064376419678013\) and \(\epsilon_L=10^{-4}\). This is conservative:
the largest positive drift and largest volatility occur at different values of
the two-parameter physical map. The time budget must cover the entire history
and subsequent decisions, not just one propagation step.

The result is unconditional. Conditioning on rare observations can amplify the
error, as discussed below. No posterior error of `1e-4` is asserted.

## 4. Independent continuous first-passage and renewal enclosures

For an active start \(x>0\), the unbounded first-hit CDF is

\[
 F_x(t)=\Phi\!\left(\frac{-x-\mu t}{\sigma\sqrt t}\right)
 +e^{-2\mu x/\sigma^2}
 \Phi\!\left(\frac{-x+\mu t}{\sigma\sqrt t}\right). \tag{2}
\]

This follows by the reflected killed heat kernel with drift. Its missing mass
is the absorption probability. The code evaluates the second term with
`log_ndtr` to avoid avoidable overflow/underflow. For a continuous initial or
reset law, partition `[0,.8]` into bins with exact normal-CDF masses \(m_j\).
Since \(F_x(t)\) decreases in \(x\),

\[
 \sum_j m_jF_{x_{j+1}}(t)\le \int F_x(t)\rho(dx)
 \le\sum_jm_jF_{x_j}(t). \tag{3}
\]

This bounds the continuous mixture directly; it is not a comparison of two
FV meshes. Gaussian quadrature at orders 160 and 320 is a separate numerical
point estimate, checked against (3).

### Positive discrete clocks

Let \(F^-\le F\le F^+\) be a duration-CDF enclosure and use clock step \(d\).
Define discrete faster and slower duration CDFs at integer clock times by

\[
 F_{\rm fast}(kd)=F^+((k+1)d),\qquad
 F_{\rm slow}(kd)=F^-(kd).
\]

Independent quantile coupling gives
\(T_{\rm fast}\le T_{\rm true}\le T_{\rm slow}\) for each active excursion
and for each exponential recovery stage. All partial sums of coupled durations
preserve this ordering. Apply the construction separately to the initial active
law and to every reset excursion. Probability mass beyond the time horizon can
remain at infinity in the finite arrays.

If \(f\) is the active-duration PMF and \(e\) a recovery-stage PMF, the complete
cycle PMF is \(h=f*e*e\). The faster clock may have a nonzero atom \(h_0\) at
zero. The positive renewal equation

\[
 u=b+\eta h*u
\]

is solved recursively by

\[
 u_k=\frac{b_k+\eta\sum_{j=1}^kh_ju_{k-j}}{1-\eta h_0}. \tag{4}
\]

The denominator is essential. Dropping the zero-time atom would omit multiple
cycles within a single time bin. A different initial excursion contributes
\(b_{\rm init}+\eta h_{\rm init}*u_{\rm reset}\). These convolutions retain
the remaining time after every reset and sum every possible reset count.

### Recovering phase and content–phase probabilities

Let \(H,L,M\) count entries into R1, exits from R1, and completed resets by
time \(t\). Pathwise,

\[
 1_{R1}=H-L,\quad1_{R2}=L-M,\quad1_A=1-H+M.
\]

Expected event counts come from (4) with weight one and base CDFs
\(F, F*E, F*E*E\), respectively. Faster clocks increase each cumulative count;
subtract the appropriate lower/upper count bounds to enclose occupancies.

For content retention, define weighted cumulative counts
\(H_\eta=\sum_{j=1}^{H}\eta^{j-1}\), and analogously \(L_\eta,M_\eta\).
These still increase with each event count. Equation (4) with weight \(\eta\)
computes their expectations. If \(N=M\) is the number of resets,

\[
 \eta^N1_{R1}=H_\eta-L_\eta,\quad
 \eta^N1_{R2}=L_\eta-M_\eta,\quad
 \eta^N1_A=1-H_\eta+\eta M_\eta.
\]

For initially independent content with probability \(p_0\) of class zero,

\[
 \Pr(B_t=0,\text{phase}=j)
 =\tfrac12\Pr(\text{phase}=j)
 +(p_0-\tfrac12)\mathbb E[\eta^N1_j]. \tag{5}
\]

Thus the reference bounds joint content–phase probabilities, preserving the
correlations that a factorized state would lose. The CDF of
\(h_{\rm init}*h_{\rm reset}\) also bounds the probability of at least two
completed resets. These are full-renewal formulas, not a one-reset shortcut.

**Numerical scope.** Equations (3)–(5) are mathematical enclosure statements
given valid CDF enclosures. `renewal_bounds.py` uses float64 CDFs and explicit
`2e-13` padding, plus ordinary floating-point convolution. This is not a formal
directed-rounding implementation. High-precision spot checks are evidence of
arithmetic accuracy, not a proof of a uniform machine error bound. The returned
intervals can be conservative because separate event-count bounds are
subtracted. They do not enclose the active location density or arbitrary
location-dependent equity/debt reward functions.

## 5. Numerical budgets and action stopping rules

### Finite exponential

For the unnormalized uniformization series cut after term \(K\), every row's
missing mass is
\(\tau_K=\Pr\{\operatorname{Poisson}(\nu t)>K\}\). Its row-L1 error is exactly
\(\tau_K\) in exact arithmetic. Normalizing the truncated stochastic rows gives
TV error at most \(\tau_K\). `uniformization_terms` selects the number of terms
from a requested Poisson-tail budget. It does not certify accumulated
floating-point error or all implementation choices in a different native code.

### Observable-specific continuous bound

If (3) gives \(F\in[F^-,F^+]\) and the finite result is \(F_h\), then

\[
 |F_h-F|\le\max(|F_h-F^-|,|F_h-F^+|). \tag{6}
\]

For the 54 declared first-hit averages, `observable_budget.py` evaluates (6)
and selects the first global nested mesh meeting a specified absolute-error
budget. With budget `.002`, it selects 224 cells; the 56-cell training mesh
does not meet this observable budget. This selection is conditional on reference
and matrix arithmetic accuracy and applies only to the declared observables.

For an action payoff affine in this first-hit event, its coefficient times (6)
is an action-value error bound. This supports a genuine, narrow link between
the analytic reference, an error budget and an action gap. It does not supply
a full transition-kernel bound for the financial task.

### Generic action and policy bounds

If \(\max_a|\widehat Q(a)-Q(a)|\le\epsilon_Q\) and selection is within
\(\tau\) of the maximum, one-step action regret is at most
\(2\epsilon_Q+\tau\). A computed best-action gap greater than this quantity
certifies that action when the error budget is complete.

R13 applies the tolerance at **every** Bellman node and returns the selected
action's actual Q value. For a horizon \(H\), its value loss relative to exact
finite-model maximization is at most \(H\tau\), proved by backward induction.
The nested validation therefore uses the conservative gap allowance
\(2\epsilon_Q+H\tau\). A local comparison of two computed Q vectors concerns
those vectors and their declared continuations; it is not by itself a uniform
bound on the entire policy at all subsequently reachable beliefs.

On a common state space with the same action/observation contract, suppose every
action kernel differs in TV by at most \(\epsilon_P\), immediate signed
rewards are bounded by \(R\) and differ by at most \(\epsilon_r\), and the
terminal reward is bounded by \(G\) with error \(\epsilon_g\). Using
\(\mathrm{TV}=\tfrac12\|p-q\|_1\), standard backward induction gives

\[
 D_H\le\epsilon_g+H\epsilon_r+
 [RH(H-1)+2GH]\epsilon_P. \tag{7}
\]

This bounds values for every fixed policy and for optimal policies. Transferring
an \(H\tau\)-optimal approximate-model policy gives regret at most
\(2D_H+H\tau\). Separate uniform value-fitting or action-evaluation errors
can be added with the appropriate per-stage sum. Average errors measured only
on a training or on-policy sample do not establish the uniform hypotheses.

For upper-domain coupling alone, a total-return bound \(|J|\le M\) gives a
per-policy value discrepancy at most \(2M\epsilon_L\), and an optimal-policy
transfer bound of \(4M\epsilon_L\). Spatial, inference and fitting errors
remain separate.

**Common-space warning.** A discrete law concentrated at mesh centers and a
continuous density are generally mutually singular, with TV distance one.
A meaningful FV TV claim requires an explicit common projection/lifting and
uniform control of the resulting information loss. Projecting locations to
cells does not automatically make the projected continuous process Markov.
No such full-kernel spatial TV theorem is established here. The runtime
`grid_certificate` deliberately returns `fv_spatial_error_bound: null`, and
`action_certificate` refuses a complete certificate when a required component
is missing. Differences between adjacent meshes are diagnostic evidence,
not substitutes for this theorem.

## 6. Observation normalization, Bellman structure and Hölder scope

For a nonnegative likelihood \(\ell\le L\), the Bayesian map
\(B_\ell(p)=p\ell/(p\ell\mathbf1)\) is defined only for positive evidence.
If both evidences are at least \(\zeta>0\),

\[
 \mathrm{TV}(B_\ell(p),B_\ell(q))
 \le (L/\zeta)\,\mathrm{TV}(p,q). \tag{8}
\]

Repeated rare observations can magnify a small prior propagation error. Zero
evidence branches have zero weight in an exact Bellman observation sum and
should be skipped; they are not defined posterior states. Adding an arbitrary
normalization floor changes the model.

With fixed bounded rewards, a common finite action set and complete stochastic
kernels, a discounted Bellman operator is a sup-norm contraction of modulus
\(\gamma<1\). Its proof uses positivity, total probability one and
nonexpansiveness of the maximum. In the current undiscounted finite-horizon
controller the corresponding recursion is nonexpansive, not a stationary
strict contraction. Explicitly weighting every observation branch is essential.

[Qi, *Deep Q-Learning on Hölder Spaces*](https://proceedings.mlr.press/v336/qi26a.html)
studies regularity of Bellman targets in a uniformly elliptic diffusion setting;
the official abstract explicitly separates that result from convergence of
practical sampled DQN training. The present finite-state contraction proof
does not need that regularity theorem. Within the open active domain,
\(\sigma\ge.15\) gives ellipticity, but absorption, nonlocal reset,
discrete content and atomic recovery phases require their own boundary/hybrid
analysis. Degenerate content coordinates cannot be declared uniformly elliptic
by adjoining them to the active diffusion. Hard action choices are
discontinuous at ties even when each action value is smooth. No global Hölder
regularity theorem or SGD/DQN convergence guarantee is inherited here.

## 7. Interpretation of refinement evidence

The initial scan reduces the fine-region step while keeping far-field growth
at `1.2`. This is useful for boundary diagnosis, but does not force every far
cell to shrink to zero. `validate_nested.py` additionally subdivides **every**
frozen cell by factors two and four, producing genuine nested meshes of
56/112/224 active cells with the same upper endpoint and reset support.

The files distinguish four claims:

1. Positivity, mass conservation, finite semigroup, and the analytic
   upper-domain probability bound are proved under the stated assumptions.
2. Clock/position reference enclosures and observable-specific error budgets
   have exact mathematical proofs conditional on accurate arithmetic.
3. Reported FV errors, mesh differences, Q differences and gradient agreement
   are independently reproducible numerical evidence on declared cases.
4. A uniform FV-to-continuum financial action/policy error bound, formal
   directed-rounding arithmetic, and natural real-world temporal content
   generalization remain unproved.
