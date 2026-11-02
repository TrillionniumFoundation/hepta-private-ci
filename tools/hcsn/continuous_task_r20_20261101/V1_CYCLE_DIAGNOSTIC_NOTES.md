# Frozen V1 failure and precise repair

V1's first exact campaign completed and archived 48 coarse-mesh direction cases,
then failed at the opposed-base admission control. Its directional policy masks
did not stabilize before the 256-iteration guard. `V1_CYCLE_DIAGNOSTIC.json`
captures the actual terminal system: its mixed complementarity residual is only
`2.7755575615628914e-17`. The diagnostic's `mask_changes=0` compares locals after
the last `active=next_active` assignment, not consecutive pre-update masks; it
must not be read as evidence that the convergence guard had passed.

The real defect was using policy-mask identity as the only stopping criterion
at floating ties. Correct critical values can satisfy the mixed LCP while masks
oscillate from rounding. V2 instead checks the applicable row constraints:
forced WAIT rows use `Az-r`, forced CONTACT rows use `z-do`, and biactive rows
use `min(z-do,Az-r)`. Their complete infinity residual must be at most a fixed
roundoff-scaled solver bound. A stable mask with excessive residual now fails.

This does not widen the registered `1e-10` algebra gate, change one-sided step
sizes, change either finite-step threshold, alter the direction roster or turn
an unresolved generic numerical tie into a mathematically exact tie. For the
mixed M-matrix system, translations and the comparison principle give the same
real-arithmetic residual-to-value bound as in the mathematical review, with
`m=min(1,min(A1))`. Evaluated floating residuals remain diagnostics, not an
outward-rounded machine certificate.

All fourteen V1 frozen files and its exact original freeze are preserved under
`source_v1/`. The incomplete `exact_run/`, complete `generic_run/`, all errors,
the failed exact replay, successful generic arithmetic replay and complete outer
process costs remain. V1 generic completed all 78 attempts; its finite-step
gate failed. V2 is a separately frozen numerical solver repair under the same
original prospective protocol; no V1 failure is retroactively called a pass.
