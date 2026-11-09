# Differentiable continuous-probability HCSN candidate

This package implements the next **research candidate** after the existing
regenerative-distribution experiments: trainable physical parameters, complete
probability and vector-content state, a multilayer task loss, and an irregular
sensor input adapter. Its source and evidence are separate from the frozen S81
studies and the original 170-run campaign.

Read [MODEL.md](MODEL.md) for the continuum process, numerical approximation,
value semantics, supported parameter domain, and limitations. A successful
mechanism qualification is not a real-data benchmark, a production deployment,
or evidence that HCSN outperforms SNNs, state-space models, or Transformers.

## What is implemented

| Component | Behavior |
| --- | --- |
| Physical law | Killed log diffusion, boundary hit, fixed deterministic refractory delay, and continuous absolute reset location |
| Numerical state | Finite active cells, an explicit returning tail, and remaining-refractory-time cells |
| Trainable physics | Independent drift, diffusion, static log boundary, and absolute reset parameters in each layer |
| Content | A vector-valued marked-content mass, propagated with the same matrix as probability |
| Observations | Explicit end-of-interval likelihood conditioning and bounded content writing |
| Layers | Recurrent probability/content layers with vector messages and declared value/risk/margin readouts |
| Training | Ordinary first-order reverse AD through the actual fixed-quadrature construction; full or explicit truncated BPTT |
| Recovery | Numerical state, model, validated Adam optimizer state, clocks, truncation position, and CPU RNG restoration; no serialized autograd tape |
| Input adapter | Per-channel missingness, per-example padding, actual time gaps, and retained absolute timestamps |

There is no binary-step surrogate gradient. There is also no sampled spike
train in this implementation. The event output is a conditional expected
interval count. The `call` readout is a specified one-interval engineering
value; it is not a complete He--Xiong equity solution or a regenerative total
value solver. `risk` and `expected_events` coincide within the supported
single-event propagation interval; they are not independent physical states.
With observation conditioning, the sum of these outputs is a sum of predictive
conditional interval expectations. It is not a retrospective cumulative-count
posterior conditioned on all later observations; that would require additional
joint state and smoothing machinery.

## Run the independent qualification

Use an existing Python environment with PyTorch. The recorded qualification
uses CPU and FP64; the package does not install dependencies, allocate a
provider session, or access a study ledger.

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  python -m qualification.hcsn_differentiable.run_qualification \
    --threads 1 --output /absolute/path/to/a-new-result.json
```

Run this from the repository root. The output path must be new. The result
records source hashes before and after execution, actual test outcomes,
numerical comparisons, runtime versions, elapsed/process CPU time, and process
peak RSS where available. A missing dependency or a skipped test cannot earn
a passing qualification. A failure must be retained with the source that
produced it; fix the candidate and create a distinct result for the next run.
Recorded outcomes and resource observations are kept under `evidence/` with
their own timestamps and source identities.

The test families address different questions:

- Independent analytic/numerical references check first passage, discounted
  hits, occupation, renewal rate, and numerical refinement.
- AD/central-FD comparisons exercise physical parameters through the new
  propagator and through a two-layer task loss. Selected derivatives are
  fixtures, not exhaustive certification of the parameter domain.
- Long propagation checks probability and signed-content conservation.
  Separate phase-resolution tests expose premature release from projection.
- Continuation, explicit truncation, and checkpoint-consumption tests check
  retained state and the next optimizer step.
- Encoder tests distinguish missing data from padding and preserve the
  predecessor clock across chunks.

The coarse network fixture and the independent 81-state propagator fixture
have separate purposes. The former does not inherit the latter's fidelity,
and neither earns completion credit in an old S81 study.

## Minimal differentiable sensor example

```python
import torch
from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import IrregularHCSNEncoder

torch.manual_seed(7)
model = IrregularHCSNEncoder(
    sensor_dim=3, embedding_dim=4, content_dim=4, output_dim=1,
    layer_count=2, grid=GridSpec(active_cells=16, phase_cells=8),
).double().cpu()
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

values = torch.tensor([[
    [0.2, 0.4, -0.1], [0.1, 0.5, 0.2], [0.4, -0.2, 0.3],
    [0.7, 0.1, 0.5], [0.3, 0.6, -0.2],
]], dtype=torch.float64)
gaps = torch.tensor([[0.04, 0.03, 0.05, 0.02, 0.06]], dtype=torch.float64)
timestamps = 1000.0 + gaps.cumsum(1)
state = model.initial_state(1, start_time=1000.0)
result, state = model(values, timestamps, state=state)
loss = (result.predictions[:, -1, 0] - 0.4).square().mean()
loss.backward()
optimizer.step()
optimizer.zero_grad(set_to_none=True)
# An optimizer step ends this physical episode. Begin the next episode with
# model.initial_state(...); continuing the previous state now raises an error.
```

For streaming **before** an optimizer update, pass the returned `state` to the
next chunk. `state.detached()` deliberately cuts the old graph while retaining
the full numerical state. Checkpoint serialization also starts a new graph
segment on restoration. It cannot recover gradients through already executed
and serialized history.
Optimizer recovery in this first checkpoint schema supports `torch.optim.Adam`
explicitly. It checks parameter-group identity, moment tensors, and step values;
other optimizer schemas require their own validation. Failure rollback is an
in-memory CPU transaction, not a crash-durable storage transaction.

In this first candidate, truncation cuts the graph but does not permit an
optimizer update inside a retained episode. Accumulate the intended chunk
losses and update after the episode ends, or explicitly start another episode.
This is a real restriction on online truncated training; it must not be
reported as arbitrary mid-stream parameter adaptation.

`truncate_every=K` is fixed when the first chunk is consumed and is retained in
state. Its interval counts shared sequence positions, including padding,
across calls. It does not count elapsed physical time or each sample's number
of observations. The qualification checks this explicit convention.

## Physical time and missing data

Timestamps and refractory duration use one caller-declared physical unit.
`time_scale` only scales the encoder's time feature; it does **not** rescale
the diffusion time or clip a gap. Supply FP64 timestamps when a large absolute
epoch would otherwise erase short differences.

Every propagation interval must satisfy `0 <= dt <= refractory`. Longer gaps
are rejected. A future long-gap policy must freeze its subdivision rule and
measure the extra projection error; silently dividing an interval is not
equivalent to the present finite-basis operator.

An unobserved but valid timestamp advances the physical state. A padded
position advances neither the physical clock nor the state. Missing channels
are masked before projection; an observed nonfinite value is rejected. Equal
timestamps are allowed and represent another observation with zero physical
propagation.

## Deliberate scope boundaries

The boundary and all physical parameters remain constant during a retained
episode. Optimization can change them only between episodes. No moving-boundary
sweep, variable refractory derivative, QVI optimum, second derivative,
FP32/GPU fidelity, or full multimodal training result is claimed.

The numerical map is a fixed-basis `Q P_dt R` approximation. It preserves mass
without row repair, but repeated projection is not an exact continuum
semigroup. Phase projection can release mass earlier than the underlying
deterministic delay. The retained tail is a reconstructing density basis, not
an exact arbitrary tail distribution. These errors require their own checks
even when task gradients and mass conservation pass.

This implementation builds differentiable transition tables and uses dense
probability/content transport. It has no demonstrated sparse-hardware or
energy advantage. Parameter count, table construction, state dimension,
sequence length, memory, wall time, and hardware must all be included in any
later comparison.

Before a real sensor/audio/event benchmark, freeze a dataset version and
leakage-safe split, the physical time unit and long-gap policy, normalizations,
trainable-parameter budgets, seeds, stopping rules, and baseline budgets. Include
a frozen-physics HCSN, the explicit no-reset control, a content-channel control,
and time-aware recurrent/state-space/attention baselines. Real-data generalization
and matched-cost advantage remain open questions until those runs complete.
