# Recurrent network joint replay profile

This separate profile binds the actual two-neuron delayed-network diagnostic.
It reuses the reference journal, witness, fencing and idempotent commit state
machine from joint_replay.cjs. It does not change the fixed-external-input
single-neuron profile.

Run `node research/rr_snn_v3/validate_network_replay.cjs`.
For actual Linux process crashes, run
`node research/rr_snn_v3/validate_network_replay_fs.cjs`.

## Bound state and deterministic history

The envelope includes the complete diagnostic snapshot: both physical neurons,
their RNG and hazard clocks, budgets, obligations, refractory states, traces,
rates, censoring statistics and queues; network time, graph, step count, pulse
history and delivery cursors; full feature history, weights, seed and scenario.
It binds actual source digests of the event, continuation, network, journal and
profile modules, plus the declared model and graph.

On unpack, each unit receives strict state-shape checks. The reference recreates
the frozen diagnostic at genesis, runs to the claimed time, and compares every
snapshot field, then restores through the actual network implementation.
A recomputed checksum cannot substitute a different delayed input or a feature
perturbation orthogonal to the current weights. Sequence bounds and predecessor
identity apply before a new envelope is published.

This replay from genesis is deliberately bounded by the small diagnostic's
horizon and work caps. Its cost is not represented as a scalable production
checkpoint strategy.

## Executed reference evidence

Seven interruption points compare the entire restored snapshot, statistics,
likelihood records and physical pulses with uninterrupted execution. At t=1.9,
both neurons have an actual emitted pulse waiting in an axonal delivery queue.
The pending input times are tied to the source pulse times and fixed graph delays.

Four reference journal fault points recover exactly and do not append duplicate
records on retry. Thirty-five negative cases cover all source identities, model,
weights, seed, schedule, graph, features including a weight-nullspace change,
dynamic queues, residual hazard, unknown fields, budget accounting, nonfinite
data, external digest, time/sequence/predecessor errors, acknowledged rollback,
rehashed false history and stale writers. The final fixture contains six actual
physical pulses and both units emit.

## Actual process harness and acceptance limits

The separate Linux harness performs real temporary file writes, fsync, witness
rename, process SIGKILL and fresh-process recovery at four fault points. Passing
results must be obtained from its stdout in a real execution receipt; a V8
reference run alone does not assert a filesystem test result.

Both profiles remain offline research code. No Hepta owner or production
checkpoint version is registered. The harness assumes one supervising process
controls the child writers; it does not prove arbitrary multi-writer locking,
power-loss durability, cross-runtime bit identity, target-machine performance,
independent future utility or real Cell-scale resource costs.
