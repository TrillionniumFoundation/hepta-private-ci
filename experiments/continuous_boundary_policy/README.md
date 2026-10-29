# Matched recurrent policy supplement

This is an independent extension of `continuous_boundary_flow/study-002` at
commit `7bec42aa4f79432f4a724d5295c67f9d69ee5a8d`. The earlier three failed benefit
gates, source, selected models and evidence are preserved unchanged. New seeds,
source and model selection are sealed before new confirmation. Results are not
pooled across these studies.

## Question and model scope

Does a signed restoring/intervention prior add task utility when ordinary gated
and continuous recurrent controls are trained fully with matching input, state
and trainable coefficient budgets? The same study repeats boundary, channel and
expected-flow versus observed-event ablations under this stronger training setup.

The task remains the declared finite-window diffusion maintenance task: wait,
repair or stop; production minus discounted failure and repair costs. Current
continuation C and failure-loss P obey Q_wait=C-P. The numerical boundary is a
finite-decision Bellman intervention boundary. No exact He-Xiong equilibrium,
continuous-time smooth fit, globally monotone neural dynamics, or energy saving
is claimed.

All recurrent policies have 18 causal inputs and 6 persistent states. The signed
dual-bank GRU and ordinary GRU each have 464 actual trainable coefficients and
156 shared fixed sign coefficients. They start with identical effective weights.
The sole architectural restriction in their matched comparison is projection
of designated candidate/head magnitudes to nonnegative values in the dual cell.
Gates remain unrestricted; the signed prior is not a global monotonicity theorem.
The fully trained Elman control uses 150 recurrent coefficients, 288 coefficients
in a bias-free tanh readout hidden layer, and 26 output coefficients: also 464.
Its parameter allocation and operations differ and are separately measured.

Channel ablations deliberately mask C/P/current-risk input columns. They retain
the allocated 464-coefficient architecture, but the masked input coefficients
receive no data gradient. The strict all-live parameter match concerns the full
information dual/GRU/Elman controls. A directly fitted boundary adds 20 training
coefficients. The current native sparse reference has 420 frozen encoder and 42
fitted head coefficients; it is explicitly not a fully trainable-capacity match.

All policies receive the same public state, absolute deadline, model parameters,
costs and causal history. The generic control receives the same derived C/P,
margin, risk and prior flow as the dual policy. Expected-reset and observed-reset
arms differ only in the prescribed previous-risk versus previous-failure reset
fraction. The ordinary GRU shares the expected reset for the structural pair;
the Elman baseline learns its recurrence without a forced reset. The network
inputs also contain previous failure and repair information in every arm.

## Training and independent confirmation

Eight new seeds: 2203, 2207, 2213, 2221, 2237, 2239, 2243, 2251. Per seed, 12 training
contexts with 8 shared exploratory trajectories, 8 development contexts with 8
trajectories, then 8 ID and 8 OOD confirmation contexts with 16 trajectories each.
There are 9 learning methods and 4 reference policies, hence 26,624 confirmation
episodes. The 128/128 ID/OOD split is equally weighted within every seed.

Full-sequence NumPy BPTT trains all recurrent parameters for 120 epochs with
three fixed learning rates. Loss combines teacher-action cross entropy and
normalized expected DP action regret. The native sparse reference fits its
readout at three ridge penalties. Selection uses actual native development
utility, ties by smallest candidate index. Training/selection budgets and exact
candidate values appear in `PROTOCOL.json`.

Four primary paired-seed contrasts are value_margin-learned_margin,
dual_flow-value_call, dual_flow-generic_gru, and dual_flow-dual_event. Use four
Bonferroni-corrected two-sided t intervals (familywise 95%, df 7). Meaningful benefit
requires the lower endpoint above 0.005 and no stability failures. Other rankings
remain descriptive. No new seeds, exclusions or altered gates after confirmation.

Net utility prices the actual numeric cross-process decision input at 1e-6 per
byte:24 bytes for three continuous-policy Q24 scores and 160 for the native
sparse feature port. The four primary comparisons all share 24 bytes/tick. These
are not full wire bytes; actual JSON traffic, model-input arrays, training,
solver setup, runtime, native CPU and compilation are separately reported.
No CPU or hardware energy price is invented.

## Actual native execution

For continuous policies, NumPy computes recurrent states and bounded scores;
the separate score host calls the unchanged original NDU to select the action.
It executes zero sparse-kernel calls. Its receipt explicitly says that NDU did
not execute the Python network and does not attest model inference by itself.
An independent auditor replays causal inputs, hidden states, scores and actions.
The native_sparse reference calls the original sparse kernel and original NDU.
Both are research-only DENY_ALL paths. The original production crates and the
older continuous_host executable are not changed.

A small exact rational finite-MDP fixture enumerates 729 two-step Markov policies
to check the Bellman solver. This is exact for that finite fixture, not for the
underlying continuous diffusion. The previous numerical-grid diagnosis remains
available with the original study.

## Evidence stages

1. Run engineering-only gradients, features, native host, audit tamper tests and
   all-arm smoke using unrelated development seed 991; format; seal and publish
   source/protocol and final native build identities.
2. Initialize a fresh run, train, persist common data, all candidate models and
   development returns, and publish the selected-checkpoint seal.
3. Only then run all registered confirmation episodes with fixed-slot paired
   innovations. Persist raw task outcomes and actual native receipts.
4. Independently recompute primitive utility, risk calibration, action regret,
   parameter/feature contracts and four seed-level intervals. Publish full costs.
5. Separately run persistent-state maintenance-stream stability, cold Python
   checkpoint replay, and fixed-input warm math cost benchmarks. These are
   engineering evidence, not additional independent scientific samples.
