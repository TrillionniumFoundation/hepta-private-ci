# Draft #6950 RED originals

This directory preserves the eleven immutable artifacts from the only
admitted run of Draft #6950.

- source: `bf5f5a8567af3faccf86792249fba33d99e498b9`
- run: `45003362451`
- key: `hcsn-n256-authentic-tailcheck537-parallel-20261122-c6bc-001`

Preflight passed.  Every lane reached its journaled `index537_reached`
event, then the existing certificate path raised Python's 4300-digit decimal
integer conversion exception before any lane `RESULT` was published.  The
collector therefore correctly published `RED_INCOMPLETE_OR_CAP_EXCEEDED`
with zero completed lanes and zero authoritative completed work.

The verifier checks exact ZIP sizes and SHA-256 digests, CRCs, all ten
interruption journals, and the collector's fail-closed result.  It performs
no recurrence, tail, rounding, provider, dynamic, exponential, Torch, model,
training, or optimizer work.

This evidence does not repair or relabel the failed run.  Draft #6939 remains
RED, Draft #6942 remains RED_TIMEOUT with completed actions UNKNOWN, and
#6901 remains UNKNOWN.  Global status remains HOLD / NoUpdate /
`all_closed=false`.
