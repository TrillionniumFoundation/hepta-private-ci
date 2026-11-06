# Decision-relevant paid identification: a finite-class cost theorem

Status: 2026-11-06. This is an internally proved, explicitly restricted reference.
The allocation lower bound and sequential-testing ingredients have direct
predecessors; no claim of a new RL algorithm or priority is made. The previous
144-cell experiment, its failed primary endpoint and its source freeze are
unchanged. The numerical companion is deterministic verification, not a new
confirmation experiment, actual provider bill or external proof review.

## 1. The unknown is an environment; the answer is a decision

Let a finite, fully specified catalog be `Theta`, with `m >= 2` members. Its true
member `theta` is unknown. A fixed external decision problem assigns each member
a unique correct answer `a(theta)` in a finite set. For example, the answer can
be whether to deploy a paid sensing policy or choose prior STOP. It is not the
hidden label of the future deployment task. Ties must be excluded or assigned a
separate, explicitly justified correctness contract.

Define only the decision-changing alternatives

\[
 \mathcal A_\theta=\{\nu:a(\nu)\ne a(\theta)\}.                 \tag{1}
\]

Requiring discrimination against every other model is a different, generally
harder goal. Conversely, arbitrarily deleting a model in (1) invalidates the
decision guarantee. All assertions are conditional on membership in this known
catalog. They do not learn an unrestricted unknown transition/observation table.

There are `k` legal calibration experiments. Each is a **complete regenerative
procedure** with known finite outcome law `p(theta,e,o)`. Its outcome records
all available responses, failure/censoring information, and elapsed duration.
Any label, state preparation and reset required for that procedure is included
in its fee and duration. Successive procedures have fresh conditional randomness
given `theta` and the selected experiment. This access must actually be available;
packaging an uncontrolled stateful trajectory as IID data does not provide it.

Assume common finite positive support for each experiment. Known nonnegative
functions `f(e,o)` and `t(e,o)` give the complete monetary charge and elapsed
duration. For a prespecified exchange rate `lambda >= 0`, set

\[
 c(e,o)=f(e,o)+\lambda t(e,o),\qquad
 0<c_{\min}\le c(e,o)\le c_{\max}<\infty.                     \tag{2}
\]

Durations are bounded and positive. Resource-specific bounds follow by choosing
another prespecified scalarization; minimizing money does not simultaneously
minimize time. These are actual-time claims only when `t` is the metered latency
of the declared procedure, including charged preparation, dispatch and planning.
Otherwise it is a model-time result. Request caps or query counts cannot replace
elapsed time. A censored experiment is a distinct law and exposes no uncompleted
future state. Initial free observations cannot depend on `theta` unless their
information is included in the transcript.

Merge catalog members having identical laws for every experiment. Such a merge
is legal only if they share the answer; identical observations with different
answers make uniform `delta < 1/2` correctness impossible. After merging,
every distinct pair is distinguishable by at least one experiment. The catalog,
prices, answer map and confidence level are fixed before collecting data.

## 2. A decision-class information-cost lower bound

Write `d(theta,nu,e)=KL(p(theta,e)||p(nu,e))` and
`c(theta,e)=sum_o p(theta,e,o)c(e,o)`. For a procedure uniformly `delta`-correct,
where `0<delta<1/2`, let `N_e` count completed calibration experiments before its
almost surely finite stopping time. A request whose paid failure is an outcome
is counted; unknown final bills are not zero. For finite expected cost,

\[
 \sum_e E_\theta N_e\,d(\theta,\nu,e)
 \ge b_\delta:=\operatorname{kl}(1-\delta,\delta),
 \qquad \nu\in\mathcal A_\theta.                              \tag{3}
\]

**Proof.** The common adaptive experiment-selection and terminal-output kernels
cancel from the likelihood ratio. The stopped log ratio is the sum of observed
log likelihood increments. Their boundedness and finite expected number of
experiments justify expectation by optional stopping or truncation. Its mean is
the left side of (3). Apply binary data processing to the event that the output
equals `a(theta)`: its probabilities under `theta,nu` are at least `1-delta`
and at most `delta`. The cost identity likewise follows by conditional
expectation before each experiment is selected. Thus define

\[
 C^*(\theta)=\min_{x\ge0}\left\{\sum_e c(\theta,e)x_e:
       \sum_e d(\theta,\nu,e)x_e\ge1\quad
       (\nu\in\mathcal A_\theta)\right\}.                    \tag{4}
\]

Then every such rule satisfies

\[
                  E_\theta C\ge b_\delta C^*(\theta).          \tag{5}
\]

If all answers coincide, no acquisition is needed and the value is zero. In
the nontrivial case finite distinguishability and positive costs give a finite,
positive optimum. Put

\[
 r_\theta(w)=\min_{\nu\in\mathcal A_\theta}\sum_e w_e d(\theta,\nu,e),
 \quad g_\theta(w)=\sum_e w_e c(\theta,e),\quad w\in\Delta_k.
\]

Rescaling `x` by its sum shows
`C*(theta)=min_w g_theta(w)/r_theta(w)` over positive rates. This is a
cost-normalized testing allocation, not a new information principle.

## 3. An explicit matching rule for this fixed finite catalog

The following deliberately simple construction establishes attainability of
(4); it is not proposed as a practical advantage over Chernoff/Track-and-Stop.
Let `L=log((m-1)/delta)` and retain every accumulated catalog log likelihood.
If all catalog members have the same answer, return it without acquisition;
the steps below apply to the nontrivial case with at least two answers.

1. **Pilot:** run each experiment `ceil(L^(2/3))` times. Choose a maximum
   likelihood member `hat theta`, breaking ties by a fixed order.
2. **Main:** choose independent experiments with a fixed optimizing allocation
   `w*(hat theta)` from (4), for at most `ceil(L^2)` further experiments.
3. **Fallback:** if still unresolved, choose experiments uniformly forever.
4. After the pilot and each subsequent complete experiment, stop when some
   member `psi` has `log likelihood(psi)-log likelihood(nu) >= L` for every
   `nu` with a different answer. Return `a(psi)`. A fixed tie order suffices.

**Theorem.** For every fixed catalog satisfying Section 1, the rule is uniformly
`delta`-correct, has finite expected resource cost, and for each true member

\[
 \lim_{\delta\downarrow0}\frac{E_\theta C}{\log(1/\delta)}
      = C^*(\theta).                                         \tag{6}
\]

**Correctness.** If the rule outputs a wrong answer represented by `psi`, the
true member `theta` is among its alternatives. The adaptive likelihood ratio
`likelihood(psi)/likelihood(theta)` is a nonnegative mean-one martingale under
`theta`. Ville's inequality bounds its ever crossing `exp(L)` by `exp(-L)`.
A union bound over at most `m-1` wrong members gives error at most `delta`.
The uniform fallback has strictly positive drift against every opposite-answer
member, so the true member eventually satisfies the stopping criterion.

**Expected cost.** Let `B` be the largest absolute one-experiment log likelihood
increment over all catalog pairs, and `n0=k ceil(L^(2/3))`. The probability of a
wrong pilot estimate is at most `(m-1) exp(-kappa ceil(L^(2/3)))`, where

\[
 \kappa=\min_{\nu\ne\theta}
  -\sum_e\log\left(\sum_o\sqrt{p(\theta,e,o)p(\nu,e,o)}\right)>0.
\]

Indeed, for a fixed wrong member, Markov's inequality on the square root
likelihood ratio gives exactly the product of these Bhattacharyya factors.
Merging observationally identical members is why `kappa` is strictly positive.

On a correct pilot, main increments are IID conditional on the pilot, with
rate at least `r=r_theta(w*(theta))>0` against each opposite answer. Every
initial pairwise log likelihood is at least `-B n0`. For `n` main samples with
`nr>L+B n0`, Hoeffding's inequality gives

\[
 P_\theta(\text{not stopped by }n\mid\text{pilot history})
 \le (m-1)\exp\left[-\frac{(nr-L-Bn0)^2}{2B^2 n}\right].       \tag{7}
\]

This uses the sufficient event that the **true** member passes the criterion;
an earlier stop at any member can only reduce cost. Starting the tail sum at
`ceil((L+B n0+L^(2/3))/r)` makes its contribution `o(1)`. To see this, up to
twice `(L+B n0)/r` there are `O(L)` terms each at most
`exp(-c L^(1/3))`; beyond that point the exponent is at least a positive
constant times `n`. Expected main length is therefore at most
`L/r+O(L^(2/3))`. Conditional Wald accounting multiplies this by
`g_theta(w*(theta))`, even when costs and observations are dependent.

On a wrong pilot the main phase costs at most `c_max ceil(L^2)`, so its expected
contribution vanishes. At entry to fallback, every log likelihood is bounded
below by `-B(n0+ceil(L^2))`. Uniform sampling has a strictly positive minimum
opposite-answer drift. The same tail argument bounds remaining expected cost
by `O(L^2)` uniformly over all entry histories. The entry probability is at most
the exponentially small pilot error plus `O(exp(-c L^2))` on a correct pilot.
Thus fallback contributes `o(1)`. Pilot cost is `O(L^(2/3))`, yielding
`E C <= C*(theta)L+O(L^(2/3))`. Equation (5) and
`b_delta/log(1/delta) -> 1` prove (6). Finite expected fallback length also
justifies the martingale and cost expectations used above.

All asymptotic constants depend on the **fixed** catalog, its separation,
positive probabilities and complete costs. This is not uniform as nuisance
parameters approach nonidentifiability, as the catalog grows, or as a decision
gap vanishes. A floating-point LP implementation requires a certified allocation
error; (6) states exact optimization. The existence proof does not imply a useful
finite-confidence sample count or computation cost.

## 4. State flow and actual time cannot be removed from a lower bound

For a more general finite stateful calibration interface, index an observed
state by `s` and elapsed integer time by `t<=T`. Every legal primitive action
`q` returns a joint observed response, duration and next state. A cancellation
uses its actual capped-response law. Conditional on the catalog member and
current `(s,t,q)`, that response has the specified controlled-Markov law; no
unmodeled history dependence is allowed. Time-dependent kernels are permitted
only with their time index retained. Let `x(s,t,q)` be its expected occupancy
under the true member, and `z(s,t)` its terminal probability. Positive durations
give the conservation equations

\[
 z(s,t)+\sum_q x(s,t,q)=1\{(s,t)=(s_0,0)\}
 +\sum_{u<t,v,q}x(v,u,q)P_\theta(S'=s,D=t-u\mid v,u,q).        \tag{8}
\]

Only actions and returned events legal within `T` are admitted. Add
`sum_{s,t,q} x(s,t,q) KL(P_theta||P_nu) >= b_delta` for each different-answer
member and minimize the correctly charged expected cost. This finite LP gives
a necessary cost bound; infeasibility certifies impossibility. Its occupancies
may fail cross-model nonanticipativity, so feasibility is **not sufficient**
for a uniformly correct implementable policy. The matching theorem in Section 3
applies only to the explicitly regenerative experiment interface, not this
general primitive-action LP.

Example: a paid prepare moves locked to ready, a probe moves ready to spent,
and a paid reset moves spent to locked. Each takes one time unit; only a probe
has informative binary output. Starting locked, a path with `n>=1` completed
probes needs at least `n` prepares and `n-1` resets, hence at least `3n-1` time.
If resource costs of prepare, probe and reset are `.14,.13,.03`, respectively,
state flow implies

\[
 E C\ge .30 E N_{\rm probe}-.03,
 \qquad N_{\rm probe}\le\lfloor(T+1)/3\rfloor.                 \tag{9}
\]

The prepare cost includes the calibration label. The first cycle requires no
extra reset, which explains the boundary term. Treating a spent-state probe as
fresh or using query count as elapsed time would give a different experiment.
For a binary catalog with probe KL `D_theta`, (3) and (9) give
`E C >= .30 b_delta/D_theta-.03`; the time cap also requires
`floor((T+1)/3) D_theta >= b_delta`. A capped full-probe Bayes error can yield
a stronger obstruction. Failure of the KL obstruction alone proves nothing
about feasibility. Unlimited-time (6) cannot promise an arbitrary fixed hard
deadline or a finite realized bill.

## 5. A strict full-model versus decision-identification separation

Consider the companion pure-information gating model. Its future hidden label
is uniform. State only controls access to information; the external terminal
score is exactly correctness, independent of state. A guaranteed prepare costs
`.08` and one time unit; a ready-state probe costs `.12` and one time unit,
with known positive label orientation. With time price `.01`, the deployment
gain over prior STOP is

\[
                   g(p)=p-.72.                              \tag{10}
\]

The finite catalog has `p in {.57,.87}`. The correct answer is STOP at `.57`
and prepare/probe at `.87`. Learning the catalog member uses separately labeled
calibration tasks, not labels from future test tasks. A complete calibration
macro also charges reset `.02`, label `.05`, and three time units overall:
its resource cost is `.08+.12+.02+.05+3*.01=.30`.

Append an independent, observed nuisance bit `U~Bernoulli(1/2+eta epsilon)`,
where `eta in {-1,+1}` and `0<epsilon<1/2`. Thus there are four distinct possible
joint laws, but only two answers. A change of `eta` alone has no effect on the
terminal payoff, legal actions, time or fee. Every opposite-answer alternative
has KL at least `D_p=kl(p,p_other)`, and the alternative with the same `eta`
attains it. Consequently

\[
 C^*_{\rm answer}(p,\eta)=.30/D_p,
 \quad C^*_{\rm full}(p,\eta)=.30/\min\{D_p,D_\eta\},
 \quad D_\eta=2\epsilon\log\frac{1/2+\epsilon}{1/2-\epsilon}.
                                                               \tag{11}
\]

Here `D_eta` is the same in both directions. It equals
`8 epsilon^2+O(epsilon^4)`. The ratio of full-model to answer-identification
complexities diverges as `epsilon -> 0`, while the answer complexity stays
fixed. This separation is about the required target and access, not superiority
over a classical baseline that already knows the same decision structure.

A two-sided Bernoulli likelihood test using only the labeled correctness bit
and threshold `log(1/delta)` ignores `U`. Let
`B=max{|log(.87/.57)|,|log(.13/.43)|}`. Standard bounded-overshoot and Wald
arguments give the explicit resource interval

\[
 \frac{.30\,b_\delta}{D_p}
 \le E C\le
 \frac{.30\,[\log(1/\delta)+B]}{D_p}.                          \tag{12}
\]

Correctness follows from likelihood-ratio martingales. For the upper bound,
the true-versus-alternative stopped log ratio is at most `log(1/delta)+B`;
its expectation is `D_p E N`. Positive drift and bounded increments ensure
finite expected absorption. Thus (12) tends to the answer lower-bound constant
without learning the nuisance. It is a classical finite-catalog likelihood
test with fully charged state preparation; it is not an unrestricted learned
kernel theorem, neural architecture, new SPRT, or measured LLM performance.

## 6. Near-bound identification does not imply positive net benefit

Uniform correctness and economical deployment are distinct endpoints. In the
two-answer example, at the negative member STOP is already uniquely optimal.
The two terminal answers are STOP and deploy. If abstention is allowed, it is
an error under both members, not a free correct output.
Let `q0,q1` be the probabilities of immediately returning STOP or deploy without
buying any observation. These probabilities are the same under both members.
Uniform correctness implies `q0<=delta` and `q1<=delta`, so acquisition occurs
with probability at least `1-2 delta`. Positive first-experiment cost implies

\[
 E_{p_-}\{\text{deployment gain over STOP}-C/M\}
       \le -c_{\min}(1-2\delta)/M<0.                          \tag{13}
\]

The deployment contribution is nonpositive because STOP is optimal there.
If zero-acquisition abstention has probability `qA`, adding the two error
constraints gives `q0+q1+2qA<=2 delta`, which preserves the same payment bound.
Thus no uniformly correct paid identifier can promise strictly positive net
gain over STOP in every member of this class. A positive member can have a
positive amortized certificate, but it requires its own fixed `M`, complete
costs and validation. Raising `M` after a failed primary endpoint is not allowed.

More generally, suppose the largest attainable per-deployment gain in a fixed
positive member is `Delta_theta>0`, and `M` is a prespecified positive integer
deployment volume. Equation (5) gives the necessary condition

\[
 E_\theta[\text{gain}-C/M]\le
 \Delta_\theta-b_\delta C^*(\theta)/M,
 \qquad M> b_\delta C^*(\theta)/\Delta_\theta
 \quad\text{for strictly positive expected net gain}.          \tag{14}
\]

For fixed finite `M`, the right side becomes negative as `delta -> 0`. Lower
identification error can therefore make a fixed-volume deployment uneconomical,
even for an information-efficient method. In the binary positive member above,
the only outputs are STOP or the correct policy, so the deployment gain is at
least `(1-delta)*.15` in expectation. Combining this fact with (12) yields the
sufficient condition

\[
 M>\frac{.30[\log(1/\delta)+B]}{D_{p_+}(1-\delta)\,.15}.       \tag{15}
\]

At `delta=.05`, the necessary and sufficient volume thresholds are approximately
`24.95606134` and `41.55534453`. Thus integer `M<=24` is impossible and `M>=42`
suffices under this contract. These are analytic bounds for this different, idealized known
catalog and its fully specified synthetic prices. They require unlimited
calibration time or a separately valid deadline contract, exclude unpriced
hardware/engineering costs, and are equally available to the classical test.
They do not establish observed gains, a neural advantage, or a rescue of the
unchanged 144-cell study's failed primary `M=1000` endpoint.

## 7. Primary neighbors and unresolved claims

- [Nitinawarat and Veeravalli, Sequential Analysis 2015;
  arXiv:1310.1844v2](https://arxiv.org/pdf/1310.1844) treats controlled Markovian
  observations and nonuniform sensing costs, with asymptotic testing guarantees.
  Its scope already rules out novelty based merely on state-dependent sensing
  or a cost-normalized information rate. Sections 2–3 here give an elementary
  restricted construction, not an improvement over that line of work.
- [Degenne and Koolen, NeurIPS 2019](https://proceedings.neurips.cc/paper/2019/file/60cb558c40e4f18479664069d9642d5a-Paper.pdf)
  studies correct-answer sets and asymptotically optimal pure exploration.
  Our single-valued answer map avoids its multiple-correct-answer complication;
  selecting alternatives by an incorrect answer is an established principle.
- [Wang and You, arXiv:2606.21889v1, 20 June 2026](https://arxiv.org/html/2606.21889v1)
  develops answer-wise acceptance, restricted likelihood stopping, and cost-aware
  information-directed measurement selection. This direct recent neighbor must
  be compared before proposing answer-focused sensing as a novel framework.
- [Kanarios, Zhang and Ying, RLC 2024](https://arxiv.org/abs/2402.16710)
  develops cost-aware best-arm identification with an asymptotically matching
  procedure. [Harding and Kandasamy, NeurIPS 2025](https://papers.nips.cc/paper_files/paper/2025/hash/b0dfe8236981ba84b4d98a7ed0426f0b-Abstract-Conference.html)
  instead combines observation costs with final recommendation loss. Our
  fixed-confidence guarantee and lifecycle comparison remain separate.

Closed internally: the explicit finite-catalog cost benchmark, attainability
under paid regeneration, a strict decision/nuisance separation, and the stated
state/time and economic impossibility boundaries. Still open: unrestricted
unknown stateful kernels, useful uniform finite-sample constants, computation
and real-clock qualification on external tasks, advantage over equally informed
classical methods, actual model/billing evidence, external proof reconstruction,
and an original general RL contribution.
