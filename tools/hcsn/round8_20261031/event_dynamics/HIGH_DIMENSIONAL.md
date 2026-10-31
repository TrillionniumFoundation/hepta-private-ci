# High-dimensional approximation: statements that transfer, and their limits

This note supplements `THEORY.md` without changing the frozen event kernels.
The inequalities below are derived for the specified kernels and norms. They
are not a global convergence theorem for a coupled Hepta network. No numerical
coupling bound for such a network is claimed by the scalar audit.

## 1. Compare the complete state and event law

A comparison state must include every variable needed by the next transition:
active state or its retained distribution, shared context, remaining budget,
deadline, refractory phase/age, reset information and action eligibility.
Killed kernels are made probability kernels by adjoining a cemetery state.
Record event type/count and associated costs in the same augmented transition;
a voltage-only comparison can miss errors in paid actions or resets.

Use the convention

\[
\|\mu-\nu\|_{TV}=\sup_A|\mu(A)-\nu(A)|=\tfrac12\|\mu-\nu\|_1.
\]

For bounded `f`, expectation error is at most
`osc(f)*TV <= 2*||f||_infinity*TV`. All factors of two below use this convention.
For substochastic kernels, the cemetery augmentation also compares lost mass;
renormalizing both to unit surviving mass would hide that error.

## 2. Product approximations require conditional independence

Suppose a single transition factors, conditional on the *complete shared
state and action*, as `P=product_i P_i`. If each scalar/block approximation
satisfies `TV(P_i,Q_i)<=epsilon_i`, maximal coupling gives

\[
\|\mathop{\otimes}_iP_i-\mathop{\otimes}_iQ_i\|_{TV}
\le 1-\prod_i(1-\epsilon_i)\le\sum_i\epsilon_i.
\]

Proof: independently couple each pair of factors; all coordinates agree with
probability at least the displayed product. This is a one-transition bound,
not a dimension-free result. It can become uninformative when errors accumulate
over many cells.

If the true joint kernel is coupled, define
`delta_dependence=TV(P,product_i P_i)` using its actual marginals. Then

\[
\|P-\mathop{\otimes}_iQ_i\|_{TV}
\le \delta_{\rm dependence}+\sum_i\epsilon_i.
\]

Marginal first-hit accuracy does not bound `delta_dependence`. Two perfectly
correlated Bernoulli(1/2) events and two independent Bernoulli(1/2) events have
identical marginals but joint TV distance 1/2; their union-event probabilities
are 1/2 and 3/4. Perfectly shared continuous noise can make a joint law singular
relative to the independent product, giving TV distance one.

Conditional independence given a latent mode also does not imply independence
after that mode is marginalized:

\[
\sum_z\pi_z\prod_iP_i(\cdot\mid z)
\ne \prod_i\sum_z\pi_zP_i(\cdot\mid z).
\]

A shared posterior must remain shared. Sampling it independently per cell or
retaining only independent cell marginals changes the model. Block kernels,
shared latent mixtures or explicit coupling may be needed; their cost belongs
in the measured approximation.

## 3. When a coupling bound can actually be proved

For finite CTMC generators `Q` and `Q0` on the **same augmented state space**,
row-stochastic semigroups contract the induced infinity norm. Duhamel's identity
therefore implies

\[
\sup_x\|e^{tQ}(x,\cdot)-e^{tQ_0}(x,\cdot)\|_{TV}
\le\min\{1,\tfrac12t\|Q-Q_0\|_\infty\}.
\]

Here `||A||_infinity=max_i sum_j |A_ij|`, including diagonal changes. The bound
extends to an integral over time for bounded time-dependent finite generators.
An exact Kronecker-sum independent generator is a valid `Q0`. This identity
does not make the finite generator itself an accurate diffusion approximation;
the separate discretization and boundary errors must still be included.

For diffusions with the **same nonsingular diffusion matrix**, Girsanov and
Pinsker can instead bound path-law TV by

\[
TV(\mathbb P,\mathbb P_0)
\le\sqrt{\tfrac14 E_{\mathbb P}\int_0^T
\|\Sigma^{-1}(b-b_0)\|^2dt},
\]

provided the change of measure is valid (including the requisite integrability)
and initial laws match. Applying the same measurable event/reset map cannot
increase TV. Changing the diffusion covariance is not covered: continuous
path laws can be singular because their quadratic variations differ. Nor can
one replace a diffusion generator by a bounded finite matrix inside the first
inequality without a separate approximation argument.

These are usable sufficient conditions. If no dependence/coupling bound is
available, the correct report is “joint approximation error unknown,” even if
every scalar kernel has passed its numerical checks.

## 4. Finite-horizon and discounted value error

For a fixed policy with identical observations/action masks in both models,
uniform one-step TV error `epsilon` gives state-law error at step `t` at most
`t*epsilon` (capped at one). With `H` steps, `|r|<=R`, per-step reward error
at most `eta`, and matching initial states,

\[
|V_H^P-V_H^Q|\le H\eta+R\epsilon H(H-1).
\]

An additional bounded terminal payoff contributes its oscillation times
`min(1,H*epsilon)`. Random stopping can be represented by an absorbing done
state with zero later reward, as long as a common finite bound `H` exists.

For discount `0<beta<1`, bounded rewards and the same admissible action set,
the fixed-policy and optimal Bellman contraction argument gives

\[
\|V_P-V_Q\|_\infty
\le \frac{\eta}{1-\beta}
+\frac{2\beta R\epsilon}{(1-\beta)^2}.
\]

The performance loss from applying the approximate model's optimal policy to
the true model is at most twice a uniform fixed-policy value bound. This is
an upper bound, often loose; a measured positive net gain still needs an actual
quality/cost comparison. Unbounded rewards or unbounded stopping horizons
require additional weighted-norm or tail-control assumptions. The formula is
not imported into those settings by analogy.

For regenerative cycle kernels, the mandatory-recovery discount bound in
`THEORY.md` supplies the corresponding contraction factor. An instantaneous
action does not itself supply a factor below one.

## 5. Budgets, action margins and thin boundary layers

Even small value errors can switch an action near a tie. If every action-value
error is at most `delta`, a unique true best action is preserved whenever the
gap to the second best is greater than `2*delta`. Report the occupancy of the
region with smaller gaps, including its action costs. A global “smooth policy”
conclusion does not follow from smooth branch values.

Budget legality is another discontinuity. If a legal action requires `B>=c`,
budget/cost errors bounded by `epsilon_B,epsilon_c` can change that decision
only in `|B-c|<=epsilon_B+epsilon_c`; but probability mass can concentrate
exactly there. Budget counters, eligibility and realized charges should remain
exact discrete state where feasible. A relaxed continuous approximation needs
an explicit thin-layer occupancy/error account.

For a pre-event continuous driving path, define
`Z=max_{0<=s<=T}(X_s-b_s)`. Under a path coupling with
`P(||X-Xhat||_sup>epsilon_X)<=zeta` and
`||b-bhat||_sup<=epsilon_b`, the event mismatch probability is at most

\[
\zeta+P\{|Z|\le\epsilon_X+\epsilon_b\}.
\]

If the density of this *unabsorbed* maximum is bounded by `M` near zero, the
second term is at most `2*M*(epsilon_X+epsilon_b)`. Such a uniform density
bound must be proved on the admitted parameter domain. It generally cannot be
assumed as noise vanishes, the horizon collapses, a start/reset approaches the
boundary, or paths graze it. Using a stopped path's maximum would create an
atom at zero and invalidate the intended density argument. For reset networks,
apply a valid bound per pre-event segment and account for the number of segments.

## 6. Reset maps and state compression

Deterministic resets expose a subtle metric issue: for unequal reset points
`r` and `rhat`, `TV(delta_r,delta_rhat)=1`, however close the points are.
Wasserstein error is instead their physical distance. Converting that distance
to TV needs a genuine smoothing transition or a declared stochastic reset law;
the constant can diverge as smoothing time/noise tends to zero. For two Gaussian
resets of equal scalar SD `s>0`, Pinsker gives
`TV<=min(1,|r-rhat|/(2*s))`. Adding jitter solely to obtain this bound changes
the model and must be registered as such.

Grid interpolation, clipping at a boundary, entry to recovery, depleted budgets
and changing action sets are not globally smooth reset mechanisms. Pathwise
event-time gradients require appropriate transversality and event-jump terms;
distributional derivatives require their own domination/regularity arguments.
The scalar CDF derivative tests cover neither a generic coupled reset map nor
all event creation/disappearance points.

A compressed state `z=phi(s)` is sufficient only if states in the same fiber
have the same legal actions, rewards and pushforward transition law. Approximate
sufficiency can be expressed by explicit reward and TV discrepancies on each
fiber and then inserted in the bounds above. A memory cell's small representation
dimension does not prove these discrepancies small. The state-task fixture's
two-statistic sufficiency is proved from its particular Gaussian likelihood;
it is not evidence that arbitrary histories admit that compression.

## 7. Hölder-space results do not supply the missing assumptions

Before applying a whole-space Hölder Bellman theorem, one must verify its
actual state space and metric, reward/transition regularity, growth or weighted
norm conditions, invariance of the function class, contraction constants and
admissible action structure for the model being executed. Positive scalar
noise and a closed-form CDF do not verify those conditions for a coupled hybrid
network with reset, censoring and budget guards.

On a fixed continuation stratum, useful local Hölder/Lipschitz estimates may
hold. A maximum of finitely many uniformly Hölder branches preserves the same
exponent, but a greedy policy can still jump at ties. Discrete phase/budget
coordinates also require an explicitly chosen hybrid metric rather than an
unstated Euclidean embedding. No theorem from the paper cited in the user
request is claimed as a guarantee for this implementation.

For a future high-dimensional experiment, report separately: scalar numerical
error; block/product dependence error; finite-horizon propagation; budget and
boundary-layer occupancy; reset regularity; actual joint computation cost.
An unknown item remains an unresolved approximation scope, not a passed gate.
