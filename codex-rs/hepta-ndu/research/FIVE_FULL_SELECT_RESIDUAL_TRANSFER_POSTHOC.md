# Full-SELECT transfer audit of the completed residual directions

Date: 2026-10-15. This audit was designed after observing the paired SELECT and
full-pool retrieval results. It is explicitly post-hoc exposed-development
evidence, not an independent confirmation set or a production model choice.

## Exact inputs and denominator

The audit binds three completed immutable artifacts:

- full SELECT retrieval, source `8e213b7585221ddf9fd279037caa4dc6f972af6c`,
  run `38540293994`, artifact `11885366683`, ZIP SHA256
  `6534177c6974ee0e9fe0a331891ec5cb0b2443481198ece36cfcaf754003d436`;
- cosine-residual v3, source `14eb7234a32fd20c8fd4e677f11a241db0d00ad6`,
  run `38665708709`, artifact `11942057629`, ZIP SHA256
  `23d8d35da612a45d99aafcf2f9f09eceae94b08bb3ee61cb853ac71c50d8cd90`;
- crossed paired inputs, source `9da0908298f26fab8173a7ffa04807c9ab179ca7`,
  artifact `11878031858`, ZIP SHA256
  `bb61d593ed46f3245339ca5a41a4198d3c346823c7b7a091b090274c33ab3b78`.

The worker replays the exact nine saved residual checkpoints on the sealed
full-SELECT frozen feature pool:

- 296 planned questions, 295 scoreable and one retained unavailable;
- 248 available evidence candidates;
- 73,160 scored question/candidate pairs per checkpoint;
- 658,440 new residual pair scores across nine checkpoint directions;
- seven nonzero scales per checkpoint, for 63 sealed score matrices.

No pretrained model or Reader is loaded. No Encoder forward or optimizer update
occurs. The answer body never enters scoring. The original cosine and lexical
matrices are independently revalidated before adding any residual.

## Fixed evaluation

Every checkpoint is evaluated at

```
alpha = 1/64, 1/32, 1/16, 1/8, 1/4, 1/2, 1
score = sealed_cosine + alpha * saved_residual
```

No seed, checkpoint or alpha is selected from the full pool. The paired
TRAIN-only rule is recomputed from the v3 artifact and must reproduce its exact
decision before the broad audit proceeds: all three balanced checkpoints choose
`1/16`; the one-way and reversed checkpoints have no qualifying scale.

The frozen baselines are:

| Method | Global top-1 | Global top-5 | Global MRR | Within-family top-1 | Within-family top-5 | Within-family MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cosine | 43/295 | 88/295 | 0.228930 | 46/295 | 91/295 | 0.246316 |
| lexical Jaccard | 83/295 | 151/295 | 0.402532 | 84/295 | 158/295 | 0.409927 |

## The paired TRAIN-only choice does not transfer to the full pool

At `alpha=1/16`, every balanced seed is below frozen cosine on all six aggregate
retrieval measures:

| Seed | Global top-1 | Global top-5 | Global MRR | Within top-1 | Within top-5 | Within MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20261014 | 36 | 73 | 0.190405 | 39 | 76 | 0.209805 |
| 20261015 | 31 | 66 | 0.175790 | 34 | 74 | 0.197771 |
| 20261016 | 33 | 71 | 0.183084 | 34 | 80 | 0.200550 |

Paired item comparisons agree with the aggregate decline. Globally, frozen
cosine has a better deterministic rank on 156–161 questions, while the balanced
`1/16` residual is better on only 99–101. It also loses 14–17 cosine-only unique
top-1 successes while adding only five to seven new unique top-1 successes.

This rejects the broad interpretation that closing all 13 TRAIN rectangles and
improving the three paired SELECT rectangles at `1/16` learned a generally useful
retrieval correction.

## Small perturbations are not specific to the intended balanced direction

The best full-pool row in the fixed grid is the one-way seed 20261014 at
`alpha=1/64`:

- global: 46 top-1, 93 top-5, MRR 0.236865;
- within family: 48 top-1, 98 top-5, MRR 0.251178.

It is the only grid row that exceeds frozen cosine on all six aggregate measures.
But that checkpoint does not satisfy the strict paired TRAIN rectangle rule.
Moreover, reversed controls at `1/64` also raise some top-1 or MRR measures:
within-family top-1 reaches 49–50 and MRR reaches about 0.252 while strict top-5
usually falls. Therefore tiny score perturbations can change tie and near-tie
ordering without showing that the intended balanced relation was learned.

All full-amplitude residuals collapse badly. Across the nine checkpoints at
`alpha=1`, global top-1 is only 1–6/295 and strict top-5 is 10–16/295, far below
frozen cosine and lexical retrieval.

## Interpretation and next confirmation

The combined evidence now separates three claims:

1. frozen cosine contains broad but limited retrieval information;
2. the balanced residual contains a locally useful small-amplitude direction on
   the three paired rectangles;
3. that direction does not improve broad full-pool retrieval under the same
   TRAIN-only `1/16` rule.

The next valid experiment should not tune another scalar on this exposed pool.
It should freeze the Encoder, label construction, residual family and a
regularization/stopping rule before evaluating a genuinely new task family. A
strong design must also include tiny one-way and reversed perturbations, because
the full-pool audit shows that generic local reordering can mimic isolated metric
improvements. Final Reader answer quality and evidence sufficiency remain
separate required outcomes.

`full_select_fit=false`, `alpha_selection_from_full_select=false`,
`new_optimizer_updates=0`, `new_reader_calls=0`,
`reader_call_skipping_authorized=false`, `semantic_accuracy=null`,
`production_accepted=false`, `five_experiments_completed=false`.
