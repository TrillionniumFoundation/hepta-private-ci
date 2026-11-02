# Independent V2 diff review after freeze and fresh launch

This narrow read-only review was requested after the V2 freeze and after its
fresh confirmation had started. It is subsequent review evidence, not
prequalification or pre-outcome approval of that campaign. No fresh arrays or
outcomes were inspected, no numerical campaign was rerun, and no frozen source
was changed. All 17 frozen file sizes and SHA256 hashes matched; the freeze hash
is `1265f45f19932c6c5e2a2d8cbb9fc9f386e699a006c60ad5ad3cad47ed061488`.

## V1 omission and the change

V1 initialized the numerical builder's left arrays correctly, but omitted the
saved `left_values[0]` and `left_tangent[0]` slices from its error maxima.
Consequently, a caller could corrupt those verifier inputs without affecting
the old maxima. The later corruption probe exposed a real verifier-input hole.
The earlier independent V1 source review did not identify this omission; its
assessment of complete-array checking was too broad for these two initial-left
slices. The V1 source, probe failure and retrospective results should remain
preserved. This finding does not by itself invalidate arrays produced by the
unchanged, correctly initializing V1 builder.

V2's certificate now includes both `values[0]` and `left_values[0]` in the
primal maximum, and both `tangent[0]` and `left_tangent[0]` in the derivative
maximum. Each is compared against the independently recomputed payoff or its
directional derivative. The existing later-time left/right checks are retained.
V2 also requires the primal enclosure bound, as well as the derivative bound,
to satisfy the same `1e-10` admission threshold. Affine-radius qualification
uses that strengthened admission condition too. This closes the specific
omission and the prior source-review gate-wording boundary without widening a
threshold or changing the underlying task equations.

## New controls and replay

The two added controls alter the INITIAL left row `k=0` at the zero spatial
node in mode zero. In the explicit binary-rational configuration, the original
primal value there is `5/8` and its initial payoff derivative in the fee
direction is zero. Adding `1/2` is exact in binary arithmetic. This initial
derivative is distinct from the nonzero directional value after the later
reset admission.

The executable controls require rejection and a corresponding reported bound
of at least `1/2`. The standard-library replay reconstructs the before/after
numbers from hexadecimal strings using exact fractions, verifies the actual
`1/2` injection, and checks consistency of the stored rejection/bound result.
That replay is an independent arithmetic check; it does not independently
re-execute the interval package to establish the rejection.

The three selected old cases are expressly engineering revalidation. Protocol
comparison retains the fresh seed, six-profile count, ranges, meshes, original
real steps, complex increment and all numerical tolerances. The added controls
and primal admission strengthen the contract. Neither the old R20 finite-step
failures nor the V1 omission are reclassified as historical passes.

No actual algebraic flaw was identified in these reviewed V1-to-V2 changes.
This assessment is confined to the stated initial-left repair and control/gate
changes. It is not a new formal verification of all interval arithmetic or
runtime dependencies, and supplies no fresh numerical success claim. Generic
unrecognized ties, moving delay/domain, continuum and full-neural gradients
retain their previously stated limits.
