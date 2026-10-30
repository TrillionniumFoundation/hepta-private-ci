# HCSN sequence microbenchmarks

This directory contains executable, synthetic, CPU reference experiments. It is
not a reproduction of the full He–Xiong valuation formula, a production neuron
runtime, or evidence of LLM/multimodal pretraining performance.

## Models and API

`models.py` exposes:

```python
params = init_model(kind, key, input_dim, hidden_dim, output_dim)
logits = apply_model(params, x, dt, kind)
```

`x` has shape `(batch,time,features)`, `dt` has shape `(batch,time)` and logits
have shape `(batch,classes)`. Every model receives `log1p(dt)` as an additional
input. The four model kinds are:

- `hcsn`: two-state fast/slow recurrent dynamics using the simplified
  abandonment-put activation and normalized continuation-value activation;
- `sigmoid`: the identical recurrent graph and parameter count, changing only
  the put activation to `sigmoid(2*x)`, which matches the put's value and first
  derivative at the boundary;
- `gru`: a conventional gated recurrent unit;
- `transformer`: one encoder block with one attention head, sinusoidal position
  encoding, pre-normalization and a two-times-width feedforward layer. It uses
  final-position readout. Attention is bidirectional because only the final
  sequence label is predicted, with no future input beyond that query.

The HCSN step freezes its nonlinear gates over each time interval and solves
the linear leak term exponentially. This is an explicit numerical method, not
the exact flow of its nonlinear ODE. Fast time constants lie in `(0.2,5)`, slow
time constants in `(2,100)`, regeneration gains in `(0,4)`, recovery gains in
`(0,6)` and call gains in `(0,2)`. The drive is bounded by `3*tanh(.)`.
For positive `dt`, zero initial state and finite weights, each recovery state
remains in `[0,6]` and each fast state remains in `[-9,9]`: every update is a
convex combination with a target in those bounds. This does not prove stable
gradients or good memory. Threshold offsets are learned per unit and are
static within a sequence in this experiment.

The two value channels are not independent information dimensions. The
`read_y` projection and the recurrent input mixing are new engineering choices.
No production resource authority or external effect is modified.

## Fixed protocol

The parameter target is 6200. Width is selected using parameter count before
training; actual trainable counts are 6178 (HCSN and sigmoid), 6257 (GRU) and
6166 (Transformer). Every model uses Adam with learning rate 0.003, global
gradient clipping at norm 1, batch size 32, and 300 updates. No hyperparameter
search was performed. This is a matched-parameter, matched-data and
matched-update protocol, **not** a matched-FLOP or equal-wall-time experiment.
Neither the model widths nor training settings are selected using test scores.

For each of five seeds, there are 2048 training examples, 512 validation
examples and 512 independent test examples. A checkpoint is selected only by
the lowest validation loss at 50-update intervals. Test and OOD examples do
not participate in checkpoint selection. Minibatch indices and data are paired
across models. Model execution order rotates by seed.

The tasks use 32 input steps and four classes (chance accuracy 25%):

1. `memory`: recover the initial marked symbol after random symbol distractors;
2. `retrieval`: retrieve a value associated with one of four distinct keys, using
   a query key at the final step;
3. `irregular`: classify the two signs of a decaying two-dimensional event
   accumulator, with variable time gaps, Gaussian observation noise and missing
   observations. The ground-truth accumulator uses observed clean events and
   the exact specified exponential decay.

OOD evaluation doubles the sequence length to 64 without retraining. The
irregular task additionally changes observation noise from 0.1 to 0.35 and
missing probability from 0.25 to 0.5. These are small controlled tasks, not a
comprehensive long-context or real-world modality benchmark.

Data fingerprints, source hashes, every per-seed metric, gradient norms,
checkpoint history and timing are retained in `sequence_results.json`.
`gradient_validation.json` separately checks temporal-parameter gradients in
float64. It checks gradients of the implemented discrete update, not continuous
ODE sensitivities.

## Reproduction

Dependencies used: Python 3.12, JAX/JAXlib 0.4.38, NumPy 2.3.5, SciPy 1.17.0,
ml_dtypes 0.5.1, opt_einsum 3.4.0. No data download is required.

```bash
python run_benchmarks.py --steps 300 --seeds 5 --out sequence_results.json
python validate_models.py
```

For multi-process experiments, limit CPU affinity or thread use to avoid
oversubscription. The recorded run used four CPU cores. Timing is CPU-only. The
raw field `warm_training_seconds` removes only the first update. A later audit
found that weakly typed scalar parameters can cause a second JIT compilation
on a new signature, so this field can contain compilation; cache reuse means
this does not occur on every seed. All training-time fields are reference
diagnostics, not pure warm timings or evidence of speed or energy differences.
Sequence latency measures the full evaluation function, including loss,
accuracy and Brier score; it must not be directly compared with the encoder
experiment's logits-only latency. Peak RSS is the
cumulative process high-water mark including JIT caches; it **must not** be
interpreted as independent per-model memory usage. No GPU kernels, joule
measurements, p95/p99 latency study or production-scale throughput are included.

## Interpretation

All negative results are retained. In particular, excellent accuracy on the
training-length distribution does not establish length extrapolation. A result
that fails the longer sequence or key/value retrieval test is not sufficient
evidence to advance to a large pretrained backbone.

The sigmoid comparison isolates the put shape while retaining the call branch
and fast/slow mechanism. It is not an ablation of every finance-inspired
component. Future tests must separately remove the call branch, recovery state
and learnable boundary, using a new validation protocol before evaluating new
held-out tests.

## Completed follow-ups

`V2_RESULTS.md` records one fixed architecture repair on fresh synthetic data.
`FROZEN_V2_RESULTS.md` records the same fixed architecture on frozen text
features. `SNN_RESULTS.md` adds a conventional recurrent LIF baseline with hard
0/1 spikes and a stated surrogate backward rule: 15 synthetic runs and five
frozen-head runs, all with the same data/update budget. `snn_protocol.json`
was written before those runs. All 20 SNN checkpoints were replayed with
exactly matching test accuracy, loss and Brier score. The frozen v2 and SNN
comparisons reuse an already-examined SST holdout and are exploratory.
