# P44: New COCO ontology-semantic source cohort (research only)

P39/#3122 already completed the original-caption/source-pairing closed loop, with
real EG2 inference, six matched modality/Head arms, interventions and per-row
ledgers. P42/#3491 and P43/#3542 are independently auditing **whether learning
beats the cheap frozen image-text cosine**. P39's 251/256 pairing success does
not certify open-world semantic grounding or incremental learned-Head benefit.

P44 adds an **independently specified new task**, not a replacement for P39's
images, trained tensors, thresholds, publications or post-hoc conclusions.
It is a *source-sealing stage*; the real-model training/evaluation stage has
**not** run. Security and product admission remain `SHADOW_ONLY / DENY_ALL /
HOLD_NO_GO`. No model, GPU or energy result is claimed by a passing source job.

## Task and prospective source selection

Original source: byte-pinned [COCO annotations_trainval2017.zip](https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip)
(SHA256 `113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268`).
The implementation validates the exact original archive and both original
caption and object annotation members. It independently rebuilds P39's pinned
384-photo registry from the archived captions to exclude original P39 photo IDs,
Flickr sources, original JPEG/RGB bytes and dHash near-duplicates. No machine
prediction influences sampling; selected JPEGs must be original files acquired
from the official COCO bucket, with original license ID 4 or 5 and full byte,
RGB and dHash receipts.

Four originally annotated COCO category names are fixed **before sampling**:
`cat`, `dog`, `horse`, `cow`. Images with multiple of these four categories
are rejected. Selected source photos always have one of the pair's original
COCO object annotation categories. Each photo gets *two fixed category
questions*, one true and one false: `Does this photograph contain a cat?` and
`Does this photograph contain a dog?` (or horse/cow for OOD). Original COCO
human captions and their hashes are retained **only as source provenance**,
not as model input. The negative says only that the *opposing annotated target
category* was not present in this annotated closed set: COCO labels are not a
certified exhaustive object inventory.

| Cohort | Fixed source concepts | Photos / category | Rows | Primary purpose |
| --- | --- | ---: | ---: | --- |
| train | cat / dog | 16 | 64 | Head learning only |
| dev | cat / dog | 8 | 32 | Train-side selection only |
| calibration | cat / dog | 8 | 32 | Temperature/threshold diagnostics only |
| test | cat / dog | 16 | 64 | New original-photo test (do not inspect during selection) |
| OOD | horse / cow | 8 | 32 | Category-family-disjoint OOD; never tune on OOD |
| **Total** | | | **224** | **112 original photos** |

The two rows for any photo contain one positive and one negative. Both the
image-only and text-only marginal labels are therefore balanced at 50%; a
source-photo-ID shortcut cannot solve these labels by itself. The same four
pair-block entries are used across all future arms. Split groups have distinct
original image IDs, Flickr source IDs, exact image and decoded RGB hashes,
and dHash distance at least 5 to each other and all P39 protected images.
The OOD set uses unseen category *names*, unlike the primary test. The dataset
is historical public COCO; contamination by pretrained EG2 remains unknown.

## Source lock protocol

`qa/stem-bakeoff/prospective_semantic_cohorts.py` has two fail-closed commands:

```sh
python qa/stem-bakeoff/prospective_semantic_cohorts.py seal \
  --archive /external/pinned-annotations.zip --output /external/new-semantic-seal
python qa/stem-bakeoff/prospective_semantic_cohorts.py audit \
  --archive /external/pinned-annotations.zip --source /external/new-semantic-seal
```

The first command writes the frozen original-photo selection **before** any
photo encoding, then downloads and seals the JPEGs, hashes, source metadata,
class ontology, class-balanced source rows and source manifest. It fails on
shortfalls and duplicate/near-duplicate images instead of silently replacing
cohorts after looking at quality. The second command independently replays
selection from the original archive, verifies source/photo fingerprints,
regenerates every label and compares every line of the JSONL and manifest.
Replayed source bytes may be bound to a caller-provided digest, but that alone
cannot prove **independent prepublication**. The receipt explicitly says
`independent_prepublication_verified: false`. A separate signed/published
source-lock review must bind this artifact before it becomes an eligible
training or qualifying evaluation input. The CI job uploads only metadata and
source receipts, not third-party original JPEGs.

## Frozen next-stage matched experiment and acceptance criteria

Only after the source manifest is independently pinned, run real EG2 CPU/GPU
original forwards on these **new** pixels and fixed text queries. Keep the
following as separate arms with identical train/dev/calibration/test assignments,
Encoder version, preprocessing, number of Head updates, batch budget and seeds:

- text-only; image-only; text+image linear Head; text+image gated Head;
  and raw frozen cosine plus train-only two-scalar calibrated cosine as strong
  cheap controls (neither may see test/held-out rows before hyperparameters
  are frozen).
- paired, within-block image shuffle, missing text, missing image, and
  wrong-category text. Missing required modality must fail closed **before**
  any Head forward. Pairing corruption must be evaluated as an intervention;
  mere presence validation does not prove pairing correctness.
- at least three independently fixed Head seeds, distinct trained private
  Heads with immutable replay artifacts, per-row predictions/labels, correct
  positives, negative recall, balanced accuracy, AUPRC, NLL, ECE, acceptance
  coverage and accepted-error risk. Resample confidence intervals over
  original photo groups, not duplicate image/text rows. Preserve full
  model + Head + queue p50/p95/p99, RSS/VRAM, throughput and energy *only when
  actually measured on a named target device*.

Prerecorded proposed quality thresholds (not yet tested): joint Head must exceed
both unimodal baselines **and** calibrated cheap cosine by at least 2 percentage
points; its one-sided 95% grouped bootstrap lower bound versus cheap cosine
must be strictly positive; positive recall >= 80%, coverage at fixed 0.7 >=
80%, accepted-error risk <= 5% on a fresh test. An OOD result is reported
separately and cannot be turned into a pass by tuning on OOD. Full product,
state/action/value/uncertainty, target-device, original publisher custody,
exact composed GitHub CI and Windows outside-root DELETE/FILE_DELETE_CHILD
remain independent unclosed gates.

The P44 workflow runs 8 adversarial tests in normal and optimized Python,
then attempts the genuine official-source sealing stage. A green unit test
proves only code behavior, never source availability or model quality. An
original-source seal does not authorize an experiment's pass without the
prepublished source lock and a subsequent real-model execution.
