# Shared-observation structural critic probe

This stage implements a bounded, supervised investigation of value and value-gradient
representations. It is **not a new actor–critic algorithm**, an rsEAC reproduction,
a production resource controller, or evidence that NDU improves real-task utility.
No actor is trained here. Every fitted critic chooses from the same finite legal
internal-state interventions. All original multimodal experiments remain unchanged.

## Explicit task and independent truth

Let the public internal state be `x` in dimension `d`. A chosen intervention has
destination `y`; then independent Gaussian internal noise gives
`Y = y + sigma * epsilon`, with `epsilon ~ N(0, I)`. Terminal quality is

\[
q(Y)=-\frac{1}{2d}\sum_i(Y_i-b_i)^2
       +\frac{k}{d}Y_0Y_1+0.15\sin(a^T Y),
\]

where `b = linspace(-0.25, 0.45, d)` and
`a = linspace(0.5, 1, d) / sqrt(d)`. Independent Gaussian integration gives

\[
V(x)=-\frac{1}{2d}\sum_i(x_i-b_i)^2-\frac{\sigma^2}{2}
       +\frac{k}{d}x_0x_1
       +0.15e^{-\sigma^2\lVert a\rVert^2/2}\sin(a^T x).
\]

The evaluator differentiates this expression analytically. Tests separately
integrate physical quality with tensor Gauss–Hermite quadrature and differentiate
that independent integral. Training does not call the analytic reference; a test
replaces it with an exception while acquiring observations and fitting every family.

Legal actions are STOP/keep, positive and negative coordinate adjustments, a joint
first-two-coordinate adjustment when capacity permits, and a probabilistic reset
to zero. All actions terminate. Adjustment charges are quadratic in displacement;
loading a nonresident coordinate costs an explicit fee. Reset pays its fee whether
or not it succeeds. Its value is `r V(0) + (1-r) V(x) - reset_fee`. Capacity is a
one-step touched-coordinate bound; there is no multi-step residency dynamics.

The 11 preregistered panels vary internal noise (zero, 1e-6, 0.2, 0.7), dimension
(2, 4), adjustment cost, complementarity, resource/residency limits, a biased training
simulator, and reset success probability. The bias panel shifts the simulator's
`b` by 0.3 while evaluation retains the original task. Every learner receives the
same misspecified simulator observations. This is a specified model error, not an
unobserved future-window result.

## Common observations and actual fitting

For each anchor, acquire quality at the center and both sides of every coordinate
with step 0.02. Eight Monte Carlo realizations share the same internal noise across
the full stencil. Each quality measurement also has independent sensor noise.
The identical full table is available to every method. Value critics fit all stencil
values; direct-gradient critics fit central differences derived from those values.
No exact gradient target is provided to a learner. The raw observations and their
digest are retained, so this common-information condition is reviewable.

Three genuine fitted representations are tested: linear ridge, quadratic ridge,
and a fully trained 12-unit tanh network. The first two solve regularized normal
equations; the neural model uses 160 full-batch Adam updates. Each family has a
scalar value version and vector direct-gradient/Z versions. **Effective parameter
counts, output dimensions, observations used, update counts and CPU differ.**
They are reported explicitly. These panels cannot isolate a pure learning-method
advantage under matched capacity or matched compute.

Value critics evaluate destination minus source value. Gradient critics integrate
their fitted field along the straight segment using four-point Gaussian quadrature;
the reset probability and all fees are then applied identically. A learned vector
field need not be conservative: the report includes a finite-difference curl
diagnostic. Straight-line integration is part of this probe's declared policy.
The analytic reference maximizes the same one-step expected net objective. The
strong fixed-action reference chooses its action using the exact model over the
training anchor pool and cannot adapt the action identity to test states. Its model
access is privileged and labeled. The frozen-state action ablation only uses STOP;
it is not a matched-action learning baseline.
The fixed reference is selected over the training anchor pool; it is not a proof
of the population-optimal fixed action.

## Z inversion without an artificial victory

The Z-target arm receives `sigma * paired_gradient`, derived from the same table.
All target types use per-output normalization. Consequently noiseless rescaling
should leave direct/Z fits and actions equivalent when sigma is positive; tests
check this even at sigma=1e-6. This arm does **not** estimate a BSDE martingale
coefficient from path increments and does not establish the statistical variance
of a practical Z estimator.

A separate algebraic sensitivity table applies the same absolute Z measurement
error at different sigma. Inversion amplifies it by `1/sigma`. It is explicitly
not another learned competing arm. At zero diffusion all gradients map to Z=0,
so inversion is unidentified; all 15 zero-noise Z records are retained in the
default 5-seed study rather than silently dropped or assigned a zero gradient.

## Evidence, cost and limitations

The default roster is 11 panels × 5 seeds × 12 arms: 660 records, including
15 expected unidentified records. Test seeds differ from the formal roster.
Every completed fit retains its complete parameters, calibration, raw chosen
actions, expected net values, realized quality, fees and per-request CPU/wall
measurements. Independent test states, reset outcomes and Gaussian noise are
retained. A new subprocess can replay each checkpoint's decisions. Fitting
failures keep their elapsed costs and do not erase later arms.

Task quality and action fees define the mathematical objective. Actual CPU is
measured separately, with no conversion tariff or economic break-even claim.
Shared acquisition/truth construction is metered once; training and request
intervals are separate. Case/run intervals enclose those components and must not
be added to them. Imports, launch, JSON serialization, publication and external
qualification remain outside the internal run timer and require an outer command
meter. The reported latency percentiles describe this small CPU probe only.
This module does not measure production RSS/GPU, cancellation or external failures.

Run behavioral tests with
`python -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.test_structure -v`.
After freezing source and protocol, execute the complete default roster with
`python -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.rl_audit.structure --out NEW_DIRECTORY`.
The directory must be new. Individual case files and a hash index preserve the
roster. API overrides are labeled nonformal. All outcomes are exploratory; no
winner is chosen from the heldout results and no scientific benefit gate closes
automatically. Full RL, existing Hepta learner/rsEAC, matched compute/capacity,
real tasks and independent future-window evaluation remain open.
