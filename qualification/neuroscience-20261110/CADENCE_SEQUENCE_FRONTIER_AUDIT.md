# Seven-lineage clock observation frontier — 2026-11-11

**RESEARCH_ONLY / HOLD_NO_GO / DENY_ALL.** This is a shadow contract repair
stacked on #5939, not a native StageOwner guarantee or science result.

## Defect and red test

At parent `c67042414803acc9316b799fde63494b95a47dca`,
`cadence_gate` checked `ev.sequence` only against the last *admitted* clock
slot. Example: `PERC` seq 1 admitted; seq 10 rejected by the 16-step
clock; seq 9 then accepted as a valid chronologically earlier observation
rather than rejected as a clock regression. This is an order/identity contract
hole, not proof of training data leakage or real actor compromise.

New test `test_clock_denied_event_still_advances_observed_sequence` reproduced
failure before the code change (AssertionError: ContractError not raised).
The separate evidence-denied case was already rejected, because evidence-denied
slots had been admitted by the clock; we retain it as a non-regression control.

## Remedy and constraints

Keep two distinct frontiers, each scoped by lineage: most recent **observed**
sequence (monotone, including `NO_UPDATE` clock denials), and most recent
**admitted** slot (determines rate limit). Equal-sequence events remain legal
in this shadow API; an actual owner must specify duplicate receipt semantics
and authenticate event identity and sequence. Generation monotonicity added
by #5939 remains separate and unchanged. Interleaved lineages remain independent.

The test suite uses synthetic update opportunities only; no model run,
optimizer step, actual outcome, source attestation, learning adoption, or
cold recovery is established. Production and efficacy qualification remain HOLD.
