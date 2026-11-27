# Retained local development RED

Before source freeze, the first local implementation propagated cumulative hit
and returned intervals independently, then formed pending as `hit - returned`.
The subtraction interval did not uniquely round to binary64 because independent
enclosures discarded the strong correlation between those coordinates.

The gate failed closed with:

`HitDelayResetIntervalError: pending interval lacks unique binary64 rounding`

No tolerance or rounding threshold was changed. The repaired candidate adds an
explicit pending/new-hit accumulator during the second method-of-steps segment.
Its derivative is the same current active hit flux, so the pending coordinate
is integrated directly and the lossy interval subtraction is removed.

This record is local development evidence, not a precommitted execution result.
