# R12 local propositions and limits

This note concerns the proposed finite continuous-time Markov chain (CTMC), not a
closed-form regenerative extension of the He--Xiong financial model. The full
He--Xiong boundary may parameterize the active grid; this does not identify the
grid approximation, reflected upper boundary, reset, or recovery with that paper.
The results below are conditional mathematical statements, not claims of learned
task improvement or production acceptance. `audit.py` constructs independent
finite examples; it does not generate an empirical confirmation set.

## 1. State, orientation, and generator

Let active states be `(i,c)`, with positive log-distance `x_i = (i+1)h`,
`i=0,...,n-1`, and binary content `c`. Include recovery states `(R1,c)` and
`(R2,c)`. A distribution is a **row** vector, evolving by `p'(t)=p(t)Q`.
For frozen drift `mu`, diffusion `sigma`, and grid width `h>0`, one monotone
upwind generator uses

\[
q_+=\frac{\sigma^2}{2h^2}+\frac{\max(\mu,0)}h,\qquad
q_-=\frac{\sigma^2}{2h^2}+\frac{\max(-\mu,0)}h.
\]

Downward motion from the first active site enters `R1`; upper outward motion is
omitted (a specified reflecting/holding truncation). Recovery transitions are
`R1 -> R2` and `R2 -> (j_reset,c')`, at rate `kappa>0`, with nonnegative
reinjection probabilities summing to one. Diagonals are minus the sum of actual
off-diagonal rates. A different positive finite generator obeys the same results.

**Proposition 1 (positivity and conservation).** If every rate is finite,
`Q_ij >= 0` for `i != j`, and `Q 1 = 0`, then for every `t>=0`,
`P(t)=exp(tQ)` is entrywise nonnegative and `P(t)1=1`.

*Proof.* For `nu >= max_i(-Q_ii)`, `M=I+Q/nu` is stochastic and

\[
P(t)=e^{-\nu t}\sum_{k=0}^{\infty}\frac{(\nu t)^k}{k!}M^k.
\]

This is a convex combination of stochastic matrices. The `Q=0` case gives `I`.
Thus `pP(t)` remains a probability distribution and expectations are monotone.
The proof does not establish that a floating-point implementation preserves these
properties exactly; clipping or renormalizing output changes its numerical map.

**Proposition 2 (Markov extension and semigroup).** For a fixed generator and the
complete state above, `P(t+s)=P(t)P(s)`. Two exponential recovery stages have a
specified Erlang-2 duration of mean `2/kappa`. They are not a deterministic delay.
Combining the two stages into a single inactive flag is generally not Markov:
the instantaneous rate to active states is zero in `R1` but `kappa` in `R2`.
For validity under every initial distribution, a coarse partition must be
strongly lumpable: rates into each coarse block must agree within every block.

Time-varying inputs, controls, or learned boundaries give a chronological
evolution family, not one homogeneous semigroup. Products of interval-specific
stochastic matrices preserve mass, but do not establish exactness for a
continuously varying diffusion. Bayesian observations introduce a nonlinear step.

## 2. First events, occupancy, and approximation scope

Let `K` be the active-state principal submatrix, retaining its original negative
diagonal. Its missing mass records the first exit to recovery. For an initial
active law `p_A`,

\[
\Pr(\tau\le t)=1-p_Ae^{tK}{\bf1}.
\]

This is a first-event probability. It is **not** `1 - active_mass(p exp(tQ))`,
because a path may already have recovered and re-entered. Expected event count is
another quantity: with first-stage entry intensities `lambda_event`, it is
`integral_0^t p exp(sQ) lambda_event ds`. It can exceed one.

Matrix exponentiation is exact at the level of the mathematical finite CTMC,
subject to numerical error in computation. It does not remove spatial truncation,
upwinding, finite-grid, time-freezing, or model error relative to a continuous
absorbing diffusion. Uniformization and SciPy comparisons check the matrix map,
not convergence to the financial model. A refinement study must separately vary
grid spacing and upper extent; changing both arbitrarily can hide boundary bias.

On a parameter region where every rate is differentiable, the exponential has
the Fréchet derivative

\[
D\exp(tQ)[E]=\int_0^t e^{(t-s)Q}E e^{sQ}\,ds.
\]

Since stochastic matrices have induced infinity norm one, its norm is at most
`t ||E||_infty`. This is local trainability of the finite propagator, not a bound
on the upstream parameter Jacobian, nor on a normalized Bayesian update. Upwind
`max(mu,0)` is not differentiable at zero; parameter clipping, floors, or root
branches need separate treatment. Smooth matrix exponentiation cannot repair an
undefined or poorly conditioned financial boundary calculation upstream.

## 3. Bellman stability for a fixed model

Let the reward and transition model be fixed, let actions range over a common
nonempty finite set, and let every `P_a` be stochastic. For `0<=gamma<1`,

\[
(TV)(s)=\max_a\{r(s,a)+\gamma P_aV(s)\}
\quad\Longrightarrow\quad
\|TV-TW\|_\infty\le\gamma\|V-W\|_\infty.
\]

*Proof.* The absolute difference of two maxima is bounded by the largest
absolute difference of their arguments. A stochastic average is nonexpansive
in the uniform norm. Hence a discounted fixed point is unique. At `gamma=1`
the map is only nonexpansive; a finite-horizon backward recursion remains valid,
but a strict contraction or infinite-horizon uniqueness does not follow.

For `TQ = r + gamma P(max_a Q)`, the identical bound holds. It does not prove
contraction of SGD, changing parameters, arbitrary boundary solvers, or the full
content network. A financial discount rate is not automatically the task discount.

## 4. Model error, critic error, and action regret

Use `TV(P,P_hat)=1/2 sum_j |P_j-P_hat_j|`. Consider two finite-horizon MDPs
with the **same state and action spaces**, `H` decisions, `|r_t|<=R`, and
`|g|<=G` in both models. Assume uniform bounds for every state, action, and time:

\[
|r_t-\hat r_t|\le\epsilon_r,\quad
\operatorname{TV}(P_t,\hat P_t)\le\epsilon_P,\quad
|g-\hat g|\le\epsilon_g.
\]

**Proposition 3 (finite-horizon value bound).** Both optimal values and the
values of any fixed policy differ by at most

\[
D_H=\epsilon_g+H\epsilon_r+
\bigl[R H(H-1)+2GH\bigr]\epsilon_P.
\]

*Proof.* For `h` decisions remaining, continuation values have magnitude at most
`(h-1)R+G`. The inequality `|(P-P_hat)f|<=2 ||f||_infty TV` and the
nonexpansiveness of maximization give
`d_h <= d_(h-1) + epsilon_r + 2((h-1)R+G)epsilon_P`.
Sum from `d_0<=epsilon_g`. The same argument omits the maximum for a fixed
policy. With nonnegative rewards and terminal payoffs, their range can tighten
the displayed factor two; the signed-reward version is used here.

If a critic `Q_tilde_t` is uniformly within `epsilon_fit,t` of the approximate
model's **optimal** `Q_hat*_t`, and its greedy action is computed exactly, then:

* One decision followed by true optimal continuation has regret at most
  `2(D_h+epsilon_fit,t)` at that state.
* Repeatedly deploying its greedy policy `pi` has total true-model regret at most
  `2D_H + 2 sum_t epsilon_fit,t`.

For the second bound, insert the approximate model's optimal and deployed values
between the two true-model values, apply Proposition 3 twice, and telescope
approximate-model greedy losses. An action-selection tolerance `epsilon_arg,t`
adds `sum_t epsilon_arg,t`. This is an upper bound, not a prediction of regret.

These hypotheses cannot be closed by on-policy mean calibration, training loss,
a confidence interval on a small test set, or a sample maximum without coverage
control. Sampling, representation error, optimization, distribution shift, and
inexact maximization remain separate. `audit.py` includes a two-state example
with zero observed critic error and strictly positive unseen-state regret.

In a partially observed task the comparison must concern the full observation
history model or a sufficient Markov belief with specified observation kernels.
An error bound on latent transitions alone is not automatically a uniform bound
on the induced belief transition: deterministic belief maps at different points
can even have total variation one. Use a justified history-model coupling or a
metric-sensitive belief bound rather than silently transferring the theorem.

## 5. Observation normalization

For likelihoods `0<=ell_i<=L`, the posterior is
`B_ell(p)_i=p_i ell_i / Z_p`, where `Z_p=sum_i p_i ell_i`.
It is defined only when `Z_p>0`. If `Z_p,Z_q>=eta>0`, then

\[
\operatorname{TV}(B_\ell(p),B_\ell(q))
\le\min\{1,(L/\eta)\operatorname{TV}(p,q)\}.
\]

*Proof.* For `0<=f<=1`, put `c=B_ell(q)f`. The posterior expectation difference
is `(p-q)[ell(f-c)]/Z_p`. The bracketed function has range at most `L`.
Taking the supremum over `f` gives the bound. Thus conditioning can amplify
small prior errors; it is not uniformly nonexpansive as evidence becomes rare.
For a fixed prior and likelihood error `||ell-ell_hat||_infty<=epsilon_ell`,
the normalization identity also gives `TV(B_ell(p),B_ell_hat(p))<=epsilon_ell/eta`
when the posteriors exist and the reference evidence is at least `eta`.

Returning the prior at zero evidence, flooring a denominator, or clipping a
likelihood is an explicit model/fallback choice. It must be identical in teacher,
training, and execution and cannot be described as exact Bayesian conditioning.

## 6. Relation to Hölder theory and unresolved conditions

Qian Qi, *Deep Q-Learning on Hölder Spaces*, arXiv:2606.16846v1,
[official COLT/PMLR record](https://proceedings.mlr.press/v336/qi26a.html), studies
diffusion Bellman targets, not general sampled DQN optimization. Its Assumptions
1 and 3 require uniform ellipticity and regular coefficients; Remark 2 uses a
whole-space Cauchy problem. Theorem 15 additionally assumes monotone reconstruction,
decoupled capacity, and a controlled hypothesis class (Assumptions 23--25).

Our finite-state semigroup is differentiable in time, but that is not a theorem
about continuum `C^(2,alpha)` spatial regularity. Recovery phases and binary
content are discrete; deterministic content coordinates in a continuous model
would make its full diffusion matrix degenerate. None of these conditions is
repaired merely by choosing a smooth activation. First-hit and reset boundaries
need their own compatibility and nonlocal boundary analysis. Local regularity
away from the boundary at positive time does not provide a uniform bound as
time or noise tends to zero, nor does it imply a low separation rank.

## 7. Experimental interpretation

The independent examples establish possible information loss, not a task advantage:
equal means can have different first-hit risks; equal separate content and distance
marginals can conceal different joint correlations; an inactive flag can conceal
different recovery stages. The same likelihoods and causal observations must be
available to every comparator. Supplying an exact posterior only to an analytic
cell would confound representation and information. Model training and cost must
also include propagation, observation normalization, recovery, and content updates.
No empirical gate is passed merely because a conditional proposition is proved.
