# Population B with physical-time refractory cohorts

`population_age_v1` is a separate, opt-in integration profile. Its checkpoint
schema is 3. Fixed-grid `population_grid_v1` and its schema 2 keep their original
queue and ceiling semantics. Loading an old checkpoint does not convert its
queue, change its model identity, or change its admitted time profile.

## Time, mass and coupling

The profile accepts positive integer microsecond intervals within the native gap,
event-step and tensor budgets. Each numerical step ends at the earliest of the
requested interval end, `max_step_micros`, or the oldest refractory cohort's
expiry. Every Cell advances on the same event schedule and consumes its
predecessor's previous-boundary trace; external input is held on each coarse
interval. The forecast horizon remains the target timestamp offset.

The new `upwind_ctmc_v1` spatial kernel uses a conservative finite-volume
continuous-time Markov generator. On a uniform grid with width `h` and diffusion
`D = sigma²/2`, the interior jump rates are `D/h²` plus the outward upwind drift
at each face divided by `h`. Boundary diffusion rates are `2D/h²` because the
absorbing face is half a cell from the terminal centre. The generator has one
account for each active bin and two absorbing accounts: left-boundary hit and
upper-boundary escape. Its matrix exponential advances all mass by the actual
step duration, without clipping or row normalization. Both boundaries represent
first exit; this upper-boundary rule differs from the frozen legacy kernel.

Absorbed mass is deposited in a refractory cohort at the numerical right boundary, with
240,000 microseconds remaining. A cohort is released at its exact recorded
expiry, after that step's active-population propagation; the released population
can fire again during subsequent steps. Recovery and trace decay use the actual
elapsed seconds; the filtered trace uses each segment's average absorption rate.
No queue-index shift is used as a substitute for elapsed time.

The complete state contains six tensors per Cell, in this order:

| Slot | Meaning |
| --- | --- |
| 0 | filtered absorption trace |
| 1 | active spatial-bin masses |
| 2 | refractory cohort masses, with a variable final dimension |
| 3 | recovery |
| 4 | cumulative upper escaped mass |
| 5 | nondecreasing remaining cohort lifetimes in integer microseconds |

Lifetimes are stored in the checkpoint's FP32 or FP64 tensor precision; all
integers from 1 through 240,000 are exactly representable in either format.
Explicit legacy migration may admit longer remaining lifetimes up to `2²⁴`
microseconds, which also remain exact in both formats. Equal-expiry cohorts are
allowed; their masses release together. They are scheduling metadata, not differentiable parameters. The mass tensors
remain in the joint autograd graph throughout the block. Zero-mass cohorts use
the same schedule so control flow never depends on a learned threshold.

Before numerical work, the worker plans the complete event schedule from the
admitted initial lifetimes. Each coarse interval is capped by `max_substeps`;
the whole block and queue each have an independent 4,096-entry cap. Restored
expiries count against the event budget. The tensor-work estimate includes the
actual number of event steps and the carried cohorts. An exceeded budget
rejects before a transition kernel runs.

The native plan uses `substep_micros` for the maximum allowed numerical step and
`substeps` for the event-step budget. This new profile does not claim that their
product equals elapsed time. The native planner checks the minimum required
step count; only the worker with the authenticated complete state can know the
additional expiry splits. Profile identity includes a distinct canonical tag 2,
`max_step_micros` and `max_substeps`.

## What the tests establish

Tests execute unequal microsecond intervals, an expiry one microsecond after a
checkpoint, complete state loading in a new process, all eight scalar parameter
finite differences, input derivatives, total mass checks, and event-budget
rejection before the numerical kernel. Grouping intervals at already selected
numerical boundaries reproduces the same recurrence exactly.

For fixed face drift, the new kernel obeys the matrix-exponential semigroup on
its discrete spatial grid. It avoids the legacy killed-density kernel's repeated
bin-centre projection, which can freeze transport as time steps shrink. This
property does not make the full nonlinear renewal model an exact continuous-time
solution. Drive and recovery remain frozen within each step, absorption is
timestamped at the numerical right boundary, and the spatial upwind generator is
an approximation. Splitting a step at a new input boundary changes the recurrence.
Temporal refinement, spatial convergence and scientific benefit remain separate
checks; old CUDA results qualify only the unchanged legacy profile.

## Bounded numerical evidence

`test_population_generator.py` constructs an independent NumPy face-flux
generator and compares its SciPy exponential with the implementation. It checks
probability conservation and nonnegativity, fixed-generator semigroup replay,
nonzero transport after 800 one-millisecond steps, and scalar drift derivatives
away from upwind kinks. For zero-drift Brownian motion it also checks the exact
finite-volume mean-exit error `h²/(8D)` and its fourfold reduction when spatial
resolution doubles. This linear spatial check is separate from the nonlinear
network test.

A CPU FP64 observation uses two width-one Cells, 32 spatial bins, all weights
0.3, biases 0.1, a held input 0.25, and 800,000 microseconds elapsed. There are no
optimizer updates. The first Cell's final filtered trace is:

| Maximum step | First Cell trace | Absolute difference from 1 ms reference |
| --- | --- | --- |
| 100 ms | 1.059229782582455 | 0.034263469665152 |
| 25 ms | 1.079513704633142 | 0.013979547614466 |
| 6.25 ms | 1.090067689746625 | 0.003425562500982 |
| 3.125 ms | 1.092079608728940 | 0.001413643518668 |
| 1 ms | 1.093493252247608 | 0 |

The 1 ms row uses 800 event steps; the largest observed complete-state mass error
in this observation is `2.8e-14`. This is a finite-grid temporal refinement check.
The finest row is a numerical reference, not an analytic continuous-PDE oracle.
The test suite additionally differentiates the task loss after loading a
first-block candidate and validates all eight scalar derivatives of the resumed
block against independent central finite differences.

## Explicit legacy migration

`migrate_fixed_grid(source, state, max_step_micros=..., max_substeps=...)` returns
a new age model and detached complete state. It validates the source state,
copies all five numerical slots and all model tensors, then gives old queue slot
`j` the exact remaining lifetime `(j+1)*old_step_micros`. Thus a pending 300 ms
tail from a 100 ms legacy grid remains 300 ms. New absorbed mass subsequently
uses the new 240 ms physical residence. Cohorts are stably sorted as new cohorts
can expire before old tails; equal expiries are retained and released together.

The new graph specification records `legacy_step_micros`, whose integer ceiling
of the legacy refractory duration bounds the permitted remaining lifetime. It
also records `kernel="upwind_ctmc_v1"`; both fields participate in graph identity
and schema-3 serialization. Migration fails if legacy times exceed the exact
FP32 integer bound, and never mutates the source. It is an explicit model/profile
transition that the existing owner must admit as a new training lineage. Merely
loading schema 2 still restores the original fixed-grid model and original
queue. A migrated checkpoint can subsequently resume its complete six-slot
state under the new profile.
