# Asymmetric conditional risk did not improve joint NDU

The proposed text-neutral risk target and its reverse-direction control both
underperformed original joint NDU in this fixed synthetic study. The strict primary
gate remains **false**. Removing one modality's outer risk is not supported as a
repair for the small greedy-text regressions observed in earlier aligned training.

## What changed

Keep the same shared encoder, learned decoder, independent product serving law,
semantic transport and aligned anchor. Change only the scalar training utility:

- **J**: original joint certainty equivalent (CE) over text/image outcomes.
- **T**, proposed: expectation over text of image-conditional CE.
- **I**, reverse control: expectation over image of text-conditional CE.
- **A**: ordinary expected reward.

For positive risk aversion, J<=T<=A and J<=I<=A. T/I are different explicit scalar
objectives, not equivalent rewrites of J, STEs or nonconservative head-gradient
splices. Neither text nor image is frozen; both still learn through the shared
encoder. Evaluation always uses **original joint CE**, never the changed target.
No claim of greedy accuracy preservation or unbiased Adam updates follows.

## Fixed results

Two seeds, four objectives,300 updates each,batch64,lr.003,anchor.2,rho1.5,unchanged
full sampling. All eight final models preceded validation. Four A/J control digests
exactly reproduced previous aligned-training controls. Both conditional objectives
were computed in every arm, including controls, so added arithmetic was charged.

Partial-command macro(full,low) changes:

| Contrast | Seed11 joint-CE | Seed23 joint-CE | Greedy-text change11/23 |
|---|---:|---:|---:|
| Proposed T − J | −0.006382 | −0.005831 | −1/624,0 |
| T − A | +0.008039 | +0.011036 | −1/624,−1/624 |
| Reverse I − J | −0.005231 | −0.008608 | 0,0 |

T−J also worsened correct-text mass,joint success and pixel MSE in both seeds.
The reverse direction did not rescue those metrics. T−A improved mean probability
and image measures but failed greedy-text nonregression in both seeds. The original
two-seed/two-contrast five-condition gate is unchanged; no direction,rho or seed was
selected after viewing these results. The asymmetric-risk mechanism is closed for
this profile, rather than refined until validation becomes favorable.

This tests a mechanism suggested by earlier risk-component attribution, not its
causal interpretation. The proposed intervention failed on this new RGB profile;
it does not causally reinterpret the unavailable original study.

## Code and qualification

`conditional.py` implements both scalar targets and their exact softmax-logit
gradients, with centered-expm1 and logsumexp branches. `test_conditional.py` has
eight tests, including central differences,small-rho behavior,zero support,rho0
parity,modality swap,Jensen bounds,transport identity and complete anchor gradient.
Run within this directory using already qualified repository dependencies:

```sh
PYTHONPATH=..:../transport-aligned-training python -B -m unittest -v test_conditional
```

`PLAN.md` is the pre-execution plan. `SUMMARY.json` retains every arm,contrast,
channel,population and measured cost, including negative outcomes.

## Cost and scope

Whole waited child: **7.980548 CPU seconds**,8.016415 wall seconds,47324KiB RSS.
Includes eight tests,two restores,8clones,2400updates,7220forwardbatches/471120rows,
4800 additional conditional-objective evaluations,2decoder observations/24images
and exit.
Bounds20CPU/90wall/512MiB,CPU0/one thread,existing new synthetic-only shared lock.
Historical base preparation,source/review and supervisor tail remain additional,
not zero. Matched operations/common caps are not equality of actual total cost.

These are exploratory results on reused finite-RGB validation,not fresh held-out
confirmation,natural-image capability or restoration of the unavailable original
digit study. No TEST data,private inputs,model payloads or per-request outputs are
published. No deployment or gate relaxation followed.
