# Finite deterministic-delay flow with differentiable initial laws

The earlier variational bridge fixes its initial probability/content and does
not differentiate the deterministic delay. This separate research oracle uses
native Torch matrix exponentials throughout. All six physical parameters
(`log_boundary`, drift, sigma, absolute reset, delay, discount), initial nodal
probability and arbitrary signed content, phase probability/content and phase
support coordinates retain their computational graphs.

For `k` completed resets, form a lower block bidiagonal matrix with the killed
generator `A` on the diagonal and the reset/first-hit map `r*l^T` on the first
subdiagonal. The last block of its exponential at `t-k*delay` gives the exact
`k`-reset Duhamel convolution. Only finitely many resets can complete at a
finite time with positive delay. Extra integration rows compute cumulative
hits, upper escape, active occupation, exact uniform phase input integrals,
and discounted versions. Refractory mass and remaining-age discount follow
from the difference between cumulative hits at `t` and `t-delay`. This is
the finite CTMC/delay law; matrix-exponential floating-point error remains.

There is no time stepping, repeated bin projection, approximate per-step
uniform hit law, supplied custom Jacobian, or fixed-law NumPy conversion.
Detached scalars only select a smooth region and enforce resource limits.
Reset knots, zero rates and release fronts reject rather than emit an
undefined two-sided derivative. Upper escape stays permanently active and
nonreturning, exactly as in the source #6129 DDE. Initial lower-node atoms
remain forbidden. The API bounds dense matrix dimension, resets and queries.

## Verification contract

The separate SciPy method-of-steps implementation at exact source
`36aa7bc7c36a56861a5ce70bc143a7dde16c5e49` supplies all seven flow fields at
four query times, for active, phase-only and mixed signed initial laws.
Six native test methods additionally cover full-output finite differences
for all six physical parameters at one internal fixture, random-projection
initial/phase/support gradient checks, an
absolute-prior boundary chain rule, query-insertion invariance and rejection
of undefined derivatives and resource overflow. The runner retains raw logs,
all six executed source file identities before/after, runtime versions,
test count, failures, timeout and process-only resources.

The initial source stage has no test success claim. Native or hosted receipts
must be read before qualifying these checks. Tests are synthetic numerical
validation, not new task data or network retraining. This does not establish
graded-mesh AD, continuum derivative precision, rare-tail relative precision,
observation-update differentiability, a recurrent network training replay,
independent future task benefit, production authority or default-cell status.
**Draft / HOLD_NO_GO.**
