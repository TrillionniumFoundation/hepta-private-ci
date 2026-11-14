# CTRL-1: decision and coordination Cell research pilot

CTRL-1 measures how much value a bounded decision controller loses relative to
an exhaustive small POMDP / semi-Markov reference. It allocates task actions,
observations, memory lookup, verification, repair and paid planning. This package
is an executable research adapter. It does not update a native Cell, change a
production objective, grant authority, or establish real-task improvement.

## Fixed semantics and source

The contract anchor is
[`utility.ndu` at `732e934b`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/docs/modules/utility.ndu/TECHNICAL.md).
The implementation parent is PR #5336 head
`9c6c18cec8c56260d633de5a6adf321de2a4e3d4`. Its existing
`ndu_real_runtime/objective.py` supplies `hepta.ndu.finite-entropic.v1` unchanged.
The new, explicit adapter is `hepta.ctrl1.resource-cost.v1`:

```text
edge(T, U) = -latency_weight * T + discount_per_second ** T * U
Q(s,a) = CE_risk(-resource_weight * C + edge(T, continuation))
CE_0(X) = E[X]
CE_risk(X) = -log(E[exp(-risk*X)]) / risk       (risk > 0)
V*(s) = max over legal actions of Q(s,a)
```

Each joint outcome receives its own resource charge, duration and continuation
before the certainty equivalent is calculated. The operator is nested at public
observation boundaries; it is not a single flattened terminal lottery. The
resource charge is immediate, outside temporal discount and inside the edge CE.
Seconds and simulated resource credits have distinct meanings and units.

The original Q32 path evaluator remains a different numeric profile: clipped
backward recursion with signed nearest/ties-to-even multiplication. Tests match
its pinned integer golden fixture using an independent Python reference, and
also read the parent's shared finite-entropic golden vectors. These are source
fixture checks, not a new execution of the Rust binary or a stochastic FBSDE
qualification. The helper's profile and this adapter are both explicit and
validated; EFE, entropy bonuses and novelty are not substituted for NDU.

## Environment, oracle and safety of the comparison

The hidden bit represents whether execution will succeed. Public state contains
an exact rational belief, remaining seconds, remaining credits, remaining action
steps and consumed observation/repair flags. Six task actions have real kernels:
`stop`, `execute`, `observe`, `recall`, `verify`, `repair`.

Sensors return a noisy label together with observable duration and cost. Bayes
conditioning uses all three; their supports overlap, so elapsed time does not
perfectly reveal the hidden bit. Repair changes success probability but does not
reveal its realization. The independent environment kernel supplies terminal
payoffs in [0,1]. All methods have the same known public transition model; this
is not a model-free benchmark or evidence of learned distribution calibration.

Admission checks every positive-probability outcome against time and resource
limits. STOP is always available. Fractions keep probabilities and posteriors
exact. The oracle exhausts reachable belief states with a 20,000-state cap;
small independent contingent-policy-tree enumeration checks the Bellman result.
Combinatorial search is exhaustive; FP64 logarithms/exponentials are numerical
approximations, not a formal proof over real numbers.

The theoretical oracle has no online controller overhead and is reported as an
upper bound. Its offline solving work is measured separately. No controller sees
the sampled hidden state or obtains oracle policy labels during ordinary AC
training. Public training states are shared; oracle construction of that shared
roster is recorded separately from each learner.

## Controllers and accounting

| Controller | Frozen behavior |
| --- | --- |
| Fixed | Execute at public belief >= 0.75 if legal; otherwise STOP. |
| Fitted actor-critic | Linear softmax actor and bounded linear critic; deterministic legal argmax at deployment. |
| VOI | At most one information acquisition, followed by charged terminal choice. |
| MPC | Iterative depth 1/2/3 joint-kernel planning; at most 96 action forecasts. |
| Mean MPC | Same information and search allowance; collapse cost, duration and continuation to their means inside the forecast only. |
| Fast/slow hybrid | Frozen uncertainty router over the learned actor and bounded joint planner. |
| Learned router | Predict the downstream NDU advantage of paid planning over the frozen fast reference; request slow computation only for positive predicted advantage. |
| Distilled candidate | Same actor architecture trained on every bounded teacher label, including fallback/no-improvement cases. |
| Selected fast | Candidate only after the frozen development gain/cost gate; otherwise the original fast policy. |

The mean-MPC contrast holds the complete known public kernel fixed, including
all posterior branches and hard-budget checks, and changes the forecast backup.
It therefore tests a mean approximation of a known joint model. It does not
compare a learned mean predictor with a learned, calibrated joint predictor.

Every non-emergency decision pays one simulated credit. A slow invocation
prepays a fixed, nonrefundable three further credits and one simulated second.
This is an invocation price, not a claim that every reserved operation was used.
Actual node expansions, mask calls, CPU and wall time are retained separately.
The same `compute_charge` function supplies forecast and runtime charges.
Future decisions and truncated STOP boundaries pay their declared charges.
Exhausted steps or a budget below one credit permit a predetermined free STOP.
Incomplete deeper searches can use only a previous fully compared root depth.

Training uses frozen-critic action values and the explicitly declared
`sum(pi * frozen_Q)` policy-improvement surrogate. It is not an unbiased gradient
through a whole risk-sensitive environment trajectory. Parameter updates live in
the isolated learning adapter; the utility operator only supplies values.
Known STOP boundaries cannot be replaced by an unconstrained critic prediction.

AC and distillation share public training instances, initial actor seed, actor
architecture, state order and update allowance. Teacher and critic work differ;
their inclusive costs are reported, so equal epochs are not presented as equal
total consumption. No model is selected on confirmation results. Development
evidence must bind identical profile hashes, resource units and scenario IDs.
Missing, nonfinite, unpaired or non-improving evidence yields `NoUpdate`.

The learned router uses paired environment evaluation of all-fast behavior and
one paid MPC call followed by that same fast reference. Every positive, negative
and zero advantage remains in its training record. Its target is one-step
improvement against a frozen continuation; repeated routing at deployment is
evaluated separately on the full environment tree. Neither uncertainty nor
entropy is used as a replacement reward. The extra router-training computation
is retained and is not presented as free training shared by the other methods.

## Frozen experiment and reproduction

The main pilot uses three independent training seeds, four explicit utility
profiles, four train instances, four development instances and eight held-out
synthetic confirmation instances per profile. The confirmation set changes
priors, sensor accuracy, repair success and outcome correlation. Fixed/variable
duration, risk 0/0.25 and zero/positive explicit latency/resource prices are
separate factors. Removing explicit prices does not remove temporal discount or
hard budgets. There are 864 policy comparisons and 13,824 sampled executions.

At the confirmation priors of 1/3 and 2/3, reversing outcome correlation also
changes the marginal time/cost distribution. Those rows measure a joint
distribution shift; they cannot isolate a pure correlation effect. A separate
prior-1/2 regression preserves the marginals and changes only the coupling.

The CPU-allowance sensitivity has 72 isolated POSIX workers: four profiles,
three seeds, two learners and common 1/2/4-second worker CPU limits. Each latest
complete checkpoint has eight confirmation rows, yielding 576 retained rows
including unavailable candidates. Teacher preparation, fitting and checkpoint
serialization count toward worker CPU; shared roster construction, parent
supervision and evaluation have separate scopes. The last complete epoch is
used without selecting on development or confirmation performance. Equal CPU
allowances do not imply equal consumed CPU, and neither equals complete physical
cost or energy. Abnormal exits remain visible and do not silently become
successful budget-limited candidates.

```sh
PYTHONPATH=scripts python3 -m unittest discover \
  -s scripts/ndu_ctrl1 -t scripts -p 'test_ctrl1_*.py' -v
PYTHONPATH=scripts python3 -m ndu_ctrl1.run --output /path/to/absent/ctrl1-run
PYTHONPATH=scripts python3 -m ndu_ctrl1.verify /path/to/absent/ctrl1-run
PYTHONPATH=scripts python3 -m ndu_ctrl1.sensitivity_run \
  --output /path/to/absent/ctrl1-cpu-sensitivity
```

The output directory must not already exist. `PLAN.json` binds source hashes,
profiles, training/test split, seeds, budgets and the complete roster before
training starts. Checkpoints, complete teacher-label inventories, development
selection evidence, exact evaluation rows, compressed original trajectories and
Started/Completed/Failed attempts are retained. `ARTIFACTS.json` binds every file.
The verifier checks original denominators, hashes, checkpoint identities and
budget reconciliation. `--historical-source` only disables the current-source
equality check; it never relabels an old run as execution of new code.

`policy_gap` is the same-profile oracle value minus actual charged policy value.
`net_terminal_utility` separately reports the undiscounted expected terminal
payoff minus declared costs. `stop_regret` is occupancy-weighted regret after
computation; `compute_and_stop_regret` also includes the computation that led to
STOP. Continuation regret identifies continuing when the oracle would stop.
Risk-sensitive nested CE is evaluated from the true tree; an average sampled
path return is not mislabeled as that CE. Repeated episodes are not independent
training replicates. CPU and wall measurements are scoped; nested timers must
not be added. Energy and monetary charges remain unknown.

## Research basis and remaining acceptance

[Sousa et al., Nature 2025](https://pubmed.ncbi.nlm.nih.gov/40468078/) motivate
joint reward-magnitude/time representations; adding cost is an engineering
extension in CTRL-1.
[Lowet et al., Nature 2025](https://pubmed.ncbi.nlm.nih.gov/39972123/) report
preferential right/left reward-tail encoding in D1/D2 striatal populations.
That biological evidence motivates distributional representations; it does not
establish a software controller's risk calibration or performance advantage.
[Mills et al., 2025](https://escholarship.org/uc/item/8f52z7hx) provide a one-page
conference abstract on learned and online metareasoning, not a complete
reproducible distillation algorithm.
[Nuijten et al., UAI 2026](https://proceedings.mlr.press/v337/nuijten26a.html)
distinguish inference-based planning objectives; an EFE comparison must retain
its own semantics and would still be evaluated on the common task outcomes.

Correctness, a complete small-environment run and an accepted research candidate
do not establish improvement on documents, tools or GUIs. Independent external
outcomes, full physical-cost accounting, native owner integration and real-task
adoption/recovery remain separate gates. A failed or ineffective controller is
an experimental result and remains in the denominator.
