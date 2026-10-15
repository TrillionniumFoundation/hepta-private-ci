# Completed cosine-preserving residual experiment

Date: 2026-10-15. Development evidence only. This result does not establish
answer correctness, independent generalization, calibrated abstention, permission
to skip a Reader call, or production readiness.

## Exact completed execution

The third strictly bound execution completed successfully:

- source commit: `14eb7234a32fd20c8fd4e677f11a241db0d00ad6`;
- workflow run: `38665708709`;
- job: `116197071927`;
- artifact: `11942057629`, `hepta-cosine-residual-gate-v3-development`;
- artifact ZIP SHA256:
  `23d8d35da612a45d99aafcf2f9f09eceae94b08bb3ee61cb853ac71c50d8cd90`;
- plan SHA256:
  `50a881121b7b2b27d5534223b9999b35623199a61c2e9c108e2a4708595f3a55`;
- raw prediction SHA256:
  `2f80324da563491397adb6dfb9d7d8466a4c176be318b206156fdb199b213f9a`.

All ten required suites passed, totaling 197 tests. All five fixed input
archives were independently downloaded and SHA-checked before model work. The
run reconstructed the exact admitted TRAIN cohort rather than confusing it with
the larger pre-eligibility selection cohort:

- 24 selected TRAIN questions;
- 14 admitted relevance units;
- 10 selected but not admitted;
- 13 available TRAIN rectangles and one retained unavailable donor;
- four planned SELECT rectangles, three scoreable and one retained unavailable.

Only the 13 missing original TRAIN evidence vectors were encoded. The strict
archived 22.7M-parameter Encoder was loaded once and invoked in six actual
batches. The authenticated 33-vector crossed cache was reused unchanged. No
Reader was called and no pretrained parameter was updated.

Nine 6,152-parameter residual checkpoints were trained: three arms by three
fixed seeds, 256 steps each, for 2,304 actual small-Head optimizer updates.
SELECT was read-only; no seed, checkpoint, threshold or stopping point was
selected from it.

## Frozen cosine baseline

The fixed base score is cosine minus the previously fitted TRAIN-only scalar
threshold `0.393732527116822`.

| Split | Positive interaction | Both question rankings | Both evidence rankings | All four fixed signs | Per-pair separable |
| --- | ---: | ---: | ---: | ---: | ---: |
| TRAIN | 13/13 | 10/13 | 7/13 | 3/13 | 6/13 |
| SELECT | 3/3 | 3/3 | 3/3 | 1/3 | 3/3 |

No single threshold separates all three SELECT rectangles.

## Full 256-step residual result

### Balanced four-corner labels

Every seed completely fits the admitted TRAIN rectangles:

- 13/13 positive interactions;
- 13/13 both question rankings;
- 13/13 both evidence rankings;
- 13/13 all four fixed-threshold signs;
- 13/13 per-pair separability;
- a nonempty common TRAIN threshold interval.

That fit does not transfer at full residual amplitude:

| Seed | SELECT positive interaction | Both question rankings | Both evidence rankings | All four signs | Per-pair separable |
| --- | ---: | ---: | ---: | ---: | ---: |
| 20261014 | 2/3 | 1/3 | 2/3 | 0/3 | 1/3 |
| 20261015 | 2/3 | 0/3 | 0/3 | 0/3 | 0/3 |
| 20261016 | 2/3 | 0/3 | 1/3 | 0/3 | 0/3 |

Thus the final balanced residual is a strong TRAIN fit and a negative SELECT
transfer result. It destroys much of the frozen cosine geometry instead of
adding a stable correction.

### One-way and reversed controls

The repeated one-way `BB/AB` objective never produces a scoreable SELECT
rectangle under the threshold-free separability test: 0/3 for all three seeds,
and 0/3 all-four-sign outcomes. It also fails to close the complete TRAIN
rectangle.

The deliberately reversed balanced objective behaves as a sign control. It
produces zero positive interactions, rankings, all-four-sign outcomes and
separable rectangles on all 13 available TRAIN pairs. SELECT remains at 0/3
all-four-sign outcomes and at most 1/3 on either joint ranking. This confirms
that the balanced interaction labels, rather than only additional optimizer
work, determine the learned direction.

## Interpretation

The experiment establishes three narrower facts:

1. the frozen representation contains a useful question/evidence relation that
   direct cosine reads on all three exposed SELECT rectangles;
2. a 6,152-parameter interaction residual can close every admitted TRAIN
   rectangle without modifying the Encoder;
3. driving that residual to the full 256-step solution badly overfits the weak
   cross-family TRAIN labels and erases the base relation on SELECT.

The next discriminating question is therefore not whether to add more Head
capacity. It is whether the learned direction has useful low-amplitude signal
that requires TRAIN-only shrinkage or stopping. Any analysis on these same
SELECT pairs is necessarily post-hoc development evidence; an independent new
cohort remains required for confirmation.

`reader_adequacy_established=false`, `production_accepted=false`,
`five_experiments_completed=false`.
