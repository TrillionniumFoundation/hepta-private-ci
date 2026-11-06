# Non-oracle recursive confidence and propagation of safe improvements

This is a finite known-support reference. It supplies the model-coverage premise
left external by `ndu_jac/policy_gate.py`, and a sufficient propagation bound that
can recognize a delayed improvement even when the root policy row is unchanged.
It is not a new information-cost lower bound, a new general RL algorithm, or a
solution to unknown-support/stateful latent-model learning.

## 1. Explicit information contract

There are finitely many fully observed states arranged in an acyclic graph. The
legal actions and each full outcome support are known. Outcome `i` of row `(s,a)`
has known immediate external net reward `r_i`, nonnegative duration `d_i`, and
successor `s_i` or a terminal marker. The only unknown numbers are row probability
vectors `p_sa`. Each calibration row supplies a fixed, prospectively chosen
number of iid draws with full outcome identity. Missing empirical atoms remain
in the known support. This is the same reset-bank access as the inherited JAC
experiment, including its known state construction; it is not an inferred
permission to access an unknown physical state or latent label.

The frozen objective is

\[
 Q_P^\pi(s,a)=-\eta^{-1}\log\sum_i p_{sai}
 \exp\{-\eta[r_i+e^{-\rho d_i}V_P^\pi(s_i)]\},\qquad
 V_P^\pi(s)=\sum_a\pi(a\mid s)Q_P^\pi(s,a),
\]

with terminal continuation zero, `eta>0`, `rho>=0`, and action randomization
outside each conditional certainty equivalent. Terminal rewards are immediate
in this inherited contract; only continuation is discounted. The analysis does
not reinterpret these simulated durations as actual model-service latency.

## 2. A model confidence event that survives data-dependent policy selection

For each non-singleton row outcome, let `k` of `n` draws have that identity. Its
marginal count is binomial even though coordinates of the multinomial count
vector are dependent. Let `M` be the number of non-singleton outcome coordinates
per bank and `J` the number of reported banks. Allocate two-sided marginal error
`a=alpha/(JM)`. Use Clopper-Pearson endpoints

\[
 \ell=\begin{cases}0,&k=0,\\
 F^{-1}_{\mathrm{Beta}(k,n-k+1)}(a/2),&k>0,
 \end{cases}\quad
 u=\begin{cases}1,&k=n,\\
 F^{-1}_{\mathrm{Beta}(k+1,n-k)}(1-a/2),&k<n.
 \end{cases}
\]

A singleton support has probability exactly one. Intersect each coordinate box
with its row simplex to obtain a set `C_sa` of probability vectors. By binomial
coverage and a union bound, with probability at least `1-alpha`, every true row
of every reported bank lies in its set. Row independence is unnecessary for this
union bound; within-row iid sampling at its fixed `n` is required. This is not
an anytime confidence sequence or an optional-sampling theorem.

On this event, the following bounds hold for **every policy** in the declared
finite graph. Thus baseline and candidate policies may be fitted on the same
counts without an invalid independence assertion. This is uniform coverage
induced by a model event, not uncorrected evaluation of a selected point estimate.

For a fixed policy `pi`, recursively compute

\[
 LQ(s,a)=\inf_{p\in C_{sa}}\operatorname{CE}_p
       (r_i+e^{-\rho d_i}LV(s_i)),\quad
 UQ(s,a)=\sup_{p\in C_{sa}}\operatorname{CE}_p
       (r_i+e^{-\rho d_i}UV(s_i)),
\]

and `LV(s)=sum_a pi(a|s)LQ(s,a)`, likewise for `UV`. Monotonicity of CE and
backward induction give `LQ<=Q_P^pi<=UQ` and `LV<=V_P^pi<=UV`. There is no
unknown neural approximation term because this implementation enumerates the
finite model exactly in ordinary arithmetic.

CE minimization maximizes its exponential moment, and CE maximization minimizes
that moment. For fixed branch returns the moment is linear in `p`. To optimize
it over a box-simplex, start at all lower endpoints and allocate the remaining
mass in order of increasing or decreasing moment weight, respecting upper
endpoints. An exchange argument proves optimality: any mass allocated to a
lower-priority coordinate while a better coordinate has spare capacity can be
moved to improve the linear objective. This is classical robust dynamic
programming with a particularly simple uncertainty set.

## 3. Local gating

Fix a baseline `pi0` and a proposed policy. For each state, the intervals from
Section 2 cover the complete `Q_P^pi0(s,a)`. If a row changes to `pi1`, its true
baseline advantage is

\[
 A(s)=\sum_a[\pi_1(a\mid s)-\pi_0(a\mid s)]Q_P^{\pi_0}(s,a).
\]

A lower bound `a(s)` uses the lower Q endpoint where the probability difference
is nonnegative and the upper endpoint where it is negative. Retain a proposed
row only if this lower bound is nonnegative; otherwise retain the baseline row
and set `a(s)=0`. An unchanged row has exactly zero local advantage. The current
numerical implementation asks for a positive margin above `1e-12` before changing
a row; this is a conservative floating-point guard, not a new statistical
parameter tuned on the bank results.

Backward induction already gives `V_P^pi1>=V_P^pi0` everywhere. A root-local
certificate such as the inherited gate can nevertheless miss a beneficial
change: if only a downstream row improves, `a(root)=0` even though the root value
strictly increases. The next section propagates a sufficient gain bound.

## 4. Propagation through unchanged roots

For each baseline branch write

\[
 x_i=r_i+e^{-\rho d_i}V_P^{\pi_0}(s_i),\quad
 x_i^-=r_i+e^{-\rho d_i}LV(s_i),\quad
 x_i^+=r_i+e^{-\rho d_i}UV(s_i).
\]

Define an upper bound on the baseline exponential moment and a lower bound on
each risk-tilted probability:

\[
 Z^+_{sa}=\max_{p\in C_{sa}}\sum_i p_i e^{-\eta x_i^-},\qquad
 w^-_{sai}=\frac{\ell_{sai}e^{-\eta x_i^+}}{Z^+_{sa}}.
\]

Since `p_i>=ell_i` and `x_i<=x_i^+`, the numerator is at least its stated lower
bound; since `x_i>=x_i^-`, the denominator is at most `Z^+`. Thus the true tilted
probability `w_i=p_i exp(-eta*x_i)/sum_j p_j exp(-eta*x_j)` satisfies
`w_i>=w_i^-`. In particular, their lower bounds sum to at most one for nonempty
sets containing the true model.

Starting from terminal successors with gain zero, set

\[
 D(s,a)=-\eta^{-1}\log\left[
 1-\sum_{i:s_i\ne\varnothing}w^-_{sai}
       (1-e^{-\eta e^{-\rho d_i}G(s_i)})\right],
\qquad
 G(s)=a(s)+\sum_a\pi_1(a\mid s)D(s,a).
\]

**Proposition.** On the simultaneous model event, `0<=G(s)<=V_P^pi1(s)-V_P^pi0(s)`
for every state, including when the root row is unchanged.

**Proof.** Assume the assertion holds at all successors. CE monotonicity gives

\[
 Q_P^{\pi_1}(s,a)-Q_P^{\pi_0}(s,a)
 \ge-\eta^{-1}\log\sum_iw_i
       e^{-\eta e^{-\rho d_i}G(s_i)}.
\]

All successor bounds are nonnegative, so each
`1-exp(-eta*discount*G)` is nonnegative. Using `w_i>=w_i^-`, the expression inside
the last logarithm is at most the bracket defining `D(s,a)`. The function
`-log` is decreasing, hence the action gain is at least `D(s,a)`. Finally

\[
 V_P^{\pi_1}(s)-V_P^{\pi_0}(s)
 =A(s)+\sum_a\pi_1(a\mid s)
   [Q_P^{\pi_1}(s,a)-Q_P^{\pi_0}(s,a)]\ge G(s).
\]

Terminal rows provide the base. Finiteness and acyclicity complete the induction.
The bracket is positive for finite branch returns and finite gains. ∎

A minimal deterministic example has a forced one-second transition at the root
and two terminal actions, with payoffs 1 and 0, at the next state. Changing a
50:50 terminal policy to the good action leaves the root unchanged yet improves
its value by `exp(-rho)/2`. The propagation bound is exact here; a gate requiring
strict root-local advantage rejects. The executable test retains this example.

## 5. Paid acceptance and limitations

Accept the gated policy only when `G(root)>verification_fee`. Rejection returns
the baseline but retains the spent fee; its gain relative to never auditing is
then `-verification_fee`. This is a bound for the declared fee, not permission to
ignore acquisition, fitting, engineering, provider or opportunity costs. A true
lifecycle gate must subtract all incremental costs under its declared accounting.

The confidence set may be statistically valid and numerically unhelpful. This
implementation deliberately retains that possibility. It uses classic finite
confidence and robust-control ingredients, and does not establish an advantage
over the strongest same-data policy or an information-cost optimum. Exact
binomial quantiles and real-arithmetic proofs are evaluated with ordinary SciPy
and floating-point arithmetic here; this is not a formally rounded interval
implementation. Observed coverage in 20 banks cannot prove population coverage.

## Primary predecessors

- C. J. Clopper and E. S. Pearson, “The Use of Confidence or Fiducial Limits
  Illustrated in the Case of the Binomial,” *Biometrika* 26(4), 404–413 (1934).
  [DOI](https://doi.org/10.1093/biomet/26.4.404).
- A. Nilim and L. El Ghaoui, “Robust Control of Markov Decision Processes with
  Uncertain Transition Matrices,” *Operations Research* 53(5), 780–798 (2005).
  [DOI](https://doi.org/10.1287/opre.1050.0216),
  [author-hosted full text](https://people.eecs.berkeley.edu/~elghaoui/Pubs/RobMDP_OR2005.pdf).

These references establish direct classical ingredients. They do not certify
novelty of the present propagation formula; no such novelty claim is made.
