# Continuation after actual graded / lower-fold migration

This stage re-evaluates all 14,336 original posteriors using the actual migration
from #6182. It does not inherit the earlier v1 backward-function integral result.
The original 80-digit reference and unchanged 0.01 scaled-error limit remain.

Both n256 and n512 have zero failures. Maximum errors are 1.58748787e-5 and
4.00956339e-6. Separating spatial CTMC error, initial/reset migration error and
upper truncation error, the conservative sums are 1.58749081e-5 and
4.00959286e-6; no cancellation is needed. The same folded initial distribution
and randomized two-node reset law are used in the finite-continuum comparison.

Complete guarded attempt002 retains both full per-position arrays. It adds the
inherited JointModel source to the guard; all 28,672 values are numerically
identical to attempt001. The earlier summary/digests are retained separately.
An independent reversible spectral solve and independently integrated hat/fold
weights verify every row: candidate differences are at most 7.00e-12 / 4.21e-11,
and mapped-continuum differences are below 3.56e-15. The original finite and
80-digit references agree exactly. These checks concern exposed fixed laws.

```sh
python -B -m qualification.hcsn_graded.verify_continuation qualification/hcsn_graded/evidence/actual-migrated-continuation-attempt002
```

Read-only CI verifies the retained arithmetic with zero model executions. It
does not repeat the complete original-input numerical audit. That audit's
source/input hashes and process receipts remain distinct.

This closes the exposed actual-migration continuation-value gate only.
Finite rare-phase risk, full filtered trajectories, graded physical gradients,
training, independent future sources, complete costs and adoption remain open.
`REMAINING_GATES.json` retains `all_closed=false`.
