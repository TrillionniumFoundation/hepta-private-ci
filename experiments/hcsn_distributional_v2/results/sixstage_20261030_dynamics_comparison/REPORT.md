# Same-drive reset and refractory comparison

All four processes use the same finite-grid drift, diffusion, boundary, reset location and initial state. Absorption permits one event in the entire episode. Endpoint probability reset permits one event per observation window and deliberately delays reinjection. Immediate reset and Erlang refractory variants are continuous-time marked chains and permit repeated events within one window.

| Process | Observation dt | T | Expected count | Active mass | Refractory phase mass | Passive recovery |
|---|---:|---:|---:|---:|---|---:|
| absorbing_no_reset | 0.0625 | 16.0 | 0.999599262 | 0.000400738242 | [] | 0.000192473872 |
| absorbing_no_reset | 0.25 | 16.0 | 0.999599262 | 0.000400738242 | [] | 0.000192473872 |
| absorbing_no_reset | 1.0 | 16.0 | 0.999599262 | 0.000400738242 | [] | 0.000192473872 |
| end_window_probability_reset | 0.0625 | 16.0 | 13.4345256 | 1 | [] | 0.678402561 |
| end_window_probability_reset | 0.25 | 16.0 | 12.4514814 | 1 | [] | 0.705440383 |
| end_window_probability_reset | 1.0 | 16.0 | 9.23879993 | 1 | [] | 0.793452877 |
| instant_reset_ctmc | 0.0625 | 16.0 | 13.7958205 | 1 | [] | 0.669650713 |
| instant_reset_ctmc | 0.25 | 16.0 | 13.7958205 | 1 | [] | 0.669650713 |
| instant_reset_ctmc | 1.0 | 16.0 | 13.7958205 | 1 | [] | 0.669650713 |
| erlang2_refractory_ctmc | 0.0625 | 16.0 | 10.9923732 | 0.799284634 | [0.10035761281275035, 0.10035775333407423] | 0.535246327 |
| erlang2_refractory_ctmc | 0.25 | 16.0 | 10.9923732 | 0.799284634 | [0.10035761281274902, 0.10035775333407287] | 0.535246327 |
| erlang2_refractory_ctmc | 1.0 | 16.0 | 10.9923732 | 0.799284634 | [0.10035761281274896, 0.10035775333407282] | 0.535246327 |

The continuous chains satisfy time-subdivision consistency, including expected counts and a passive exponentially decaying event trace. The endpoint reset approximation generally does not; its discrepancy and convergence with smaller observation steps are reported rather than hidden.

Count distributions use a separately assembled marked-uniformization recursion. Each of the 36 scenarios has 12000 independent event-driven Monte Carlo paths, final per-path count/state/recovery records, and 128 complete sampled trajectories. Count CDF comparisons use a predeclared simultaneous DKW bound.

The passive recovery trace has no feedback into the drive. Refractory recovery is the Erlang phase exit; neither is presented as a newly verified biophysical adaptation law. Trainable parameters are evaluated by the separate content experiments, not by inventing reset gradients for an absorbing process.

Passed: True. Self CPU 5.517608s; wall 12.534999s.
