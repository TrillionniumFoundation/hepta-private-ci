# Graded spatial candidate with conservative initial-law migration

The v1 fixed-law continuation result did not qualify spatial state migration.
Interpreting its uniform-grid linear value function as hat-weight migration
creates a lower-boundary atom: for the first original uniform cell at gap .001,
the n512 hypothetical first-hit probability is .0379061 versus the continuum
.0296371. The actual v1 solver rejects that atom. This new candidate addresses
the migration and short-gap mechanism without changing that historical result.

Nodes are `8*expm1(6*i/n)/expm1(6)`. On unequal left/right spacings, jump rates
match the drift and infinitesimal variance. Reset interpolation and the
perpetual solve use the actual nodes. The actual probability/signed-content
delay/reset DDE from #6129 is reused, with no uniform-spacing assumptions.
The v1 free basis-integral API now explicitly rejects graded spatial objects;
it cannot silently apply `linspace` to this geometry.

`hcsn_initial_law` integrates each original uniform/exponential density against
nonnegative nodal hats. Lower hat mass is folded into the first interior node;
there is no initial hit atom. That fold has a disclosed mean bias. Uniform
interior means, probability totals and every signed content total are preserved
in rational arithmetic. Tail mass beyond 8 enters the separate permanently
active/nonreturning escape coordinate, with overshoot and rounding reported.
No original probability law is normalized or silently truncated.

The source-bound local final suite passes **28/28** checks: 7 new graded checks,
9 migration checks and 12 affected prior checks. This includes actual graded
DDE versus an independent serial CTMC, finite reward/continuation consistency,
actual-node moments/reset, and exact mass/content migration. A separate
spectral implementation agrees on the n64 generator exactly, the discounted
transform within 1.62e-12 and perpetual values within 8.55e-12.

Eight real DDE runs execute n256/n512 on four frozen cases and all six original
gaps .001/.003/.02/.04/.08/.16: the original posterior with maximum first-cell
mass (including its original signed content), isolated first uniform cell,
isolated first phase cell, and the exponential tail. At n512, the original
posterior has maximum absolute M/H/A errors
`2.56255e-6 / 2.52954e-6 / 1.85098e-7`; its maximum relative M error is
0.000115706. Across these runs mass residual is below 1.5e-14 and signed-content
residual below 4.7e-14. The complete arrays, source/input guards and process
output are retained. The measured complete probe took 128.49 seconds on the
shared local runtime; this is not a kernel, energy or equal-quality speedup.

The probe also retains a material negative result. For isolated initial phase
mass at time .02, continuum M is 1.21634e-11 and n512 gives 1.45559e-11:
**19.67% relative error**. At .04 it remains 2.836%. Low absolute errors do not
qualify relative rare-phase risk. This discrepancy includes spatial CTMC tail
error and cannot be attributed only to reset interpolation.

```sh
OPENBLAS_NUM_THREADS=1 python -B -m unittest qualification.hcsn_graded.test_model qualification.hcsn_initial_law.test_migration -v
python -B -m qualification.hcsn_graded.probe_migration --original-audit ORIGINAL_AUDIT --original-experiment ORIGINAL_EXPERIMENT --output NEW_OUTPUT
```

This is post-failure repair on exposed laws. The mechanical solver accepts
smaller times; current numerical evidence concerns the six listed gaps, with
minimum .001. Fixed finite CTMCs cannot reproduce the relative sqrt(time)
boundary asymptotic at arbitrarily short times. Upper return, rare-phase
relative precision, complete observed-domain rollout, graded physical gradients, filtering/full-network training,
future sources and complete costs remain separate gates.

`REMAINING_GATES.json` records the source ownership and each open requirement.
Overall status is **Draft / HOLD_NO_GO / all_closed=false**. Uniform-grid
gradient/native successes do not transfer to this graded candidate.

The next source-bound actual-migration continuation stage evaluates all 14,336
original posteriors at n256/n512 against the unchanged 1% limit. Both profiles
have zero failures even for the conservative spatial/mapping/truncation error
sum; n512 maximum is 4.00959286e-6. This closes only that exposed fixed-law
value gate after the real migration, and does not close the retained rare-phase
relative-risk counterexample or full-trajectory/training gates.
