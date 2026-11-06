# Next-candidate clock semantics: an objective guard, no algorithm promotion

**Decision: reject risk-parameter transport alone as a new algorithm candidate.**
It is needed when the declared objective is the certainty equivalent of the
time-zero discounted physical payoff. It then agrees with the correctly matched
classical trajectory-CE planner. The historical fixed-node local-risk objective
remains a different, explicitly retained contract.

## Actual deterministic audit

The local source freeze precedes the grid execution and discloses that the
analytic counterexample was already known. The grid varies eta in {.5,1,2},
one-tick discount in {.5,.8,1}, success probability in {.1,.5,.9}, and duration
in {1,2,3}; all 81 cells are retained. These are constructed finite models, not
random confirmation trials, empirical latency estimates, or independent tasks.

| Gate | Recorded outcome |
| --- | --- |
| Same physical payoff/completion-time law under forced-wait subdivision | All 81 cells |
| Fixed local eta changes the chosen root action after subdivision | 2 / 81 cells |
| Transported eta changes the probe value under subdivision | 0 / 81 within declared 1e-95 Decimal tolerance |
| Transported planner differs in value/action from independent full-policy terminal evaluation | 0 / 162 graph encodings |
| Deterministic numerical/contract checks | 518 passed |
| Separate internal review using old JAC and independent closed forms | 266 checks passed; both flips reproduced |
| Calibration observations, model forwards, actual task-tool calls | 0 |
| Independent task or new-RL gate | Not passed |

The representative eta=2, gamma=.5 example pays .01 to query, then receives 0
or 1 at time 1 with equal probability; STOP gives .16 at time 0. Its physical
discounted payoff law is {(-.01,.5),(.49,.5)} in both encodings.

- Coarse fixed-local probe value: **.17994274652086124**; choose probe.
- Refined fixed-local probe value: **.1315547923792432**; choose STOP.
- Transported risk and the classical trajectory baseline: **.17994274652086124**
  in both encodings; both choose probe.
- Paid headroom above STOP: **.01994274652086124**.
- Headroom above the matched strong planner: **0**.

Positive headroom against STOP alone therefore does not qualify this ingredient
for a new independent-task experiment. No new scientific superiority is inferred
from preserving a physical objective under a graph representation change.

## Meaning and limitations

`THEORY.md` proves the entropic scaling identity, necessity of eta_(t+d)=eta_t
exp(-rho*d) for this no-information wait invariance, and the finite-history
trajectory recursion. It separately explains action randomization: taking a
mixture outside CE is not the same as evaluating the mixture's trajectory CE.
It also maps direct prior results and their different objectives/access models.

The original `ndu_jac/core.py` defines fixed local risk at supplied event nodes;
this audit does not label its documented objective an implementation error or
rewrite its old scores. To retain that preference in a physical application,
the primitive events at which risk is reset must be fixed independently of
administrative graph subdivisions. To use trajectory risk, both candidate and
baseline must use the same transported-risk or equivalent augmented-state
formulation. Randomized constrained/minimax policies are a separate problem;
the earlier deadline LP results are not changed here.

The independent strong comparator enumerates deterministic policies and their
complete terminal payoff law, rather than using the candidate's Bellman values.
The small audit trees have one elapsed time per named state; a general merged
state graph must include time/history when needed. The random-duration fixture
also conditions subsequent observation laws on the observed duration.
The small enumerator does not automatically validate that unique-clock
precondition for arbitrary supplied graphs. The trajectory Bellman proof also
requires observed transition cash flows/duration or corresponding conditional
sufficiency; unobserved past payments correlated with future payoff require an
appropriate augmented information state. These restrictions are satisfied by
the registered fixtures and are made explicit in `THEORY.md`.

Numerical checks use 110-digit ordinary Decimal arithmetic, not formally
outward-rounded intervals. The equality theorem is mathematical; the reported
1e-95 agreement is internal numerical verification. Source hashes, protocol,
freeze and measured solver wall/CPU time are recorded in
`evidence/run-01/result.json`. The solver timing is not a task latency or a
priced host invoice. There is no model call, learned kernel, new sample, trained
actor, or full-cost actual-tool result.

The independent internal review is preserved in `review/`, together with the
pre-clarification theory text. It calls the retained JAC implementation on
handwritten graphs and uses independent closed forms for all 81 cells. Its
source and evidence remain historical records with their original local paths.
The review is not an external mathematical audit. No primary grid cell was
added or rerun for this review.

## Reproduction

From the repository root, with Python 3.12's standard library:

```bash
python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.ndu_clock_semantics_20261106.study --output /tmp/ndu-clock-semantics-new
```

The output directory must not exist. The runner refuses changed frozen source
and never overwrites earlier evidence. All proof and old/new-objective scope
limitations are part of the result, not optional alternative scoring rules.
The safe-reward and launch-fee protocol fields equal the graph builder's frozen
defaults; changing them requires updating the invocation and freezing a new
source version. This package is an audit of the registered contract, not a
general-purpose configurable planning library.
