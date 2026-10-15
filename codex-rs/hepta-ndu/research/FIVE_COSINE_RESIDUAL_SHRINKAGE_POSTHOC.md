# Post-hoc shrinkage audit of completed residual checkpoints

Date: 2026-10-15. The completed SELECT outcome was observed before this audit
was designed. All results below are therefore exposed-development mechanism
diagnostics, not preregistered confirmation or production model selection.

## Exact immutable inputs

The audit consumes only two authenticated completed artifacts:

1. cosine-residual v3, run `38665708709`, source
   `14eb7234a32fd20c8fd4e677f11a241db0d00ad6`, artifact `11942057629`, ZIP
   SHA256 `23d8d35da612a45d99aafcf2f9f09eceae94b08bb3ee61cb853ac71c50d8cd90`;
2. crossed SELECT inputs, source
   `9da0908298f26fab8173a7ffa04807c9ab179ca7`, artifact `11878031858`, ZIP
   SHA256 `bb61d593ed46f3245339ca5a41a4198d3c346823c7b7a091b090274c33ab3b78`.

The worker revalidates source commits, execution disposition, plans, prediction
seals, denominators, raw-result hashes and all nine checkpoint parameter hashes.
It loads only those nine 6,152-parameter checkpoints and the completed frozen
feature file. It performs zero Encoder, Reader or optimizer work.

## Fixed scale path

For each saved residual checkpoint, the score is replayed at the fixed grid

```
alpha = 0, 1/64, 1/32, 1/16, 1/8, 1/4, 1/2, 1
s_alpha(q,e) = cosine(q,e) - threshold + alpha * r_theta(q,e)
```

`alpha=0` must reproduce the frozen-cosine rows byte-for-byte and `alpha=1`
must reproduce the completed v3 rows byte-for-byte. No value is fitted. The
full audit contains 72 checkpoint/scale combinations and 1,008 actual residual
forward batches. Ten new synthetic tests cover exact endpoints, linearity,
input/checkpoint immutability, unavailable-pair preservation, scale identity,
and the TRAIN-only rule below.

## What the scale path shows

The balanced residual direction is useful at small amplitude and destructive at
full amplitude. Selected fixed points are:

| Seed | Alpha | TRAIN all signs | TRAIN separable | SELECT both Q/E rankings | SELECT all signs | SELECT separable | SELECT common threshold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 20261014 | 1/32 | 11/13 | 13/13 | 3/3 and 3/3 | 2/3 | 3/3 | no |
| 20261014 | 1/16 | 13/13 | 13/13 | 2/3 and 3/3 | 2/3 | 2/3 | no |
| 20261015 | 1/32 | 10/13 | 13/13 | 3/3 and 3/3 | 2/3 | 3/3 | no |
| 20261015 | 1/16 | 13/13 | 13/13 | 3/3 and 3/3 | 2/3 | 3/3 | no |
| 20261016 | 1/32 | 9/13 | 13/13 | 3/3 and 3/3 | 2/3 | 3/3 | yes |
| 20261016 | 1/16 | 13/13 | 13/13 | 3/3 and 3/3 | 2/3 | 3/3 | yes |
| every seed | 1 | 13/13 | 13/13 | at most 1/3 and 2/3 | 0/3 | at most 1/3 | no |

The frozen baseline has 3/3 both rankings, 1/3 all signs and 3/3 separability.
Thus a small residual can increase the fixed-sign count to 2/3 while preserving
most or all ranking/separability structure; the final full residual erases it.
This is an amplitude/regularization failure, not evidence that the learned
direction is wholly uninformative.

## Strict TRAIN-only rule

The audit also evaluates one deterministic rule for each checkpoint:

> choose the smallest nonzero registered alpha for which every available TRAIN
> rectangle has both question and evidence rankings, all four fixed-threshold
> signs, per-pair separability and a nonempty common threshold interval.

The rule never reads SELECT and never chooses a seed or checkpoint. Its design is
still post-hoc because the earlier SELECT result motivated this audit.

- no one-way checkpoint qualifies;
- no reversed checkpoint qualifies;
- all three balanced checkpoints independently choose exactly `alpha=1/16`.

At that TRAIN-only choice all three balanced seeds retain 13/13 TRAIN rankings,
signs and separability. Their SELECT readouts are:

| Seed | Both question rankings | Both evidence rankings | All four signs | Per-pair separable | Common threshold |
| --- | ---: | ---: | ---: | ---: | --- |
| 20261014 | 2/3 | 3/3 | 2/3 | 2/3 | no |
| 20261015 | 3/3 | 3/3 | 2/3 | 3/3 | no |
| 20261016 | 3/3 | 3/3 | 2/3 | 3/3 | yes |

This consistency makes the rule a concrete preregistration candidate for a new
cohort. It does not retroactively turn these exposed SELECT pairs into an
independent test.

## Required confirmation

The next valid confirmation must freeze the scale grid and TRAIN-only rule
before seeing a genuinely new task family. It must report every fixed seed,
retain unavailable units, include the frozen cosine, one-way and reversed
controls, and separately evaluate evidence sufficiency and final Reader answer
quality. No result here permits a Reader call to be skipped.

`posthoc_after_select_observation=true`, `alpha_selection_from_select=false`,
`new_optimizer_updates=0`, `new_reader_calls=0`,
`reader_call_skipping_authorized=false`, `semantic_accuracy=null`,
`production_accepted=false`, `five_experiments_completed=false`.
