# What this continuation can identify

The parent is R15 commit `74144a3f5d5c77c953ecdc4708d3d90b56b67d3c`.
All earlier evidence and failed acceptance decisions remain unchanged.

## Same-operator equivalence is a constraint on the research question

Let two filters have the same initial distribution, transition generator
\(Q\), emission matrices, WRITE transformation, rewards, prices, and causal
controller. They therefore have the same transition \(P(t)=\exp(tQ)\).
Induction over the public event history gives the same predictive distribution
and the same Bayes posterior after every possible observation. The controller
then selects the same action, including the same deterministic tie rule.
Coupling both executions to the same owner tape gives the same observations,
answers, fees, rewards, and later actions. This reasoning also applies after
restoring the same complete trusted state.

Consequently, relabeling that operator as HX or an ordinary HMM cannot create
a quality advantage. A positive difference requires an explicitly different
estimated model, prior, representation, available information, controller, or
numerical approximation. Those are separate hypotheses with separate controls.
Six of the eight inherited R15 ordinary selections use the same fitted matrix;
their primary D-B differences are structurally zero. Increasing the number of
query samples does not repair that identification issue.

There is also an exact testing limit for this inherited freeze. If at most
\(m\) paired differences can be nonzero, the smallest attainable two-sided
exhaustive sign-flip p-value is \(2^{1-m}\) (or 1 when \(m=0\)). With six
structural zeros among eight fits, \(m\le2\), so the p-value cannot be below
0.5, whatever the number of new episodes. The registered alpha=.05/Holm gate
is therefore unattainable for a strict positive D-B claim on these inherited
fits. R16 preserves and reports that failure; it does not reinterpret it as
merely a request for more samples. `identifiability.py` checks the frozen
operators and exhaustively verifies this lower bound.

R16 retains this control. It does not delete the strongest ordinary candidate
or count a useful task-value controller as an HX-specific improvement.

## Two reachable histories with the same current marginals

The new witness starts with the same exact public WRITE of content 0. At time
2 it receives a high-quality REFRESH observation; after a further interval
\(s\), it receives a READ observation. Compare histories `(1, 2)` and `(2, 1)`.
All other events, the law, and the emission kernels agree.

The initial law and generator are symmetric under exchange of content labels
1 and 2. Hence the two histories have equal positive probability and equal
phase marginals, and their content marginals are label permutations. Choose
\(s\) so that the first history's content-1 and content-2 posterior masses
are equal. Then both full content marginals agree as well.

This is not an arbitrary posterior injection. At zero gap the stronger first
observation favors label 1. For a long gap, the ergodic content-symmetric law
forgets that first observation and the final READ favors label 2. Continuity
therefore supplies an intermediate equality. The implementation freezes a
finite bracket, records failures of that bracket, and numerically solves it.
The posterior and forecast are checked independently by a positive-series
uniformization calculation. Float64 equality is reported with its numerical
tolerance; this is not an interval-certified continuum theorem.

At a fixed further horizon of 2, retained phase-content dependence can give
different optimal content answers. For the equal mixture of these two
histories, the value of remembering which occurred is

\[
\frac12\sum_{o\in\{+,-\}}\max_a r_a^\top P^\top p_o
-\max_a\frac12\sum_{o\in\{+,-\}}r_a^\top P^\top p_o.
\]

The second term is the best common answer when the two histories are collapsed
to exactly the same representation. The code implements this as row-vector
predictions. It checks four predeclared dynamics families and retains the
family with no positive decision witness. The selected future horizon is not
chosen using later sampled rewards.

The interval schedule extends R15's original fixed discrete query timings.
The different decisions are content answers, not necessarily READ versus WAIT
or REFRESH timing choices. The result is conditional on this two-history
experiment; it is not a population net-utility estimate. An ordinary model
that remembers the public history obtains the same value. The implemented
tracker recomputes the 40-state filter; no one-bit runtime speed claim is made.

## Representation, learned binding, control, and execution remain distinct

The grouped compression proof and its original-world confirmation concern the
same 40-state addressed owner. The content experiment independently learns a
linear mapping between two synthetic key views before testing unseen keys.
Its strongest ordinary retrieval baseline is retained. That front end has not
been joined to the HX-versus-ordinary 2x2 experiment.

The reset experiment is a declared fully observed finite maintenance MDP. Its
RESET changes the actual owner state; R15 REFRESH remains an observation. The
finite dynamic program is optimal for that finite action/time/state contract.
It does not solve the continuous free-boundary control problem.

The PDE experiment is a fixed absorbing/reflecting, constant-coefficient
diffusion reference. The Q24 experiment is a four-address finite filter with
integer mass, structural support, explicit error bounds, and trusted-snapshot
restart. Neither establishes the original complete HX PDE, authorized owner
crash recovery, anti-rollback, network availability, or deployment energy.

The final report keeps the acceptance decision for each of these scopes
separate. A passing auxiliary check cannot replace the registered D-B gate.
