# P4: small self-supervised sensor encoder curves

This experiment trains the HCSN encoder and a GRU encoder through every
trainable parameter. It measures a small sensor pretraining problem and does
not establish foundation-model scaling or an advantage over unimplemented
Transformer/SNN baselines.

## Frozen matrix and capacity

`uci_config.json` declares two architectures, widths 4/8/16, seeds 11/29/47,
and optimizer checkpoints 0/8/24: 18 trajectories. A single deterministic
raw-sensor ridge baseline is the nineteenth trajectory. The baseline uses
sensor last/mean and known interval last/mean/sum summaries; it has no random
encoder and is not replicated as three artificial seed observations.

HCSN width changes the number of signed content channels. It is not a neuron
count or a mesh-resolution parameter. Spatial bins remain 4 and phase stages
remain 2. The GRU uses the declared hidden width. Actual encoder, prediction
head, probe, and total parameter counts are reported; equal widths are not
claimed to imply equal parameter counts.

## Clock and objective

The source adapter provides independent chronological windows and actual
seconds between observations. No interval is averaged or replaced. Each
window runs independently, so different schedules cannot share recurrent
state. The final query occurs when the next arrival timestamp is known, before
its sensor values or occupancy label are revealed.

The fixed conversion is `s0 = 10 * median(train dt)` seconds per model-time
unit. Drift, drift limits, discount, gain and maintenance divide by s0;
sigma divides by sqrt(s0); refractory mean multiplies by s0. Geometry and
spike cost do not change. HCSN uses the declared reflecting finite-cell
approximation. Writes remain once per observation, so subdividing time with
additional writes is a different content process. GRU receives the same
interval information as log1p(dt/s0).

Self-supervision predicts x[t+1] from x[t] and its known interval. The unseen
sensor values at the external query row are unavailable and never become a
self-supervised target. The loss is mean squared sensor prediction error.
All HCSN drive, writer, boundary-controller and prediction-head parameters,
or all GRU and prediction-head parameters, receive task BP. Gradient hashes,
nonzero-gradient names, batch identities and parameter hashes are recorded
at each completed optimizer update.

At checkpoints 0/8/24, last/mean encoder features are frozen. Training labels
fit a common affine probe with objective
`mean((prediction-target)^2) + lambda * sum(non-bias weights^2)`.
Normalization uses only training features. Development MSE selects the
checkpoint; test labels are not arguments to training or selection.
`NoUpdate` means checkpoint 0 remains selected despite any charged training.

## Budgets, checkpoints and final holdout

Every trajectory has the same configured ceilings, including 180 seconds,
24 update proposals and three development evaluations. Wall overruns from
individual non-preemptible operations remain visible. These ceilings are not
a matched-FLOP claim. Feature extraction, probe fitting, failed operations,
backpropagation and checkpoint work are retained in the write-ahead ledger.

Checkpoints occur between completed independent windows, where the next
window has its model-defined initial state: HCSN reset distribution or zero
GRU hidden state. There is no in-flight queue or past AD graph to serialize
at this boundary. Weights, Adam, random streams, controller, selection
history and cost prefix are restored. A process killed inside an unclosed
operation has uncertain physical cost and cannot silently resume for free.
These are trusted-local integrity checks, not adversarial authentication.

`run` launches a fresh process per trajectory. Reported peak RSS is the whole
process high-water mark, including Python/Torch startup; it is not tensor
state size or isolated incremental training memory. Process receipts retain
stdout, stderr, exit status and wall time. Complete source hashes, runtime
configuration, data hashes and adapter metadata are bound at freezing.

`finalize` requires every planned trajectory to terminate. It seals each
selected checkpoint and the capacity/seed choice made using development MSE.
Only then may final labels open. Each final evaluation uses an exclusive
claim; an interrupted final evaluation is unavailable, not retried. All
predeclared trajectories are reported, including failures and raw baseline.

## Run from the repository root

```bash
python -m unittest qualification.hcsn_scale.scale_tests
python -m qualification.hcsn_scale.campaign freeze --config qualification/hcsn_scale/uci_config.json --manifest /path/to/new/manifest.json
python -m qualification.hcsn_scale.campaign run --manifest /path/to/new/manifest.json --output /path/to/new/results
python -m qualification.hcsn_scale.campaign finalize --manifest /path/to/new/manifest.json --output /path/to/new/results
```

Use `run --resume` only for an explicitly resumed complete-step checkpoint.
A new source/configuration requires a new frozen identity. No historical
HCSN, HPCA, N256 or single-attempt experiment is imported or rerun here.
