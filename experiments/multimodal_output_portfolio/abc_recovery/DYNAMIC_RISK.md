# Conditional risk and a finite causal reference

This module implements an offline, known-law reference. It establishes neither
a correct neural conditional value model nor a global optimum over generator
parameters. Its finite-process fixtures are mathematical checks, not evidence
of improvement on real media. The risk profile is constant `gamma >= 0`.

## Information and terminal uncertainty

Let `h` denote the entire public history available before an action, including
observed generation results, usable conditions, remaining budget and relevant
realized costs. A node key must not encode a private target, a future random
draw, or an offline oracle answer. Actions are restricted to that node's feasible
set. `Outcome(p, h_next, cost)` describes a **joint** conditional law of the next
history and realized cost. Model correctness and history sufficiency are caller
assumptions; this code checks finite probabilities, actions and acyclicity, not
those scientific assumptions. Merging histories is valid only when their future
conditional laws and feasible sets agree.

If the true task target is not measurable in the final public history, the
terminal value is a conditional law, `TerminalLaw(utilities, probabilities)`:

\[
 Z_T(h)=E[\exp(-\gamma U)\mid h],
 \qquad V_T(h)=-\gamma^{-1}\log Z_T(h).
\]

It is not `exp(-gamma * E[U|h])`, nor a separate policy node for each private
target realization. The conditional law is an offline model object; the returned
policy contains only public-history keys and action names. A point-mass leaf is
appropriate only when the remaining utility is determined by that public history.
If prior costs reveal information about a hidden target, that information must
be retained when constructing the terminal law. Hidden cost/utility dependence
cannot be repaired by multiplying unrelated marginal expectations.

## Objective and recursion

For bounded utility and finite costs, define, under a fixed causal policy,

\[
 C_t(X)=-\gamma^{-1}\log E[e^{-\gamma X}\mid\mathcal F_t],
 \qquad C_t^{(0)}(X)=E[X\mid\mathcal F_t].
\]

For terminal utility minus remaining costs, backward induction gives

\[
 Z_t(h)=\min_{a\in A(h)}E[e^{\gamma c_t} Z_{t+1}(H_{t+1})\mid h,a],
 \qquad V_t(h)=-\gamma^{-1}\log Z_t(h).
\]

`solve_finite_tree` computes the equivalent value-space recursion
`CE([V(next_history) - realized_cost], joint_probabilities, gamma)`. Random cost
stays inside the expectation and remains paired with its next history. At zero
risk aversion the recursion is ordinary expected net utility. A supplied policy
evaluates only its chosen feasible action at each reached public history.

Numerically, small centered exponents use `expm1`/`log1p`, which preserves the
continuous limit at zero. Larger exponents use shifted weighted logsumexp;
the implementation never directly evaluates a large positive exponential.

## Four finite-model statements and proofs

### Time consistency

For a fixed probability law and constant gamma, exponentiating the inner CE
gives `exp(-gamma*C_(t+1)(X)) = E[exp(-gamma*X)|F_(t+1)]`. Apply conditional
expectation given `F_t`, use the tower property and apply `-log(.)/gamma` to obtain
`C_t(C_(t+1)(X)) = C_t(X)`. Gamma zero is the ordinary tower property. Changing
gamma with time does not inherit this identity from the constant-profile proof.

### Finite causal optimum and deterministic actions

At a terminal history the conditional exponentiated utility is exactly its
terminal law. Suppose the continuation optimum is established at the next depth.
For any action, conditional expectation of `exp(gamma*c)*Z_next` evaluates its
net-utility moment. Choosing the minimum yields the optimal continuation at the
current history; induction proves the result at the root. All choices use the
current history, so they are nonanticipating. Randomizing over actions yields a
convex combination of their conditional moments, which cannot be smaller than
the smallest component. Thus a deterministic optimum exists when there are no
additional constraints requiring randomization. At gamma zero use linearity of
expected utility. This proof is for the supplied finite conditional model only.

### Information value

If one information structure contains another and feasible actions/costs are
unchanged, every old causal policy is feasible with the richer information: it
can ignore the additional observations. The supremum value therefore cannot
decrease. An observation acquisition cost must be included in the payoff; this
set-inclusion argument does not guarantee that its net benefit is positive.

### A conditional policy-loss bound

Conditional CE is monotone and cash-translation invariant. If `||X-Y||_inf <= d`,
then `Y-d <= X <= Y+d` implies `|CE(X)-CE(Y)| <= d`. Let `Q*_t` be the true optimal
action value and assume `sup_(h,a)|Qhat_t-Q*_t| <= delta_t` over every relevant
feasible history/action. For a greedy choice `ahat` and an optimal choice `a*`,

\[
 Q^*_t(h,a^*) \le \widehat Q_t(h,a^*)+\delta_t
 \le \widehat Q_t(h,\hat a)+\delta_t
 \le Q^*_t(h,\hat a)+2\delta_t.
\]

Propagate the continuation error through the 1-Lipschitz CE and induct backward,
with zero terminal approximation error, to get `V*_0-V^policy_0 <= 2*sum(delta_t)`.
`conditional_policy_loss_bound` performs only this arithmetic. Its arguments must
be independently justified uniform bounds. Average calibration, training loss,
agreement on replayed samples, or a few seeds do not establish them. No such
uniform neural-critic certificate is asserted here.

## Conditional and joint-task training are different objectives

Write `L=-U` and `M_x=E[exp(gamma*L)|x]`. Training on

\[
 E_x E[\operatorname{expm1}(\gamma L)/\gamma\mid x]
\]

is monotone-equivalent, for positive gamma, to minimizing the **joint task/noise**
entropic loss `(1/gamma)*log E_x[M_x]`. It is not the task-average conditional
entropic loss `E_x[(1/gamma)*log M_x]`. Shared parameters generally create different
task tradeoffs. For equally likely tasks with deterministic utility, policy A
gives `(0,1)` and B gives `(0.4,0.4)`. Mean conditional CE prefers A (`0.5 > 0.4`),
while at gamma two joint CE prefers B (`0.28311 < 0.4`). Either objective can be
declared; the evaluated primary endpoint must match that declaration. Per-source
or per-view noise draws remain separate when reporting conditional CE.

For a moment critic with target `Y=exp(gamma*c)*Z_next`, squared-error regression
of `Z` targets `E[Y|h,a]`. Squared-error regression of `log(Y)` targets
`E[log(Y)|h,a]`, not `log E[Y|h,a]`. With equiprobable targets `1,9`, the former
moment is `5` while exponentiating the log-target fit gives `3`. Against a sure
moment `4`, this shortcut reverses the risk decision. The tests calculate both
empirical regressions explicitly.

## Verification and primary sources

Run `python3 -m unittest experiments.multimodal_output_portfolio.abc_recovery.risk_tests`.
Tests enumerate complete small-process trajectories and all deterministic causal
policies, and compare to high-precision Decimal exponential expectations. They
also check hidden-target leaves, random costs, information revelation, the
zero-risk limit, mixture policies, and the two counterexamples above. These are
not neural-performance tests.

- [Ruszczynski, Risk-Averse Dynamic Programming for Markov Decision Processes](https://optimization-online.org/wp-content/uploads/2009/12/2497.pdf): original work on conditional Markov risk mappings and risk-averse dynamic programming; the short entropic proofs above state the narrower assumptions used here.
- [Noorani, Mavridis and Baras, Risk-Sensitive Reinforcement Learning with Exponential Criteria](https://arxiv.org/html/2212.09010v4): trajectory-gradient and multiplicative-Bellman approaches for exponential criteria; it does not certify this experiment's learned critic or source generalization.
