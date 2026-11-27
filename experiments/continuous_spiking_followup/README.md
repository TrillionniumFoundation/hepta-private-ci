# HCSN follow-up: measured compute and actual streaming control

This research package continues the user's four-layer study from immutable
commit `23c98e77e4d2cc98e8c32caf7db763bc85c6794b` (PR #4159). It imports that
study's model/data definitions without modifying their scientific source or
historical results. The new protocol separately binds all follow-up source.

## Questions and fixed comparisons

| Layer | New execution | Principal comparison |
|---|---|---|
| Mechanism | Jointly trained restoration, regeneration, adaptation and content under a measured training budget | HCSN versus single channel, no adaptation, ordinary event gate, active-parameter-matched continuous RNN; 50 jobs |
| Representation | Same frontend, source data, output head and validation-only search opportunity | HCSN, LIF, continuous RNN, ordinary two-gate RNN, official CfC, verified CPU Mamba-1, actual CPU-SDPA Transformer; 84 jobs |
| Scaling | Capacity/data/real-history axes and one separate multimodal stress case | HCSN/Mamba/Transformer; 81 jobs; all validation–CPU curves retained |
| Task boundary | Same five frozen actors, freshly generated episodes and shared temperature fitting | Fixed/direct/model-informed value stopping; actual paid reads and model steps cease |
| Runtime | Genuine single-token execution, state restoration and original native owner | 55 preselected batch/stream cases, seven separate-interpreter replays, 96 native task episodes |

There are 215 model jobs and two learning-rate candidates per job. Each
candidate receives 12 measured process-CPU seconds of training, with validation
at the first update crossing 25%, 50% and 100% of that allowance. The final
indivisible update can overshoot; its actual cost is recorded. The 4,096-update
safeguard is disclosed whenever it prevents exhaustion of the CPU allowance.

Both learning rates, 0.001 and 0.003, start from the same initialization and
minibatch RNG stream. The minimum validation cross-entropy selects a retained
checkpoint; the test set is scored only after selection is recorded and the
winner is reloaded. Every candidate's training, validation, initialization,
checkpointing and evaluation costs remain in the ledger. Equal training CPU
does not mean equal total search cost, examples, update count or parameter count.

The new episode seed is 8123. Canonical MNIST/FSDD source populations are reused,
so this is not an independent new raw-data population or a controlled one-factor
comparison with study001. The shared feature and speaker-split limitations in
the [base data contract](../continuous_spiking_network/DATA.md) still apply.

## Actual streaming and persistence

`StreamingClassifier` consumes each current observation once. Recurrent models
retain their hidden state, Mamba retains its convolution/SSM state, and
Transformer retains causal keys/values. Active rows may be removed after STOP.
The adapter does not recompute full prefixes while calling that streaming.

State snapshots bind all model tensors and configuration, validate their numeric
schema and preserve elapsed time. The elapsed accumulator uses float64 and is
rounded to model dtype at use, following the pre-seal T128 discrepancy and its
recorded correction. The fixed batch/stream fixture tolerance is rtol=3e-5,
atol=3e-6; formal measurement records retain any disagreement. Same-order cold
replay is checked for exact equality. See [STREAMING.md](STREAMING.md) and
[MEASUREMENT.md](MEASUREMENT.md).

## Boundary semantics and real native consumption

Each boundary study reuses one selected study001 actor, with its complete
checkpoint identity and historical training cost. A single positive temperature
is fitted on new training prefixes and shared by fixed/direct/value policies.
Fixed thresholds use validation utility; the direct four-parameter threshold
uses training utility. The value policy uses a 257-point finite-horizon Bellman
grid and the known Gaussian observation model. Temperature fitting does not
prove the actor score has the assumed Bayesian Markov transitions.

Every policy receives the same causal actor score, SNR, observation cost and
remaining horizon. Correct classification rewards one; every purchased
observation, including the first, is charged. The in-memory source exposes an
actual paid-read iterator with a terminal guard. Avoided model steps and
iterator reads are real execution counts; input arrays are already prepared in
RAM, so they are not network/sensor acquisition or energy savings.

The native subset is fixed before outcomes: actor seed4403, first 16 episodes
of each heldout split, all three policies (96 episodes). The exact pinned
PR #4157 research host executes original sparse transitions and the original
NDU; its returned action controls the next read. Q24 rounding differences are
recorded and consumed, never overridden by a Python expected action. A retained
binary archive allows exact restoration without relying on an old temporary
build directory. See [NATIVE_BRIDGE.md](NATIVE_BRIDGE.md).

Threshold confidence margins are explicitly policy scores. Only the value arm
exposes genuine model-derived continuation/stopping utilities. At the terminal
horizon continuation is unavailable, so the forced finite STOP score is labeled
as a constraint, not an invented continuation value. Natural margin, predicted
task error and interval first-passage activity are separately typed.

The native profile deterministically compiles the declared decision score.
Auxiliary margin/risk/activity coordinates enter native temporal state and
receipts, but this does not isolate their independent action utility or prove a
learned native sparse-head advantage. The tensor HCSN owns its recurrence;
the host is a pinned Linux research executable, not a newly deployed full daemon.
Original native authority remains `DENY_ALL`.

## Reproduction

Use Python 3.12 and the pinned base requirements. From the repository root:

```bash
python -m experiments.continuous_spiking_network.prepare_data --cache-dir /path/to/cache
python -m experiments.continuous_spiking_followup.restore_native \
  experiments/continuous_spiking_followup/results/preflight/native_host \
  /tmp/hcsn-native-host/continuous_host
HCSN_NATIVE_BINARY=/tmp/hcsn-native-host/continuous_host \
  python -m pytest -q experiments/continuous_spiking_followup/tests
python -m experiments.continuous_spiking_followup.run_matrix \
  --output experiments/continuous_spiking_followup/results/study002 \
  --cache-dir /path/to/cache --workers 1
python -m experiments.continuous_spiking_followup.boundary_online \
  --seed 4403 \
  --output experiments/continuous_spiking_followup/results/study002/boundary_online/seed4403 \
  --base-results experiments/continuous_spiking_network/results/study001 \
  --native-binary /tmp/hcsn-native-host/continuous_host \
  --native-work /tmp/hcsn-native-study002
```

The other boundary seeds are 4401, 4402, 4404 and 4405. Completed evidence must
not be overwritten; use a fresh destination for an independent replication.
The model controller preserves failed attempts before an unchanged-spec retry
and records each exact child process's CPU, wall time and exit status. It is a
POSIX execution harness; the archived native host is Linux x86_64-specific.

Run the preselected serial measurement pass only after training and other
research computations have stopped. Every model has separate batch and stream
latency samples, reset/hash costs, state payload size and parity diagnostics;
the seven specified MNIST models also use a new Python interpreter for recovery.

## Interpretation

The local first-passage law and mean-field cell equations are unchanged from
study001. Natural neuron thresholds remain directly learned; the task value
boundary remains a separate finite-horizon stopping problem. This follow-up
does not claim a literal Call/Put neuron, a smooth-pasting endogenous neuronal
barrier, GPU/kernel superiority, neuromorphic energy savings or foundation-model
scaling. Its additional evidence concerns quality at measured CPU budgets,
actual incremental costs and trained-model consumption by a real native owner.
