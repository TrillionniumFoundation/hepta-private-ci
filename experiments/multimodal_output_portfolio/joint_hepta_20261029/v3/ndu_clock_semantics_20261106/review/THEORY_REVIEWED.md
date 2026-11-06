# Clock refinement, local risk, and the next candidate's objective

This note is a semantic audit of a proposed next-candidate ingredient. It does
not replace the historical `ndu_jac/core.py` objective or modify any prior result.
The identities are classical entropic-risk facts. The contribution here is a
concrete reproducible guard against comparing controllers under different
objectives or giving a representation change an algorithmic interpretation.

## 1. The two contracts

Write the monetary certainty equivalent as

\[
 C_\eta(X)=-\eta^{-1}\log\mathbb E[e^{-\eta X}],\qquad \eta>0.
\]

The retained JAC evaluator uses local recursion

\[
 Q(s,a)=C_\eta\{r-c+e^{-\rho d}V(s')\},\qquad
 V(s)=\sum_a\pi(a\mid s)Q(s,a).
\]

The same eta is used at each supplied decision node; action randomization is
outside the CE. This defines a legitimate declared recursive preference. It is
not in general the CE of the time-zero discounted trajectory payoff, and its
primitive decision-event boundaries are part of its contract.

A separate, externally timed contract scores the physical payoff

\[
 G=\sum_j e^{-\rho t_j}r_j,\qquad J(\pi)=C_{\eta_0}(G),
\]

where every cash flow is located at its actual declared time. A launch fee is
paid at launch; a completion reward is paid at completion; cancellation exposes
only available observations and does not receive a later reward for free.
An administrative graph subdivision that adds no action choice, observation,
fee, elapsed time or payoff should leave this latter objective unchanged.

Model ticks in this note are not measured wall seconds. The comparison supplies
all laws to both planners; there is no learned-kernel or paid-calibration claim.

## 2. A forced-wait refinement changes fixed local risk

Let X be 0 or 1 with equal probability, let one tick discount by gamma=1/2, and
set eta=2. A probe pays .01 at launch, completes after one tick, and reveals X.
STOP pays .16 immediately.

In the coarse representation, the completing transition branches to the
revealed X. Its probe value under the retained local recursion is

\[
 -.01+C_2(X/2)
 =-.01-\tfrac12\log\{(1+e^{-1})/2\}
 \approx .17994274652086124.
\]

In the refined representation, there is a deterministic one-tick wait, then a
forced zero-time resolution node. That node offers no choice, fee or extra
observation. After removing this administrative node, the joint law of the
physical terminal payoff and completion time is identical. Nevertheless fixed
local eta gives

\[
 -.01+\tfrac12 C_2(X)
 =-.01-\tfrac14\log\{(1+e^{-2})/2\}
 \approx .1315547923792432.
\]

Thus one encoding chooses the probe while the other chooses STOP. This is not a
bug relative to the fixed-node recursive definition; it is an obstruction to
claiming that the definition depends only on the externally timed payoff law.
If local risk resets are intended, the actual events that trigger resets must
be fixed, and an administrative node may not create a new reset.

This example also has positive *paid* headroom relative to STOP under the
trajectory contract: approximately .01994274652. The correctly matched strong
planner chooses the same probe, so that headroom does not establish an advantage
for a new controller.

## 3. Risk transport is necessary for this refinement invariance

For any gamma>0,

\[
 C_\eta(\gamma X)=\gamma C_{\eta\gamma}(X).
\]

The identity follows directly by substituting in the exponential and dividing
by eta. Suppose a no-information deterministic wait with discount gamma is
required to preserve values for every bounded lottery X. If the child uses
parameter eta', invariance requires

\[
 C_\eta(\gamma X)=\gamma C_{\eta'}(X)
\]

for every such X. This forces eta'=eta*gamma. One way to see necessity is to
apply both sides to epsilon*Y for a bounded, nondegenerate, mean-zero lottery Y.
Its CE has expansion

\[
 C_\alpha(\epsilon Y)
 =-\tfrac12\alpha\epsilon^2\operatorname{Var}(Y)+O(\epsilon^3).
\]

Matching the quadratic coefficients gives eta*gamma^2=gamma*eta'. The expansion
is justified because bounded Y has an analytic moment generating function near
zero. Sufficiency is the displayed identity. Degenerate X alone would not
identify eta'; the assertion is for all bounded lotteries.

Consequently a time-zero trajectory-CE interpretation uses

\[
 \eta_t=\eta_0e^{-\rho t},\qquad
 \eta_{t+d}=\eta_te^{-\rho d}.
\]

This rule also applies branchwise to observed random durations. It is not valid
to replace a random duration by its mean before applying CE or before deciding
which actions fit a hard deadline.

## 4. Bellman recursion for the trajectory contract

Let h be the complete observable history, t its elapsed time, and r the local
present value at time t of all cash flows during a transition. Given action a,
an outcome consists of (r,d,h'). For a fixed continuation policy, define U(h)
as its remaining local-unit certainty equivalent using eta_t. Then

\[
 U(h)=C_{\eta_t}\{r+e^{-\rho d}U(h')\}.
\]

To prove the claim, use the induction hypothesis

\[
 e^{-\eta_{t+d}U(h')}=
 \mathbb E[e^{-\eta_{t+d}G_{h'}}\mid h'].
\]

Since eta_{t+d}=eta_t*exp(-rho*d), multiplying by exp(-eta_t*r) and integrating
the joint outcome law yields the exponential moment of the complete remaining
physical payoff. Taking the logarithm gives the stated recursion. Induct from
the finite terminal nodes. The proof assumes the complete history contains
everything needed to give a common legal action set and conditional law; it
does not infer hidden state or grant calibration labels.

For unconstrained expected exponential utility on a finite history tree, an
optimal deterministic action exists at each history. Maximizing this recursion
therefore agrees with the classical clock-augmented trajectory-CE planner.
This is a reduction, not a new policy-identification algorithm. In a merged
state representation, clock/history must be included whenever it changes the
conditional law, eta, legality or continuation policy. Our independent small
enumerator uses trees with a unique elapsed time per named state.

This argument does not remove randomization from a minimax error or constrained
resource problem. The earlier deadline LP explicitly permits randomization,
and its 5% certificates remain statements about its separate declared loss.

## 5. Policy randomization must also be matched

If a randomized action selects deterministic rewards 0 or 1 with equal
probability, action mixing outside CE gives .5. Time-zero trajectory CE at
eta=2 instead gives

\[
 C_2(X)=-\tfrac12\log\{(1+e^{-2})/2\}\approx .2831095847584864.
\]

Thus evaluating stochastic actor policies with the old outside-CE convention
and comparing them to an inside-CE trajectory baseline changes the target.
Deterministic optimal-policy agreement in an applicable special case does not
make all stochastic policies or their gradients equivalent.

## 6. Direct prior work and what remains unproved

- Essakine and Vernade, *Tight Sample Complexity Bounds for Entropic Best Policy
  Identification*, COLT 2026, studies finite-horizon trajectory entropic policy
  identification and gives matching exponential-horizon sample bounds. This
  rules out claiming that entropic BPI plus a stopping rule is an empty topic:
  https://proceedings.mlr.press/v336/essakine26a.html . Its exact reward/access
  assumptions must be checked before transferring a theorem to random-duration
  or censored tool observations.
- Mortensen and Talebi, *Recursive Entropic Risk Optimization in Discounted
  MDPs: Sample Complexity Bounds with a Generative Model*, arXiv v3,
  https://arxiv.org/html/2506.00286v3 , distinguishes static and recursive risk.
  For deterministic reward and a fixed discount gamma, the retained JAC form
  obeys C_eta(r+gamma*V)=r+gamma*C_(eta*gamma)(V); the change of risk parameter
  must be made when comparing conventions. Joint random rewards/durations are
  not asserted to satisfy that paper's theorem without further work.
- Baeuerle and Jaskiewicz, *Markov decision processes with risk-sensitive
  criteria: an overview*, 2024, Section 5, explicitly gives the expanded
  discount-state Bellman equation for static entropic risk and distinguishes
  it from nested recursion. The risk-transport mechanism is established:
  https://doi.org/10.1007/s00186-024-00857-0 .

No independent-task benefit, sample-complexity improvement, net monetary gain,
or original RL contribution follows from this note. The implementation preserves
all 81 prospective grid cells, verifies identical physical terminal laws and
compares the transported recursion with independent full-policy terminal-payoff
enumeration. It rejects risk transport alone as a new algorithm candidate.
