# Causal complete-state content-flow network

This candidate connects two or more actual regenerative populations through
time-dependent content messages. Its forward state includes the active density,
signed content densities, upper escape, all deterministic-delay packets, value
accumulators, the previous interlayer messages and the content-writing ledger.
It builds on the event-time reset snapshot repair in the complete-state kernel.

## Contract

At sample time `t_n`, all release atoms due at that time join active state first.
Layer zero reads the current sample; each later layer reads the previous
interval's upstream `[hit probability, signed content masses]`. The writer
computes `mark = tanh(W source + bias)` by default, and performs

```
active_content[channel,cell] += active_probability[cell] * mark[channel]
```

The cumulative write ledger adds `active_probability.sum() * mark`. Refractory
and escaped content do not receive the write. Each population then evolves to
`t_n + dt` through the existing complete-state finite generator and exact
deterministic-delay packet mechanism. The message is the difference in its
cumulative hit vector across that interval. All layers use the old message
buffer, so no layer receives information from a future part of its interval.
Each population retains its own probability; a synaptic message does not copy
probability from one neuron into another.

This defines one interval of synaptic latency. It is a sample-triggered write
model. Repeating samples while reducing `dt` changes the write schedule and is
not an invariant repartition of the same continuous-input problem. The scalar
kernel's frozen-law composition property remains separate from this contract.

## API and shared-law batching

```python
from fractions import Fraction
from qualification.hcsn_network.network import FlowNetwork

model = FlowNetwork(2, 4, layers=2, dt=Fraction(1, 10)).double()
# laws is one Physics per layer; x has shape [time,batch,input].
emissions, complete_state = model(x, laws)
# emissions has shape [time,batch,1+content].
```

The unbatched shape `[time,input]` is also accepted. `initial_state` can receive
an explicit probability vector per layer and signed content of shape
`[batch,content,space]`. Batch entries share the entire probability trajectory
and the same physics. Their signed content channels are flattened into one
matrix action without mixing samples. Forward outputs and VJPs are tested
against independent per-sample execution. Batch size is bounded to 256.

`message_mode="mass"` zeros the transmitted content channels while retaining
the same parameter count. Under fixed input-independent physics this intentionally
removes input-dependent information from downstream populations; it is an
interface ablation, not a competitive architecture claim.

`rate_drive=True` is available only for batch size one. It multiplies the active
generator and both exit rates by `exp(tanh(drive))`. This is a learned time
change; it does not inherit the optimality of any separately solved task boundary.
The default is False. `activation="linear"` supports the independent linear
ODE reference; the default nonlinear deterministic network is not claimed equal
to the expected nonlinear loss of a sampled discrete SNN.

## Complete forward checkpoint

`checkpoint.state_to_record` snapshots tensors without aliases into a
`torch.load(..., weights_only=True)` compatible record. The record contains all
packets, all message buffers, clocks, batch size, initial totals and content
writes. `state_from_record` restores that forward state. The caller must also
retain model weights/configuration, the future input schedule and the intended
physics. A training checkpoint additionally needs its optimizer, RNG and cursor.
This API does not claim to restore the autograd graph preceding a cold save.

`NetworkState.tensor_bytes()` counts the complete logical tensor payload,
including repeated tensors. It excludes model/Physics tensors, allocator
overhead and the live autograd tape. `balances()` independently queries the
current waiting mass and subtracts the initial totals plus actual writes.
The finite matrix/packet/exponential caps fail explicitly rather than pruning
the state.

## Verification and actual study

The seven focused tests cover an independent delayed ODE, no future-input
leakage, weight/input/initial-content/physics gradients, complete saved-state
continuation, shared-law batch forward and VJP equivalence, the mass-only
ablation, explicit resource exhaustion and release-before-write for a due atom.
The first six tests exposed no problem; subsequent source review found that a
due atom could miss a write. The separate repair and seventh test establish the
current ordering. Earlier source is not assigned that coverage retroactively.

`PLAN.json` and `study.py` were committed locally before execution. Publication
is separate. The first shell envelope could not find `/usr/bin/time`, exited
127 and started no Python/model/optimizer. Its stderr and null cost are retained.
A stdlib envelope was then frozen; it applies address-space/CPU limits and pins
one allowed CPU before numerical imports. This unique actual study is attempt002.

| Observation | Actual result |
| --- | ---: |
| Disclosed synthetic fit trajectories | 4, length 8 |
| Actual Adam calls | 60 |
| Initial / final same-input MSE | 0.0002749290467 / 0.0000002800126191 |
| Final / initial MSE | 0.00101849049 |
| Probability/content balance maximum absolute error | 8.8818e-16 |
| Fresh-process continuation tensor coordinates | 796, zero mismatches |
| Complete warm/cold tensor bytes | Equal |
| Final logical state bytes, B=4, two content channels/layer | 5,984 |
| Training matrix exponentials / largest order | 2,640 / 10 |
| Full elapsed time including imports and cold child | 6.136572 s |
| Full CPU including cold child | 6.039495 s |
| Waited process-tree peak RSS | 278,880 KiB |

The child resumes the saved state at time 0.4 and advances to 0.8. This includes
pending exact-delay releases and the interlayer message buffer. Parent counts
are 64 student forwards and one teacher forward; the fresh child adds one
student forward. The study has no held-out set and proves no real-task benefit.
Only specified calls instrumented their exponential totals; uninstrumented
initialization, balance-query and warm-prefix actions are not counted as zero.
All process costs include them.

`review.py` reads the original saved tensors without importing the model. It
recomputes the 60 Adam updates from all recorded gradients, moments and parameter
values, checks every cold tensor and all record metadata, and recomputes final
MSE from the saved predictions. Recorded gradients are not regenerated by this
reader. A separate real-task benchmark must freeze its own source and data and
cannot inherit a benefit claim from this synthetic fit.

## Remaining scientific scope

The finite spatial model is not the full diffusion, and this bounded small-grid
study does not establish long-sequence affordability. A task-derived boundary
must be mapped to the finite Physics consistently and assessed separately; the
present study uses two fixed one-state exponential excursion laws. The complete
model is ready for such an integration and fair empirical comparison, but its
new time-coupled content interface alone does not establish task optimality,
superiority over SNN/Transformer baselines, energy savings or multimodal scaling.
