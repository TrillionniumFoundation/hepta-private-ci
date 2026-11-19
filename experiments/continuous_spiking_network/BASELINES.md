# Sequence baselines and reproducibility

These controls are trainable sequence modules with the common interface
`build_baseline(name, width, depth=1)` and
`forward(x, dt, context=None) -> (sequence, aux)`.
Inputs and outputs have shape `[batch, time, width]`; `dt` has shape
`[batch, time]`. They do not change the experiment's shared encoder or head.

The implementation is in `baseline.py`. Models are causal, start each call with
zero recurrent state, and do not retain state between calls. This interface is
for full-sequence training/evaluation, not a claim of implemented streaming
cache performance. The shared front end must supply the same observable time
and task-context features to every architecture. The optional `context`
argument is accepted for interface compatibility but is not independently
interpreted by these baselines.

## Architectures

| Name | Actual computation | Time handling |
| --- | --- | --- |
| `lif_snn` | Recurrent current-based LIF; exponential leak; hard 0/1 forward spikes; fast-sigmoid surrogate derivative; subtractive detached-spike reset | Learned positive decay rate times observed `dt` |
| `continuous_rnn` | Tanh recurrent target and exponential relaxation with a learned positive rate | Observed `dt`; frozen-target update, not an exact solution of an arbitrary nonlinear recurrent ODE |
| `two_gates` | Separate ordinary sigmoid retention/input gates plus tanh candidate | Retention is `sigmoid(logit)**dt`; input gate controls the write amplitude |
| `cfc` | Official `ncps.torch.CfCCell`, default mode, LeCun activation, one backbone layer, no dropout | Each cell receives `dt[:, t:t+1]`, avoiding accidental batch/feature broadcasting |
| `mamba1` | Pre-RMSNorm residual block around the genuine Mamba-1 mixer, using a real-valued serial PyTorch reference scan | Canonical learned selective delta; elapsed time is not silently multiplied into that delta |
| `transformer` | Pre-LayerNorm causal attention via `torch.nn.functional.scaled_dot_product_attention`, residual connection, GELU FFN of width `4H` | Cumulative observed-time sinusoidal encoding; no future attention |

The Mamba-1 mixer includes input expansion (`expand=2`), a causal depthwise
convolution (`d_conv=4`), SiLU, input-dependent delta/B/C, the stable
`A=-exp(A_log)` parameterization, the D skip, a SiLU output gate, and output
projection. State size defaults to 16; delta rank is `ceil(H/16)`. Delta
initialization follows the official logarithmic range `[0.001, 0.1]` and
inverse-softplus bias initialization. This is not a fixed-coefficient SSM
relabeled as Mamba. The scan accumulates in float32, as the pinned official
reference does. Complex and grouped scan variants are outside this experiment.

The LIF surrogate derivative is `1/(1+5*abs(margin))**2`. It is a surrogate,
not the derivative of the hard forward step. Threshold and leak rates are
trained. Reset uses `spike.detach()`; the recurrent synaptic input uses the
non-detached spike, allowing surrogate learning through recurrent connections.

## Capacity comparison

Equal feature width does not mean equal parameter count. At width 16 and
depth 1 the verified trainable counts, excluding the common encoder/head, are:

| Model | Parameters |
| --- | ---: |
| LIF SNN | 560 |
| Continuous RNN | 544 |
| Two ordinary gates | 1,584 |
| Official CfC | 1,616 |
| Mamba-1 CPU reference | 3,376 |
| SDPA Transformer | 3,280 |

Use `parameter_count(model)` for every actual configuration.
`match_parameter_budget(name, width, target_parameters, candidates=...)`
selects the nearest real internal width and reports the remaining relative
gap. Build that model with `hidden_width=record["hidden_width"]`. When internal
and external width differ, active input and output projections preserve the
shared interface. There are no unused parameter tensors to manufacture a
match. The search preserves the caller's random-number-generator state.

Report both width-matched and approximately parameter-matched experiments,
the chosen internal width, actual parameter count and residual matching gap.
This procedure does not match recurrent state size, FLOPs, optimization
difficulty, or wall time. Those require separate measurements.

## Exact source pins, hashes and licenses

The controls are grounded in the authors' implementations and the installed
runtime, with the following reproducible pins:

| Component | Pin and source | Verification |
| --- | --- | --- |
| CfC | [`ncps==1.0.1`](https://pypi.org/project/ncps/1.0.1/), released 2024-08-14; authors Mathias Lechner and Ramin Hasani; Apache-2.0 | Wheel SHA-256 `249b2a62c38608df62d454fe20f4e880f74c27ef97ea3a45e101d47b1b273fb5`; installed `ncps/torch/cfc_cell.py` SHA-256 `79dcc1cbb3b6898dc2310e9086a2e031e31cbaeb129d69adcbf45eaa16d6b74d` |
| Mamba mixer | [Official `mamba_simple.py`](https://github.com/state-spaces/mamba/blob/e0761ece1db07e0949dd88b4f4cd440420a19fd9/mamba_ssm/modules/mamba_simple.py), v2.2.5 commit `e0761ece1db07e0949dd88b4f4cd440420a19fd9`; Apache-2.0 | Git blob SHA-1 `4c8a388217c4cd4d21d5ea4704a5d571be294781` |
| Mamba scan oracle | [Official `selective_scan_interface.py`](https://github.com/state-spaces/mamba/blob/e0761ece1db07e0949dd88b4f4cd440420a19fd9/mamba_ssm/ops/selective_scan_interface.py), same commit | Git blob SHA-1 `a41f1359c2463e69a2a8e52035749893f126769a` |
| Mamba license | [Official LICENSE at the same commit](https://github.com/state-spaces/mamba/blob/e0761ece1db07e0949dd88b4f4cd440420a19fd9/LICENSE) | Git blob SHA-1 `f4abe24eb520fbb077753ae4f34bfaa43cb3b83f` |
| SDPA | [PyTorch 2.8 API and reference formula](https://docs.pytorch.org/docs/2.8/generated/torch.nn.functional.scaled_dot_product_attention.html); runtime `torch==2.8.0+cpu` | The test compares the selected runtime kernel with explicit masked attention and profiles its actual operator names |
| Test tensor layout helper | `einops==0.8.1` | Used by the preserved upstream scan oracle, not needed by the production reference scan |

Scientific references: [CfC](https://doi.org/10.1038/s42256-022-00556-7),
[Mamba](https://arxiv.org/abs/2312.00752),
[Transformer](https://arxiv.org/abs/1706.03762), and
[FlashAttention](https://arxiv.org/abs/2205.14135).
The baseline code does not claim that a closed-form neural approximation is
the exact dynamics of an arbitrary coupled stochastic network.

### Attribution and changes

The Mamba mixer adaptation and the scan oracle retain:

> Copyright (c) 2023, Tri Dao, Albert Gu.

They are provided under the Apache License, Version 2.0. The complete license
text is distributed in the repository's [LICENSE](../../LICENSE) and is also
available at [apache.org](https://www.apache.org/licenses/LICENSE-2.0).

The production adaptation removes CUDA extension imports, inference caches,
complex/grouped scan modes, and fused kernels; uses `[B,T,D]` for its local
scan interface; and implements the same real-valued recurrence with a serial
torch loop. It preserves the mixer projections, convolution, selectivity,
gating, parameterization, and initialization. The additional residual/RMSNorm
wrapper and common sequence interface are experiment code.

`_upstream_selective_scan_ref` in the test file preserves the upstream reference
body with name, documentation and formatting changes. The separate complete
mixer oracle follows the official non-fused layout and equations. CfC is
imported from the official package; its implementation is not rebranded or
silently replaced. The package carries its original Apache-2.0 notices.

## Verification and performance scope

Run the focused checks with:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m pytest -q experiments/continuous_spiking_network/tests/test_baselines.py
```

Nineteen tests passed on the installed CPU runtime. They check causality and
finite gradients through all trainable parameters; hard forward LIF events;
CfC outputs and gradients against an independent explicit gate formula;
Mamba scan outputs and all input gradients against the pinned official
reference; complete Mamba mixer outputs and all parameter gradients against
the official non-fused path; and SDPA outputs/gradients against explicit causal
softmax attention. Each architecture also decreases a fixed sequence loss
while training with the same small linear head. This last check establishes
basic trainability, not benchmark superiority or generalization.

On this runtime, `profile_sdpa_operators` observed:

```text
aten::scaled_dot_product_attention
aten::_scaled_dot_product_flash_attention_for_cpu
```

CUDA availability was false. The CPU operator name does not mean that a CUDA
FlashAttention-2 kernel ran. Mamba uses serial reference operations, not the
official optimized selective-scan CUDA kernel. CPU timings can compare these
implementations on this machine; they cannot establish that another
architecture is faster than optimized Mamba on GPU, nor establish a
neuromorphic energy advantage. Reprofile and report actual operator names
when changing hardware, dtype, sequence shapes, or PyTorch version.
