# Authentic N256 signed initial capsule

Status: **PRECOMMITTED INITIAL INPUT ONLY / RESOURCE HOLD / all_closed=false**.

This separately frozen stage reads one immutable #6908 artifact, applies the
canonical #6916 adapter, and constructs one index-zero capsule for each N256
lane.  Each capsule contains the full canonical operator, duration, and five
seed vectors.  Cold decode re-parses every coordinate, rebuilds the initial
transition, and must reproduce the capsule bytes exactly.

The one admitted hosted execution performs 1 artifact read, 2 adapter calls,
2 initial builds, 2 cold-decode rebuilds, and 13,135 exact input conversions.
It performs 0 tail checks, recurrence row actions, provider outputs, dynamic
steps, matrix exponentials, Torch calls, or optimizer steps.  Attempt 2 or a
reused workflow run is rejected before reading the authentic artifact.

This is an initial request capsule, not a mid-recurrence checkpoint, hostile
writer custody mechanism, full-state oracle, or resource admission.  It does
not close N256/N512 numerics, unique rounding, arbitrary histories, later
cycles, migration, full-network training, C2 full replay, HPCA custody or
benefit, production, or adoption.

#6908 remains `RED_DUPLICATE_KEY`; #6913 remains
`RED_NONCANONICAL_INPUT`; #6901's numerical cause remains `UNKNOWN`; C2 full
replay remains 0/6; HPCA remains NoUpdate; `all_closed=false`.
