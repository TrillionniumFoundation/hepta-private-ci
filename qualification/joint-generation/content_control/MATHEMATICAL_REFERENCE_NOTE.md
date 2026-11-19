# Parent-reported two-stage exact reference

This post-build note records a mathematical reference reported by the parent
thread `01a156db-3214-7376-8d02-62ca706bc0dd` on2026-10-23. The parent attributes
it to its independent dot literature/reference group. No code path, commit or
test log accompanied that message, so its numerical checks are parent-reported,
not independently executed or reproduced in this cloud workspace. This note
does not change the frozen protocol, source, model selection or measured results.

The parent reports15 passing finite two-stage checks covering entropic tower
recursion, joint path mixtures, observable-state versus latent-oracle values,
the initial-state gate comparator and control cost. Its hand-designed informative
case has feedback-minus-initial-gate CE +1.050856; no-information and deterministic
controls have zero gain. A misleading observation gives a naive policy CE
-1.612844. Charging its declared2.0 reward-unit overhead changes the positive
case to-.949144. These are toy reference values, not text/image model training,
generation quality, or evidence of a10-second/12B-unit win.

## Exact law to preserve

For each request, path weights pi(s), conditional content distributions p_s,q_s,
fixed decoded reward R and fixed rho>0, the relevant joint outcome law is:

```
Z = sum_s pi(s) * sum_jk p_s(j) * q_s(k) * exp(-rho * R(j,k))
CE = -log(Z) / rho
```

Multiplying path-averaged text/image marginals would introduce cross-path
combinations that were never generated. Averaging path CEs is also different
from the CE of the joint path mixture. The request average stays outside each
request's log. Appropriate conditional information and the same risk profile
are needed when applying the entropic tower identity. This note supplies no
new NDU implementation or theorem about the neural model.

The completed content experiment uses the rho=0 additive contribution, with
the explicitly registered mean of five path losses. Its utility term is exactly
the average of conditional joint expected rewards. Its supervised anchor is the
registered mean of pathwise CE losses; it is not reinterpreted as CE of a mixed
output law. No new entropic path optimization was run.

## Cost and information boundaries

The parent's coarse resource example distinguishes refinement allowance from
complete allowance: two refinement units plus0.25 control-resource units are
infeasible under a total cap2, and feasible under a prospectively fixed cap2.25.
Static controls must also be allowed every legal sequence at that same total
cap. Its resource units and reward-cost units are not mapped to project CPU
seconds or the declared operator profile.

Our TT/TI/IT/II/J allowance counts two single-head refinement actions, while the
actual complete build and service accounting separately includes preparation,
all candidate/path search, training, export and executed inference/output work
under the original10-second/12B ceilings. A future gate's computation/training
must be added to that complete account; two refinement actions alone would not
make the gate free or admissible. Neither the complete caps nor old plans have
been increased to2.25 or otherwise changed.

For this group's selected deterministic refiner, h and each intermediate
content state are functions of the initial input and fixed learned weights;
there is no newly observed external signal. Action crossing alone therefore
does not establish extra information from feedback or superiority to an
initial-state gate. The label-known source-oracle headroom was only.00013289
and failed the preregistered.002 threshold. The initial gate and larger policy
were consequently not trained. No toy positive number can override that result,
the new refiner's negative TRAIN comparison, or CORE c1's consumed formal failure.

See [the actual content results](RESULTS.md) and
[the nonexecutable confirmation/history review](HISTORY_AND_CONFIRMATION.md).
