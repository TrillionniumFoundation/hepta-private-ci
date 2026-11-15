# Independent P1 review: exact discrete gradients leave numerical gaps

Reviewed source: PR #6151, commit
`f9345af3c74e32a2b6ab62f84e8998f37f0d2ac3`.
This change adds review evidence only. `SOURCE.json` binds eight imported
or inspected source files to their remotely retrieved Git blob IDs;
the probe verifies every byte and records SHA256 values before comparison.
The candidate operator, its tests and its original thresholds are unchanged.
All new comparisons here are exploratory; they are not new passing gates.

## A correct discrete derivative can follow a biased first-hit probability

Use `B=.01, mu=-.12, sigma=.5, Vr=exp(.51), q=.15`, endpoint 2,
grading 1, equal left/right interval counts and delay .2. A unit phase atom
at time zero releases at the exact reset .5. Before one delay, the event
count is the first-hit probability. An independent dense matrix exponential
computes that probability without DDE interpolation or integration error.

At time .1 the half-line continuum first-hit probability is
`0.0019850919213766746`. The probability of reaching the upper endpoint
by this time is at most `1.1559855968678395e-21`, bounding the difference
between half-line and finite-interval first-hit probabilities. Upper
truncation cannot explain the following spatial errors:

| Intervals | CTMC first-hit probability | Relative error |
| --- | ---: | ---: |
| 8 | 0.005675277835024654 | +185.894964% |
| 16 | 0.002991935378631970 | +50.720244% |
| 32 | 0.002243142820873167 | +12.999443% |
| 64 | 0.002049911452646918 | +3.265316% |

At time .01, the eight-interval CTMC gives `1.5497247830119474e-6`,
while the continuum reference is approximately `1.9368e-23`.
The raw records also retain time .001 and every listed mesh size.
The reference formula uses `log_ndtr` and `logaddexp` to retain rare tails.

For the eight-interval, time-.1 fixture, all five variational event
partials agree with independent matrix-exponential Frechet derivatives
to a maximum absolute difference of `1.057e-11`. The discount derivative
of this undiscounted event count is zero, so that component is not an
additional test of discounted-output sensitivity. The drift derivative
is `-0.01310066667086` in the CTMC, versus `-0.00388821434832` in the
continuum reference; the latter was differenced at two recorded step sizes.

This is evidence that the variational solver differentiates its actual
discrete model correctly in this fixture. It does not establish that the
result approximates the continuum gradient accurately. A same-model teacher
fit on eight intervals cannot resolve this spatial bias.

## Negative drift plus low noise is outside this tested native geometry

Keep reset .5, endpoint 2, grading 1, equal segment counts and drift -.12,
but set sigma .08. Meshes with 8, 16, 32 and 64 intervals are all rejected
by the positive-rate requirement. A 128-interval mesh is accepted, with
minimum rate `0.7646171062458893`, but exceeds `aligned_flow`'s total
64-row initial-law budget even without a phase row. The published low-noise
finite-difference fixture instead sets drift to zero.

This counterexample concerns the declared geometry and its current budget.
It does not claim every possible mesh or low-noise parameter is unusable.
Changing the mesh is a new numerical candidate requiring its own checks.

## Boundary and absolute reset are not separately identified here

At fixed moving nodal weights, B and Vr enter only through
`r = log(Vr) - B`. Hence every output obeys
`d/dB + Vr * d/dVr = 0`. The probe retains generator and event-partial
residuals for this identity, plus the invariant transformation
`B += .02; Vr *= exp(.02)`.

This coordinate derivative is valid. It is not the derivative obtained by
moving the absorbing boundary while holding a physical initial density
fixed. The latter also needs the density-to-moving-mesh migration Jacobian.
An independent boundary-learning claim cannot be inferred from the five
parameter gradcheck alone.

## Qualification consequence

The retained original-node kink and the published moving-mesh checks address
reset differentiability within the fixed-topology discrete model. The
variational code propagates delayed sensitivities through its dense history;
this review found no detached-history shortcut in that code. The new probe
independently supports its event derivative in the stated fixture.

The continuum short-time/rare-event accuracy gate, low-noise coverage with
negative drift, fixed-physical-prior chain rule, differentiable checkpoint
and real-task training sufficiency remain open. The #6151 API has no
checkpoint input or serialized sensitivity history. A primal checkpoint
from a separate candidate does not itself close the differentiable-resume
requirement. The two-scalar 120-Adam target measures a same-model synthetic
fit; its loss and node crossing do not establish real-task learning or
separate recovery of boundary and reset. Native Torch execution is owned
by the candidate author and is not reclassified by this SciPy-only review.

## Reproduce

From a checkout containing this review and the unchanged candidate sources:

```bash
python -B qualification/hcsn_reset_aligned/evidence/independent-review-20261112-4092/probe_shorttime_domain.py --source-root . --output-dir /tmp/hcsn-p1-independent-new-run
```

The output directory must not already exist. `REVIEW.json` contains every
comparison and environment version; `REVIEW.stdout` and `REVIEW.stderr`
retain the execution output. `probe_shorttime_domain.tested.py` is the exact
executed source. Formatting was performed afterwards and AST equivalence
is recorded in `FORMAT.json`; the probe was not rerun after formatting.
No original continuation or gradient threshold was lowered, and the new
moving mesh has not acquired the old 14,336-position qualification by this
review.
