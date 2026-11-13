# N128 second-cycle canonical coarse/cold controls

Status at source freeze: **HOLD / INTENT_NOT_EXECUTED / qualification=false / all_closed=false**.

This separately frozen successor uses the exact #6282 `t=.2` start and the
exact three #6283 warm capsules. It starts eight fresh Python processes: a CSR
candidate and an independent dense oracle for one coarse lane and three cold
lanes. The requested outputs are compared against each other and against the
immutable #6283 containers.

Two unfrozen development failures remain in `DEVELOPMENT-RED.json`. The first
was a missing local start path before numerical imports. The second is the
scientifically relevant negative: a direct `.2 -> .36` cold request that did
not expose the `.28` slice failed the frozen packet-roster identity. The failed
child's executed call count is `UNKNOWN`; successful prefixes are recorded
separately and are not added to it.

The post-failure candidate tested here is explicit canonical slicing, not a
claim that arbitrary query schedules are invariant. Every fresh process
internally visits `.201`, `.28`, and `.36` up to its requested target, even if
an intermediate capsule is not returned. This bounded contract prevents the
observed packetization drift for these three frozen slice times.

Even success does not qualify arbitrary histories or query times, third-cycle
release after `.4`, N256/N512 dynamics, full-network training, finite-domain
behavior, asynchronous complete cost, C2 full replay, or HPCA external
custody. It does not modify production defaults.
