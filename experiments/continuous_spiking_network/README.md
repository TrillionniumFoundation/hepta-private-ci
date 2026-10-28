# Continuous spiking network: four-layer study

This package implements and runs the four requested comparisons: learned
recovery/regeneration/adaptation/content, task stopping boundaries, temporal
representation architectures, and bounded CPU scaling. The experiment inventory
is fixed in `PROTOCOL.json`; `RUNS.json` and `SOURCE_SEAL.json` bind every actual
run to that source. Results are in `results/study001/` once execution completes.

## Exact integration baseline

- Main commit: `f8c9419df6ddeb36ff8b522a50219981fb8d9345`.
- Main tree: `15c9d6ea07bf3832de82825a6cc1e8c958dd3d45`.
- Numerical reference: the unmodified five-file slice listed in
  `reference/SOURCE.json`, from PR #4154 commit
  `c32392367b7587d09806ca5cbc74678a168b4e16`.

All changes belong to this package. The existing native Neuron kernel, owner,
authority, journals, other papers and experiments retain their existing source.
This is a tensor training and inference implementation with a checkpoint
contract. It does not relabel a Python readout as replacement of the native
Rust state transition or as deployed owner cancellation.

## Mathematical contract

`cell.py` separates high-dimensional content from pressure, adaptation and event
statistics. Two learned channels modulate a restoring drift and regenerative
feedback from the preceding event. An adaptation state supplies delayed
negative feedback. Drift, diffusion, channel strengths, adaptation, content
weights and positive natural barriers all receive task gradients.

`kernels.py` computes a Brownian first-passage law for frozen interval parameters.
The killed transition's exact first moment plus event mass reset at the interval
end updates pressure. Feedback across intervals propagates a mean: this is an
explicit mean-field neural model, not exact marginalization of a recurrent
random network, continuous nonlinear first-passage solution, or repeated
within-interval reset process. The learned diffusion scale is not claimed to
be independently calibrated uncertainty.

He and Xiong's 2012 papers motivate endogenous value boundaries and feedback;
they do not themselves identify equity/credit values with neuronal currents.
The two channels here have explicit learned dynamical roles. `boundary.py`
separately implements task stopping using a finite Bayesian decision problem.
That value boundary is distinct from the cell's natural firing barrier. The
baseline natural barrier is positive and directly learned; fixed barriers are
also supported by the module API.

See `BOUNDARY.md`, `BASELINES.md`, and `DATA.md` for the exact model, source
identities, data splits, licenses and approximation domains.

## Four layers

1. **Mechanism.** Five independent optimization seeds on keyed evidence and a
   real-image/real-audio query benchmark. Compare dual, single channel, no
   adaptation, ordinary event gate and a continuous RNN matched by active
   parameters. Unused ablation parameters are not counted as trainable capacity.
2. **Boundary.** Train one actor per seed, then compare fixed, directly learned
   and model-informed value stopping on exactly that actor's causal logits.
   A raw Bayesian oracle is separate. Count the first observation and all later
   observations. No full-prefix computation is relabeled as early cancellation.
3. **Representation.** Common input features, trainable frontend, readout,
   initialization, minibatch stream and optimizer recipe. Compare LIF SNN,
   continuous RNN, ordinary gates, official CfC, an equation-verified Mamba-1
   CPU reference and a Transformer using actual PyTorch SDPA.
4. **Scaling.** Separate capacity, training-set size and real history-length
   axes. Add one joint larger multimodal configuration. Track validation loss
   versus measured training CPU, final test quality, actual parameter counts
   and serialized inference measurements. Equal updates are not equal compute,
   equal source exposure or equal parameter count.

The primary mechanism statistic is the paired accuracy difference over training
seeds, conditional on the fixed heldout sources. Four candidate/control contrasts
per task use 98.75% intervals and a 0.01 practical-effect threshold. Small-seed
representation and scaling comparisons are descriptive. Two heldout audio
speakers do not establish speaker-population generalization.

## Reproduce

Create an isolated Python 3.12 environment and install `requirements.txt`.
The recorded execution uses CPU PyTorch 2.8.0. Install its CPU wheel from the
official PyTorch wheel index if CUDA is not needed. No GPU speedup or Joule
claim follows from these CPU measurements.

From the repository root:

```bash
python -m experiments.continuous_spiking_network.prepare_data --cache-dir /path/to/cache
python -m pytest experiments/continuous_spiking_network/tests -q
python -m experiments.continuous_spiking_network.run_study \
  --output experiments/continuous_spiking_network/results/study001 \
  --cache-dir /path/to/cache --workers 4
python -m experiments.continuous_spiking_network.measure_study \
  --results experiments/continuous_spiking_network/results/study001 \
  --cache-dir /path/to/cache
python -m experiments.continuous_spiking_network.audit \
  --results experiments/continuous_spiking_network/results/study001 \
  --output experiments/continuous_spiking_network/results/study001/AUDIT.json
```

The checked-in seal must match before running. A source modification creates a
new study and a new seal; never overwrite historical completed outputs. The
runner preserves failed logs and execution attempts. Completed runs are skipped
on recovery and the planned inventory must remain exactly equal.

The primary data are public MNIST images and FSDD recordings with split-disjoint
sources and speakers. Their pairing is constructed, and queries are four literal
tokens, not a general language corpus or naturally synchronized video. Audio
preprocessing uses complete utterances and is an offline encoder frontend.
`long_memory` adds independent distractor observations and real elapsed time;
the separate multimodal length stress inserts null steps. These tests have
different meanings and are reported separately.

## Evidence and accounting

Each classifier run stores its full specification, data/source identities,
minibatch indices, first-update parameter gradients, validation history,
selected model checkpoint, heldout logits and labels, environment and separate
preparation/training/validation/scoring costs. Model tensors are concatenated
into lossless compressed chunks below 400 KB, with blob and tensor hashes.
They support exact inference reload; optimizer/RNG state is not retained for
bitwise training continuation.

A separate serial pass reloads representative preselected checkpoints, measures
actual CPU/wall latency and profiles tensor allocations and supported operator
FLOPs. It lists unsupported special-function FLOPs rather than calling a partial
count the full algorithm cost. CPU allocations are not process RSS, and CPU time
is not energy. Training can use concurrent independent workers; clean inference
timings are collected only after all training finishes.

## Placement in Hepta

The trainable block can supply representation and decision features to
`neuron.runtime`/`inference.control`; task utility and continuation belong to
`utility.ndu`/`learning.operator`; immutable checkpoints belong to
`learning.artifacts`. A native integration must explicitly carry the new
pressure, adaptation, content, boundary and model identity. Existing
`NeuronModelPort` outputs alone do not change the native Q24 sparse kernel.

This package's measured comparisons, source pins and reload behavior are the
delivered evidence. Broader synchronized multimodal pretraining, optimized
GPU Mamba performance and foundation-model scaling require their own runs.
