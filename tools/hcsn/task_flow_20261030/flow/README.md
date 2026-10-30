# Observation assimilation and physical gaps

This implementation separates a real observation from time passing without an
observation. It extends the interface tested in earlier work; it does not
relabel PR4255's existing finite CTMC or the third-round continuous renewal
reference as new mathematics.

```python
import jax.numpy as jnp
from tools.hcsn.task_flow_20261030.flow import api

parameters = api.init_parameters(input_dim=3, width=4, seed=0)
state = api.initial_state(parameters)
state = api.observe(parameters, jnp.array([1., 0., -.5]), state)
state = api.checked_propagate(state, 2.0)  # no observation is fabricated
state = api.observe(parameters, jnp.zeros(3), state)  # an actual zero observation
```

`observe(parameters, observation, state)` writes recurrent content once, updates
drift/noise/boundary from the actual observation, and conservatively remaps
physical mass once. The physical clock does not move. Boundary lowering can
cause immediate marked events. Existing refractory phases retain their index.

`propagate(state, duration)` is the differentiable JAX core. It accepts no
observation or new coefficients. It advances the stored finite generator and
the autonomous content equation `dh/dt = -decay*h`. Content and probability
interact through the next observation's learned gate. This is not an arbitrary
coupled nonlinear ODE. `checked_propagate` checks external host inputs; pure JAX
propagation assumes valid states and returns NaNs for an out-of-domain duration.

`run_sequence` propagates the gap **before** assimilating the observation arriving
at its end. A future observation cannot determine the coefficients used over
the preceding gap. Use `jax.vmap` for independent batch examples. Each state is
a plain pytree; reset positions, refractory mean, content decay and internal
cost remain fixed within an episode. Training changes their parameters between
complete rollouts. A new episode uses `initial_state`.

## Mathematical scope

The retained distribution contains eight active finite-volume cells and two
Erlang refractory phases, on pressure interval `[-2, boundary)`. Upwinding,
finite reflection and remapping retain spatial errors. Two Erlang phases do
not represent a deterministic delay. The numerical bound controls time
propagation of the finite process only.

The positive uniformization mixture has fixed rate 8.1, 21 terms and subinterval
at most 0.36. Each interval independently chooses a power-of-two subdivision;
at most 10 squarings permit duration 368.64. `kernel.error_bounds` returns the
state L1 and event-count truncation bounds, excluding roundoff and spatial
error. Local derivatives are supported away from upwind, remap/interpolation
and integer numerical branch changes.

`events` is cumulative expected repeated emission count and can exceed one.
`kernel.next_event_probability` uses a killed chain and returns probability of
at least one next event. `reward` is the internal affine reward `position-cost`
per event, including reset continuation in future propagation; it is not a
classification utility, task Bellman value or financial equity/debt price.

## Reproduction and evidence

`protocol.json` was written before the first validation. Audits compare against
independent SciPy matrix exponentials, Frechet derivatives and centered
differences. They check complete-state gap composition, phase retention,
zero-time boundary events, content gradients, missing versus explicit-zero
observations and new-process recovery. Prior continuous and finite-grid
references are imported unchanged to report spatial discrepancy separately.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
taskset -c 0,1 python -m tools.hcsn.task_flow_20261030.flow.validate \
  --output NEW_EMPTY_DIRECTORY
```

Attempt001 passed its 28 recorded checks. Review found its explicit-zero check
could pass from the observation counter alone; its complete source and results
are preserved. Attempt002 strengthens that check to require an actual content
change and passed all 28 checks. Numerical gates and the physical/model
implementation are unchanged.
Every attempt records source hashes, source snapshots, raw metrics, process
timing, environment and checkpoint/recovery files. These tests establish a
small trainable interface, not an empirical advantage on a content task.

The final audit's maximum dense-reference state L1 error is `2.4153e-13`, event
error `2.7542e-12`, and whole-state gap-composition error `3.2596e-13`.
Physical-parameter AD versus independent Frechet scaled error is `5.1303e-11`;
content-projection centered-difference error is `4.6974e-12`. Fresh-process
suffix recovery matches exactly. At a 40-unit gap the expected repeated count
is `4.34719`, while next-event probability is `0.979826`.

All 28 acceptance checks and the errors above were measured with JAX x64
explicitly enabled and FP64 parameters/state. The public initializer defaults
to FP32; the example above does not inherit the FP64 accuracy certificate.
Checkpoint loading uses the receiving process's JAX configuration: loading an
FP64 archive with x64 disabled can lower precision. Exact recovery therefore
requires preserving the recorded precision configuration. Default FP32 and
mixed-precision recovery have not received the same acceptance evaluation.

Attempt002 took 12.8323 wall seconds, 10.8824 parent CPU seconds and 3.3338 child
CPU seconds; peak parent RSS was 485280 KiB. Both attempts' complete receipts
remain under `results/`. These timings are validation costs, not a training or
inference speed comparison. The independent continuum diagnostic also remains:
the eight-cell count is `0.614103`, the 64-cell count `0.596742`, and the
unbounded continuous reference `0.590097`; finite reflecting-space error has
not been hidden by the accurate time propagator.
