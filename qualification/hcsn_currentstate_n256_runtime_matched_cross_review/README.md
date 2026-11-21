# N256 runtime-matched cross-lineage review

This evidence-only review binds the immutable coordinate localization from
#6892/#6893 to the later exact-runtime attempt in #6901/#6902.

Both numerical attempts published the same candidate SHA256
`33ee695bfc001ca9bb5555befe384e0dee60e49be32832170ceabfeebee9c6bc`
and the same strict result: 665 mismatches among 69,728 coordinates, maximum
absolute error `0x1.e000000000000p-54`, and maximum ULP distance 98.

#6892 localized those mismatches without numerical execution: 650 are in
`state/active`, and five each are in `state/discounted_hit`, `state/mass`, and
`state/occupation`. Metadata, packets, upper state, and the unchanged active
slot are bitwise exact.

#6901 then reproduced the same candidate and mismatch ledger after exact
runtime admission for Python 3.12.3, NumPy 2.3.5, and SciPy 1.17.0. Therefore
the earlier Python 3.12.16 versus 3.12.3 lineage difference cannot explain the
RED. The remaining arithmetic/path cause is still UNKNOWN; this review does
not repair either attempt or grant qualification.

Review work is 0 model, 0 dynamic step, 0 expm, 0 Torch, and 0 optimizer.
Historical RED/OOM/cancelled/UNKNOWN records remain preserved. C2 full replay
remains 0/6, HPCA remains NoUpdate, production adoption is false, global status
is HOLD, and `all_closed=false`.
