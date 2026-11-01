# R15 independent scientific design review

This review fixes the interpretation of the addressed decision experiment before
confirmation. It is a finite synthetic tracking and memory experiment. It does
not establish learned semantic addressing, a continuum He--Xiong spiking
network, or production readiness.

## Task and information boundary

Four typed addresses route observations to four persistent content slots. Each
source has ten physical phases and four content classes. The 40-state joint
generator is a declared symmetric extension of the earlier finite CTMC. The
financial model parameterizes that generator; financial default does not by
itself imply the regeneration or content transition used here.

At the starts of queries 2 and 4 (zero-based), an exogenous public WRITE replaces
one source's content while preserving its physical phase. Every query start
also contains a separately typed DISTRACTOR that changes no source. These tags
are supplied by the task: ignoring a tagged distractor is not evidence of
learned semantic interference resistance. A preceding query's deadline score
and observation occur before a next-query WRITE at the same timestamp.

Each episode has six queries: a permutation of all four addresses followed by
two repeated addresses. Exogenous deadlines fix both the target address and the
absolute time at which its true content is scored. A STOP submitted early is a
forecast of that deadline, not a prediction of an easier, action-dependent
target. All methods share the same complete, hidden world trajectories.

The environment generates its CTMC jump paths independently of the policy.
Only the environment and scorer may inspect hidden phases, true content, jump
times, or the target. Model-facing data contain typed writes, observations,
observation quality, elapsed time, and the public query schedule and costs.
Training likelihood may use the public initial WRITE but not latent labels or
the true generator as candidate initialization.

## READ, REFRESH, WAIT, and STOP

READ takes one stage and produces a noisy content observation on completion.
Active states have correct-symbol probability 0.70 and each other symbol 0.10;
recovery produces an explicit erasure. REFRESH takes two stages and produces a
new observation with correct-symbol probability 0.97 and each other symbol
0.01, including during recovery. REFRESH is paid external evidence acquisition;
it neither repairs the source nor sets the belief to hidden truth. WAIT takes
one stage and supplies no observation. STOP commits the current prediction.

Every elapsed interval advances all four sources and all four retained beliefs.
Only the addressed source receives an observation update. Unqueried memory is
therefore allowed to become stale. A shared front end routes addresses and
observations but must not solve the full HMM posterior for every candidate.

An internal information-free RESET is not an implemented information source.
Deleting or reinitializing agent state cannot improve ideal Bayes-optimal
information. If a restricted learned implementation benefits from resetting,
that would be recovery from its own approximation, not creation of evidence.
No claim about beneficial internal reset follows from this REFRESH experiment.
External physical repair would require a separately declared world transition,
time, price, and content-preservation rule; it is outside this protocol.

## What the control comparison identifies

The primary 2-by-2 contrasts ordinary versus analytic estimation under fixed
and shared task-value control. The same public action set, costs, query target,
and finite-horizon planner are used. The exact same-matrix HMM is a mandatory
reference: matching its outputs is a correctness result, not an HX-exclusive
effect. The free CTMC family supplies a further strong ordinary alternative.

The planner optimizes the current query's remaining finite deadline. It is not
claimed to optimize total utility over all six future queries: present
observations can help later repeated-address queries, and that continuation is
not necessarily included in the planner's objective. All actual later outcomes
are nevertheless included in episode evaluation.

Capacity, model family, parameterization, and calibration prior differences are
reported explicitly. Equal public data do not erase structural prior
differences. Public WRITE content is an initial observation, not a general
semantic encoder. Known typed addressing is an admitted front end in this task.

## Independent invariants and counterexamples

The audit uses a separate Poisson-uniformization series and an ODE occupation
integral to check the production matrix exponential, first-event probability,
and expected count. A killed generator removes only the marked natural
absorption transitions while retaining their diagonal killing rate. Expected
counts include events after recovery and may exceed one; first-event
probability cannot exceed one.

A constructed pair of joint beliefs has equal phase and content marginals but
different phase--content dependence. Its observation-conditioned predictions
and value of observing differ. This demonstrates that marginal means are not a
sufficient state in general. It is a mathematical unit witness, not evidence
that such histories are common in confirmation or that the analytic model
outperforms a full HMM.

World trajectories must remain unchanged by observation order, repeated
observation requests, model reinitialization, or checkpoint restoration. An
observation must be timestamped at action completion. No observation is
available during WAIT. Checkpoint replay must restore all address states,
absolute time, and any model state needed for identical subsequent behavior.

A REFRESH price greater than the entire possible current-query reward makes
REFRESH dominated for this planner. Selection despite that price is a control
bug, not a benefit of a regenerative mechanism.

## Cost and claim limits

Report chosen-action fees and elapsed task time separately from measured CPU,
wall time, matrix construction, calibration, failed evaluations, candidate
selection, and control work. The cost of all considered actions counts toward
implementation cost even when only one action is executed. Distinguish cold
costs from explicitly amortized reuse scenarios.

The independent confirmatory unit is the declared fit seed, not every query or
episode treated as independent evidence for a fitted model. Development
witnesses and structural tests do not tune confirmation thresholds. A zero or
negative D-minus-B and exact HX/HMM equivalence are admissible scientific
outcomes. This finite CPU experiment cannot establish native Rust cost,
distributed communication, GPU energy, biological realism, or open-domain
language memory.
