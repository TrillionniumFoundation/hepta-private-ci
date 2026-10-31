# Round 7 dynamics: three different contracts

`dynamics.py` provides a differentiable probability-mass implementation. It
does not treat a terminal crossing, a first passage, and a recurrent event count
as the same random variable. It does not use a straight-through estimator.

## Common state, process and interface

The active process during an update is

\[
dX=(d-\kappa X)dt+\sigma dW,
\]

where the externally supplied content drive `d` is frozen during that update.
The physical voltage nodes are

\[
x_i=b\left(-1+\frac{2(i+1)}{N+1}\right),\quad i=0,\ldots,N-1.
\]

`N` is odd, so zero is a node. The two additional states denote positive-event
and negative-event refractory modes. State mass has shape `[batch, N+2]` and
initially puts unit mass at zero voltage. Float64 is used throughout.

```python
cell = EventDynamics("clocked", n_grid=15)
mass = cell.initial(batch)
mass, events = cell(mass, drive, dt=1.0)
features = cell.state_features(mass)
```

`drive` has shape `[batch]` or `[batch,1]`. `events` has shape `[batch,2]`, in
positive/negative order. `features` contains unconditional voltage mean,
variance, positive refractory mass and negative refractory mass. Refractory
voltage moments include the reset distribution's variance. Neither the active
nor refractory variance is replaced by the square of its mean.

`transition_matrix(drive,dt)` separately exposes a row-source Markov transition
of shape `[batch,N+2,N+2]` and an event reward tensor `[batch,N+2,2]`. This lets a
value oracle and an independent rollout consume the same declared process.
It does not establish that a controller using only the four summary features
has the same information as one using the full distribution.

## Learned parameters and bounds

Smooth physical transformations define:

| Group | Parameters | Physical range |
|---|---|---|
| Dynamics | leak `kappa`, diffusion amplitude `sigma` | `0 < kappa < 2`, `0.05 < sigma < 0.80` |
| Boundary | symmetric magnitude `b` | `0.35 < b < 2` |
| Reset | independent reset centers `r_plus`, `r_minus` | `-0.75 b < r < 0.75 b` |
| Recovery | end-of-tick release probability `q` | `0.05 < q < 0.95` |

The content encoder and task readout belong to the calling model. Gradients
through the caller's drive are retained. Bounds are part of this finite
experiment, not physical laws. The symmetric boundary is a scope limitation;
independently learned upper and lower boundaries are not claimed.

Reset is a *stochastic* distribution: Gaussian with learned center and fixed
standard deviation `0.08 b`, projected onto the voltage nodes. Projection
folds Gaussian tails into edge bins. This deliberately avoids pretending that
a smooth assignment is an exact deterministic point reset. `physical_parameters`
reports the underlying center; the discrete reset mean can differ slightly.

## 1. Continuous distribution mode

The exact frozen-input OU Gaussian transition is integrated over nearest-node
bins, then all tails are projected into the two extreme bins. There are no
events, absorption or refractory transitions from the initial state. The last
two state entries are unused placeholders.

This is a finite-grid distribution propagation model. It is **not** an exact
unbounded OU law after repeated projection, and it is not a spiking model.
The boundary parameter is a projection scale in this mode, not a firing
threshold. Large drive can saturate the representation. Comparisons must
report this limitation and must count continuous communication separately from
event communication.

## 2. Clocked endpoint mode

For each active source node, the frozen-input OU transition has

\[
m=e^{-\kappa\Delta}x+
\frac{1-e^{-\kappa\Delta}}{\kappa}d,\qquad
s^2=\frac{\sigma^2}{2\kappa}(1-e^{-2\kappa\Delta}).
\]

The event probabilities are the two *terminal* tails:

\[
p_+=\Phi((m-b)/s),\quad p_-=\Phi((-b-m)/s).
\]

The remaining Gaussian mass is integrated over the interior voltage bins.
Positive/negative events enter their corresponding refractory states at the
end of the tick. Crossing and returning before the tick ends does not produce
an event in this mode. Event probabilities at a fixed source point are exact
for the stated OU transition; repeated projected-state propagation is a grid
approximation to a continuous-state process.

These two opposite thresholds leave an idle event, so
`p_plus + p_minus + p_idle = 1`. They are not same-strike digital call/put
complements. No binary call-put parity is asserted for this two-boundary cell.

## 3. First-passage mode

The OU generator is approximated on the same voltage grid. With mesh spacing
`h=2b/(N+1)`, drift `mu_i=d-kappa*x_i`, and `D=sigma^2/2`, rates are

\[
q_{i,i+1}=D/h^2+\max(\mu_i,0)/h,
\quad
q_{i,i-1}=D/h^2+\max(-\mu_i,0)/h.
\]

An outward neighbor of an endpoint is a positive or negative absorbing state;
the diagonal is minus the total outward rate. The matrix exponential
`exp(dt*Q)` gives surviving transitions and the probabilities of the **first**
absorption at either boundary within the tick. It accounts for crossings
between observation ticks in this continuous-time *finite-state* model.

The first-absorption law is exact up to floating-point matrix-exponential error
for this CTMC. It is only a numerical approximation to the continuous OU
first-passage law. The upwind drift adds numerical diffusion and introduces
first-order spatial error; it can change measured firing probabilities and
cannot be advertised as an architectural benefit. Grid convergence and an
independent reference are required. A Brownian zero-drift subcase is checked
against an independent infinite-series survival formula in the tests.

## Reset, recovery and recurrence

An event freezes its path for the remainder of its tick and enters one of the
two refractory states. Old refractory mass is released with probability `q`
at the **end** of a subsequent tick into its reset distribution. Released mass
starts evolving only in the following call. Newly emitted mass cannot recover
or fire again during its event tick.

Thus the model has at least one complete refractory tick and at most one event
per path per tick. It allows repeated events across ticks. The number of whole
refractory ticks is geometrically distributed with mean `1/q`. If `dt` changes,
the physical recovery time changes too; experiments must hold `dt` fixed unless
this discrete recovery law is intentionally changed. It is not an inferred
continuous-time recovery hazard.

This contract intentionally does not resolve an exact intra-tick event time,
nor a deterministic continuous recovery deadline, nor multiple events within
a tick. The task must not award a fictitious latency saving from unobserved
subtick event timestamps.

## Training semantics

Every transition, event probability, reset distribution, and release is part
of the PyTorch graph. A finite-horizon loss that propagates the full mass and
uses the actual transition rewards can have an exact gradient for this
finite-state distribution model, apart from floating-point error and the
piecewise-differentiable upwind rate at zero drift.

This fact does **not** make a loss on averaged features equal to the expected
loss of a hard sampled event network. For a nonlinear task,
`L(E[state])` and `E[L(state)]` generally differ. The caller must state which is
trained, and hard-event rollout quality must be measured independently.
Likewise, exact Bellman iteration for the grid model is not a proof that the
continuous diffusion's QVI or a deployed Hepta task has been solved.

## Truncated moments: independent check

For `X ~ Normal(m,s^2)`, lower and upper standardized bounds
`a=(-b-m)/s`, `c=(b-m)/s`, the retained first moment is

\[
E[X\mathbf1_{-b<X<b}]
=m(\Phi(c)-\Phi(a))+s(\phi(a)-\phi(c)).
\]

Adding the two reset means times their event probabilities gives the true
one-tick post-reset mean before voltage projection. Replacing the retained
term by `m * P(-b<X<b)` drops a truncation term. The tests compare this formula
to independent SciPy quadrature, then compare the high-resolution cell's mean
to that reference. This is a contract check, not an allegation about previous
repository implementations.

## Validation

Run in the supplied runtime without modifying the shared environment:

```sh
PYTHONPATH=/tmp/convergence-smollm-runtime/lib/python3.12/site-packages python -m unittest experiments.analytic_event_neuron.round7.test_dynamics -v
```

The tests use one CPU thread and check probability conservation, independently
computed OU terminal tails, an independent SciPy CTMC exponential, Brownian
first-passage mesh convergence, refractory timing, recurrent counts exceeding
one, projected truncated moments, all six learned parameter derivatives
against central finite differences, and continuous-mode projection without
invented events. These are mathematical and implementation checks, not
evidence of task-level superiority or production readiness.

## Independent corner audit: numerical promotion is blocked

`numerical_audit.py` records diagnostic accuracy gates in
`evidence/numerical_audit.json`. It leaves the registered generator unchanged.
The gates concern whether results can be promoted from the finite-grid model
to a continuous-process interpretation. A failed gate is not automatically an
implementation defect: a perfectly valid CTMC can poorly approximate the
diffusion it was meant to represent. Diagnostic tolerances were chosen after
the exploratory failures were observed and are not preregistered statistical
acceptance claims.

The most significant issue is drift-induced numerical diffusion. At an
interior node the upwind CTMC's instantaneous second-moment rate is

\[
\sigma_{\rm effective}^2=\sigma^2+|\mu_i|h.
\]

Thus a coarse-grid FPT cell can emit more frequently because of numerical
noise. Learning a small physical `sigma` does not remove that extra noise.

An independent killed-Brownian boundary-flux series gives the positive first
exit probability `0.5857766596` for drift `1`, sigma `0.45`, boundaries `+-1`,
time `1`, initial voltage zero. The negligible-leak cell gives:

| Voltage grid | Positive first-exit probability | Absolute error |
|---|---:|---:|
| 9 | 0.6071508573 | 0.0213741977 |
| 15, primary diagnostic grid | 0.6014271659 | 0.0156505062 |
| 31 | 0.5951583465 | 0.0093816869 |
| 63 | 0.5910475233 | 0.0052708637 |

Mesh refinement reduces this error, but none of these grids passes an absolute
probability tolerance of `0.001` for this probe. This is a Brownian subcase
with negligible leak, not a measurement of a trained checkpoint's default OU
parameters.

The low-noise probe is substantially worse. For sigma `0.05`, drift `1`, time
`0.8`, and the same boundary/initial point, the true upper-hit probability is
approximately `4.321826e-6`; accounting for a competing lower boundary changes
it by at most `exp(-800)`. The grid-9 approximation is about `0.37278`, and
even grid 63 is about `0.13308`. This parameter regime is not an accepted
continuous-OU approximation. It remains a numerical promotion blocker even
if task training improves its finite-model objective.

There are three additional scope limits:

1. **Small time steps at fixed voltage mesh.** Gaussian endpoint binning can
   freeze the voltage state. With grid 9, zero drift, sigma `0.45`, and
   `dt=0.001`, its one-step variance is only about `4.16e-10` times the true
   Brownian variance. Reducing `dt` alone is not a convergence test; the voltage
   mesh must be refined so quantization does not dominate the transition.
2. **Physical recovery time.** The current mean number of whole refractory
   ticks is `1/q`, hence mean duration is `dt/q`. At `q=.65`, changing `dt`
   from `1` to `.1` changes that duration from about `1.538` to `.154`. The
   multiwindow cohort law `(1-q)^k` is correct, but a fixed-q time-step sweep
   changes the physical process. A fixed continuous recovery rate would need
   a different, explicitly specified `q(dt)`.
3. **Non-Gaussian internal increments.** Equal mean and variance do not imply
   the Gaussian terminal tail. At three standard deviations the Gaussian
   upper tail is `0.0013499`, while equal-variance Laplace and Student-t(3)
   tails are about `0.0071848` and `0.0069234`. This is a hypothetical noise-law
   substitution audit. Non-Gaussian content inputs by themselves do not
   invalidate a Gaussian transition conditional on each frozen input.

The audit emits individual PASS/FAIL records for probability conservation,
mesh-refinement progress, absolute FPT accuracy, small-time-step variance,
refractory cohort timing, physical-time invariance and heavy-tail calibration.
Passing the implementation tests does not override failed accuracy gates.

The frozen normal-CDF implementation has a separate extreme-tail limitation
in the recorded PyTorch 2.9.1 CPU runtime. In Float64,
`torch.special.ndtr(-8)` returns about `6.10623e-16`, whereas SciPy and the
`0.5*erfc(-z/sqrt(2))` formulation give about `6.22096e-16`. At arguments `-9`
and `-10`, the registered call returns zero; the independent references are
`1.1285884e-19` and `7.6198530e-24`. This cancellation matters for rare-event
calibration or a future log-likelihood objective. No claim of reliable extreme
tails is made. The dynamics source was intentionally kept fixed after the
primary training run started; changing CDF evaluation would require a
separately identified source and rerun. This tail issue does not explain or
remove the much larger upwind errors measured above.

```sh
PYTHONPATH=/tmp/convergence-smollm-runtime/lib/python3.12/site-packages python -m experiments.analytic_event_neuron.round7.numerical_audit
```

## Full task-return gradient audit

`test_joint_control.py` additionally checks the caller's complete return
recursion, rather than only differentiating a state-feature surrogate. For
each event mode, it explicitly enumerates 16 latent external worlds and
1,552 internal-state/action leaf paths at horizon two. Policy inputs remain
public features; actual rewards come from `task.step`, without using the
oracle transition or reward functions. The explicit sums and the control
graph agree to about `2.3e-16` or better in the audited fixtures.

Finite differences of compute/event prices equal the independently counted
expected numbers of decisions/events, including the terminal STOP decision.
At horizon four, full-return derivatives of all six core parameters, an
encoder weight, the drive bias and a readout weight match central finite
differences; the largest absolute discrepancy in the recorded audit is
`1.1e-10`. A horizon-one forced-STOP probe charges the already incurred
transition/compute/event costs once and has zero reset/recovery return
derivatives, as required when there is no future opportunity to use them.

These checks validate gradients of the finite model under its soft policy.
They do not certify a marginalized-Q greedy policy, a continuous diffusion
model, or task-level superiority. The raw measurements are saved in
`evidence/joint_control_audit.json`.

The final refinement's one-step head is also aligned to the internal cost
contract. Its target includes current action/compute cost, then the next
core transition's expected event charge and the next forced STOP's compute
and task costs. The current incoming event charge is already sunk at the
post-transition action-value state and is counted separately in the before-
transition value. `graph.myopic` remains an external-task-only construction
field; refinement uses `myopic_targets`, not that field. An additional
16-world direct enumeration test checks the one-step targets, including zero
future reset/recovery dependence for an immediate STOP. The earlier external-
cost-only supervision is pretraining; both heads use the full stated cost
contract during joint refinement.

```sh
PYTHONPATH=/tmp/convergence-smollm-runtime/lib/python3.12/site-packages python -m experiments.analytic_event_neuron.round7.test_joint_control --evidence experiments/analytic_event_neuron/round7/evidence/joint_control_audit.json
```

## Learned-checkpoint resolution transfer

`resolution_transfer.py` reads saved checkpoints and transfers only named
learned parameters to newly built voltage grids. Encoder/readout parameters,
physical parameters and their byte-level digest remain identical; grid nodes,
bin edges and generator bases are rebuilt. Source checkpoint bytes are checked
again at the end and never rewritten. There is no optimizer or retraining.

The audit compares source-grid, grid-31 and grid-63 results in two ways:

- Identical public inputs: one-step event probabilities from zero, followed
  by repeated propagation on identical public oracle-policy traces. It records
  event counts, moments, refractory masses, continuous tail projection and the
  active-mass-weighted upwind extra-variance ratio using the **learned** drift,
  noise and boundary parameters.
- Action-dependent performance: finite-DAG expected return, decisions and
  events under soft dynamic, statewise greedy dynamic and one-step greedy
  policies. These values use each transferred model's own action probabilities
  and the full registered internal proxy fees.

The default public configuration indices are the short cases `1,4`, with
eight replay traces. Use `--config-indices 0 1 2 3 4 5 6 7` to audit the full
configuration set. The output names the subset, checkpoint/source hashes and
every fixed input trace. A short-case result must not be reported as covering
all configurations. The source checkpoint's grid is always included even if
it is omitted from `--grids`.

```sh
PYTHONPATH=/tmp/convergence-smollm-runtime/lib/python3.12/site-packages python -m experiments.analytic_event_neuron.round7.resolution_transfer --checkpoints PATH_TO_REGISTERED_CHECKPOINT.json --grids 15 31 63 --config-indices 1 4 --output experiments/analytic_event_neuron/round7/evidence/checkpoint_resolution_transfer.json
```

`test_resolution_transfer.py` checks identical parameter bytes and rebuilt
buffers, and verifies the counter/return recursion against `evaluate_graph`
and independent compute/event-price derivatives. Grid-transfer differences
remain deployment-sensitivity measurements. They do not establish continuous
OU accuracy, and a greedy decision can change discontinuously under a small
state/value perturbation.

