# Optional one-sided retention objective

This is a mathematical/implementation repair candidate, not a new task result.
The published PFT source and evidence at `ff5baef731f36420370c5bcc049c50a567cda06a`
are unchanged. No old May/June evaluation, model checkpoint or learned policy is
read by this module or its tests. The adjacent validation protocol is a draft;
it cannot execute until new source manifests and a separate runner are frozen.

## Loss semantics

For a **frozen** old-probe loss anchor `a`, tolerance `delta >= 0` and weight `w >= 0`:

`excess = L_old - a - delta`

`penalty = 0.5 * w * max(excess, 0)^2`.

Improvement and degradation within the tolerance band cost zero. Greater
degradation costs the squared excess. This is a soft penalty, not a guarantee
that old ability cannot decline. Never update `a` after each step: doing so
would let repeated tolerances accumulate into unbounded forgetting.

The loss derivative is `w * max(excess, 0)`. The penalty is C1, but is not C2 at
zero excess. The implementation reports curvature zero there as a chosen
generalized derivative, not as an ordinary Hessian. For nonlinear `L(theta)`,
the active Hessian is `w * (grad(L) grad(L)^T + excess * Hessian(L))`.
The affine-loss tangent includes only the first term. It is exact for that
linearized problem, not for the original nonlinear training trajectory.

## Correct connection to the existing controller

The existing `solve_lq()` assumes a globally quadratic cost and produces affine
feedback. It must not be reused unchanged with a hinge merely substituted into
its final report. `run_nonlinear()` also unconditionally reports the old
`quadratic_cost()`: this patch deliberately does not duck-type a new controller
into that runner or change published objective identities.

The opt-in `solve_retention_tangent()` instead solves a finite deterministic
piecewise-quadratic problem with the existing affine dynamics, **zero drift**,
two charged fields, stage weight `dt`, terminal weight 1, and positive quadratic
action effort. Its procedure is:

1. Roll out the current action sequence and compute the true hinge objective
   and its complete adjoint gradient, independent of Riccati internals.
2. Select active old-loss times. Multiply both the old charged row and its
   target by `sqrt(w) * active`; solve this local quadratic by `solve_lq()`.
3. Roll the resulting candidate forward from the same initial state. Its
   difference from the current action sequence is a generalized Newton step.
4. Accept a step only by Armijo backtracking on the **true hinge objective**.
   Nonfinite trials are rejected and still counted. Bounded iteration or
   backtracking exhaustion is an explicit failure with cost counters.
5. Report success only at the declared full control-gradient tolerance.

For fixed finite affine arrays the control objective is strongly convex with
`mu = dt * effort_price > 0`. This justifies the direction and unique tangent
solution. The numerical receipt includes residual and
`||gradient||^2 / (2*mu)`, a conditional floating-point suboptimality bound.
It is not interval arithmetic. A small residual can imply a weak bound if
`mu` is tiny. Nonfinite bounds and unrepresentable nonzero retention penalties reject.

Stage and retention weights are square-rooted **separately** before scaling
losses; gradient uses the same scaled residual and Jacobian. This preserves the
representable `5e-101` cost when `dt=w=1e-200` and old violation is `1e150`.
An active subnormal combined square-root factor is rejected: it can lose a large
fraction before a large residual rescales it. Zero weight and zero hinge stay valid.
The old Riccati arithmetic has a narrower range: each current/active-old row is
checked separately, before even a small-gradient success. If its squared,
stage-weighted, Gram-diagonal or linear terms lose a nonzero contribution to
zero/subnormal or overflow, the solver returns `quadratic_scale` failure.
Another large current term cannot mask a lost old term. Diagnostics supporting
a scale do not imply that the legacy quadratic recursion can solve that scale.

The return value is an action sequence for **one specified initial tangent
state**, with no global affine `K`. The existing `E` already includes physical
action `dt`; the new solver does not multiply it again. Projection errors,
nonlinear curvature, stochastic dynamics, hard constraints, and global NDU
credit assignment are outside this numerical claim.

### Explicit integration seam, not an executed nonlinear policy

```python
target = retention_targets(reference.observations[:, :2], -0.03,
                           anchor=frozen_old_probe_anchor, tolerance=0.02)
# geometry.F/D/charged come from the SAME frozen full or projected tangent.
# At k, initial is the current reference-relative state/observation in that
# geometry. Preserve the original anchor and slice the original target.
solution = solve_retention_tangent(
    geometry.F[k:], geometry.D[k:], geometry.charged[k:], target[k:],
    geometry.dt, geometry.effort_price, initial=current_relative_state)
first_action = solution["actions"][0]
```

A future nonlinear runner must explicitly apply and record the first action,
observe the resulting real state, solve the suffix again, and score real losses
using `retention_cost()`. All suffix solves, failed attempts and shared geometry
construction must be charged. Do not clip an action and still report the
unconstrained optimizer's certificate. A trust-region or safety rejection must
be recorded as such, not as successful task completion or legacy fallback.
An affine drift or new constraints require a new solver contract.

## CPU verification and scope

`test_cell_field_retention.py` uses small arrays only. It checks scalar analytic
solutions; independent dense condensing with exhaustive active-mask enumeration
for twelve multistep systems; true-cost backtracking; adjoint finite differences;
local curvature and the kink; frozen-anchor translation; legacy objective
compatibility; list inputs; numerical underflow/overflow; and failure accounting.
It does not load an Encoder or evaluate any scientific cohort.

Run from `qa/stem-bakeoff`:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -W error -m unittest \
  test_cell_field_retention test_cell_field_control test_cell_field_retention_subnormal -v
```

The third module covers subnormal-factor rejection and supported boundary cases.
The second module is the existing compatibility suite. Its small synthetic Head
fixture is a software test, not an additional task experiment or model-benefit
sample. Real historical or new task gains, old-capability retention and complete
controller/runtime costs remain unmeasured for the new profile.
