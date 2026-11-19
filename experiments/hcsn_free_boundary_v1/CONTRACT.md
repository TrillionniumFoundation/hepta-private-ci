# HCSN free-boundary v1 mathematical and event contract

## Oracle identity

The certified object is `scalar-regenerative-impulse-v1`: stationary arithmetic
Brownian state, upper firing boundary, immediate linear reward, fixed reset,
frozen mandatory refractory interval, and infinite-horizon exponential
discount. It is a new tractable oracle inspired by endogenous value boundaries;
it is not the He--Xiong debt/equity model. Its proof is in `MATH.md`.

| Quantity | Meaning | Validity / unit |
| --- | --- | --- |
| `x` | Active observable scalar state | state units; can be negative |
| `mu` | Active-state drift | state / time; finite |
| `sigma` | Diffusion coefficient | state / sqrt(time); nonnegative scalar oracle, positive Torch bridge |
| `rho` | Exponential discount rate | 1 / time; strictly positive |
| `K` | Cost subtracted from state at firing | state units; finite |
| `r` | State immediately after firing | same state units; strictly less than K |
| `tau` | Mandatory frozen refractory duration | time; nonnegative |
| `b` | Optimal upper firing threshold | derived from the value problem |
| `q` | Discounted probability weight of one reset/refractory cycle | dimensionless; not a firing probability or event count |
| `J` | Expected discounted sum of all firing rewards | reward units |

All learned reparameterizations must enforce the domain and preserve the chain
rule. Derivatives named `K` and `r` in the scalar solver hold the other physical
parameter fixed. The Torch custom boundary backward certifies first derivatives
only. It does not claim correct higher-order gradients.

## Event chronology

1. While active, the process evolves with its declared drift and diffusion.
2. On the first upper crossing, the event time is the crossing time. The reward
   uses the pre-reset state. In continuous diffusion the state equals the
   threshold at a crossing from below. An initial state already at/above the
   threshold fires immediately and uses its actual initial state.
3. The state resets once to `r`; the complete refractory duration is charged in
   the same clock used by discount and evaluation.
4. During refractoriness, state, content of this scalar oracle, and event count
   remain frozen. No new firing is permitted.
5. At refractory expiry the process resumes; later firings and their costs are
   included. A path that never crosses again contributes no additional reward.

A finite simulation may discretize this chronology, but must record the grid,
crossing approximation, overshoot treatment, reset count, refractory occupancy,
and remaining time. Rounding a hit to an observation boundary is not exact
continuous-time execution. Brownian substeps can miss within-step recrossings;
refinement or bridge correction is needed to quantify that error.

## Prediction objects are not interchangeable

| Output | Precisely predicts | Excludes |
| --- | --- | --- |
| `first_passage_cdf` | At least one upper crossing by elapsed time, from an active start | Unobserved-reset posterior, repeated event count |
| `first_passage_survival` | No upper crossing before elapsed time | Missing observation or absent communication |
| `first_passage_density` | Continuous density of the first crossing time | Initial-hit and deterministic atoms |
| `discounted_hitting` | First-hit probability weighted by discount at the hit time | Undiscounted event probability |
| `continuation_gap` | Optimal stationary value minus immediate-fire value | Probability, confidence calibration, or action execution |
| `finite_time_threshold_value` | Finite-time expected discounted reward from all repeated firings, via a finite/convergent first-hit series | Deadline-optimal threshold, full neural-state propagation |
| `renewal_reference` | Finite-time reward of a fixed threshold with repeated resets/refractory | Finite-horizon optimal threshold |

`first_passage_terms` in the Torch bridge returns `(cdf, survival, image_mass)`
for a single frozen-coefficient absorbing interval. The killed first moment is
exact for that interval. Resetting the entire absorbed mass at the interval end
is a mean-state approximation with no within-interval repeated firings.

## Relation to a trainable network

A high-dimensional content state, changing input-dependent drift, learned
gating, and feedback can be built around these operators. Such a model is
separately identified as a **frozen-local neural approximation**. Its boundary
is the optimum of each declared local scalar surrogate, not a proof of the
optimal action for the whole network or owner. Neither an observation-dependent
boundary nor joint training automatically converts the stationary theorem into
a finite-horizon theorem.

An evaluation must distinguish: continuous mean-state inference; simulated
sample-path events with actual reset/refractory actions; first-event-only
prediction; and stationary regenerative value. Shared input, model size,
training data, task reward, and compute budgets are required when comparing
fixed, directly learned, and value-derived boundaries. The exact same cost and
deadline information must be exposed to strong ordinary baselines.

## Neural implementation contract

`model.py` implements a **task-trained stationary regenerative boundary
inductive bias**. Classification cross-entropy jointly trains its vector
content, drift, diffusion, discount, latent firing cost, reset, refractory
duration, and gates. The stationary boundary equation is solved for these local
parameters. The classification loss does not establish that this boundary is
optimal for classification, a remaining deadline, an owner action, or an actual
read/compute charge. `K * event_probability` is a modeled latent quantity;
native owner reads and their externally declared costs are separate records.
Neither positive gradients nor improved task accuracy identify the latent
parameters as uniquely estimated physical quantities.

### State and one-interval approximation

Each neuron retains vector-content coordinates and scalar pressure coordinates.
At the start of a new sequence, pressure, content, refractory occupancy, and the
stored event statistic are zero. This is a declared initial condition, not an
assertion that the learned reset `r` is zero. An absorbed interval resets its
first-hit mass to the current learned `r`; a resumed sequence instead uses its
saved state and elapsed time.

For an observation interval, the input-dependent coefficients and boundary are
frozen. Conditional on a deterministic active starting pressure and duration,
the first-hit probability and killed first moment are the exact absorbing
Brownian expressions. The network adds `r` times the absorbed probability at
the **end** of that interval. It does not propagate the distribution of the
within-interval hit time, the time left after reset, repeated firings within
the interval, or uncertainty in the starting pressure. The resulting pressure
is one mean-state representative used in the next nonlinear update; applying
the next operator to this mean is not the exact propagation of a distribution.

The stored refractory coordinate is also a mean-state approximation. Active
time is `max(dt - stored_refractory, 0)` and the next stored cooldown mixes the
surviving previous cooldown with `event_probability * tau`. This interval-end
reset convention is not the expected residual cooldown of the exact sample
path, whose expiry depends on its random hit time. Consequently neither the
neural state update nor arbitrary time subdivision is claimed to satisfy the
exact regenerative semigroup.

Refractoriness suppresses pressure evolution and the first-hit statistic in
this neural implementation. The separate vector content continues to update
over the full observation duration. This differs explicitly from the complete
freeze of the scalar oracle's state during its refractory period. A
zero-duration observation preserves all recurrent coordinates and does not
fire. The neural update only applies an initial-hit atom when its active
duration is positive; it does not implement instantaneous events caused solely
by a moving boundary at zero elapsed time. Outputs may still depend on the
current observation through the residual signal even when recurrent state is
unchanged.

### Value features and experimental names

The neural auxiliary field `continuation` is the stationary value of the
declared threshold policy, including the immediate-fire branch for pressure
at or above the threshold. It is not the scalar oracle's `continuation_gap`, a
classification confidence, or a learned task-level advantage. Fixed and direct
boundary controls use their own threshold-policy values. Only the free-boundary
arm uses the stationary optimum of the specified scalar reward problem.

Writing `J` for this value, `J_b = (b - K) / (1 - q)`, and
`q = exp(-rho * tau - kappa * (b - r))`, the second value channel is the immediate
intervention obstacle `G(x) = x - K + q * J_b`. It is exposed as `intervention`;
`continuation_gap` is `J(x) - G(x)`. These are the value envelope and intervention
obstacle of this regenerative scalar problem, not financial Call/Put prices or
two independently solved option problems. `J` is also not a pure
continue-action Q value: it equals `G` throughout the intervention region.

At the free boundary the unscaled values match and both spatial derivatives
equal one. The same transform `z / (1 + abs(z))` is applied to both value
channels, preserving their value and first-derivative matching at that boundary.
Fixed and directly learned thresholds preserve value matching but generally
do not satisfy smooth fit. Their threshold-policy gap may be negative where
an immediate deviation would improve on that particular threshold policy; it
is not forced to be a nonnegative optimal advantage. No fixed restoring or
panic-force direction follows from these equations: the task-trained gate
weights determine how the two channels affect vector content.

The gate-feature ablations have the following literal meanings:

| Experiment name | Features supplied to the analytic gate contribution |
| --- | --- |
| `free_margin` | Scaled boundary distance |
| `free_continuation` | Scaled boundary distance and scaled stationary policy value |
| `free_dual` | Scaled boundary distance, scaled stationary policy value `J`, and scaled immediate-intervention value `G` |
| `free_ordinary` | Scaled boundary distance and two ordinary state/time/drift features |

All four retain the same absorbing-pressure and interval-end reset recurrence.
First-hit probability remains part of that recurrence and the recorded activity
signal; it is not the second value channel.
`free_ordinary` is therefore a gate-feature ablation, not an ordinary network
with all first-passage machinery removed. The separate `two_gates`,
`continuous_rnn`, and other benchmark architectures provide independent
baselines. Layer normalization, parameter preparation, and time features act
pointwise or on causal prefixes; preparing a sequence in one tensor operation
does not provide later observations to earlier states.

## Reproduction and artifact scope

`python oracle_tests.py` writes `results/oracle_validation.json`. If Torch is
unavailable its checks are recorded as `not_run`; success in scalar NumPy/SciPy
checks does not imply that autograd ran. The JSON binds the oracle, Torch bridge,
and test source bytes with SHA-256. It does not certify other packages,
repository-wide CI, multimodal quality, speed, energy, or deployment.
