# Differentiable complete-distribution renewal kernel

`joint_kernel.py` defines a finite-space, continuous-time Markov process with
31 active internal voltage representatives and two refractory modes. It retains
the complete 33-state mass. A row mass advances as `p @ exp(dt*Q)`; no event
probability is substituted for event count, and no new event is forced to remain
refractory until an external interval ends. Matrix exponentiation integrates
all finite-process boundary/recovery/reset cycles in the available time.

This is a new opt-in finite CTMC interface. It does not change any earlier
frozen cell, trajectory sampler, model, or confirmation result. Its deterministic
state mass is distinct from the earlier sampled trajectory checkpoint containing
an already drawn, known refractory residual time.

## State and generator

For odd `n_grid>=31`, active coordinates are
`x_j=b*(-1+2*j/(n_grid+1))`, `j=1,...,n_grid`. State order is active coordinates
ascending, lower refractory, upper refractory. Refractory coordinates used by
digital indicators are `-b,+b`. `initial()` returns the central active atom;
callers can supply any valid full initial distribution, including public
balanced bimodal priors.

Let `dx=2*b/(n_grid+1)`. Each active state has rates

\[
q_+=\frac{\sigma^2}{2dx^2}+\frac{\mu}{2dx},\qquad
q_-=\frac{\sigma^2}{2dx^2}-\frac{\mu}{2dx}.
\]

Interior jumps go to adjacent active states. An outward jump at the first or
last active state enters the corresponding refractory mode. The active diagonal
is `-(q_++q_-)`. A refractory row releases at rate `gamma` into the declared reset
mass, with diagonal `-gamma`. Reset mass is the continuous Gaussian probability
in the active representatives' Voronoi bins, divided by its probability inside
`(-b,b)`. Its means and standard deviation are trainable. Tail probabilities use
reflected `log_ndtr` intervals and `expm1`, avoiding direct `1-1` tail subtraction.
No defective generator row is repaired by clipping or renormalizing expm output.

The declared envelope is `b∈[.8,1.2]`, `sigma∈[.35,.8]`, `|mu|<=1.1`,
`gamma∈[.25,2]`, reset centers within `.6*b`, and reset SD within `(0,.12*b]`.
At the coarsest supported grid, `dx<=.075`; consequently both active rates are
at least `(0.1225-1.1*.075)/(2*.075^2)=3.55555556`, so rate positivity is uniform
on this envelope. Larger grids preserve that property. `ordinary` mode is a
finite reflecting-chain mechanism control obtained by suppressing outward jumps;
its refractory states are unreachable and its reset/recovery coordinates are
inactive. It is not the sole strong ordinary baseline in the joint task.

The eight unconstrained raw coordinates map as follows:

| Raw coordinate | Physical map |
| --- | --- |
| boundary | `.8+.4*sigmoid(r0)` |
| diffusion | `.35+.45*sigmoid(r1)` |
| gain | `.9*tanh(r2)` |
| drift_bias | `.2*tanh(r3)` |
| reset_plus | `.6*b*tanh(r4)` |
| reset_minus | `.6*b*tanh(r5)` |
| recovery_rate | `.25+1.75*sigmoid(r6)` |
| reset_sd | `b*(.06+.06*sigmoid(r7))` |

`mu=drift_bias+gain*symbol*(2*reliability-1)`. Signed gain permits exact zero with
a nonzero local derivative. External public drive may use `symbol=±1,r=1`;
observational noise need not be reused as physical drive. If a task always uses
`symbol=0` or `reliability=.5`, gain is inactive and must be counted accordingly.
With `learn_boundary=False`, the boundary uses a separate immutable buffer;
optimizer weight decay on unused raw zero does not move the fixed boundary.

## Learning interface

All tensors use float64. Context and duration tensors use standard broadcasting:

- `generator(symbol,reliability)` returns `[...,33,33]`.
- `transition(dt,symbol,reliability)` returns `matrix_exp(dt*Q)`, for `dt∈[0,2]`.
- `advance_distribution(mass,dt,symbol,reliability)` propagates complete mass.
- `bank_features(symbol,reliability)` returns `[...,33,9]`; multiplying by mass
  gives the nine conditional future probabilities.
- `features(...)` returns nine bank columns, normalized coordinate, and two mode
  flags. `free_features(...)` separately exposes the earlier free-endpoint form.
- `expected_events(mass,dt,...)` uses an augmented matrix exponential to
  integrate boundary event intensity, including repeated events.
- `physical_from_raw` and `generator_from_physical` are functional interfaces for
  independent derivatives and same-generator baseline initialization.

The default bank is reset-aware for this finite CTMC: for horizons
`.25,.75,1.5` and relative thresholds `-.5,0,.5`, it computes
`exp(h*Q) @ 1{x/b>threshold}`, including refractory states. Calls use strict `>`;
puts are their complements. These are constant-context forecasts. When a public
future drive schedule changes, actual scheduled forecasts require products of
the relevant interval transitions. The bank alone is not a deadline task
success probability or an independent additional information source.

The full raw, physical, transition, reset, bank and prefix-mass computations
remain in the autograd graph. The qualification differentiates deterministic
finite-law sums and matrix exponentials. It does not estimate gradients by
perturbing rare Monte Carlo paths. Content-likelihood conditioning, head losses,
action choice and the task controller are separate layers with their own
qualification; this kernel does not supply private labels or teacher posteriors.

## Qualification and limitations

Run from the repository root:

```bash
PYTHONPATH=/tmp/hcsn-torch-runtime python3 -m tools.hcsn.digital_joint_20261102.joint_kernel_validate --attempt NEW_ID
```

The installed CPU runtime is Torch `2.15.0+cpu`, NumPy `2.3.5`, SciPy `1.17.0`.
The test fixes Torch to one CPU thread and preserves exclusive source snapshots
for each attempt. Attempt 001 retained a legacy PDE-script import-path failure
before numerical checks; attempt 002 fixed only the new validation import and
passed 47 checks. See `joint_kernel_RESULT.md` for all measured errors, including
coarse-grid continuum bias and the independent audit.

Time-continuous expm and its gradients are qualified for the finite generator,
up to float64 numerical error. Space remains discretized. At grid 31, the
registered Brownian killed-law stress cases have maximum absolute error about
`.009742`; refining to grid 127 reduces this to `.0005808`. These registered
comparisons do not prove a uniform continuum error bound. Exponential recovery
is memoryless; a refractory mode mass is sufficient for its unobserved holding
clock. An externally known deterministic residual duration or an age-dependent
recovery law requires a richer state representation.

Simultaneously scaling `b,sigma,mu,reset centers,reset SD` leaves normalized `Q`
unchanged. Reset means/SD are already normalized in their bin probabilities.
Thus eight nonzero raw partial derivatives do not imply eight independently
identifiable physical directions. The finite global learned boundary has a
scale gauge, and does not implement a time-moving or task-value free boundary.
No continuum-gradient, unique parameter recovery, task-benefit, Rust parity,
energy-saving or production qualification follows from these kernel checks.
