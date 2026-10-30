# Learn the separate text branch: exploratory RGB follow-up

**New independent finite RGB task, not a recovered round04 experiment.** This
prospective follow-up was chosen after the published frozen-text failure at
`a8e1423ae2c0f7484c3244ced74767b5a81e06cc`; that failure remains unchanged.

## Tested mechanism

Freezing the pretrained text marginal blocked useful learning. Here the text
branch continues to learn using the original supervised half cross-entropy, while
an independent image branch learns anchored additive or entropic utility under
the current text distribution. Both pullbacks use the same pre-update pair.
The served law is the actual product of these two learned categorical marginals;
the original fixed learned RGB decoder and 144-outcome observer remain unchanged.

This is **not full joint NDU optimization**: the text branch receives supervised
CE rather than the utility gradient. NDU is applied to the image branch only.
With identical batches and initialization, text parameters must be exactly equal
between additive and NDU, and this is asserted before validation. The joint
control is the original complete additive/NDU pullback, tested for exact identity.

## Prespecified design

Same original task and settings: seeds 11/23; joint/decoupled × A/N = eight cells;
300 decoder, 500 pretraining and 300 adaptation updates; batch64; lr.003;
anchor.2; rho1.5. All eight artifacts are frozen before generating validation.
Six variants per group; both full and low inputs retained with equal-weight mean
primary. No TEST generation or selection. This is reused benchmark validation,
not independent confirmation. Five literal tests pass, including the two exact
reference updates and independence of text learning from the image objective.

The primary contrasts require rho gain >=.005, no text-mass/greedy-text or
expected-joint-success decrease, and no image-MSE increase, in both seeds.
Full and low are separately reported but were not independent no-regression gates.

## Results

| Contrast | Seed | Delta rho | Delta text mass | Delta image MSE |
|---|---:|---:|---:|---:|
| decoupled N − joint N |11| −0.01681805 | −0.01067561 | +0.00005888 |
| decoupled N − joint N |23| −0.02301208 | −0.01165791 | +0.00014569 |
| decoupled N − decoupled A |11| +0.00584810 | 0 (exact) | −0.00036787 |
| decoupled N − decoupled A |23| +0.00636703 | 0 (exact) | −0.00039952 |

**Overall method gate fails.** Decoupling with CE-only text still underperforms
original joint NDU, although greedy text accuracy increases. The within-decoupled
NDU increment passes its two prespecified seed gates. This narrower exploratory
result must not be advertised as beating the original baseline or confirming the
missing round04 hypothesis.

Greedy **joint** success, not part of the prespecified no-regression gate, falls
by .00096899/.00581395 for N−A. This adverse metric is retained, not hidden behind
the expected-utility improvement. Every arm, contrast and channel is in
`RESULT.json`; no post-result arm or threshold was added.

The next distinct question is whether separating encoders helps when **both**
branches retain the original anchored utility gradients. That would isolate
architecture separation from this experiment's text-objective replacement.
It requires its own prospective freeze; it is not an interpretation of this run.

## Cost and limits

Complete driver and reaped children: **3.906938 CPU / 3.908740 wall seconds**.
Five tests: .172314 CPU; worker:3.686706; driver own:.047918. Full conservative
per-method cost is .975700–1.099634 seconds under the same 60-second cap; campaign
cap400CPU/600wall. Full own-seed base and all shared preparation/tests/imports/
reports/tails are charged per method; campaign amortized shares are separate.
The outer settlement writer and historical development/publication remain
unmeasured, nonzero costs outside this instrumented execution scope.

Decoupled uses **300 text plus 300 image optimizer calls**, versus 300 full joint
calls. It has extra backward work and separate encoders; there is no dummy
backward padding. Equal prospective caps and scheduled updates do not mean equal
actual CPU/FLOPs, equal fully spent budgets, or an efficiency improvement.
No model/data payloads are published; no merge/deployment/hosted-CI assertion.
The independent synthetic lock is shared with concurrent RGB work, never used to
bypass the missing original lock.

## Reproduce

```sh
python3 -I -B qualification/joint-generation/decoupled-text-training/test_mechanism.py
python3 -I -B qualification/joint-generation/decoupled-text-training/settle_once.py /absolute/new/output
```

`FREEZE.json` binds exact code and plan, including the unchanged original
`model.py`, `data.py`, and `utility.py`. Existing outputs and held locks are refused.
