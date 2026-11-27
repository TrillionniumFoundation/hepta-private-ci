# Fixed Haar optimizer coordinates — qualification only

**11 literal tests passed; no generation benefit has been tested.**

The fixed orthonormal 2×2 transform keeps all 192 RGB coordinates. It separates
block averages from three detail coordinates, matching the already known paired
low-resolution construction. It neither adds parameters nor restricts the model
function class. It adds no FIT labels and does not factor the class posterior.
The ten instruction coordinates remain intact in the helper and are masked by
the unchanged source-perception model.

At the adaptation boundary, x′ = xH and W′ = HᵀW preserve the encoder and policy
in exact arithmetic (within prescribed tolerance in binary64). All other tensors
are copied unchanged. Conversion accepts only the explicit raw source model and
resets Adam moments, as does the old adaptation clone. The new mode/profile-bound
digest is distinct; cloning does not convert twice. Checkpoint I/O is disabled.
Transformed coordinates can be signed: no clipping, epsilon or standardization
is introduced. Nonfinite inputs or overflow reject rather than repair.

SGD is orthogonally covariant in exact arithmetic; the existing global L2 gradient
clip also preserves that symmetry. Diagonal Adam generally does not, because its
coordinatewise squared moments and divisions depend on the chosen basis. A fixed
literal example yields a mapped update difference of about 0.01. That demonstrates
non-equivalence, not a better optimizer, an unbiased update or an NDU improvement.

The executed tests comprise five unchanged source-model tests and six new Haar
tests: full 192-dimensional basis/involution/norm checks; bounded block-constant
low-view detail zeros; function, decoder, identity and clone preservation;
seven supervised-loss parameter finite differences; unclipped SGD covariance;
a fixed Adam counterexample; and finite/domain/mode/checkpoint refusals.
The FD maximum was **2.786701008838932e−10**, below the fixed 2e−7 bound.
Complete A+anchor and active-clipping integration are **not** measured here;
they belong to the separately frozen prospective scientific control.

Fully waited cost: **0.199515 CPU seconds**, 0.205026 wall seconds, 31,324 KiB RSS,
within the fixed 10 CPU / 30 wall / 512 MiB / 4 MiB limits, CPU 0 and one numerical
thread under the existing synthetic-only lock. Included: 20 literal toy model
initializations, four Adam updates and two separately counted manual SGD steps.
There were no restored models, scientific models, scientific data rows or renderer
calls. Source/review/historical work and unknown supervisor tails are additional,
not zero. Expected overflow warnings came from successful refusal fixtures.

## Portable tests

```sh
PYTHONPATH=../source-scene-decomposition:.. python -B -m unittest -v test_haar_coordinate
```

The command above runs the six new tests; the saved qualification also included
the five unchanged source-scene tests. This package includes only portable source,
tests, the executed plan and complete scalar qualification records. No weights,
private inputs, runtime paths, per-request predictions or unrestricted runner.
No default change, merge or deployment. Publication is separate from execution.
