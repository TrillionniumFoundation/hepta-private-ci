# R14 zero-delay complete-state propagation

This additive experiment closes the **declared numerical profile** for zero
refractory delay, an initial boundary atom, repeated events and arbitrary real
observation partitions. It leaves the R12/R13 source and evidence unchanged.
It does not replace a content-training or value-control path.

## Process and continuous reference

The target is `X(t)=x+mu*t+sigma*W(t)` on the positive half-line. At zero an event
is counted immediately, and the process restarts at a fixed `reset>0` without a
delay. All coefficients and the boundary remain fixed. For `x=0`, the initial
event occurs at time zero, including when the requested horizon is zero. The
post-event physical state is the reset atom. Zero reset is refused: repeatedly
resetting directly onto the absorbing boundary does not define this renewal
profile.

Write `F_a(t)` and `f_a(t)` for the first-hit CDF and density from distance `a`,
and `k_a(t,dy)` for the killed, never-hit successor. Strong Markov renewal gives,
for an interior initial point and `n>=1`,

\[
\Pr(N_t\ge n)=F_{x+(n-1)r}(t),\qquad
\mathbb E N_t=\sum_{n\ge1}F_{x+(n-1)r}(t),
\]

and the complete active successor is

\[
p_t(dy)=k_x(t,dy)+\sum_{n\ge1}\int_0^t
 f_{x+(n-1)r}(s)k_r(t-s,dy)\,ds.
\]

These formulas retain the actual remaining time `t-s` after every reset. For an
initial boundary atom, the active successor equals that starting at `r`, while
the event count includes the extra immediate event. Positive-drift non-hit mass
is retained by the inherited renewal CDF; no normalization conditions on a hit.

`continuous_reference.py` imports the unchanged R12 continuous killed-law
functionals and the original renewal operator. It separately integrates every
completed-reset branch. The omitted probability after `n` branches is bounded
by the next count tail; quadrature error estimates are reported separately.
This is independent of the new spatial generator. A second implementation in
mpmath differentiates 64- and 128-term continuous sums at 70 decimal digits.
These numerical comparisons are not uniform interval-arithmetic certificates.

## Finite-state implementation

`zero_delay.py` uses interior spatial nodes `i*h`, lower reset and upper
absorption. Its centered nearest-neighbor rates are

\[
u=\frac{\sigma^2}{2h^2}+\frac{\mu}{2h},\qquad
d=\frac{\sigma^2}{2h^2}-\frac{\mu}{2h}.
\]

Negative rates are refused. Interior initial/reset atoms use adjacent-node
interpolation. Positive atoms below the first resolved node are refused instead
of silently treating their missing distance as zero. Each count layer carries
its full active distribution and its own upper cemetery. Lower flux enters the
next count layer at the reset law. Exact layers `N=0,1,2,3` are followed by an
overflow layer `N>=4`; the overflow state continues to regenerate, so it does
not truncate future event counts. An additional reward coordinate integrates
the event rate across all layers.

This construction counts a reset that returns to the same physical state. The
Poisson self-reset control checks that failure mode independently: its physical
position does not change, while its event count remains nonzero.

The constant augmented generator is advanced by `expm_multiply(delta*M,state)`.
Observations do not rebuild its mesh, discard its distribution, or round their
time to a lattice. The finite model therefore has a semigroup at arbitrary
nondecreasing real times; floating-point partition discrepancies are measured.
That property alone says nothing about spatial approximation error, which is
checked separately against the continuous formulas on three spatial meshes.
Histograms reconstruct each spatial node mass uniformly over its centered cell;
they are binned numerical observables, not an exact continuous density.

No probability clipping or renormalization is performed. Upper-boundary loss
is included in all count-layer mass balances and reported independently. It is
a measured finite-model truncation loss, not a rigorous bound on every possible
continuum output error.

## Derivatives

For expected count, summing out the mark layers produces the same unmarked
generator with its event reward coordinate. The implementation integrates the
tangent equations

\[
\dot s_\theta=M s_\theta+(\partial_\theta M)y
\]

with the corresponding initial-atom derivative. It checks all five parameters
`x,mu,sigma,horizon,reset`. The actual finite-generator tangent is compared with
two centered-difference step sizes; its continuum approximation is separately
compared with the 70-digit formula under mesh refinement. The initial distance
and reset location are deliberately away from every tested interpolation knot.
Ordinary derivatives at spatial knots and the initial boundary atom are outside
this method's contract and are explicitly refused.

## Execution and retained evidence

From the repository root, with the pinned requirements installed:

```bash
python -B experiments/hcsn_validation_r14_20261101/numerics/launch.py \
  --out experiments/hcsn_validation_r14_20261101/numerics/results/new_unique_attempt
```

The output directory must not already exist. Before numerical execution the
audit snapshots all seven direct local source/protocol dependencies, recording
both SHA256 and Git blob identity. It records the actual runtime versions,
continuous references, every check and expected negative result, all full raw
direct/segmented states, post-execution source consistency, and a complete
scientific-child Linux `wait4` receipt. The launcher enforces one BLAS thread,
a 1 GiB address-space limit and a 600-second CPU limit. The receipt includes
imports, references, gradients and evidence writes. Nested phase timings must
not be added to it. Joules remain `null` because no energy meter was available.

The scientific thresholds in `PROTOCOL.json` were fixed before the first local
numerical execution. This is a local source freeze, not a claim of external
preregistration. The first complete attempt is `results/development_01`.

## Scope of closure

The registered zero-delay cases pass their existing numerical thresholds. This
does not establish positive or random delay, moving or learned boundaries,
full-parameter-domain accuracy, neural `D-B` gain, GPU efficiency or energy
benefit. R13's positive-delay recovery-age queue remains a separate validated
profile. Any training integration must consume the complete state and undergo
its own task and cost checks.

API reference: [SciPy `expm_multiply`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.expm_multiply.html).
The actual executed version is SciPy 1.17.0, recorded in `RUNTIME.json`; the
linked moving documentation may describe a later release. Mathematical
precedents and the original renewal model are documented in the unchanged
R12 files rather than inferred from matrix-exponential self-consistency.
