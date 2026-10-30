# Independent audit of the neural mean-state closure

## Finding and scope

The implemented neural recurrence is a usable, explicitly approximate
architecture, but it is **not a consistent time discretization of the exact
scalar regenerative process**. Reducing the observation interval alone can
increase its error: the recurrence repeatedly replaces a distribution by its
mean and treats that mean as the next exactly observed starting state.

This finding does not refute the scalar QVI theorem or the first-passage kernel.
It identifies the difference between their contracts and the new neural mean
recurrence. Task-quality comparisons can evaluate that recurrence as an
architecture. They cannot certify exact stochastic propagation, calibrated
sample-path event probabilities, or physical event costs merely by citing the
scalar theorem.

The audit reads `model.py` and `oracle_torch.py` without changing them. It uses
fixed physical parameters and no training data, learned checkpoint, or test
benchmark outcomes. `results/closure001.json` records the source hashes it
actually inspected. Channel-feature revisions that preserve the voltage and
refractory recurrence do not change the mathematical comparison, but the audit
must be rerun to bind the final source bytes.

## Independent reference

For a fixed threshold \(b\), reset \(r\), and initial active state \(x<b\), write
\(C(T)=\mathbb E[N_T]\). The nth firing-time identity from `MATH.md` gives

\[
 C(T)=\sum_{n\ge1}F\!\left(T-(n-1)\tau;
             (b-x)+(n-1)(b-r),\mu,\sigma\right).
\]

With \(\tau>0\), this is a finite sum. A term with nonpositive remaining time
vanishes. Let \(D_T\) be time actually spent refractory before T. Each event
contributes its truncated refractory interval, so

\[
 \mathbb E[D_T]=\int_0^{\min(\tau,T)}C(T-u)\,du,
 \qquad \mathbb E[R_T]=\tau C(T)-\mathbb E[D_T].
\]

The actual active time is \(A_T=T-D_T\). The state satisfies

\[
 X_T=x+\mu A_T+\sigma W_{A_T}+(r-b)N_T.
\]

Since active time is bounded by T, the stopped stochastic integral has zero
mean. Thus

\[
 \mathbb E[X_T]
 =x+\mu\{T-\mathbb E[D_T]\}+(r-b)C(T).
\]

An initial state already at/above b is handled by an immediate event, its reset,
and the complete initial refractory duration. These mean identities and a
one-dimensional numerical integral are the primary reference. Integration
error estimates are recorded; they are not interval-arithmetic bounds on every
floating-point operation.

### Random reference with no Euler crossing bias

Each scenario also runs 60,000 independent trajectories. Active first-hit
times are sampled from the exact inverse-Gaussian law. For negative drift, the
sampler separately includes the defective eventual-hit probability
\(\exp(2\mu d/\sigma^2)\); conditional on a hit it uses the positive-absolute-drift
law. The simulation uses actual hit times, reset, and deterministic refractory
expiry, including repeated firings within an observation interval.

When the remaining interval survives, its terminal state is sampled from the
killed Gaussian kernel. A Gaussian proposal truncated below b is accepted with
Brownian-bridge survival probability

\[
 1-\exp\{-2(b-x)(b-y)/(\sigma^2t)\}.
\]

This is an endpoint distribution conditional on no hit, not an unconstrained
Gaussian endpoint. No Brownian Euler grid is used. Pointwise 95% normal
confidence intervals quantify Monte Carlo error. All reference/Monte Carlo
z-scores in this run are below 1.46 in absolute value. The predeclared diagnostic
gate is absolute z below 5, not a hypothesis test for neural superiority.

## Measured mean-closure bias

The following are physical-state/count comparisons with coefficients held
fixed throughout. The source exposes `activity` as one interval's local first-hit
mass; summing it is a proxy, not necessarily the true number of repeated events.

| Scenario | Total time | Exact expected events | Closure events, coarse dt | Closure events, small dt | Exact mean voltage | Closure mean voltage, small dt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Positive drift, initially at reset | 4 | 0.392218 | 0.177324 at dt=1 | approximately 0 at dt=0.03125 | -0.000093 | 0.800000 |
| Negative drift, near boundary | 2 | 0.721807 | 0.668879 at dt=1 | 0.103894 at dt=0.03125 | -0.623992 | 0.202966 |
| Several possible firings | 12 | 3.710644 | 2.508393 at dt=4 | 3.302384 at dt=0.125 | 0.588282 | 1.330901 |
| Initial state above boundary | 1 | 1.002034 | 1.000000 at dt=1 | 1.000000 at dt=0.03125 | -0.029050 | -0.032813 |

The first case tends toward a deterministic mean path when the step becomes
small; no individual short step injects the missing distribution of states
accumulated during previous steps. This is an O(1) distribution-closure error,
so assigning a general weak convergence order in dt would be incorrect.
The negative-drift case confirms that this is not confined to upward drift.

There is also a direct inconsistency argument. Suppose the deterministic path
\(x+\mu t\) stays at least epsilon below b throughout a fixed time T. For small
enough dt, one-step hitting masses at this point state are bounded by
\(C\exp(-c/\Delta t)\) for positive constants C,c. Over T/dt steps their sum
still tends to zero. The mean closure therefore approaches the deterministic
path and reports zero activity, whereas a nondegenerate diffusion has positive
probability of crossing before T. For nonnegative drift its limiting mean-state
bias is

\[
 \{x+\mu T\}-\mathbb E[X_T]
 =\mu\mathbb E[D_T]+(b-r)C(T)>0.
\]

In the first recorded case this limit is approximately 0.800093. Thus the
failure to converge is structural, not an insufficiently fine tested grid.

In the third case, counting only one first-hit mass per long observation loses
approximately 1.20225 expected events. Therefore `K * activity` must retain its
**proxy-cost** interpretation. It is not a measured number of physical firings,
joules, processor time, or complete regenerative execution cost.

## What has a local error bound

For an initially active, exactly observed point state and an interval
\(\Delta t\le\tau\), a first hit cannot finish its refractory period before the
interval ends. In that special case, the implemented killed first moment plus
\(rF(\Delta t)\) gives the exact terminal mean voltage, and its event mass is
the exact expected count. The remaining refractory time is still biased:

\[
 R_{\rm closure}-\mathbb E[R_{\Delta t}]
 =\int_0^{\Delta t}F(s)\,ds
 \in[0,\Delta t F(\Delta t)].
\]

The audit verifies this identity at dt=0.05, 0.1, 0.2, and 0.3. Measured biases
are approximately 0.004388, 0.020542, 0.070770, and 0.133092. Away from the
boundary, the small-time hitting probability can be very small; close to the
boundary this is generally an O(dt) timing bias. This single-interval statement
does not remove the repeated distribution-collapse error above.

Using mean refractory time also changes the next active clock. Convexity gives

\[
 (\Delta t-\mathbb E[R])_+
 \le \mathbb E[(\Delta t-R)_+].
\]

For example, when half the paths are active and half have one unit of
refractory time left, dt=0.1 yields true expected active time 0.05. Substituting
the mean remaining cooldown gives zero. No smaller root-solver tolerance can
repair this lost mixture state.

## Boundary, large-time, and numerical interfaces

- Moving an input-dependent boundary below the existing mean state produces
  the initial-hit branch. The mean recurrence places that reset at the interval
  end, which loses usable post-hit time. The scalar reference applies it at the
  initial instant for a positive observation duration.
- The audit found an initial-atom omission in the helper
  `simulate_event_interval`: initial x=1.01, boundary=1, drift=-1, sigma=0,
  dt=0.1, and one substep previously reported zero events. The implementation
  owner repaired this before source freeze. The audit now requires one initial
  event before substep propagation and records the regression in the JSON.
  Later crossings still occur at grid endpoints, so this helper remains an
  explicitly discretized reference. Zero-duration neural observations remain
  no-ops; that convention differs from the scalar oracle's initial-hit atom.
- The initial-hit branch, nonnegative active-time clamp, and reset branches
  remain piecewise operations. Smooth fit of the optimal J/G values does not
  make the entire neural recurrence globally analytic.
- Across 270 moderate parameter combinations covering both drift signs,
  boundary distances 0.0001 to 10, sigma 0.15 to 2, and intervals 0.01 to 32,
  float32 versus float64 maximum CDF error was about \(8.95\times10^{-8}\).
  The largest probability-mass defect was \(1.19\times10^{-7}\); all inspected
  outputs and first gradients were finite. The largest scaled gradient
  difference was \(3.25\times10^{-5}\). This does not certify arbitrarily extreme
  finite floating-point inputs or higher-order derivatives.

## Frozen statistical interpretation for the mechanism study

The pre-outcome protocol uses the two fixed mechanism tasks and eight paired
training seeds. For each comparator, compute each seed's equal-weight mean
accuracy difference across those two tasks first. There are eight independent
seed units, not sixteen independent task-by-seed units. The six contrasts
against the designated free-dual arm form one Holm family.

The proposed acceptance rule requires all three conditions: Holm-adjusted
two-sided p at most 0.05; a mean improvement of at least 0.01 absolute accuracy;
and a positive lower bound of the paired 95% interval. Exact sign-flip
enumeration has minimum two-sided p=2/256=0.0078125 at eight seeds. Its
exactness for the mean relies on sign exchangeability/symmetry under the null;
it is not an unconditional distribution-free test. A paired-t interval with
seven degrees of freedom is a nominal small-sample interval, not a simultaneous
interval for all six comparisons. Holm supplies the multiple-testing gate.

The three-seed broad task table is descriptive. Two fixed mechanism tasks do
not support inference to an unspecified population of tasks. Learning-rate
selection must use validation only, and failures or missing seed pairs must
follow the predeclared failure rule, rather than being silently removed.
No effect threshold, task weighting, direction, budget, or test method should
be changed after viewing test outcomes. None of those outcomes was inspected
for this closure audit.

## Reproduction

From the repository root, with NumPy, SciPy, and Torch available:

```bash
python -m experiments.hcsn_free_boundary_v1.closure_audit
```

The result status deliberately reads
`passed_with_measured_approximation_bias`. It means the audit ran and its
independent references agreed; it does not mean the neural closure has passed
an exact-regeneration acceptance criterion.
