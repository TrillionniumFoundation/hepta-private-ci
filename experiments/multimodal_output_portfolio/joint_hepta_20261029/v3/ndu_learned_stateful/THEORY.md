# Paid calibration and stateful sensing: finite reference bounds

Status: 2026-11-06; a scope-correct reference extension, not a new RL algorithm,
a new simulation lemma, or a solution to general POMDP learning. These results
are mathematical statements under the access and accounting assumptions below.
Their numerical usefulness is a separate, falsifiable question. In particular,
a statistically valid certificate may be negative after calibration amortization.

## 0. Normative interface for the experiment

The experiment's eight raw rows are indexed by `(h,z,q)`, with `h,z in {0,1}`
and two paid actions. Each row is a distribution on the **joint** 12-element
alphabet `(label, duration, next_z)`: three labels, two positive durations, and
two next states. This does not impose independence of its three coordinates.
A completed failure label still applies its returned next state. A selected cap
`b` cancels `duration>b`; cancellation returns `(timeout,b,current_z)`, preserves
the current state, consumes one query, and pays the launch fee. Completion at
`duration=b` is observed. This cancellation rule is an explicit physical model.

For a simultaneous confidence level `1-alpha`, `J` fitted banks, `R` rows per
bank, alphabet size `m`, and **prespecified** sample count `n` per row, define

\[
 e_n=\min\left\{1,\sqrt{\frac{\log((2^m-2)RJ/\alpha)}{2n}}\right\},\quad
 w_n=\frac{m\beta}{n+m\beta},\quad
 \epsilon_n=(1-w_n)e_n+w_n. \tag{A}
\]

Here `beta` is the Dirichlet pseudocount per outcome, not the failure probability.
The simpler radius `min(1,e_n+w_n)` is also valid and is slightly looser. With
`m=12`, `R=8`, `J=24`, and `beta=1/2`, `w_n=6/(n+6)`. Nested sample prefixes
and reused data across banks do not invalidate the union bound: their sizes and
confidence allocation must be chosen before seeing their outcomes. No
independence between different banks is required. In the frozen protocol, the
kernel event receives `alpha=.025` and confirmation receives another `.025`;
using `.05` for each would not give the advertised `.05` overall failure budget.

If at most `K` queries and `T` integer time units are allowed, every query consumes
at least one time unit, and terminal quality is in `[0,1]`, put

\[
 L=\min(K,T),\quad B=1+L c_{\max}+\lambda T,\quad
 \Gamma_L(\epsilon)=1-(1-\epsilon)^L,\quad E=B\Gamma_L(\epsilon). \tag{B}
\]

Use `Gamma_0=0`. The looser `B min(1,K epsilon)` in the coordination README is
valid. On the event guaranteed by (A), all the following hold simultaneously:

- Every **same history policy** has true-versus-fitted expected utility error at
  most `E`, including fitted policies selected using these data.
- An exact fitted optimum has true regret at most `2E` against the true optimum
  in the same policy class. Approximate optimization adds its declared gap.
- A fitted candidate-minus-baseline advantage `g_hat` has true advantage at least
  `g_hat-2E`. If the baseline is prior STOP with a known payoff, its value has no
  model error, so the sharper lower bound is `g_hat-E`.
- Subtract `(C_setup_candidate-C_setup_baseline)/M` from the applicable bound to
  certify expected net benefit across `M` declared deployment episodes. Setup
  includes paid calibration, labels, resets, retries, and any priced planning or
  validation cost. A certificate is positive only if this final lower bound is
  strictly positive. An unfulfilled large deployment volume is not a realized
  saving.

This interface permits the planned undiscounted objective
`terminal_quality - sum(launch_fees) - lambda * elapsed_time`. It does not replace
physical duration by query count. Sections 1–5 prove these statements and give
their limits. They apply bank by bank; the simultaneous event permits reporting
all prespecified worlds, seeds, sample sizes, fees and deadlines without choosing
only successful cells. An exploratory new bank needs its own confidence budget. The frozen experiment
uses the stated looser radii; the sharper variants proved here are supplementary
mathematical bounds, not permission to rewrite its registered gate or evidence.

## 1. Model, observation pattern, and external contract

Let `H,Z,Q,D` be finite. A deployment episode draws a hidden, static `h` from a
known prior `p`, starts at known observed state `z0`, time zero, and query count
zero. The prior and initial state are the same in true and fitted evaluation.
The unknown table is

\[
 P_{h,z,q}(y,d,z'),\qquad d\in\{1,\ldots,d_{\max}\}. \tag{1}
\]

Its finite alphabet is known; structural impossibilities can be excluded in
advance. Conditional on `h`, current `z`, and chosen `q`, a fresh draw has this
row law independently of earlier randomness. This is a controlled Markov
assumption conditional on a static hidden parameter, **not a reset assumption**.
The next state affects subsequent row laws. The model cannot hide persistent
unobserved changes outside `h,z`; such changes require a larger state or a
different theorem. Calendar nonstationarity likewise requires an extra index.

At a decision history `eta`, the controller observes all previous actions,
returned labels or timeouts, actual elapsed durations, observed states and
remaining budgets. It either chooses `STOP(d_hat)`, or a query `(q,b)` with
integer cap `1 <= b <= T-t`. It cannot observe `h` or a future raw result. STOP
is mandatory once `K` queries are consumed or `t=T`. A completed query uses
`min(d,b)` time and one query slot; there is no free cancellation or reset.
For the experiment's deferred-transition cancellation semantics, the observation
map is

\[
 \phi_{z,b}(y,d,z')=
 \begin{cases}(y,d,z'),&d\le b,\\(\bot,b,z),&d>b.\end{cases}\quad
 \bar P_{h,z,q,b}=P_{h,z,q}\phi_{z,b}^{-1}. \tag{2}
\]

State transition on completion applies even to an outcome designated a failure.
The future `z'` of an unfinished raw query is **not** observable at cancellation.
No work continues in the background in this model. For a system that changes
state before completion, (1) alone is insufficient: use a raw path containing
the state at cancellation and a valid common observation map, or directly
estimate a cap-specific joint kernel. One must not infer a cancellation state
from an unavailable eventual completion state. All the transcript arguments
below also hold for finite cap-specific kernels, with their own calibrated rows.

A policy is a probability kernel on the same legal actions at each observed
history. Policies may use the entire history; feasibility depends on actual
observed state and resource counts, not on a fitted posterior. Specify a legal
fallback at every history, including those assigned zero probability by an
empirical model. A fitted belief policy, once selected, is frozen as this history
mapping: evaluating it in the true environment does not replace its internal
filter by an oracle filter.

The known external acceptance score is `u(h,z,d_hat)` in `[0,R_u]`. More generally
it may be any fixed bounded function of `h` and the observable transcript. It
is not learned or changed to make the intervention attractive. Let `c(eta,q,b)`
be a known nonnegative launch fee bounded by `c_max`. The primary utility is

\[
 U(h,W)=u(h,Z_N,\widehat d)
       -\sum_{i=0}^{N-1}c(\eta_i,Q_i,B_i)-\lambda t_N,\quad \lambda\ge0. \tag{3}
\]

Each fee is charged at launch, including failures and cancellations, exactly
once. Time cost charges actual consumed time, not requested caps or unused
budget. `N <= L=min(K,T)`, `t_N<=T`, and

\[
 -L c_{\max}-\lambda T\le U\le R_u,\qquad
 \operatorname{span}(U)\le B=R_u+L c_{\max}+\lambda T. \tag{4}
\]

If the frozen contract instead discounts terminal quality and launch charges
at their actual absolute times by `exp(-rho*t)`, `rho>=0`, the same range bound
and proofs hold. This is an optional different contract, not a substitution of
`exp(-rho*N)` for the clock. Any additional path-dependent reward or resource
cost must have a declared finite span and be included in `B`.

External scoring can depend on `h`; it is not an observation available before
the terminal decision. The KL transcript in Section 2 excludes hidden `h` and
any revealing post-decision score. The coupling in Section 4 includes `h` in
both worlds so that the fixed external score is compared correctly.

## 2. Stateful transcript KL, with a testable failure of query-only counts

Fix a policy `pi` and two hidden hypotheses `h,g` in the **same true table**.
Let `W` contain actions, observed joint responses, states, time and terminal
decision, padded after STOP to a fixed finite length. Initial state is `z0` in
both hypotheses. For this section assume the reachable rows of `bar P_h` are
absolutely continuous with respect to `bar P_g`; common strictly positive
finite support is a sufficient condition. Define

\[
 D_{hg}(z,q,b)=\mathrm{KL}(\bar P_{h,z,q,b}\|\bar P_{g,z,q,b}),\qquad
 \mu_h^\pi(z,q,b)=E_h^\pi\sum_{i<N}
   1\{Z_i=z,Q_i=q,B_i=b\}. \tag{5}
\]

**Theorem 1 (finite stateful chain rule).**

\[
 \boxed{\mathrm{KL}(P_h^\pi(W)\|P_g^\pi(W))
 =E_h^\pi\sum_{i<N}D_{hg}(Z_i,Q_i,B_i)
 =\sum_{z,q,b}\mu_h^\pi(z,q,b)D_{hg}(z,q,b).} \tag{6}
\]

More generally, replace the row divergence by the divergence of the two true
conditional response laws at the whole history. A time-dependent kernel needs
a time index. A hypothesis-dependent initial state adds its initial KL. For a policy fitted
from calibration `C` independent of the target hypothesis, this statement holds
conditional on `C`; including `C` in the transcript averages the conditional
identity over `C`. If acquisition data depend on the target hypothesis, their
own KL must instead be included. Training labels cannot become uncharged
information about the deployment episode.

**Proof.** For each finite padded transcript, its probability factors into the
common policy probabilities at its histories and the applicable conditional
response probabilities. Common action and terminal-decision probabilities
cancel in the likelihood ratio. A padded or STOP transition is deterministic
and contributes zero. The log ratio is therefore the sum, over launched
queries, of the log ratios of their observed row probabilities. Finite horizon
and finite common support allow expectation term by term. Conditional on the
current history and action under `h`, the expected log ratio is exactly (5).
Grouping the finite sum by `(z,q,b)` proves (6). The same argument at full-history
conditional laws gives the general form. If an initial random observation has
unequal laws, its log ratio appears as the first summand. ∎

If terminal labels `d*(h)` are fixed, distinct across the alternatives being
tested, and the **same** policy has error at most `delta<1/2` for every `h`, then
(6) and binary data processing imply

\[
 \sum_{z,q,b}\mu_h^\pi(z,q,b)D_{hg}(z,q,b)
 \ge \mathrm{kl}(1-\delta,\delta)
 \quad\text{when }d^*(g)\ne d^*(h). \tag{7}
\]

For completeness, apply log-sum separately to an event
`A={d_hat=d*(h)}` and its complement. This gives KL at least
`kl(P_h(A),P_g(A))`. For `x>y`, its derivative in `x` is
`log(x(1-y)/(y(1-x)))>0` and its derivative in `y` is
`(y-x)/(y(1-y))<0`; hence the minimum over `x>=1-delta,y<=delta` is the right
side of (7). This correctness requirement is an additional contract. Maximizing
(3), whose state quality also changes with interventions, does not imply it.
Counts in (7) must arise from feasible state, time and action paths. Relaxing
away those constraints yields at most a necessary lower bound, not a feasible
allocation or a sufficient deadline guarantee. Discounted fee accounting also
requires launch-time occupancy; it cannot be reconstructed from `mu(z,q,b)`
alone unless fees are undiscounted and depend only on that row.

**Minimal nonreset counterexample.** There are two observed states, fresh and
spent, one query, duration one, and two queries are always made. In fresh, the
query returns `Y=1` with probabilities `0.9` under `h` and `0.1` under `g`, and
moves to spent. In spent, it returns a fair coin under either hypothesis and
stays spent. Thus

\[
 \mathrm{KL}(W_h\|W_g)=0.8\log 9\simeq1.7577796619,
 \quad E_hN_q\,D_{hg}(\text{fresh},q)=1.6\log9\simeq3.5155593237. \tag{8}
\]

Both fresh and spent rows have common positive support. A hypothetical free
reset would create a different experiment. Equation (6), with one visit to
each state, gives the correct value. No query-only constant KL represents both
rows.

## 3. What paid data legitimately estimate the table

**Declared calibration access.** Before deployment, a training laboratory or
simulator can be asked to instantiate a specified `h`, reset or prepare a
specified observed `z`, and run `q` to completion. Its known label `h` is a
training capability; deployment never receives the test episode's `h`. These
training draws are independent of the subsequently drawn test hypothesis.
The calibration distribution for that row is exactly the stationary law (1).
For each row `r=(h,z,q)`, collect a prespecified number `n_r>=1` of IID complete
joint responses. The assumption is stronger than ordinary unlabelled stateful
interaction. It must be physically justified for the application.

Record every acquisition charge: query launches, preparation/reset, labels,
consumed full duration, retries and failures. A simulator reset or diagnostic
truth table is not evidence of free real-world access. If labels arrive only
in hindsight, their delay and price belong in the ledger. The results below
require the declared IID labelled row samples, not an asserted equivalence to
arbitrary adaptively collected logged data. An adaptive sample-size/stopping
rule needs a confidence sequence or a union bound over its possible sizes.

If only capped responses are obtainable, empirical frequencies estimate those
cap-specific laws. They do **not** identify unseen raw outcomes or an uncapped
row. Such a restricted model can still use the theorem by calibrating every
allowed capped row, paying for all of them, and restricting deployment to that
interface. A larger cap must not be extrapolated from censored frequencies.

Let the known alphabet of a row have `m_r` elements and let `hat P_r` be its
empirical law. Choose confidence shares `alpha_r>0` before data collection,
with sum at most `alpha` across every reported bank and row. For `m_r>=2`, set

\[
 e_r=\min\left\{1,\sqrt{\frac{\log((2^{m_r}-2)/\alpha_r)}{2n_r}}\right\}.
 \tag{9}
\]

A one-element alphabet has error zero. A missing row with `n_r=0` only has the
trivial radius one; it cannot be certified using another row's sample size.

**Theorem 2 (simultaneous multinomial TV bound).** With probability at least
`1-alpha`, every calibrated row obeys `TV(P_r,hat P_r)<=e_r`, where
`TV(P,Q)=1/2 sum_x |P(x)-Q(x)|`.

**Proof.** For distributions on a finite alphabet,
`TV(P,Q)=max_A (Q(A)-P(A))`. This follows by choosing all coordinates with
`Q(x)>P(x)`; their positive differences sum to half the absolute differences,
and no other subset has a larger sum. For a fixed nonempty proper subset `A`,
the empirical proportion of observations in `A` averages `n` IID Bernoulli
variables. Here is the needed one-sided concentration argument. For a variable
`X in [0,1]`, the log moment-generating function of `X-E X` has value and slope
zero at zero, and its second derivative is the variance under an exponential
tilt. Every distribution supported on `[0,1]` has variance at most `1/4`:
`Var(X)<=E[(X-1/2)^2]<=1/4`. Integrating twice gives
`log E exp(s(X-E X))<=s^2/8`. Independence, exponential Markov inequality and
`s=4e` now give
`Pr{hat P(A)-P(A)>e}<=exp(-2n e^2)`.
There are `2^m-2` nonempty proper subsets; their one-sided events already cover
both signs through complements. Thus

\[
 \Pr\{\mathrm{TV}(P,\widehat P)>e\}
 \le (2^m-2)e^{-2ne^2}. \tag{10}
\]

Use (9) and a union bound over rows and banks. If the square root exceeds one,
TV is deterministically at most one. No independence between rows or fitted
banks is needed. ∎

Strict positivity of the true row is unnecessary for this theorem. To make
fitted belief updates defined even after outcomes with zero counts, one may use
a **prespecified** pseudocount `beta>=0` on each of its `m` possible outcomes:

\[
 \widetilde P=(1-w)\widehat P+wU_m,
 \quad w=\frac{m\beta}{n+m\beta},
 \quad\mathrm{TV}(P,\widetilde P)
 \le (1-w)\mathrm{TV}(P,\widehat P)+w. \tag{11}
\]

The last inequality follows from the triangle inequality and `TV(P,U_m)<=1`.
Combining (9) and (11) proves (A). Smoothing has a bias term; it must not receive
the unsmoothed confidence radius without this term. If different rows have
different radii, use their maximum for the uniform bound below.

For every common censoring map in (2),

\[
 \mathrm{TV}(\bar P,\bar Q)\le\mathrm{TV}(P,Q),\qquad
 \mathrm{KL}(\bar P\|\bar Q)\le\mathrm{KL}(P\|Q). \tag{12}
\]

For TV, sum the absolute differences in each observation fiber and apply the
triangle inequality. For KL, the log-sum inequality in each fiber gives
`sum_{x in F} p_x log(p_x/q_x) >= p(F) log(p(F)/q(F))`; sum over fibers. The
log-sum inequality itself follows from convexity of `x log x` with weights
`q_x/q(F)` (with limits for zeros). This also proves the binary data-processing
step used above. Importantly, (12) is one way: matching censored laws does not
bound raw-law error or make lost information available.

## 4. Joint-transcript coupling and value transfer

Let `P` and `Q` be any two tables with the same prior, initial state, actions,
censoring semantics and fixed utility. Suppose all raw rows satisfy
`TV(P_r,Q_r)<=epsilon`, `0<=epsilon<=1`. Section 3 also permits taking the
uniform bound directly on all cap-specific observed rows.

**Theorem 3 (uniform same-policy transfer).** For every history policy `pi`,

\[
 \mathrm{TV}(\mathcal L_P(h,W),\mathcal L_Q(h,W))
 \le\Gamma_L(\epsilon):=1-(1-\epsilon)^L,
 \qquad |V_P(\pi)-V_Q(\pi)|\le B\Gamma_L(\epsilon). \tag{13}
\]

Here `V_P(pi)=E_P U(h,W)`. In particular
`Gamma_L(epsilon)<=min(1,L epsilon)`. No lower bound on observation probabilities
and no posterior-Lipschitz assumption are required.

**Proof.** Couple the initial hidden hypothesis identically using `p`, and set
both initial states and clocks equal. As long as the observable histories
agree, draw the next action identically from their common policy distribution.
If this is STOP, use the same terminal decision. For a query, maximally couple
the two **observed joint** response laws at the common `h,z,q,b`. Their TV is at
most `epsilon` by (12), so they match with probability at least `1-epsilon`.
Such a finite coupling exists: allocate probability `min(P(x),Q(x))` to equal
pairs `x,x`, whose total is `1-TV(P,Q)`, and couple the residual masses in any
way. Equal responses give equal state updates, elapsed time, costs and legal
budgets. After a first mismatch, complete both marginal processes arbitrarily.

Pad stopped episodes with identical dummy transitions. Conditional on no prior
mismatch, each of at most `L` query responses matches with probability at least
`1-epsilon`; dummy transitions match with probability one. Induction gives
probability of any mismatch at most `1-(1-epsilon)^L`. For any event `A`, the
indicator difference of the two joint transcripts is zero when they match and
at most one otherwise. Taking expectations and a supremum proves the TV bound.
The fixed external payoff functions agree on matching `(h,W)` and differ by at
most their range span `B` otherwise, proving the value bound. Finally
`1-(1-epsilon)^L<=L epsilon` follows by induction or a union bound. ∎

The joint law includes `h` only for this proof and evaluation, not as input to
the controller. Bounding the observable transcript alone would not suffice to
compare an arbitrary score `u(h,z,d_hat)`. Conversely the proof never compares
posterior vectors at the same rare history.

**Why no posterior stability claim follows.** With prior one half, suppose
both true hypotheses assign probability `a` to an observation `Y=1`. A fitted
table assigns probabilities `a` and `a^2` instead. Its maximum row TV error is
`a-a^2`, yet after `Y=1` the true posterior is `1/2` and the fitted posterior is
`1/(1+a)`. Their difference tends to `1/2` as `a` tends to zero. Both tables can
have full positive binary support. Rare histories therefore preclude a uniform
posterior bound from row TV alone, while (13) remains valid.

The finite horizon makes the policy class well-defined and admits exhaustive
planning, but can still have an exponentially large history tree. This theorem
does not supply a computationally efficient general POMDP solver.

## 5. Regret and a full-cost baseline certificate

Condition on a calibration dataset on the simultaneous event of Theorem 2,
and let `Q` be its fitted table. Let `Pi` be the same feasible history-policy
class in both models; it must not contain policies that observe the test `h`.
Put `E=B Gamma_L(epsilon)`. A fitted candidate satisfying

\[
 V_Q(\widehat\pi)\ge\sup_{\pi\in\Pi}V_Q(\pi)-\xi,\quad\xi\ge0,
\]

obeys

\[
 \boxed{\sup_{\pi\in\Pi}V_P(\pi)-V_P(\widehat\pi)\le 2E+\xi.} \tag{14}
\]

**Proof.** For each `pi in Pi`, add and subtract its fitted value and the fitted
candidate's value. The first and last differences are at most `E` by (13), and
the fitted optimization difference is at most `xi`. Take the supremum. This
argument is uniform on the row-confidence event, so selection of `pi_hat` using
the same data does not require an additional policy-count union bound. ∎

For any baseline `pi0 in Pi` set `g_hat=V_Q(pi_hat)-V_Q(pi0)`. No optimality of
the candidate is required for

\[
 V_P(\widehat\pi)-V_P(\pi_0)\ge \widehat g-E-E_0, \tag{15}
\]

where `E0=E` always works, and a proved smaller baseline-specific error can be
used. For prior STOP with known `p,u,z0`, `E0=0`. This follows directly by two
applications of (13), or by one when the baseline value is model-independent.
A data-selected baseline is also allowed under the uniform event. An oracle
with access to the true table is a diagnostic extra-information comparator,
not a same-paid-data baseline.

Let the accounting contract contain `M>=1` future episodes with the specified
starting law and independent test draws. Let `C_setup_hat` and `C_setup_0` be
charged setup costs, expressed in the same utility units, including all paid
calibration and any priced labels, resets, failed acquisitions, fitting,
planning, and evaluation required to deliver the respective policy. They may
be observed functions of the calibration data. Conditional on those data,
expected per-episode net gain is at least

\[
 \boxed{\widehat g-E-E_0-
        \frac{C_{\mathrm{setup},\widehat\pi}-C_{\mathrm{setup},0}}{M}.} \tag{16}
\]

Multiplying by `M` gives an expected total-gain bound. If both alternatives use
an already-paid bank, shared setup costs cancel in an incremental comparison.
That does not justify canceling them against a from-scratch prior STOP baseline.
If a positive marginal operational advantage `a=g_hat-E-E0` is established and
incremental setup cost is `Delta C>=0`, (16) is positive exactly when
`M > Delta C/a`. If `a<=0`, no amortization volume makes this certificate positive.
This arithmetic is not a promise that the declared `M` tasks will materialize.

The statement concerns expected deployment utility, with confidence over
calibration. It is not a guarantee on a particular finite batch's realized
utility. Monte Carlo estimates of fitted values or independent confirmation
means require their own declared confidence errors and evaluation cost; those
errors must be subtracted from (16). Exact finite-tree values do not incur this
additional statistical error. Planner approximation affects (14); a certified
interval for the candidate's actual fitted value is what matters for (15).

Calibration is assumed to finish before each deployment episode's externally
defined clock starts. This is an explicit offline-access contract. If instead
calibration and deployment share a hard campaign deadline, calibration's actual
time consumes it: start deployment at that elapsed time with the remaining
budget, retain all launch times in any discount, and bound that combined
process. The simple offline `C_setup/M` formula must not erase this delay or
provide a free reset of the real clock. CPU planning time is likewise a charged
resource if the application counts it; simulated durations do not measure it.

## 6. A boundary that more unlabelled data cannot remove

Consider `h in {0,1}`, prior one half, a single state, unit-duration paid queries,
and frozen acceptance score `1{d_hat=h}`. In world `+`, every query returns the
correct label with probability `p>1/2`. In world `-`, the labels are inverted:
`P_{-,h}=P_{+,1-h}`. All binary row probabilities are positive. Training and
deployment provide no labelled `h` samples and no external orientation signal.
Independent unlabelled training episodes have the same symmetric prior.

**Proposition (unidentifiable orientation).** For any common learning and
history-dependent deployment rule, the complete available transcript has the
same marginal law in the two worlds, and its two deployment correctness
probabilities sum to one. Hence one world has accuracy at most one half.

**Proof.** Couple training episodes and the test episode by flipping each hidden
label `h` between worlds. Uniform priors and `P_{-,h}=P_{+,1-h}` permit identical
observations at each adaptive query, identical random policy choices, and
identical stopping decisions. Thus all unlabelled training and test histories
match in the coupling. The test hypotheses are opposite and the emitted binary
decision is the same, so exactly one world's answer is correct. Take
expectations. ∎

For `p=.9` and a launch fee `.01`, a known orientation permits one-query expected
utility `.89`; without orientation, some world has utility at most `.5` even
before subtracting paid-query costs. An observed correctness score that reveals the label would break the
no-orientation premise and must be counted as labelled access. This example is
already a special case of the stateful model, so allowing more general states
cannot remove it without
an added identifying assumption. The labelled calibration access of Section 3
breaks this symmetry, and its cost and attainability are part of the claim.
Rows never observed under a permitted calibration interface likewise receive
no small TV guarantee merely because other rows were estimated accurately.

## 7. Pre-result numerical checks and failure criteria

The independent verifier `verify_theory.py` uses finite enumeration, rational
probabilities and elementary formulas. It is not an implementation of the
experiment's fitted planner. It checks the following predictions, specified
without looking at that planner's outcomes:

1. The nonreset transcript in (8) has one fresh-row KL, not twice that KL.
2. A completion exactly at the cap is visible; cancellation cannot leak the
   unfinished next state. Coarsening never increases finite-row TV or KL.
3. A rare-history posterior can differ by almost one half despite small row TV.
4. A length-`L` rare-event construction attains transcript TV
   `1-(1-epsilon)^L`, checking the factor in (13). This construction tests the
   TV theorem; full support was only an extra assumption for finite KL.
5. On a separately enumerated small policy class, all same-policy value errors,
   fitted-policy regret, and the baseline certificate obey (13)–(16).
6. Exact small multinomial tail probabilities lie below (10), and smoothed
   estimates satisfy (11).
7. An unlabelled orientation swap leaves histories equal and the two correctness
   probabilities summing to one.
8. For the coordination grid's `n in {16,256,8192}`, the verifier records all
   confidence radii and error penalties for `m=12,R=8,J=24,beta=.5`. The
   registered kernel budget is `alpha=.025`; `.05` is retained as an explicitly
   illustrative arithmetic comparison, not the joint-experiment confidence.
   These are bound arithmetic, not claims of empirical gains. If the registered
   confidence level or number of banks changes, rerun with that declared choice.

For the registered kernel budget `.025` and two possible queries, the
independent arithmetic gives the following dimensionless penalties. No measured
utility or empirical error was used to choose these constants; all registered
fee/deadline combinations are included in the JSON output.

| Samples per row | Smoothed uniform TV radius | Sharper `E/B` for `L=2` | Frozen looser `E/B` for `K=2` |
| --- | ---: | ---: | ---: |
| 16 | 0.8069085431 | 0.9627156893 | 1.0000000000 |
| 256 | 0.2023204267 | 0.3637072983 | 0.4130511501 |
| 8192 | 0.0331687158 | 0.0652372678 | 0.0663849464 |

The sharp and frozen columns use their respective smoothing and accumulation
bounds. Their `B` values can also differ when `T<K`; the JSON reports both
conventions. A small diagnostic row error cannot replace these confidence
penalties without changing the claim.

Record actual row TV only as a truth-table diagnostic; a deployable certificate
uses the proved confidence radius. Do not substitute diagnostic error for the
radius while retaining its confidence label. A positive raw quality gain,
a positive fitted gap, or an empirical negative regret is insufficient for
(16). Reversed effects, dominated policies, uncovered rows, undercharged data,
and vacuous certificates are reportable failures. Existing known-law SPRT
results do not transfer a PAC guarantee or asymptotic optimality to this model.

## 8. Primary neighbors and claim boundary

- [Lee, Agarwal, Dann and Zhang, ICML 2023, *Learning in POMDPs is
  Sample-Efficient with Hindsight Observability*](https://proceedings.mlr.press/v202/lee23a/lee23a.pdf),
  Lemma E.1 and Appendix F.1, explicitly give a model/transcript simulation
  lemma for arbitrary history policies. Their training-time latent-state access
  is directly relevant to why our labelled calibration assumption must be
  explicit. Equation (13) is a finite joint-response coupling specialization.
- [Demirci, Kara and Yüksel, *Sensitivity of Filter Kernels and Robustness to
  Incorrect Transition and Measurement Kernel Perturbations in Partially
  Observable Stochastic Control*, v2](https://arxiv.org/html/2508.10658v2)
  develop explicit value and policy robustness bounds under their stated
  regularity assumptions. Our bounded finite-horizon argument establishes only
  the particular assumptions and constants above.
- [Nitinawarat and Veeravalli, *Controlled Sensing for Sequential Multihypothesis
  Testing with Controlled Markovian Observations and Non-Uniform Control Cost*](https://arxiv.org/abs/1310.1844)
  already studies controlled observation memory and unequal control costs.
  Equation (6) is the classical likelihood chain rule with legal state occupancy.
- [Cheng and Huan, *Optimal Stopping for Sequential Bayesian Experimental
  Design*, v3](https://arxiv.org/abs/2509.21734v3)
  already couples experiment design and stopping, including a policy-gradient
  method and a training curriculum. Adding STOP or a physical state is not a
  new algorithmic contribution.
- [Kanarios, Zhang and Ying, RLC 2024](https://rlj.org/papers/kanarios2024cost)
  and [Harding and Kandasamy, NeurIPS 2025](https://papers.nips.cc/paper_files/paper/2025/hash/b0dfe8236981ba84b4d98a7ed0426f0b-Abstract-Conference.html)
  are direct cost-aware identification comparators. Neither a cost-normalized
  KL expression nor acquisition-cost-plus-decision-loss objective is claimed
  here as new.

The scoped contribution of this unit is an auditable reference contract and
its explicit finite bounds for the experiment. Whether a useful new method
exists remains conditional on an increment over these neighbors, independently
confirmed benefit with legitimate data access, and a nonempty full-cost
certificate. A classic plug-in dynamic program plus these bounds does not by
itself establish an original general RL framework.
