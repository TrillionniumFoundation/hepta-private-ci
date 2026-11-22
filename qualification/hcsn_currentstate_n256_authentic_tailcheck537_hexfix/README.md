# Authentic N256 index537 first-tail check: hex-only fix

Status: **HOLD / all_closed=false**.

This separately frozen successor preserves the full RED run in #6950 and its
immutable originals in #6955. It consumes the same byte-exact compact index256
full-state originals from #6948/#6949. Ten fixed lane jobs each decode one
compact checkpoint, apply exactly 281 exact recurrence row actions to included
index537, evaluate exactly one ratio-bound signed interval, and persist both the
complete compact index537 state and full tail/rounding record.

The collector requires all ten lanes and unchanged 8 MiB per-cursor, 32 MiB raw
state, and 64 MiB aggregate compact-state caps. It accepts either a unique or a
non-unique scientific result: a negative first-tail result is not a job failure
and cannot be rerun to pursue positivity. Missing lanes, malformed originals,
cap breaches, identity changes, or incomplete work remain RED.

Each lane has one attempt, a 115-minute command limit inside a 120-minute job,
and an `always()` interruption-journal upload. The unique key is not reusable.
The work budget is 2,810 exact row actions, ten tail checks, at most 5,180 exact
rounding calls for the authentic 258/259-coordinate lanes, 20 index537 compact
encodes, ten index537 compact decodes, and ten index256 compact decodes. It
permits zero provider, dynamic, exponential, Torch, optimizer, model, or
training calls.

The only algorithmic change replaces the old certificate-producing rounding
wrapper with the same exact integer roundTiesToEven calculation returning only
the canonical 16-hex-digit result. It does not stringify the huge numerator or
denominator, mutate Python's global digit limit, or weaken a numerical gate.
Small boundary controls compare it directly with the existing primitive, and a
5000-digit exact control exercises the original failure class before admission.

Completion closes only the observed first possible tail check and an index537
checkpoint resource profile. Tail termination closes only if all ten observed
lanes are unique; provider completion, independent provider comparison,
arbitrary-history resume, N256 qualification, C2 full replay, HPCA external
custody, equal-budget benefit, asynchronous cost, and production adoption stay
open. #6950 and #6939 remain RED, #6942 remains RED_TIMEOUT with UNKNOWN
completed actions, and #6901 remains UNKNOWN.
