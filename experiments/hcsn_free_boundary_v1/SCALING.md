# CPU performance, bounded streaming state, and mid-stream recovery

## Scope and outcome

`results/scaling002` contains 48 sequence-performance configurations, six width/depth configurations, a 512-step state-storage probe, and a genuine new-process continuation from a numeric mid-stream checkpoint. All correctness probes passed.

The final gate uses scaled margin, the regenerative policy envelope J, and its intervention obstacle G. These are not literal financial Call/Put prices. First-hit probability remains in the reset/refractory dynamics.

This implementation has bounded **inference state** and exact checkpoint continuation under its stated mean-state recurrence. It is substantially slower than the compared baselines in these small CPU sequence measurements. These results establish neither accuracy superiority nor energy efficiency. The separate task-training experiments determine task quality.

All inputs and training labels in this work package are fixed-seed synthetic tensors. Each timing configuration performs one warmup and three measured repetitions for inference and for a training step. A training step includes zeroing gradients, full-sequence forward, cross-entropy, backward, and Adam update; it excludes the main training harness's gradient-summary logging, clipping, validation, and checkpoint I/O. These four timing updates are not a model-quality experiment.

## Environment and measurement

- CPU: AMD EPYC 9V74 80-Core Processor; nine logical CPUs visible to the process. The process was not pinned to an isolated core.
- OS: Linux 6.18.55, x86_64, glibc 2.39.
- Python 3.12.14; PyTorch 2.8.0+cpu; NumPy 2.3.5.
- PyTorch intra-op and inter-op thread counts: both 1. No CUDA device was available.
- `time.process_time()` measures CPU seconds. Each raw repeat also records wall time.
- Whole-process RSS high-water mark increased from **193.93 MiB to 367.83 MiB** during the run. This is a cumulative process statistic, not an isolated per-model allocation or a training-activation-memory comparison.
- Parent-process CPU time: **29.32 seconds**. Total wall time including the child recovery run: **31.79 seconds**. The parent's CPU counter excludes the child's CPU consumption.
- Energy, GPU throughput, hardware counters, and thermal/CPU-frequency controls were not measured.

The backbone counts are matched to the 8,800-parameter free-dual backbone within 2.19%; frontend and readout are identical. Transformer uses the existing causal PyTorch SDPA reference. Mamba uses the explicitly identified serial CPU reference of Mamba-1, not the upstream fused GPU implementation. Baselines are timed through full-sequence APIs; their streaming caches are **not measured** here.

The root forward and implicit backward are timed by temporary function wrappers that call the original implementations unchanged. CPU totals include the wrappers. The reported root fraction is the sum of measured root CPU time divided by the sum of full-pass CPU time over three repetitions. First-passage functions, recurrent content updates, autograd outside the boundary function, and Adam are outside this numerator.

## Same-size sequence comparison

Below: batch 16, sequence length 128, external width 32, depth 1, 12 input features and eight output classes. Values are medians of three repetitions, in milliseconds of CPU time.

| Model | Forward, ms | Training step, ms |
|---|---:|---:|
| Free-dual HCSN | 134.21 | 366.46 |
| Legacy HCSN | 63.57 | 255.19 |
| Ordinary two-gate RNN | 8.58 | 38.35 |
| Continuous RNN | 7.85 | 44.06 |
| CfC, pinned official cell | 17.78 | 57.93 |
| Mamba-1 CPU reference | 14.23 | 90.76 |
| Causal Transformer / SDPA | 4.47 | 18.21 |
| LIF SNN with surrogate gradient | 12.90 | 62.81 |

At this shape, the free-boundary solve accounts for **35.97% of free-dual forward CPU** and **11.87% of its training-step CPU**, including the implicit backward. Therefore, eliminating the root solve alone would not eliminate the observed training-time gap. This is an inference from the measured component fraction, not a profile of all other operations.

These are matched-size timing comparisons, not matched-quality comparisons. The short lengths and CPU implementation do not support claims about asymptotic crossover or GPU scaling.

### Free-dual sequence-length and batch sweep

| Batch | Length | Forward, ms | Training step, ms | Root share of training CPU |
|---:|---:|---:|---:|---:|
| 1 | 32 | 17.32 | 64.95 | 3.96% |
| 1 | 64 | 31.76 | 142.48 | 2.56% |
| 1 | 128 | 62.75 | 268.58 | 1.72% |
| 16 | 32 | 36.92 | 77.33 | 14.17% |
| 16 | 64 | 57.34 | 157.65 | 12.95% |
| 16 | 128 | 134.21 | 366.46 | 11.87% |

Every baseline has the same batch/length sweep in `performance.json`. Three repeats are sufficient for this scoped engineering probe, but not for a precise latency-distribution or tail-latency claim.

## Width and depth

Below: batch 16, length 64, 12 input features, eight outputs. Parameter counts include frontend, backbone and readout. State bytes refer only to the explicitly retained streaming state, not weights or returned logits.

| Width | Depth | Parameters | State elements | State bytes | Forward, ms | Training step, ms |
|---:|---:|---:|---:|---:|---:|---:|
| 16 | 1 | 2,760 | 1,040 | 4,160 | 44.74 | 148.10 |
| 16 | 2 | 5,112 | 2,064 | 8,256 | 79.97 | 345.66 |
| 32 | 1 | 9,608 | 2,064 | 8,256 | 64.97 | 191.26 |
| 32 | 2 | 18,408 | 4,112 | 16,448 | 98.87 | 371.81 |
| 64 | 1 | 35,592 | 4,112 | 16,448 | 83.69 | 189.05 |
| 64 | 2 | 69,576 | 8,208 | 32,832 | 180.01 | 478.61 |

The state formula is `B * (1 + 4 * width * depth)` float32 elements: elapsed time plus content, voltage, refractory state and previous event per layer. This says nothing about BPTT's saved activations or an application's decision to retain its output history.

## Streaming correctness and storage

For batch 2, width 32, depth 2, the probe consumed 512 observations using `.step` in inference mode. At prefix lengths 32, 64, 128, 256 and 512:

- Tensor elements remained **514**.
- Tensor payload and unique backing-storage size both remained **2,056 bytes**.
- No state tensor retained an autograd graph.
- All 512 streaming logits agreed with the batch forward within maximum absolute error **3.5762786865234375e-07**.

The batched forward used 0.562 CPU seconds; 512 individual step calls used 2.096 CPU seconds. They are the same recurrence, but step calls repeatedly invoke small kernels and boundary solves, while the batch path solves each layer's input-conditioned local boundaries in a single batch. Bounded state does not itself imply faster execution.

## Genuine new-process continuation

The recovery probe used batch 3, width 32, depth 2 and 256 observations. At step 113 it saved:

1. Numeric model weights and JSON architecture configuration.
2. `elapsed`, and every layer's `content`, `voltage`, `refractory` and `event` tensors.
3. The remaining 143 input observations and durations.

A distinct Python process reconstructed the model, loaded only those numeric arrays and configuration, and consumed the suffix. The checkpoint contained a nonzero refractory state, with maximum **0.1539465189**. Suffix logits and all final state arrays matched the uninterrupted step run **bit for bit**: maximum absolute errors were zero.

This validates the model's actual stored mean-refractory state. It does not turn the mean-state recurrence into an exact stochastic refractory-population propagator. Weights were instantiated for this recovery check; no quality claim is attached to them.

## Evidence and reproduction

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime \
python -m experiments.hcsn_free_boundary_v1.scale_tests

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime \
python -m experiments.hcsn_free_boundary_v1.scale \
  --output experiments/hcsn_free_boundary_v1/results/NEW_SCALING_RUN \
  --repeats 3
```

The external PyTorch path is the execution environment's reused runtime, not a source dependency to vendor. A normal compatible CPU PyTorch installation can provide the same packages.

Evidence files under `results/scaling002`:

- `performance.json`: all 48 configurations, raw repeats, medians, root timing and cumulative RSS observations.
- `width_depth.json`: six width/depth configurations, actual parameter counts and explicit state sizes.
- `streaming.json`: prefix-state storage measurements and batch/step equivalence.
- `recovery/`: numeric weights, checkpoint state, remaining inputs, uninterrupted/resumed logits, final states, distinct-process receipt and child environment.
- `environment.json`, `summary.json`, `provenance.json`: execution context and source fingerprints; all recorded source hashes match the final files.

All three focused scale tests passed before the probes. The final model's ten tests passed, including J/G boundary value and slope matching, genuine task gradients, and the initial-hit/negative-drift regression. The final measurement binds model SHA-256 `c86535bf5b37589503aada3b1d979d80b75e54eb19e6be4f3b93482066147625`. All five recorded source files, including the training checkpoint helpers, remained unchanged during this final run.

`results/scaling001` and its nested intermediate runs are retained as **nonfinal development measurements**. They are not used for the tables above. The pre-correction model source snapshots were verified against their original recorded SHA-256 hashes. Their timings are not combined with, or substituted for, the final run.
