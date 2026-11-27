# Positive rational output interval for bounded uniformization

Status: **HOLD / small-fixture source stage**.

This package closes one narrow output-side prerequisite.  For a nonnegative
binary64 input vector and a finite Metzler generator whose uniformized
transition is substochastic, it constructs exact rational lower and upper
bounds for each mathematical uniformization output.  It proves a binary64
output only when both endpoints round to the same value through the frozen
exact roundTiesToEven primitive from #6320.

The exponential enclosure is independent of Decimal exp: a positive Taylor
sum bounds exp(a) from below, a geometric majorant bounds its remaining
positive tail, and reciprocal bounds enclose exp(-a).  The operator action
and Poisson series use only standard-library exact rational arithmetic.

The dedicated workflow executes four successful small fixture proofs in total:
two assertions-enabled and the same two under python -O.  It performs no
authentic N256, HCSN dynamic, model, Torch, optimizer, or training work.

This stage deliberately rejects signed vectors and generator rows that would
produce non-substochastic transitions.  It does not certify the existing
Decimal primitive, selector-augmented channels, authentic packet inputs,
18,225,028 records, N256 resources, or an independent reference provider.
Historical RED/UNKNOWN, C2 0/6, HPCA NoUpdate, and global HOLD are unchanged.

