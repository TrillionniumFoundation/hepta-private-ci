# NDU-JAC: finite-horizon mathematics and evidence limits

Research draft, 2026-11-05. These are directly proved sufficient results for the
specified model. They are not a claim of algorithmic novelty, a general NDU
theorem, a convergence theorem for neural training, or a production certificate.

## 1. Freeze the objective before estimating it

Use decision times t = 0,...,H-1; elapsed physical time is a state coordinate.
The state contains task information, a protocol-bounded internal state p,
remaining budget, module/cache residency, elapsed time, and objective/model
version. A joint action alpha = (a,nu) may consume resources, reconfigure the
internal state, or stop. Legal actions are determined by the frozen protocol.

Let the joint outcome kernel K_t(dxi|s,alpha) generate the net immediate external
payoff r = R-C-kappa, duration Delta, and successor S'. Define beta =
exp(-rho Delta) for a nonterminal transition and beta = 0 for STOP. Costs,
durations and successor states may be correlated. Fix rho >= 0 and eta > 0.
Set V_H = 0 and

\[
T_t^\alpha U(s)=-\eta^{-1}\log E_K\exp[-\eta(r+\beta U(S'))],\quad
Q_t^\pi=T_t^\alpha V_{t+1}^\pi,\quad
V_t^\pi(s)=\sum_\alpha\pi_t(\alpha|s)Q_t^\pi(s,\alpha).
\]

The policy mixture is outside the certainty equivalent (CE). This choice is
part of the definition, not an implementation detail. The first implementation
should assume bounded r, a finite horizon, and a fixed legal action set at each
observed state. These conditions ensure finite, positive conditional moments.
The results extend to suitable integrable models, but that extension requires
its own domination and differentiation assumptions.

The rsEAC paper [1], equations 7-8, places stochastic action selection inside its
exponential/CE recursion. Its objective and stochastic-policy derivative are
therefore not interchangeable with the objective above. Risk-sensitive
gradients and exponential critics already have prior work; the derivations
below establish consistency for this chosen model, not originality.

### Counterexample: mixing actions inside the CE changes the objective

One decision, deterministic rewards 0 and 2, eta = 1, each action probability
1/2: the specified external mixture gives V = 1. The CE of the mixture is
-log((1+exp(-2))/2) = 0.5662191695. For logistic action probability at logit zero,
the respective derivatives are 0.5 and 0.3807970780.

Even without discounting, these two stochastic-policy objectives differ.
Random durations and discounting introduce further distinctions from a single
exponential utility of a whole trajectory.

### Integrability is a hard prerequisite

An audit of the predecessor R32 U3/M8 models identified Gaussian disturbances
combined with a positive quartic terminal cost. If Z has nonzero Gaussian
variance and terminal loss contains c Z^4, c > 0, then

\[
E\exp(\eta c Z^4)=\infty\qquad(\eta>0).
\]

Indeed, the exponent eta*c*z^4 minus the Gaussian quadratic exponent tends to
positive infinity in either tail, and its integral diverges. Lower-order
polynomial terms cannot repair this. Thus finite Monte Carlo output for such a
model does not establish a finite entropic objective. This observation is
conditional on the actual noncancelled positive quartic tail; it must not be
applied to an unrelated R32 objective that never exponentiates that loss.

The new bounded-outcome testbed is a separately defined experiment. Clipping an
unbounded predecessor's loss would change its objective and cannot silently
transfer old results to the new recursion.

## 2. Exact stochastic-policy gradient

Assume the outcome kernel, external payoff, duration, risk rule and legal
action protocol do not explicitly depend on actor parameters theta. Assume a
common policy support and differentiability, with valid interchange of
derivatives and expectations. Define

\[
X_t=r_t+\beta_t V_{t+1}^\pi(S_{t+1}),\quad
M_t(s,\alpha)=E[e^{-\eta X_t}|s,\alpha],\quad
m_t=e^{-\eta X_t}/M_t(s_t,\alpha_t).
\]

For a bounded perturbation f of the continuation value,

\[
D T_t^\alpha(U)[f]=E[m_t(U)\beta_t f(S')|s,\alpha].
\]

Differentiating the policy evaluation recursion gives

\[
\nabla V_t(s)=E_{\alpha\sim\pi_t}\left[
\nabla\log\pi_t(\alpha|s)Q_t^\pi(s,\alpha)
+E_K[m_t\beta_t\nabla V_{t+1}(S')]
\right].
\]

Unrolling this finite recursion and using an initial distribution independent
of theta proves

\[
\nabla J(\pi_\theta)=E_{\pi,K}\sum_{t=0}^{H-1}
w_t\nabla\log\pi_\theta(\alpha_t|s_t)
\{Q_t^\pi(s_t,\alpha_t)-b_t(s_t)\},\qquad
w_0=1,\quad w_{t+1}=w_t m_t\beta_t.
\]

The baseline is valid because w_t is measurable before the current action and
the policy score has conditional mean zero. The baseline must not depend on
the sampled action unless an appropriate correction is included.

Implementation consequences:

- A score-function actor surrogate must detach the evaluated Q and w. Taking
  their derivatives again adds terms absent from this surrogate identity.
  Differentiating an exact full dynamic-programming computation is a different,
  valid way to obtain the same derivative.
- The canonical current-step weight is w_t. Replacing it by w_(t+1), including
  the current random duration discount, generally changes the gradient.
- Multiplying a current score term by m_t alone does **not**, by itself, change
  its exact expectation: E[m_t|s,alpha] = 1. It usually changes variance. This is
  not a valid bias counterexample when the conditional normalizer is exact.
  With an estimated normalizer that identity need not hold.
- Omitting past risk weights or separating correlated duration and outcome
  factors is generally incorrect. Ordinary GAE is not justified by this proof.
- A deterministic continuous reconfiguration controller requires pathwise
  differentiation (and the relevant state/action Jacobians); a score identity
  cannot be applied to a Dirac action density without additional treatment.
- Explicit actor dependence of the evaluator, KL penalty, risk parameter,
  transition model or state initialization adds direct derivative terms.
- Arbitrary off-policy replay requires additional change-of-measure and
  coverage arguments. This proof is on-policy under the original kernel.

### Small numerical counterexample for the historical weight

At time zero the only action has two equally likely outcomes. At time one a
shared logistic parameter gives probability p of the good action. Outcome A
has r0 = 0, beta0 = 1, and terminal action rewards 1 or 0. Outcome B has r0 = -1,
beta0 = 1/2, and terminal rewards 4 or 0. At eta = 1 and p = 1/2,

\[
J=-\log\{(e^{-p}+e^{1-2p})/2\},\qquad
\partial_\theta J=0.4056148328004636.
\]

A centered finite difference at step 1e-6 gives 0.4056148328046572. Omitting the
historical risk tilt but retaining the duration discount gives 0.375; omitting
both gives 0.625. These differences concern the stated objective, not training
performance.

## 3. Proper moment fitting and what it does not make unbiased

For a frozen continuation target let Y = exp(-eta X), with 0 < E[Y] < infinity.
A predictor ell for log E[Y|s,alpha] can use the conditional proper loss

\[
\mathcal L(\ell,Y)=\ell+Y e^{-\ell}.
\]

Its expected derivative is 1-E[Y]e^(-ell), with unique minimizer ell = log E[Y]
and positive expected second derivative. Another proper loss is exp(ell)-Y*ell.
Neither is ordinary least squares on log Y, whose optimum is E[log Y].
The correct target remains frozen during this fitting argument.

A deterministic, frozen offset c(s,alpha) may stabilize Y by replacing it with
exp[-eta(X-c)] and restoring Q = c-ell/eta. A sample-dependent rescaling of the
loss can change its minimizer and requires a separate argument. Tail clipping
also changes the moment unless its bias is explicitly bounded.

For an approximate continuation U with sup error epsilon_V, the CE operator is
monotone and nonexpansive with respect to continuation values:

\[
|T^\alpha U-T^\alpha V|\le\bar\beta\epsilon_V,
\quad 0\le\beta\le\bar\beta\le1.
\]

This follows by bounding the payoff perturbation pathwise by
bar_beta*epsilon_V and applying monotonicity and cash translation. Random beta
must remain inside the expectation; only its certified upper bound is used.

If the moment estimate for the frozen target obeys relative error
|Mhat/M-1| <= r_M < 1, then

\[
|\widehat Q-Q|\le-\eta^{-1}\log(1-r_M).
\]

Thus a valid action-value error radius can include

\[
e_Q=\bar\beta\epsilon_V-\eta^{-1}\log(1-r_M).
\]

This is a deterministic implication of a valid moment-error event, not a claim
that a fitted neural predictor automatically has such an event. For eta = 0,
implement the risk-neutral limit separately; dividing a noisy log estimate by
an arbitrarily small eta is not a numerical stability guarantee.

A sample mean of Y is unbiased for a frozen M. Its transformed CE is generally
upward biased, since -log is convex. Dividing by a random estimated moment also
does not give an unbiased normalized risk weight. Independent reset samples
do not remove these nonlinearities automatically. Earlier risk-sensitive
function-approximation work already treats related regression bias [2].

## 4. Direct internal gradients without dividing by vanishing diffusion

Consider a reconfiguration action for which, under a fixed exogenous noise law,

\[
p'=F(s,a,\nu)+\varepsilon\xi,\qquad
r=-\kappa(\nu)+r_0,\qquad \partial_\nu\beta=0.
\]

Suppose other successor coordinates are unchanged by nu, F is differentiable,
V is differentiable in p on the relevant intervention set, and differentiation
under the expectation is justified. Then

\[
\nabla_\nu Q(s,a,\nu)=-\nabla\kappa(\nu)
+E_m[\beta J_F^\top\nabla_pV(S')].
\]

If nu also changes payoff, duration or other successor coordinates, their
derivatives must be included. A direct derivative of V alone is not the whole
action derivative in that more general case.

Uniform bounds ||J_F|| <= J, ||grad_p V|| <= G and beta <= bar_beta imply
||grad_nu Q|| <= ||grad kappa|| + bar_beta*J*G. There is no division by epsilon.
The same formula is valid at epsilon = 0 under the same smoothness and
domination assumptions. This removes a parameterization singularity, not a
statistical identification problem or a nonsmooth optimal-control boundary.

For comparison, Z_p = epsilon*grad_p V cannot identify grad_p V at epsilon = 0;
an error delta_Z divided by epsilon is amplified by 1/epsilon. Direct value
gradient fitting avoids that inversion. It still needs intervention or
derivative evidence: Vhat_delta(p)=V(p)+delta*sin(p/delta^2) has sup value error
at most delta, while its derivative error is 1/delta at p=0.

### When the internal gradient belongs in a safety error budget

Suppose a smooth action-value function q(p) is approximated at p and an
unmeasured intervention delta is predicted by a first-order expansion. If
||ghat-grad q(p)|| <= epsilon_G and grad q is L-Lipschitz on the intervention
segment, then

\[
|q(p+\delta)-[\widehat q(p)+\widehat g^\top\delta]|
\le e_{q(p)}+\epsilon_G\|\delta\|+\tfrac L2\|\delta\|^2.
\]

The explicitly known reconfiguration cost is included in both sides.
Accordingly, add epsilon_G*||delta|| + L*||delta||^2/2 to e_Q **only for this
surrogate route**. If independent evaluation directly measures the proposed
action under the frozen target, the proposal gradient's error is not needed
for the gate's correctness. It affects proposal quality and expenditure.
Discrete module changes and STOP boundaries require action-value comparisons,
not an assumed continuous derivative.

## 5. Paid paired moment comparisons

At the same resettable prefix and with a frozen continuation target, define

\[
D=e^{-\eta X_\alpha}-e^{-\eta X_0},\quad d=E[D].
\]

Correctly coupled pairs have the prescribed marginal outcome law for each
action. Pairing reduces variance; it does not create unavailable real-world
counterfactuals. If the environment cannot be reset, ordinary logs are not
automatically paired samples.

Condition on an independent training/pilot data set. Freeze a bounded cheap
predictor H and coefficient b. Let (D_i,H_i)
be iid paid pairs, and H'_j be an independent reset sample with exactly the
same conditional H marginal. Then

\[
\widehat d=\frac1m\sum_{i=1}^m(D_i-bH_i)
+\frac b n\sum_{j=1}^n H'_j
\]

is conditionally unbiased for d. If reset H has mean error zeta, the estimator
bias is b*zeta; a distribution-mismatch allowance is therefore necessary.
Unknown-control-mean estimators and their cost allocation already occur in
approximate control-variate work [3]. The construction alone is not new.

Let Z = D-bH have a certified range of width R_Z, and W=bH' a certified range
of width R_W. At a fixed sample pair (m,n), Hoeffding and a union bound give

\[
d\le\widehat d+
R_Z\sqrt{\log(4/\alpha)/(2m)}+
R_W\sqrt{\log(4/\alpha)/(2n)}=:d_U.
\]

The same radius gives a two-sided interval with probability at least 1-alpha,
by giving each of the two sample means a two-sided failure allowance alpha/2.
Use protocol support bounds, not observed
sample minima/maxima. When b = 0, the reset term and reset sample requirement
vanish. A missing required sample cannot be treated as zero uncertainty.

For M registered candidates, spend failure probability across **all possible
sample-count prefixes**, rather than across user-supplied look numbers:

\[
\alpha_{j,m,n}=\frac{\delta}{M\,m(m+1)n(n+1)}\quad(b\ne0),\qquad
\alpha_{j,m}=\frac{\delta}{M\,m(m+1)}\quad(b=0).
\]

The identity sum_(m>=1) 1/[m(m+1)] = 1 and a union bound make the intervals
simultaneously valid for every registered candidate and count pair. Therefore
sample allocation, stopping and repeated checking can adapt to observed
validation results, provided each sample set is a prefix of its correct iid
stream and the predictor/coefficient remain frozen. Repeatedly checking the
same prefix does not renew its error budget. Candidate/target refits require
fresh validation streams and the registered candidate allowance.

This bound is conservative but closes the fixed-sample optional-stopping gap.
For comparison, alpha_(j,k) = delta/[M*k*(k+1)] is sufficient at predeclared
sample-count looks k, but merely numbering adaptively chosen sample counts as
looks does not justify applying fixed-n Hoeffding bounds.

If both exponentials have upper bound M_max and d_U < 0, then

\[
Q_\alpha-Q_0=-\eta^{-1}\log(1+d/M_0)
\ge -d_U/(\eta M_{\max})>0.
\]

This linear lower bound is valid only in the certified negative-difference
case. For d_U >= 0 and a certified M_min > 0, a general lower bound is
-log(1+d_U/M_min)/eta; using -d_U/(eta*M_max) need not be safe.

For a fixed additive validation fee c, an equivalent exact positive-net-gain
condition is M_alpha-exp(-eta*c)*M_0 < 0. A conservative alternative is to
require the gain lower bound above to exceed every actual pilot, fit, main
pair, reset and failed-call expense in the same fixed payoff units.

### Cost-aware control coefficient and allocation

With sigma_DH = Cov(D,H) and sigma_H^2 = Var(H), the conditional variance is

\[
\operatorname{Var}(\widehat d)=
[\sigma_D^2-2b\sigma_{DH}+b^2\sigma_H^2]/m
+b^2\sigma_H^2/n.
\]

For fixed m,n, the minimizing coefficient is
b_star = sigma_DH/[sigma_H^2*(1+m/n)], when sigma_H^2 > 0.
Ignoring paid estimation of the control mean generally gives a different
coefficient. For frozen b and positive sampling costs c_Z,c_W, the continuous
allocation ratio at a fixed budget is

\[
m/n=\sqrt{\operatorname{Var}(Z)c_W/
                   [\operatorname{Var}(W)c_Z]}.
\]

This optimization is conditional on known variances; estimation and fit costs
must still be paid. No universal advantage follows. If H has zero useful
correlation or excessive fit/reset cost, b = 0 and ordinary paired sampling
can be preferable.

### Rejection still consumes its audit budget

Returning no-update after paying c preserves the deployed baseline policy; it
does not undo c. Relative to doing no audit, the net economic difference of a
rejection is -c. Report policy gain, net gain after validation, and budget spent
separately. A theorem promising zero economic loss on every rejected attempt
would be false without additional funding or value-of-information assumptions.

Subtracting a scalar fee is sufficient only if validation has no other
unmodeled effect on feasible actions, deadlines or dynamics. When its real
duration and resource consumption alter B or the clock, include the validation
operation as a state transition, or conservatively account for that opportunity
loss in the fee bound.

## 6. Whole-policy improvement: an explicit finite-horizon result

Freeze a baseline pi and candidate pi'. Define the baseline-continuation
advantage

\[
A_t(s)=\sum_\alpha[\pi'_t(\alpha|s)-\pi_t(\alpha|s)]
Q_t^\pi(s,\alpha).
\]

This compares the candidate's action distribution with the baseline's action
distribution, using the baseline continuation. Merely beating STOP at some
visited states does not imply this quantity is nonnegative at every changed
state.

### Proposition 1: pointwise baseline improvement

If A_t(s) >= 0 for every reachable time/state where pi' differs from pi, then
V_t^(pi') >= V_t^pi at every such starting state. If unvalidated states retain
the exact baseline action distribution, they have A_t = 0 and require no
unjustified extrapolation.

Proof: At H both values are zero. If V_(t+1)^(pi') >= V_(t+1)^pi, monotonicity
of each action CE gives
V_t^(pi') = T_t^(pi') V_(t+1)^(pi') >= T_t^(pi') V_(t+1)^pi
= V_t^pi + A_t >= V_t^pi. Backward induction completes the proof.

This is a sufficient finite-model policy-improvement argument. Baseline
fallback for insufficient support has established antecedents such as SPIBB
[4]; these propositions do not inherit SPIBB's different statistical theorem.

### Proposition 2: a quantitative risk-occupancy lower bound

The entropic CE is concave in its continuation value. Let K_t^(pi') be the
positive substochastic kernel

\[
K_t^{\pi'}(s,ds')=
\sum_\alpha\pi'_t(\alpha|s)
E[m_t(V_{t+1}^{\pi'})\beta_t\mathbf 1_{S'\in ds'}|s,\alpha].
\]

Its row mass is at most one. Put d_0 = mu_0 and
d_t = mu_0 K_0^(pi') ... K_(t-1)^(pi'). Then

\[
J(\pi')-J(\pi)\ge\sum_{t=0}^{H-1}\int A_t(s)\,d_t(ds).
\]

Proof: Write Delta_t = V_t^(pi')-V_t^pi. A concave differentiable f satisfies
f(U)-f(V) >= Df(U)[U-V]. Apply this to T_t^(pi') to obtain
Delta_t >= A_t + K_t^(pi') Delta_(t+1). Iterating the positive kernels to the
terminal zero difference proves the displayed bound.

For an exact identity, replace the kernel above with the derivative averaged
over continuation values V^pi+u*(V^(pi')-V^pi), 0 <= u <= 1. The fundamental
theorem of calculus then gives equality. That bridge occupancy depends on
both policies and must not be replaced by an ordinary behavior occupancy.

### Proposition 3: an explicit value/gradient/moment/coverage/cost certificate

Suppose, on a simultaneous confidence event, |Qhat_t-Q_t^pi| <= e_Q,t for all
state-action pairs used to change the policy. Define

\[
\widehat A_t=\sum_\alpha(\pi'_t-\pi_t)\widehat Q_t,\qquad
e_{A,t}=\sum_\alpha|\pi'_t-\pi_t|e_{Q,t},\qquad
\ell_t=\widehat A_t-e_{A,t}.
\]

Then ell_t <= A_t. The e_Q radii may include continuation-value error and
moment-estimation error from Section 3, and an internal-gradient/Taylor error
from Section 4 only where that surrogate is actually used.

Complete each subprobability d_t from Proposition 2 to a probability
bar_d_t by adding the missing mass at an absorbing cemetery state, where
A_t = ell_t = 0. Let q_t be the validation-state distribution on the same
augmented space. Assume a **certified** bound
TV(bar_d_t,q_t) <= tau_t, and |A_t| <= M_t. Suppose independent validation gives
L_t <= E_(q_t)[ell_t] simultaneously. Then

\[
J(\pi')-J(\pi)-c_{\rm audit}
\ge\sum_{t=0}^{H-1}(L_t-2M_t\tau_t)-c_{\rm audit}.
\]

Proof: Proposition 2 lower-bounds performance by the sum of A expectations
under d_t. Adding a zero-valued cemetery state does not alter them. The TV
inequality bounds the change of expectation of an [-M_t,M_t]-valued function
by 2*M_t*tau_t. Under q_t, A_t >= ell_t and its expected lower predictor is at
least L_t. Sum these inequalities and subtract the audit fee.

On the simultaneous event, accepting only a strictly positive right-hand side
certifies positive net improvement under these assumptions. Union-bound all
moment, value, intervention, state-coverage and validation events, including
candidate selection and repeated looks. For pure pointwise certification,
Proposition 1 avoids a fitted occupancy claim; a positive initial advantage
plus nonnegative later advantages can also pay an additive fee.

This proposition makes its difficult assumptions visible. A bound on ordinary
on-policy state coverage is not automatically a bound on the risk-tilted,
discounted occupancy. tau_t cannot be set to zero because evaluation and actor
seeds differ. In a small known finite model it can be computed; for a learned
large model, certification of these quantities remains a separate blocker.

No constant in these propositions requires division by internal diffusion
epsilon. Uniformity as epsilon tends to zero still requires uniformly valid
value/gradient/coverage bounds and regularity. Risk concentration and sample
complexity can remain very unfavorable: prior risk-sensitive RL already
exhibits exponential dependence on risk and horizon in its setting [5].

## 7. Required experiments and open claims

The first meaningful closure is the finite, bounded, resettable research model:

1. Compare exact dynamic-programming derivatives, the weighted score identity,
   and finite differences, including random duration/cost correlation and STOP.
2. Test CE-inside versus CE-outside action mixtures, wrong historical weights,
   and the harmless-in-expectation current-m-only variant separately.
3. Compare proper moment fitting against regression on log outcomes; retain
   finite-sample CE bias and estimated-normalizer bias diagnostics.
4. At epsilon = 0 and a decreasing positive sequence, compare direct internal
   gradients against known interventions and the singular Z/epsilon inversion.
5. Exercise paid acceptance, no-update due to weak evidence, excessive cost,
   distribution mismatch, missing support, failed calls, and invalid tails.
6. Verify whole-policy monotonicity and Proposition 2 on exhaustively evaluated
   small models; include a counterexample where a local STOP improvement does
   not improve the whole altered policy.
7. Compare paired ordinary sampling, linear, polynomial and neural controls at
   identical total paid budgets, including fit/pilot/reset cost and failures.

Open after those experiments: a practical nonvacuous large-model coverage
certificate; valid tails for unbounded tasks; directly measured neural-gradient
generalization; end-to-end validation that consumes real clock/budget state;
sample-efficient exploration; long-horizon risk-weight stability; a full-policy
statistical certificate when only resets/local continuations are available;
and consistent cost/performance advantage against strong ordinary methods.
None is closed by correctly deriving a finite-model gradient identity.

## Primary references inspected

[1] Granados and Pacheco, *Risk-Sensitive Exponential Actor Critic*,
arXiv:2602.07202v1, 2026-02-06. In particular, equations 7-10 distinguish its
action mixture from the present model.
https://arxiv.org/html/2602.07202v1

[2] Fei, Yang and Wang, *Risk-Sensitive Reinforcement Learning with Function
Approximation: A Debiasing Approach*, ICML 2021. It treats bias-aware
approximation of an entropic objective; its guarantees are not asserted for
this different joint-control implementation.
https://proceedings.mlr.press/v139/fei21a.html

[3] Gorodetsky, Geraci, Eldred and Jakeman, *A Generalized Approximate Control
Variate Framework for Multifidelity Uncertainty Quantification*, JCP 408,
109257, 2020. Unknown control means and paid sample allocation are prior art.
https://arxiv.org/abs/1811.04988
https://www.sandia.gov/research/publications/details/a-generalized-approximate-control-variate-framework-for-multifidelity-uncer-2020-05-01/

[4] Laroche, Trichelair and Tachet des Combes, *Safe Policy Improvement with
Baseline Bootstrapping*, ICML 2019. It motivates careful baseline fallback for
insufficient information, but does not supply the present entropic certificate.
https://proceedings.mlr.press/v97/laroche19a.html

[5] Fei, Yang, Chen, Wang and Xie, *Risk-Sensitive Reinforcement Learning:
Near-Optimal Risk-Sample Tradeoff in Regret*, NeurIPS 2020. Its risk/horizon
tradeoff cautions against claiming a universally cheap entropic audit.
https://proceedings.neurips.cc/paper_files/paper/2020/hash/fdc42b6b0ee16a2f866281508ef56730-Abstract.html
