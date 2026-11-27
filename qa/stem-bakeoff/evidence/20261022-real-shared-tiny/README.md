# Real tiny shared-student distillation

## Finding and scope

This experiment executed genuine updates to a new shared Transformer backbone
and its shared teacher readout from independently prepared raw image/text
inputs. **It did not establish useful semantic compression or a multimodal
advantage.** All 45 seed/arm/role objectives improved over their own untrained
initialization, but the predeclared training-target-mean baseline was better
than every trained student in all 45 comparisons. Text-only input had lower
objective than multimodal input for all three seeds and all five roles.

The model is `hepta_shared_tiny64_v1`: 33,472 backbone parameters plus a 99,840
parameter shared readout, totaling **133,312 parameters**. It is newly
initialized; it is neither an EG2 fine-tune nor a pretrained 150M model. This
extends the existing offline shared-distillation path; it is not per-Head merge
distillation. Existing Cell weights and feature generations cannot be silently
reused with the new shared model. Artifacts only replay their exact source-bound
cohorts and remain `DENY_ALL` / `SHADOW_ONLY`.

## Fixed plan and actual data

The immutable plan preceded scoring. Seeds were 7, 17 and 29. Every arm trained
for exactly 20 full-batch SGD steps, learning rate 0.05, no momentum, gradient
norm clipped at one, with eight training source groups. There was no stopping,
resampling, threshold selection or hyperparameter change after seeing results.

The original COCO2017 source split was preserved: 8 groups from original train,
8 from calibration, 8 from dev and two disjoint groups of 8 from original test.
Groups were selected by a fixed SHA256 ordering of image IDs. Each image and
its original caption remained one source group. API names `future_1`,
`future_2` and `ood` mean **original dev, test A and test B** here; they do not
represent temporal or out-of-distribution tests.

These images and the EG2 bank had previously been used in multimodal pairing
and model-comparison work. This is exploratory reuse, not fresh blind evidence.
Eight examples per role and three seeds on the same sources cannot qualify
cross-task, temporal, larger-scale or production behavior. Foundation-model
pretraining contamination is not excluded.

Student inputs came from actual pinned JPEG bytes and caption UTF-8 bytes:
sixteen RGB patch slots plus sixteen text-byte slots, each width 64. Raw and
decoded image hashes and caption hashes were checked. The independent teacher
path used actual frozen EG2 bank arrays and original forward receipts. Every
bank batch's global feature bytes, source IDs, checkpoint revision and source
digests were checked before selection. Targets concatenate separately produced
768-wide image and text features; this is not one 1,536-wide Encoder forward.
The original image teacher input included its fixed neutral prompt, `Image.`.
Teacher features never entered the student input path.

The multimodal, image-only and text-only arms shared architecture, initial seed,
targets and parameter/example update counts. Single-modality controls mask the
other input slots; available information and active slot counts differ. The
readout averages over 32 positions, so input scaling also differs. Lower loss
for one control alone does not prove greater semantic information. The separate
training-target centroid is a cheaper non-neural control, with no SGD or raw
input; its total computation is not matched to the student arms.

## Results

Mean objective over the three seeds; lower is better. The objective is
MSE plus `0.1 * (1 - cosine)` against the concatenated teacher target.

| Original role | Multimodal before | Multimodal after | Image-only after | Text-only after | Train-target mean |
|---|---:|---:|---:|---:|---:|
| Train | 0.127696 | 0.122207 | 0.119870 | 0.109856 | 0.011219 |
| Calibration | 0.125289 | 0.120676 | 0.119769 | 0.108597 | 0.015544 |
| Dev | 0.126931 | 0.122454 | 0.121343 | 0.109574 | 0.016191 |
| Test A | 0.123082 | 0.118343 | 0.116494 | 0.108848 | 0.013551 |
| Test B | 0.127218 | 0.122409 | 0.121843 | 0.108656 | 0.015967 |

After-training multimodal matching R@1 against the eight teacher targets in
each role averaged 12.5% on dev, 8.33% on test A and 8.33% on test B. The
centroid yields 12.5% in each role because all examples receive the same
prediction. This tiny target-matching proxy is not a real memory-task benchmark.
Every seed's complete before/after predictions and per-source scores are saved.

## Actual work and consistency checks

Each of the nine models performed 21,329,920 parameter-by-example updates.
Both backbone and readout tensor hashes changed. Per model, the measured work
for **each** component was:

| Phase | Actual forwards | Actual example calls |
|---|---:|---:|
| Gradient training | 20 | 160 |
| Before/after objective evaluation | 10 | 80 |
| Before/after prediction export | 10 | 80 |
| Independently reloaded artifact replay | 5 | 40 |

There were 180 actual optimizer steps across nine models and zero pretrained
Encoder updates. Each artifact has 533,248 resident tensor bytes, 533,248
gradient bytes before clearing, and zero optimizer-state bytes. These figures
exclude backend operations, activations and allocator overhead; they are not
total machine-cost equivalence. Process lifetime peak RSS was 321,363,968 bytes.
The measured probe interval took 1.994 seconds wall time and 1.984 seconds CPU;
it excludes interpreter startup and the earlier EG2 bank acquisition/inference.

All 45 reloaded role predictions were bitwise equal. All 27 independent
ancestor-source, source-group and whole-bank withdrawal cases rejected before
a student forward; subsequent frontier rollback also rejected. The provenance
closure conservatively includes training and evaluated sources. This is local
research-host withdrawal evidence, not cryptographic production authorization
or erasure of a foundation model's pretraining.

Eight new behavior tests plus eighteen existing offline-distillation tests
passed in 1.018 seconds. Fixtures verify mechanics and do not contribute to the
real-data scores above.

## Complete evidence

`inventory.json` binds every original and stored byte stream: all 43 run files,
run/test logs, the exact twelve-file source dependency closure, and the small
original source manifests/split metadata. Stored payload totals 9,550,597 bytes.
No full JPEG collection, teacher bank arrays or foundation weights were copied.
Artifacts, source slots, teacher-target shards, original forward receipts and
all predictions are losslessly compressed. No original run payload was dropped.

- Plan: `319e8a9acfcb2fd71dc18c95cfccf4b4d665aa3244e115852621b308734da445`
- Report: `cee803359cfe9586c1861dfbd63bdff66d7e3f07ce58659238e7310d95b6898e`
- Inventory: `ab9488377615d99d0a732232feab58c0fefc89cf64fb33c898d2e8692059775f`

Restore each compressed file to its inventory `source_path`. The retained
source slots and target shards permit exact training replay without a model
download. Reconstructing raw slots additionally requires the original pinned
JPEGs; selected source metadata includes their original URLs and byte hashes.
The full acquisition-to-training probe is:

```sh
python qa/stem-bakeoff/real_shared_student_probe.py \
  --raw-root /tmp/hepta-coco-cohorts-v1 \
  --bank-root /tmp/hepta-coco-bank-v1 \
  --output /tmp/hepta-shared-tiny-replay
```

The destination must not exist. Use the frozen dependency hashes, fixed plan
and the original source pins; do not attribute a changed experiment to this run.
