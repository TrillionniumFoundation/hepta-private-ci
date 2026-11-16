# Exact binary64 input bridge for Decimal uniformization

Status: **HOLD / source-only bounded fixture stage**.

This package closes one narrow interface gap.  It accepts every sparse
operator value, vector value, duration, and absolute tolerance as exactly 16
lowercase hexadecimal digits representing a finite IEEE-754 binary64 value.
It uses the frozen exact converter from #6318 and passes only exact decimal
text to the independent standard-library Decimal uniformization primitive
from #6317.

The dedicated workflow executes only small two-state fixtures.  One dual-mode
workflow run has six successful bounded uniformization calls: three with
assertions enabled and the same three under `python -O`.  It loads no authentic
N256 bundle and performs no HCSN dynamic, model, Torch, optimizer, or training
work.

This stage does **not** certify Decimal transcendental evaluation or final
binary64 output rounding.  It is not an independent N256 provider, does not
run the 18,225,028-record denominator, and does not change any historical RED,
UNKNOWN, finite-domain failure, C2 `0/6`, HPCA NoUpdate, or global HOLD result.

