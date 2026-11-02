The three changed guards first perform the original coercion to `dtype=float`,
shape, finite-value and negative-value checks. Their accepted NumPy operands are
FP64. For a finite scalar reference 1, `rtol=0` and the unchanged positive finite
tolerance, `np.allclose(s, 1, rtol=0, atol=t)` is exactly
`np.all(np.abs(s - 1) <= t)`. The equality branch inside NumPy's `isclose` cannot
add an outcome because zero is already within the positive tolerance. A NaN or
infinite mass, including a sum that overflows from finite inputs, fails both
predicates. The comparison stays inclusive at the same representable boundary.

The probability and law guards retain the exact `p.sum(-1)` operation. Full
checkpoint restore previously reduces axis 1; its unchanged preceding shape
check is `(4, 40)`, so the new last-axis reduction has exactly the same operand,
dtype, order and result. No matrix product, BLAS operand layout, clipping,
renormalization or probability copy changes. Other `allclose` uses, including
emission and generator checks, remain unchanged. The new helper's equivalence
claim applies only to these admitted operands and scalar-one contracts.

The packed and anchored classes retain the original method bodies. The three
`COLLECT`, `SPREAD` and `GROUP` objects are imported from the frozen old module.
Full memory inherits all original methods and overrides only restore's mass
guard. The executor's function body is unchanged from R21 v2; its imports select
the new classes. Both restore routes still call R21's exact typed admission
function, preserving the counter-map schema and full projection/method checks.
Direct use of a legacy base restore outside that wrapper retains its historical
metadata admission scope.

Every complete episode still makes six actual durable commits. The exact R20
`persist`/`load` function objects retain temporary-file write/flush/fsync,
atomic rename, directory fsync, canonical checksum verification and two
readbacks. The final post-restore checkpoint comparison remains. R21's owned
snapshot reuse is retained without further modification. A scripted recovery
campaign binds the new law and all three new memory classes to cold processes.
It covers lost replies after each complete query; it does not qualify external
effects suspended mid-query, physical power loss or concurrent ownership.

All four planner variants and all three fitted cores share this optimization.
It is a common validation implementation improvement, with no exclusive claim
for the analytic core. The independent registered checker binds the exact
frozen source and tests actual guard/restore callers and unchanged contracts.
The earlier finite development profile is kept separately from the fresh
prospective resource comparison. Original adoption thresholds and the additional
software threshold are checked for every declared group, with failures retained.
