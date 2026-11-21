# Own-law policy capsule v1

Schema: `hepta-own-law-policy-capsule-v1`. The checkpoint is an original frozen
renewal model; the law consists only of its stored 33 x 33 transition tables,
fixed coordinates and original decoder confusion. This artifact is a compiled
inference program, not a 4324-coordinate network weight edit.

Top-level fields (no optional interpretation of required state fields):

```
schema: string
bindings: {compressed_sha256, decoded_sha256, task_code_sha256,
           planning_code_sha256, compiler_code_sha256, public_sha256}
public: exact joint-current-at-due-fixed-deadline-v1 public object
public_key: Python canonical JSON of public, bound by public_sha256
initial: integer state index
states: [complete nonterminal source-task state]
state_keys: [Python canonical JSON of each complete state]
legal_masks: [[bool;6]]
posterior: [own-law P(sign(X6)>0 | available history)]
edges: [[[edge];6]]
q_values: [[finite f64;6]]
actions: [integer 0..5]
order: [state indices in nondecreasing tick, stable insertion tie order]
policy_reachable: [indices reachable from initial following selected action,
                   sorted ascending, including structural zero-probability outcomes]
```

Each edge is `{probability:f64,target:usize,fee:f64,completion:{kind,
observation_tick,observation}}`. `kind` is `none`, `failure` or `observation`.
For `none`, both other completion fields are null. Failure has the due tick
and null observation. Observation has due tick and observation 0 or 1.
Edges for actions 0,4,5 and illegal actions are empty. Continuing actions 1,2,3
have either one none edge or three edges in order failure, observation0,
observation1. Zero-probability edges remain present. `fee` is the exact source
task f64 subtraction `after.charges-before.charges`, including its roundoff.

Action order is STOP, WAIT, READ, REPAIR, SUBMIT_0, SUBMIT_1. Nonterminal state
contains tick,budget,pending,broken,last_symbol,last_reliability,history,
elapsed,charges,terminal,submitted. Pending is null or {source_tick,due_tick}.
Each history record has source_tick,observation_tick,observation,reliability.
All exact field semantics and validation come from the bound joint_task.py.

Bounds: at most4096 states; six actions; at most3 edges/action; ticks0..6;
initial budget3; history length at most3. Unknown states/completions,
mismatched public schedule/checkpoint/task, nonfinite values, duplicate state
keys, invalid masks and inconsistent complete-state transitions fail closed.
The reader verifies the hashes of public_key and the typed exact equality of
its unique-key JSON object to public. It validates each state_key similarly;
JSON number formatting is not assumed identical across Python and Rust.
Terminal actions produce a source-task complete terminal state with pending
cleared and submitted=null/0/1; no further step is allowed. REPAIR changes the
sensor status only. Public schedules contain no opened packet contents.

The native reader must derive the posterior and probabilities independently
from authenticated stored-law bytes, compare at2e-11 absolute tolerance, then
recompute Bellman using the provided original-order edges with explicit f64
`total += probability * (value[target]-fee)` only when probability is nonzero.
Terminal scores are [0,0,0,0,1-2p,2p-1] with illegal scores masked. Ties select
the lowest action index. Caller-provided q_values/actions are witnesses to
check, never authority. q_values contains zero for illegal continuation scores.

Full Q evidence is retained for verification. The executable policy automaton
retains only policy_reachable states and each state's selected-action outcome
edges; it contains every possible selected-policy observation path. Runtime
choice and step must validate complete state; no observationally incomplete
Markov key is accepted as the whole owner state. Sparse execution preserves
every selected action, final expected value and terminal state of dense
execution. Preparation, validation, serialization and online costs are distinct.

Preregistered science includes only this exact own-law decision candidate.
Dense/sparse variants are equivalent execution ablations, not distinct learned
models. C/D/T/K bytes are preexisting fixed references. No fresh training or
weight optimization is performed in this protocol.
