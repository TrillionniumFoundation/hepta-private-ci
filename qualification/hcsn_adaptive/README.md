# Adaptive HCSN research backend

This package extends the conservative spatial generator in
`qualification/hcsn_training/population_generator.py`. Its baseline is integration
`0cee57ca617e0324e2df8e9447a2c075a6c76952`. It defines a new finite population model;
it does not inherit the qualification of a historical deterministic-delay run.

## Dynamics and complete state

Each sample has its own probability distribution and signed content marks. The
input changes log-state drift through `base_drift + drift_scale * tanh(drive(x))`.
The batch axis never shares probability. An explicit `drift_override` provides
the fixed-drift control. The writer makes a convex update to active marks once
per observation, preserving `abs(content) <= probability`. Its `write_fraction`
is per observation: inserting extra observations changes the content law.

The spatial coordinate is `log(V) - boundary`; `boundary_override` is an absolute
log boundary. At an observation edge, overlap of old and new finite-volume cells
conservatively projects active probability and content. Newly crossed lower
mass enters refractory phase zero and produces an immediate event. Refractory
mass keeps its phase; when it returns, it resets relative to the **current**
boundary. During the following interval, boundary and drift are held fixed.

`upper_mode="absorbing"` preserves the original permanent escape account. In
`upper_mode="reflecting"`, the upper exit rate returns to the generator diagonal;
mass projected above a moved upper edge is explicitly lumped into the last cell.
`upper_projection_mass` and `upper_projection_content` report this operation.
This lumping is a finite-cell approximation, not an exact moving reflected
diffusion. A reflecting state cannot contain escaped mass. Mode changes cannot
reuse an existing state without a separately defined migration.

The `stages` refractory chain has Erlang waiting time with mean `refractory` and
variance `refractory**2/stages`. It does not impose a strict minimum waiting time.
The matrix exponential is exact in real arithmetic for this frozen finite
generator; spatial discretization, input freezing and the waiting-time law remain
explicit approximations. These are deterministic population outputs, not an
identity between a sampled SNN's nonlinear loss and a loss of its mean output.

`FlowState` contains probability/content over all active, phase and upper states,
the current boundary, the integer-microsecond clock and the model configuration.
For batch B, content size K, N spatial cells and R phases, the dynamic tensor
payload has `B * (1 + K) * (N + R + 1) + B` elements, independent of elapsed steps.
Returned sequences, autograd tapes, model weights and temporary matrix storage
are separate costs. Use `torch.no_grad()` for inference or explicitly detach a
state when choosing truncated gradients. `dt` must be a positive scalar integer
number of microseconds; different sample schedules must be grouped or processed
separately, with their physical timestamps retained.

## Precision contract and observed numerical failure

| Configuration | Trainable layers / inputs / outputs | Geometry, complete flow state, matrix actions and value solve |
|---|---|---|
| `transport_precision="float64"` (default), `model.float()` | FP32 | FP64 |
| `transport_precision="float64"`, `model.double()` | FP64 | FP64 |
| `transport_precision="native"` | Model dtype | Model dtype |

The first row is **mixed precision** and must not be reported as native-FP32
throughput or storage. Geometry is rebuilt in its declared precision when the
module changes dtype/device. No probability renormalization or relaxed mass
threshold is used to hide drift. State records use schema
`hcsn-adaptive-phase-state-v2` and bind the precision and upper-boundary modes.

The native-FP32 predecessor, backend SHA256
`37abf67f65fa93ed04422c7b9bf5bed2ad4234548f6fd2ebdabb44625c48acc1`, passed 12 of
13 checks but failed the long-flow invariant at step 217 (21.7 seconds). The two
mass errors were approximately `9.40077e-6` and `3.00165e-5`; the generator's row
sums were zero, but matrix-exponential transition row residuals ranged from about
`-2.16e-7` to `3.33e-7`. Minimum probability remained positive (`0.01214664`) and
content stayed within its probability bound. This is cumulative transition
roundoff, not a negative-density or mark-overflow failure. Its failed receipt
remains historical evidence. The FP64 transport/state profile is a separately
identified numerical configuration with the stricter FP64 state tolerance.

## Feature semantics

`feature_names` fixes the order: event, K content channels, risk, margin,
occupation, call. `feature_mask` changes outputs only, preserving state for
channel ablations.

| Feature | Meaning |
|---|---|
| `event` | Expected event count during the interval, including boundary-jump hits; it may exceed one. |
| `content_i` | Signed content carried by those events. |
| `risk` | First-hit probability for mass active at the start, including boundary-jump hits; initially refractory mass is excluded. |
| `margin` | End-of-interval active probability weighted margin, divided by the extent; this is not a conditional mean. |
| `occupation` | Interval-average active probability. |
| `call` | End-of-interval value under the current **frozen finite policy**, including future phase returns. |

For the row generator G and event intensity k, the last channel solves
`(discount * I - G) U = running_reward - spike_cost * k` and returns `p @ U`.
Active reward is `gain * (boundary + cell_center) - maintenance`; phase and upper
accounts have zero running reward. The value may be negative. It is not the
He--Xiong equity formula, an optimal continuation advantage, or a proof that the
classification boundary satisfies smooth pasting. A full-equity comparison must
use the existing equity implementation in an explicit feature adapter and
declare its phase/reset treatment; replacing the final feature must not silently
relabel this finite-policy value as equity.

## Task-continuation boundary is an observed-input proxy

`continuation.py` estimates continue transitions from the declared training
split. Its finite state is the quantized first input and the sign of an observed
context coordinate. Reset transitions are a declared modeling assumption. The
default running utility is a quadratic operating-state objective, not the final
supervised task loss. Supplied rewards must have a recorded training definition.

The discrete Bellman calculation produces continue/reset values. A lower
threshold projects that policy and is evaluated using its own continuation;
nonmonotonicity and projection value loss are reported. `query` uses the current
observed context and known remaining horizon, with no label argument. Thus the
threshold can depend causally on input, but actual runs must report whether its
queried values vary. The lookup is discrete, not differentiable through context.
It neither models the complete population/phase/content state nor identifies
the counterfactual effect of a neural reset. Applying its observed-input
threshold as an internal log boundary is a declared surrogate control, not a
financial analytic optimum or a solved network-wide impulse-control problem.

## API and verification

```python
import torch
from qualification.hcsn_adaptive.batched_flow import BatchedFlow, FlowConfig

model = BatchedFlow(FlowConfig(input_size=3, upper_mode="reflecting",
                              transport_precision="float64")).float()
with torch.no_grad():
    features, state, diagnostics = model.step(torch.zeros(2, 3), dt=0.02)
    features, state, diagnostics = model.step(torch.ones(2, 3), state, dt=0.02)
```

Run `python -m unittest qualification.hcsn_adaptive.batched_flow_tests -v` for
conservation, independent batching, input-dependent probability, moving-boundary
accounting, a no-write frozen semigroup, AD versus finite differences, snapshot
continuation, channel masking, bounded streaming state, upper-mode differences
and explicit precision/gradient checks. Results apply to their recorded source
and runtime. A `FlowState` record restores future flow state, not an old AD tape;
semantic validation occurs in `validate_state` or the next step. Full training
replay also needs the outer checkpoint's weights, learner/controller, RNG and
cost ledger. Neither a restored record nor a research candidate activates a
production model.

The independently identified `qualification/hcsn_history` study measures
bounded streaming payload at 32/128/512 steps, phase-count delay error and
finite-policy/full-HX Call component costs. Its functional Call substitutions
do not skip the original solve; see that directory's README for the different
objectives, cache rules and limits of the history measurement.
