# Exact binary64 input conversion primitive (HOLD)

This source-only stage converts one canonical big-endian IEEE-754 binary64
hex value into its exact finite decimal expansion without constructing a
binary float. It separately records the signed integer numerator and the
power-of-two denominator.

The source accepts exactly 16 lowercase hexadecimal digits, preserves signed
zero identity, and rejects infinities, NaNs, prefixes, uppercase text, and
noncanonical widths. The test-only `struct` reference is not imported by the
primitive.

This closes only exact input-byte conversion for a future independent
uniformization provider. It does not certify arithmetic rounding, load the
authentic N256 bundle, implement packet/delay/reset/upper-escape semantics,
run a matrix action, select a tolerance, allocate resources, create a
numerical idempotency key, or grant provider/N256/production qualification.

Historical RED/UNKNOWN and Draft #6317's source-only scope remain unchanged.
C2 full replay remains 0/6 and HPCA remains NoUpdate. Global status is HOLD.

