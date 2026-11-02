# Independent source-only review of the V2 residual termination repair

Reviewed the preserved V1 `source_v1/directional.py`, current `directional.py`,
the recorded V1 terminal system and `V1_CYCLE_DIAGNOSTIC_NOTES.md`. No V2 formal
evaluation was executed or inspected for this review. This does not reclassify
the incomplete V1 exact campaign or the failed V1 generic finite-step gate.

V1 required identical consecutive policy masks before returning. At a tied
complementarity solution, different policies can produce the same value while
roundoff changes which of two near-zero slacks compares smaller. The recorded
terminal system has applicable mixed residual `2.7755575615628914e-17`.
Its recorded `mask_changes=0` is a post-assignment local comparison, not a
consecutive-policy trace; it does not show that V1's actual guard succeeded.

V2 tests the mathematical conditions of the requested mixed problem directly.
Forced continuation rows use `Az-r`; forced obstacle rows use `z-do`; biactive
rows use `min(z-do,Az-r)`. Bounding the absolute value of the latter bounds both
inequality violations and ensures at least one slack is near zero. The other
inequality is deliberately not imposed on a forced row: a strictly active
primal constraint supplies the correct directional equality without that
additional directional restriction.

The returned value must satisfy the complete applicable infinity residual
within `64*eps*(1+||r||inf+||do||inf+||A||inf*||z||inf)`. A changing mask may
therefore return only after satisfying the residual check. A stable mask whose
residual exceeds the same bound now raises an error instead of returning an
unchecked value. This fixes the actual termination defect without changing
the critical complementarity equations or selecting an arbitrary tie branch.

For the stated strictly dominant M-matrix, translation by a constant vector
increases each applicable row function by at least
`m=min(1,min_i(A1)_i)` times that constant. The comparison argument therefore
also applies to the mixed forced/equality/complementarity system: an exact
arithmetic residual delta bounds value error by `delta/m`. This supports
residual-based stopping even when policy labels are not unique. The computed
floating residual and its roundoff-scaled bound are numerical diagnostics,
not an outward-rounded certificate or a proof of a global floating error bound.

The V2 source retains the same policy iteration cap and rejects nonconvergence.
It preserves the original prospective direction roster, meshes, positive step
sizes, finite-difference thresholds and outer `1e-10` algebra admission gate.
That outer gate must still be checked on every new formal result; the scaled
solver bound is not permission to widen it. Exact-tie masks remain mathematical
assertions supplied only for declared constructions. Generic unresolved
numerical rows remain unqualified as exact ties.

The review finds the residual-based repair appropriate for the recorded defect.
Qualification still requires separately frozen V2 formal execution and raw
array replay. R19's failures, V1 failures, generic tie certification, moving
delay/domain and continuum/full-neural gradients remain outside this repair.
