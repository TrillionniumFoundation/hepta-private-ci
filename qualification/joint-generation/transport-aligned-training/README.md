# Training aligned to the final served semantics: strong alignment signal, incomplete NDU claim

Earlier probability transport repaired a serving constraint, not learning. This
experiment actually retrained eight models with the same shared encoder/heads,
same two supervised bases and same fixed300 updates. All models were evaluated
under the SAME transport service. Decoder pixels remained learned and frozen.

**Serving-aligned training improved both seeds. The combined prespecified claim
still failed:** aligned NDU regressed one seed's greedy text accuracy by1/624
relative to aligned additive training. That failure is retained, not rounded away.

## Exact mechanism

For semantic destination maps f,g and unchanged external reward R, pull back
the table as R'(i,j)=R(f(i),g(j)). Entropic A/N value under original policies and
R' equals value under the transported policies and R. The existing utility
gradient routine therefore remains exact; no STE or approximate derivative.
The aligned anchor uses the probability of the final decoded target semantics,
summing all latent proposals that transport to it. It does not infer instructions
from the training target. The serving operator still uses only explicit words.

All-keep preserves utility pullback; anchor equality with raw latent-label CE
additionally requires identity decoded semantics. Fully specified commands have
zero current aligned gradient, not necessarily a zero Adam update from history.

## Fixed useful work and results

raw/aligned × additive/NDU × seeds11/23,300 updates each,batch64,lr.003,
anchor.2,rho1.5. Every arm computes both anchors and all four utility branches,
and uses identical precomputed full/low row choices. All four raw final tensor
digests exactly reproduced the prior independently frozen joint-control finals.
All eight models were fixed before validation generation. No best-step selection.

Primary evaluation averages full/low channels on312 partial-command validation
rows. Full516-row results, both channels, both bases and all contrasts are saved.

| Contrast, partial full/low mean | Seed11 | Seed23 |
|---|---:|---:|
| aligned N − raw N: CE gain | +0.074477 | +0.082588 |
| aligned N − raw N: joint-success gain | +0.057055 | +0.062587 |
| aligned N − raw N: pixel-MSE change | -0.001556 | -0.001667 |
| aligned N − aligned A: CE gain | +0.014420 | +0.016868 |
| aligned N − aligned A: pixel-MSE change | -0.000207 | -0.000263 |
| aligned N − aligned A: greedy-text change | 0 | **-0.001603** |

Both alignment contrasts passed all five frozen conditions. NDU's incremental
contrast passed seed11 but failed seed23 greedy-text nonregression. Thus the
overall two-contrast/two-seed primary gate is **false**. Alignment also improved
the additive branch; the benefit is not uniquely attributable to NDU.
Reused synthetic validation is exploratory evidence, not independent confirmation,
natural-image capability or recovery of the unavailable original digit experiment.

## Portable code and checks

`aligned.py` implements reward/anchor pullbacks. `test_aligned.py` has seven tests,
including centered differences of the complete objective for A and N, a permuted
decoder mapping, identity-map raw parity, zero-gradient full commands and target
mass rejection without epsilon. In this directory within the repository run:

```sh
PYTHONPATH=..:../explicit-semantic-transport python -B -m unittest -v test_aligned
```

The referenced original `model.py`/`utility.py` and prior transport helpers were
verified identical to the executed dependencies. This package contains no models,
private inputs, per-request predictions or machine paths. `PLAN.md` is unchanged
from before execution; complete aggregate results are in `SUMMARY.json`.

## Complete measured cost and limits

Whole waited child: **4.924381 CPU seconds**,4.945490 wall seconds,47260KiB RSS,
including seven tests,imports,two restores,8 clones,2400 updates,7220 forward
batches/471120 rows,20 scalar/vector serving checks,metrics and exit. Bounds:
20CPU/90wall/512MiB,CPU0/one thread,new synthetic-only shared lock. Base-preparation
prefixes0.219982/0.227947 CPU seconds were inherited, not free. Other upstream
costs,source/review and supervisor final tail remain additional/unknown. Equal
useful updates and arithmetic branches are not equal actual total spend.

The remaining NDU greedy-text regression is unresolved. No gate was weakened,
no parameter was retuned and no model was selected for deployment.
