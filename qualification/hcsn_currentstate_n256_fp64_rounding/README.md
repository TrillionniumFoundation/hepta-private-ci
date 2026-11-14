# Exact rational-to-binary64 rounding source stage (HOLD)

This isolated stage implements exact integer-arithmetic IEEE-754 binary64
rounding for rational inputs.  It covers signed zero, normal and subnormal
values, normal carry, overflow, and round-to-nearest ties-to-even boundaries.

The implementation constructs no Python float and imports no `struct`,
`fractions`, NumPy, SciPy, frozen candidate, or frozen oracle.  The test-only
reference uses CPython `float(Fraction(...))` plus `struct` for a deterministic
512-rational differential corpus.  That reference is not imported by the
primitive.

This certifies only exact-rational to binary64 rounding.  It does not certify
how Decimal or binary64 operator sequences round, does not load authentic N256
inputs, and does not execute a candidate, oracle, uniformization operator,
Torch graph, or optimizer.  Provider qualification, finite operator-arithmetic
rounding, full-state semantics, resources, cost, and the 18,225,028-record
three-way comparison remain OPEN.

Historical RED and UNKNOWN results are unchanged.  Global status remains
`HOLD / all_closed=false`.

