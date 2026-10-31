# Finite evidence task and independent oracle

This is a controlled research task, not a production Hepta integration or a
continuous QVI solution. It isolates state, observation, action, budget and
terminal-utility semantics so that learned cells and controllers can be compared.

## Public API

```python
from experiments.analytic_event_neuron.round7 import task, oracle
episode = task.generate_episode(123, horizon=6, budget=6)
state = task.initial_state(episode)
x = task.features(state)                 # 18 float64 public features
available = task.legal_actions(state)    # tuple of action names
q_star = oracle.action_values(state)    # each first action, then optimal policy
q_one = oracle.myopic_action_values(state)  # each first action, then STOP
result = task.step(state, "WAIT", episode)
state = result.state
```

`ACTIONS` is `("READ", "WAIT", "REPAIR", "STOP")`; `step` also accepts their
integer indices. `StepResult` contains `state`, `reward`, `cost`, `done`, and an
auditable `info` mapping. `State.to_dict()`/`State.from_dict()` round-trip through
JSON. `State.digest()` identifies the complete public prefix state. `Episode`
contains private truth and future source outcomes and must never enter a policy,
encoder, critic or public feature record. `private_record()` is explicitly for
raw experimental evidence.

## Generative model and observations

The hidden fact is `H in {-1,+1}`, with prior one half by default. There are three
ordinary votes, each correct with probability 0.7 conditional on H. One delayed
vote, correct with probability 0.9, arrives at tick 2 and is independently
corrupted with probability 0.35. A damaged vote remains hidden until repaired.
All randomness is fixed by seed and semantic source identifiers before execution;
branching and repair do not advance a mutable RNG or redraw evidence.

Every READ uses the next distinct ordinary source. Every nonterminal action
advances the same arrival clock. WAIT polls the delayed source, but READ can also
receive an arriving source. REPAIR restores the original delayed vote. Repeating
REPAIR after recovery supplies no new observation and is rejected by the guard.
Observations are independent **conditional on H**, not marginally independent;
the independent oracle mixes their joint likelihood over the current posterior.

## Actions, deadline and costs

All four actions occupy one tick. STOP is available initially and fixes its
answer using the posterior before submission; it cannot use a source arriving
during submission. Every non-STOP action must leave a final tick for STOP. An
unavailable requested action executes STOP and additionally pays the failed
attempt cost; the trace records both requested and executed actions.

Default deadline is 6 ticks, and the initial query budget is 6 credits. READ uses
2 credits and REPAIR uses 1; WAIT and STOP use none. Default action costs are
READ 0.012, WAIT 0.004, REPAIR 0.020 and STOP 0.002. Each tick also costs 0.005.
An invalid attempt additionally costs 0.030. Query credits are a feasibility
constraint; they are not charged a second time as utility costs.

STOP receives +1 for a correct answer and -1 for an incorrect answer. Each step
subtracts its own complete modeled cost. Sum step rewards to get episode utility;
do not subtract `State.total_cost` again. Physical execution, observation parsing,
training and controller compute costs are separate measured quantities and must
be included by the study's explicit costing/amortization rule.

## Exact finite-state reference

`oracle.py` independently enumerates future observation distributions and the
guard; it never calls `task.step` or reads an Episode. Q* uses an optimal public-
state continuation. Q1 executes the candidate action and then immediately STOPs.
Both use the same budget, deadline, terminal objective and modeled costs. Returned
values are **future** values: sunk prefix costs cancel in action comparisons.
The DP cache therefore excludes sunk costs and the already committed answer.
Terminal future values are zero; terminal states are excluded from training.

The four requested-action values include invalid actions' real STOP fallback
costs for audits. Training and action selection must mask unavailable actions.
No label is a pathwise clairvoyant optimum. A learned policy's conditional Qπ
must be measured separately; Q* teacher labels are not Qπ labels.

`conditional_episode(state, seed, prefix_episode=None)` samples H from the public
posterior and samples unseen evidence conditional on H. Passing the original
prefix Episode preserves only already observed source values/order and known
corruption; its actual H and unseen votes are ignored. Without it, a canonical
ordering of already observed ordinary votes preserves the sufficient statistic.
Use this sampler for conditional Qπ ensembles. Use the original Episode for
paired **realized** branches. These answer different questions.

## Information equality and scope

`FEATURE_NAMES` declares the common 18-dimensional policy input, including
posterior, remaining clock/budget, source availability, reliability, corruption
probability, action credits and all modeled action/attempt costs. Time and budget
are scaled by fixed constants, not by episode-dependent totals that could hide
their absolute values. Varying these exposed task parameters is supported.

The state is sufficient for this specific finite observation model. This does
not establish sufficiency of a learned Hepta field, open-domain reasoning state,
or arbitrary history-dependent observation process. Corruption is independent of
truth, so waiting without an arrival and learning that a source is corrupt do
not change the posterior. Source recovery supplies information, not a direct
reward bonus. Near-tied optimal actions must be evaluated by value regret and
realized utility, not only by top-1 action accuracy.

Validation: `python -m unittest
experiments.analytic_event_neuron.round7.test_task_oracle` from the repository
root exhaustively compares exact DP labels with all latent outcomes in several
parameter domains, checks simultaneous arrivals, budget/deadline handling,
source-preserving recovery, prefix serialization and conditional resampling.

## Artifact-backed subprocess integration

`broker.BrokerClient(artifact_root)` starts an independent JSONL worker. `start`
accepts the seed and public TaskParameters; only its public state is given to a
policy. `step(action)` returns a public StepResult. The worker owns the Episode,
writes fixed-size source files, performs actual source reads and recovery, and
writes `output.json` when STOP completes. Server and client independently read
back the output, hash its bytes, and check the returned score/answer record.

Unobserved source digests, varying payload lengths and private votes are not
returned by setup. An IO/readback failure invalidates that session, records work
already incurred, and cannot be silently retried. An unavailable task action is
different: it follows the declared STOP fallback and attempt charge.

This is an artifact-backed evidence task, not repair of external program code,
an OS sandbox against arbitrary client code, or production Hepta activation.
The integration wrapper must pass only public state/features to its policy and
retain setup, source IO, subprocess roundtrip and output receipts. Worker/source
timers are nested inside client roundtrip time; do not add them twice.
