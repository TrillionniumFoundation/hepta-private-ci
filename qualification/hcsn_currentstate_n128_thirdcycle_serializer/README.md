# N128 third-cycle-ready serializer — actual parent, HOLD

This stage implements the missing canonical state format needed before a
bounded third-cycle numerical successor may be admitted.  It consumes the
exact successful #6285 order-7 capsule at logical time `.36`; it does not
reconstruct or replace any historical artifact.

The old state contains two active generations and 1,320 scalars.  The new
format preserves every old binary64 coordinate and packet byte while adding
zero-initialized generation-3 active/M/H and origin-3 upper/A coordinates.
The authoritative state therefore contains 1,975 scalars.  The new magic and
capsule identity prevent an old loader from silently interpreting the expanded
layout.

The primary serializer and an independently written raw decoder each emit the
complete conceptual dense coordinate stream for the actual 22-packet parent.
The frozen denominator is 870,739 coordinates.  A fresh process must reproduce
the primary stream byte-for-byte and verify the new container hash.

This stage executes no dynamic segment, matrix exponential, Torch operation,
or optimizer update.  It does not establish third-cycle numerical execution,
target-4 retention, `.4 -> .401` accuracy, actual 383-dimensional operator
cost, arbitrary histories, N256/N512, finite-domain qualification,
full-network training, async cost, production adoption, or `all_closed`.

The #6285 direct-slice RED and UNKNOWN failed-child call count remain unchanged.
Global status remains **HOLD / NoUpdate / all_closed=false**.
