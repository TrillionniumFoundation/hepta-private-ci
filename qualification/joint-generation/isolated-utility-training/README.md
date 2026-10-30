# Separate encoders with the original utility: family closeout

**New independent finite RGB experiment, not round04 recovery.** This third and
final mechanism-family test was fixed after the CE-only-text follow-up at
`aa2652f2433f73930ead5ac8445acb90833a43fa`. All previous failures remain failures.

## Question and implementation

The previous experiment changed both sharing architecture and the text objective.
Here **both** independent encoders receive the original anchored additive/NDU
objective's pullbacks, computed at the same pre-update p/q. Only the sharing
architecture differs from the original joint control. The decoder remains fixed;
the served product law and actual decoded RGB observer are unchanged.

This does not identify “gradient conflict” as a cause: separate encoders also
change parameter capacity, Adam state, and per-branch norm clipping. The two
optimizer calls have real extra cost, not hidden or dummy-padded work. The joint
control's update matches upstream exactly. Five literal tests pass, including
finite differences for both encoders and exact one-step reference updates.

## Design retained before execution

Eight cells: joint/isolated × A/N × seeds11/23. Same 300 decoder, 500 pretraining,
300 adaptation updates; batch64; lr.003; anchor.2; rho1.5. All eight model pairs
saved/hashed before validation generation. Six variants, full/low equal-weight
mean. No selection, TEST generation or threshold relaxation. The original
benchmark validation is reused exploratory evidence, not independent confirmation.

Main method and N-increment contrasts require >=.005 rho gain, no text-mass,
greedy-text or expected-joint-success regression, and no image-MSE regression
in both seeds. Full and low metrics are retained separately, not added later as
gates. See `PLAN.json` and exact executed `FREEZE.json`.

## Result: no improvement over original joint training

| Contrast | Seed | Delta rho | Delta text mass | Delta image MSE |
|---|---:|---:|---:|---:|
| isolated N − joint N |11| −0.00114117 | +0.00006922 | +0.00007714 |
| isolated N − joint N |23| −0.00239060 | −0.00130469 | +0.00006496 |
| isolated N − isolated A |11| +0.01154976 | +0.00288660 | −0.00037037 |
| isolated N − isolated A |23| +0.01448829 | +0.00306906 | −0.00044052 |

NDU increases expected utility within the isolated architecture, but greedy text
accuracy falls by .00096899/.00193798; therefore its prespecified no-regression
gate **fails**. The main isolated-vs-joint contrast also fails. Neither a positive
rho alone nor a near-zero baseline gap is accepted as success.

**Close this architecture family:** freezing pretrained text, independently
supervised text, and independent utility-trained encoders all fail their overall
method gates. Do not launch a finer arm sweep or lower thresholds on this reused
validation set. The narrower CE-decoupled N−A gate passed in the previous run,
but did not beat the original baseline and remains exploratory.

`FAMILY_CLOSEOUT.json` checks saved JSON only: all three runs have exactly equal
original-joint baseline metrics, base metrics and dataset manifests. Across the
family, **24 cells and 15 tests** completed; all three overall quality gates failed.
No models were reloaded for this cross-study identity check.

## Actual costs

This run: **3.528407 CPU / 3.528959 wall seconds**, full waited driver and children.
Tests:.168029 CPU; worker:3.324692; driver:.035686. Conservative standalone
per-method charges:.908570–.984902 seconds, under equal60CPU caps; campaign cap
400CPU/600wall. Full own base and all shared preparation/tests/imports/checkpoints/
reports/process tails are charged; amortized physical shares retained separately.

All three runs total **10.646379 measured CPU seconds**. This excludes the outer
settlement writer and historical recovery/source/review/publication, explicitly
unmeasured and nonzero. Equal caps and scheduled updates are **not** equal actual
spend or fully spent-budget performance; isolated has extra parameters/backward
work. There is no serving-speed improvement claim.

Use the same independent synthetic-only lock as related RGB experiments; never
substitute it for the missing round04 lock. No model/data payload is published;
no merge, deployment or hosted-CI assertion.

## Reproduce

```sh
python3 -I -B qualification/joint-generation/isolated-utility-training/test_mechanism.py
python3 -I -B qualification/joint-generation/isolated-utility-training/settle_once.py /absolute/new/output
```
