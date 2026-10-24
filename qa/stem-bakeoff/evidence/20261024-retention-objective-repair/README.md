# Optional retention objective: mathematical repair only

Base: ff5baef731f36420370c5bcc049c50a567cda06a. The five pinned legacy source,
run and protocol files remain unchanged. This stage adds a separate one-sided
retention objective and a bounded deterministic affine-tangent solver. It does
not train an encoder, evaluate a new scientific cohort, or establish task gains.

The initial optional implementation silently lost a representable nonzero old
loss cost when dt*weight underflowed. The retained root-review counterexample
records that failure (expected approximately 5e-101, observed zero). Separate
square-root factors, stable norm accumulation, consistent gradients and explicit
quadratic-scale admission now preserve supported values and reject unsupported
solver scales rather than certify a different objective.

Observed gates:
- 24 tests (18 new mathematical/solver cases and 6 legacy compatibility cases)
  pass locally under Python 3.12.14 / NumPy 2.3.5.
- The same 24 tests pass remotely under Python 3.12.3 / NumPy 1.26.4 with warnings
  treated as errors, one BLAS/OMP thread; job 1a16ce5fc31-1b6abb-4743.
- just fmt and git diff --check pass. No Rust source changed.
- Four installer admission/idempotency/collision checks pass in local fixtures.
- First local discovery failure and the earlier numerical counterexample were
  retained; new successful tests do not erase them.

The protocol remains DRAFT_BLOCKED_NOT_EXECUTABLE. A separate nonlinear runner
and a newly frozen, source-disjoint manifest are required before empirical work.
The penalty is soft and its fixed affine solve is not a global nonlinear
optimality or hard-retention guarantee.
