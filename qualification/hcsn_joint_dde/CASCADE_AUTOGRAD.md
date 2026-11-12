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

The source-only commit had no test success claim. The native execution below
now supplies actual receipts. Tests are synthetic numerical
validation, not new task data or network retraining. This does not establish
graded-mesh AD, continuum derivative precision, rare-tail relative precision,
observation-update differentiability, a recurrent network training replay,
independent future task benefit, production authority or default-cell status.
**Draft / HOLD_NO_GO.**

## Observed native execution

Exact source `19b7a99f6d63596dd77c34a1ed8e529e1c744750` ran on the configured
`desktop` host using Python 3.12.3, Torch 2.8.0+cu128 (CPU execution only),
NumPy 2.3.5 and SciPy 1.17.0. The retained terminal owner reports exit 0 and
complete output. All **6/6 tests passed, no skips**. The six executed source
identities before/after are unchanged and match the published objects.

Across all compared fields, laws and query times, the largest discrepancy from
the separate SciPy DDE is `1.6504300530406635e-11`. The full-output six-parameter
gradcheck and the separately described projected initial-law/phase checks
passed. A fixed nonuniform output projection has nonzero finite derivatives
for all six physical parameters, including delay. This is a correctness probe,
not a demonstration that optimizing these parameters improves a task.

The test subprocess consumed 10.617 seconds wall, 7.711 seconds CPU and
658,184 KiB peak RSS. These process-only numbers exclude setup, earlier work,
CI, lifecycle, model training and energy. Actual neural optimizer calls = 0;
independent future tasks = 0. Hosted CI on subsequent heads is separate.

`evidence/native-cascade-20261112/attempt002/` retains the original launch and
outcome, PREEXECUTION and RESULT, complete stdout/stderr, terminal receipt,
readback SHA256 and formatter outcome. `attempt001` was only a source transfer
whose acknowledgment timed out; file readback confirmed the transfer, and no
numerical process or training was started by it. The first actual numerical
execution is this `attempt002`, on the subsequently frozen reviewed source.

A separate same-session mathematical reviewer checked the block convolution,
uniform phase integrals and remaining-age identities. Its two findings were
fixed before this tested source: learnable zero-time phase fronts and rates
that overflow from otherwise finite parameters now reject. Mandatory scoped
`just fmt` ran after native tests and changed no source bytes; tests were not
rerun after formatting. Overall qualification remains **HOLD_NO_GO**.
