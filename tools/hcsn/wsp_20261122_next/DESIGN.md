# Value-sensitive weight interventions — frozen design candidate

Namespace: `hepta-value-sensitive-program-20261122/v1`.

## Question and permitted information

The previous shared-head hinge target converged without improving task value.
This experiment tests whether replacing that proxy with actual finite own-law
value supports a useful, radius-constrained common head. It distinguishes an
objective defect from a solver defect and measures continuation/terminal
interventions. It does not assume that an action-level regret identifies the
responsible parameter or that the representation is already sufficient.

Both algorithms receive the same original model, the same 32 old GEN worlds per
checkpoint, complete graph transitions, true own-law terminal payoffs/posterior,
and hidden features. These are explicit simulator/oracle privileges, not market
labels. No old SELECT/AUDIT or previous 80 confirmation outcomes are used to
construct or tune the new candidate family. Prior schedule fingerprints are used
only to prohibit collisions. The five checkpoint identities remain 11,23,37,53,71.

## Exactly matched nonlinear objective and legal parameter domain

For both methods the objective is the equal-world complete soft-policy value
`mean_w J_tau(theta,w) - 0.001 ||theta-theta0||^2/(2 R^2)` with `tau=0.1`.
The stochastic policy is softmax over the original six legal scores, including
the sigmoid-coupled Call/Put terminal scores. True reward and all graph fees are
included. Reverse DP computes Q_pi and V_pi; forward DP computes the current
candidate's occupancy. There is no detached, fixed occupancy approximation.

The editable set is the original joint 196-coordinate head. All frontend and
physical parameters remain original. `R^2 = ||original Q147||^2/4`, checked using
exact binary64 rational arithmetic. Projection uses an inward 1e-12 factor;
every evaluated proposal must satisfy the original exact ball. No radius search.

## Direct EditProgram and gradient baseline

DIRECT uses no parameter gradient. At each of eight rounds, rank all GEN states
by `current occupancy * (max legal Q_pi - V_pi)`, stable state-index tie order.
Take exactly eight states. For each state, compute the minimal-norm rank-one
head patch matching current Q_pi continuation values and the true own-law
posterior logit (posterior clipped to [1e-6,1-1e-6] for this proposal only).
Illegal continuation slots retain current predictions. Try doses 0.5 and 1.0,
project into the original ball, and accept the highest improving complete
objective with 1e-12 tie tolerance. This creates 128 proposal slots. Rejected
proposals and unchanged candidates still consume their slots and evaluations.

BP uses the exact derivative of that same complete stochastic-policy objective,
including occupancy and the nonlinear Belief-to-terminal-score derivative.
It performs 128 projected normalized gradient steps with initial relative step
0.25 R and schedule `0.25 R/sqrt(1+step/16)`. The best observed objective iterate
is retained, KEEP winning ties. No learning-rate or temperature pilot exists.

Each algorithm pays one initial evaluation plus 128 proposal evaluations.
BP requests the gradient on all 129 calls, including the last unused derivative;
DIRECT requests zero weight gradients. The shared representation/graph setup is
reported separately. Every score forward, reverse DP, occupancy DP, derivative,
rejected proposal, exact-radius check and data movement is within measured CPU.
Each family has a 20 CPU-second acceptance cap checked before and after each
call, inside an OS-bounded generation phase. A capped/failed family yields no
candidate and therefore KEEP for that family. No resumed or enlarged attempt.
These limits are matched caps, not a claim that actual costs are identical.

## Controls and attribution

After generation is sealed, DIRECT's full, half, opposite and four fixed-seed
random equal-norm directions are evaluated as diagnostic arms. Q-only and
Belief-only restorations isolate components. Diagnostics never enter selection.
For zero DIRECT delta these are explicit KEEP aliases. All encoded directions
must remain inside the original exact radius. Equal random norms are matched
within 1e-12 relative plus 1e-15 absolute tolerance and their actual norms reported.

GEN-only action interventions replace continuation scores with true Q-star,
terminal scores with true posterior, or both. Joint oracle must reproduce the
own-law optimum. These are counterfactual diagnostic policies, not deployable
weight edits. Frontend/head permutation checks recompute complete hidden and
readout scores; the upstream-only permutation is a broken-wiring negative control.

## New selection and confirmation

Only after all five candidate model hashes are sealed, draw one os.urandom(32)
seed for 16 IID SELECT worlds per checkpoint. No replacement after collision,
oversize graph, numeric failure or unfavorable utility. Reject a candidate if
mean hard-policy utility is not better than KEEP by more than 1e-8, or any SELECT
world loses more than 0.05 utility. This 0.05 is a declared study retention
threshold, not an estimated production risk preference. DIRECT/BP are selected
separately against KEEP. Failed fits/families return KEEP with their costs retained.

After candidate selection is sealed, draw one independent os.urandom(32) seed
for eight IID and eight OOD CONF worlds per checkpoint. Compare DIRECT-selected
minus KEEP, BP-selected minus KEEP, and DIRECT-selected minus BP-selected,
separately by domain. Report six Bonferroni-adjusted paired-t intervals targeting
familywise 95%, with checkpoint (n=5) as pairing unit. A scientific improvement
claim requires positive lower bounds against KEEP in both domains and the
declared retention check. Failure is NoUpdate; confirmation cannot trigger a retry.

Both new stages reject every collision with the historical 3,716 schedules,
the previous 80 confirmation schedules, and every earlier new stage schedule.
No future-market interpretation is permitted: all are fresh public schedules
under each stored checkpoint's own law.

## Qualification, identity, portability and cost

Synthetic mathematical admission uses an independently written trajectory
enumerator and central finite differences on all 196 head coordinates at two
temperatures. Value tolerance is 2e-13; derivative tolerance is
3e-8 + 5e-6*abs(FD). Budget/accounting refusal controls also execute. These tests
never load a real checkpoint or a quality world.

All source, dependency, primitive environment and input hashes are frozen before
GEN. A repository-relative input manifest maps immutable bytes to explicit
`--inputs` roots. Generated outputs preserve original input identities; relocating
bytes requires the same hash and the admitted numerical environment, not silent
protocol edits. An independent reader recomputes full hard policies, value,
occupancy and payoff/PDI identities from saved models and graph bytes.

Phase limits: GEN 240 soft / 250 hard CPU seconds and 500 wall seconds;
SELECT 120/130 CPU and 260 wall; CONF 120/130 CPU and 260 wall;
independent reader 180/190 CPU and 380 wall. One core, one BLAS thread, 2 GiB
address space, at most 20,000 full states per world. All attempts are create-only;
exceptions, partial records, rejected proposals and supervisor overhead are kept.
Historical cached graph/hidden preparation is reused and attributed explicitly.

No production adoption is part of this scientific run. A successful result must
still be connected to the independently qualified canonical runtime lifecycle.
