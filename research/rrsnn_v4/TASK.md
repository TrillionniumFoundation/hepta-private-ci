# RR-SNN v4: identified communication and future-query task

This is a distinct synthetic task and candidate contract. It retains the v2
four-item maturity/value problem and common 22-dimensional observation / 81-action
interface, but replaces the free terminal reward for an untransmitted live memory
with actual identified communication, deterministic delivery, and an independent
terminal query. It does not overwrite the v2 task or the v3 likelihood diagnostic.

## State and causal information

Each episode begins with four padded item slots, public nonnegative values
`v_i`, absolute deadlines, an integer task budget, and announced shock/refill
amounts and times. The main generator activates all four slots. The strict
two-item A/B fixture activates only slots 0 and 1.

The horizon is 4, renewal extends a deadline by 2, communication latency is 0.1,
and early delivery quality uses coefficient 0.15. Each item is independently
queried with fixed public probability 0.75. Query realizations are drawn by the
observer **after** the last policy call. They are absent from scenario features,
oracle inputs, training labels, and policy callbacks.

All mechanisms receive exactly the same observations:

| Indices | Information |
| --- | --- |
| 0–3 | Initial expected query values `0.75*v_i`; zero after the initial cue |
| 4 | Current task budget / 6 |
| 5–6 | Live fraction and mean remaining deadline / 4 |
| 7–10 | Complete per-item remaining deadline / 4, zero for absent items |
| 11–14 | Complete per-item live mask |
| 15–18 | Initial announced shock/refill amounts and times; zero afterward |
| 19 | Current time / 4 |
| 20 | Initial-cue flag |
| 21 | Common renewal and communication cost / 6 |

Fixed public query probability makes the initial expected-value cue sufficient
for the risk-neutral expected-utility oracle. No model gets an additional query
forecast. Raw maturity observations remain complete in every ablation; any
compression or permutation happens inside that model's designated branch.

## Events, actions and fees

Time zero is cue-only, with elapsed time zero and only the no-op action. The first
decision is at 0.25. Public observations also include 0.5, 1, 1.5, 2, 2.5, 3, 3.5,
3.75, the terminal time 4, every possible initial/renewed maturity before 4, and
the announced resource event times. The padded observation cap is 32.

At a public timestamp, pending deliveries are processed first, then the budget
shock (clipped by available budget), then refill, then the observation and task
action. A positive communication delay prevents same-time delivery feedback.
The terminal time permits no new action.

An action is four base-three digits, giving 81 common candidate actions:

- **0:** wait if the item is not due; drop it if it is due.
- **1:** renew a due live item for two time units, spending one task budget unit.
- **2:** communicate any live item, spending one task budget unit, removing its
  memory obligation immediately, and creating one identified output pulse.

All mechanisms use the same exact legality mask. Renewal of a non-due item,
output of an absent item, budget overdraft, and an output arriving after the
query are illegal. Simultaneous per-item actions settle jointly against the
shared task budget. A task action cannot output an item twice.

The pulse carries `pulse_id=item:i`, item identity, emission time, arrival time
and quality. `OutputPulseQueue` advances actual timestamped delivery records,
including outputs pending between observations. A complete queue checkpoint
binds the scenario and validates the delivered/pending partition. Identical
delivery receipt replay is idempotent; a conflicting duplicate is rejected.
This bounded reference checkpoint is not a production authorization mechanism.

## Utility and oracle

For item i emitted at time t and delivered by 4, terminal query bit Q_i gives

`realized reward = Q_i * v_i * exp[-0.15*(4-t)]`.

An unsent memory has zero terminal task reward, whether it is live or expired.
Every feasible positive-value output has positive expected reward, so the
zero-output strategy is not universally optimal. Renewal can still be useful:
it allows a valuable item to be transmitted later at better quality, but uses
budget that could have served another item or survived a resource shock.

The exact finite oracle maximizes expected delivered utility. Since delivery
is deterministic and late outputs are excluded, it can algebraically credit
`0.75*v_i*quality` at the emission action without observing future query bits.
Its state is `(public event index, live mask, budget before resource events)`;
deadline progression follows the deterministic renewal schedule.

Reported expected normalized utility is `expected utility / expected oracle`.
Zero-oracle episodes use normalized value 1 and have zero raw expected regret.
Actual query utility is separately reported in original value units. A realized
reward can exceed the expected oracle on one draw; it must not be incorrectly
treated as an invariant violation. Models share observer query seeds for paired
evaluation, with those seeds withheld from every policy.

`validate_task.py` independently codes a second DP with explicit absolute
deadlines and separate action enumeration. It checks the environment DP and
forward optimal-policy execution on 20 development cases, including shifted
maturities, coincident shock/refill, and zero budgets. Development RNG starts
at 901000; no train, validation or test dataset is generated by this validator.

## Neural events and resource interpretation

Identified task communication outputs are shared semantic actions. They are
charged identically for RR, LIF, ALIF, resource LIF and continuous-time RNN
controllers. Internal latent spikes and continuous hidden-state updates are
recorded and their CPU, memory and latency costs measured separately. This
experiment does not assert a physical energy conversion between one continuous
update and one spike, and it is not the same single resource ledger as v3.

The task's delivered output pulses have information value. Latent SNN spikes
affect decisions through each model's declared readout. This is an event-driven
operator/decision comparison, not a claim that every latent neuron spike directly
transmits one memory item or that arbitrary continuous output times were learned.

## API and reproducibility

- `Scenario`, `Oracle.demonstration()` and `make_scenario()` preserve the prior
  data interface while implementing the new contract.
- `make_dataset(count, seed, split)` returns scenarios plus `x`, `dt`, `valid`,
  `optimal`, `decision`, `lengths` and `event_mask` arrays.
- `rollout(scenario, policy, query_seed=...)` passes only observation history,
  elapsed intervals and the current legality mask to the policy.
- `OutputPulseQueue.snapshot()/restore()` supports bounded delivery replay.
- `python -m rrsnn_v4.validate_task` writes the development validation evidence.

All results are synthetic. A separate distribution shift is not a real future
Hepta window, and the task's four item slots are not Hepta Cells.
