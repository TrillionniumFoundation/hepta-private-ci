# Reproducible real image-caption research

This experiment measures whether private lightweight Heads can learn a real
image-caption pairing task from one frozen shared EmbeddingGemma 2 Encoder.
It retains original COCO photographs, human captions, modality controls,
fixed interventions, calibrated predictions and reloadable Head tensors.
The workflow reports engineering completion and research qualification
separately. Neither result grants production authority.

The implementation is `multimodal_cohorts.py` → `multimodal_features.py` →
`multimodal_research.py`. The one-job workflow is
`.github/workflows/hepta-multimodal-research.yml`. The existing
`hepta-shared-stem-bakeoff-shadow.yml` continues to own the text candidate
bake-off and procedural-image execution probe.

## Fixed source data and pairing plan

The source is the official COCO 2017 annotation archive and original validation
JPEGs from the official COCO S3 bucket. The
[COCO caption paper](https://arxiv.org/abs/1504.00325) describes the collection of
human captions. The selected sample is fixed in
`coco_caption_sample_v1.json`, including original image and caption IDs, download
URLs, byte hashes, decoded-image hashes, perceptual fingerprints, Flickr URLs
and each photograph's license. The loader replays records against the original
caption JSON and compiled source pins; replacing text or labels and recomputing
a local manifest does not establish valid source evidence.

| Source                      | Fixed value                                                                                |
| --------------------------- | ------------------------------------------------------------------------------------------ |
| Annotation archive          | `https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip` |
| Archive bytes               | 252,907,541                                                                                |
| Archive SHA256              | `113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268`                         |
| Caption member              | `annotations/captions_val2017.json`                                                        |
| Caption JSON SHA256         | `afe3b30e403dd7f228e2373023abbd60042a6e10ec6874d3652df034d289ebb9`                         |
| Sample registry SHA256      | `bdcd27245d5435820ddd6ef305b42bdeca236e4411839f1d209d314547567b23`                         |
| Sample selection seed       | `hepta-coco-pair-v1-20261022`                                                              |
| Original photos             | 384, totaling 64,130,426 bytes                                                             |
| Archive plus photo download | 317,037,967 bytes; hard budget 400,000,000 bytes                                           |

The annotations and photographs have different license sources. The
[COCO terms](https://cocodataset.org/dataset/termsofuse.htm) identify the annotation
license and direct users to individual Flickr photo licenses. This fixed sample
uses only original COCO license IDs 4 and 5, CC BY 2.0 and CC BY-SA 2.0, and
retains the original attribution URLs. CI artifacts contain the source metadata
and experimental results; the bulk original photographs can be reacquired by
their pinned URLs and hashes.

| Split       | Original photos / selected captions | Pair blocks | Rows | Role                                               |
| ----------- | ----------------------------------: | ----------: | ---: | -------------------------------------------------- |
| Train       |                                 128 |          64 |  256 | Fit private Head weights                           |
| Dev         |                                  64 |          32 |  128 | Select the predeclared Head training configuration |
| Calibration |                                  64 |          32 |  128 | Fit temperature after weight selection             |
| Test        |                                 128 |          64 |  256 | Untouched primary research evaluation              |

Each original photo contributes one deterministically selected human caption.
Inside each split, a fixed hash order pairs adjacent photos into disjoint
two-photo blocks. For photos A/B and captions a/b, each block contains the two
original pairs (A,a), (B,b) and the two swapped pairs (A,b), (B,a). Thus every
photo and caption occurs once with label 1 and once with label 0. Single-modality
marginals are exactly balanced. Labels mean **original caption-photo source
match**: a swapped caption can still plausibly describe the other photograph.

Both endpoints of every pair remain in one split and one block. The builder
rejects repeated normalized captions, identical decoded RGB images and detected
near-duplicates with 64-bit horizontal dHash distance at most 4. These checks do
not establish that every real-world entity occurs in only one photograph.
Model outputs do not influence sampling. Foundation-model exposure to COCO
during pretraining remains unknown.

## One frozen Encoder and matched modality controls

The checkpoint is `google/embeddinggemma-2` at immutable revision
`914f7f89142e33e77833254d9c9b90c3cef7303b`. Its safetensors SHA256 is
`197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79`.
`fetch_real_checkpoint.py` verifies downloaded files against the registered
revision and upstream Git/LFS digests, and writes an acquisition receipt outside
the model directory. Model execution is offline. The explicit terms-acceptance
flag covers this same registered model, following the existing shared-Stem CI
usage; it does not admit arbitrary new checkpoints or licenses.

`multimodal_features.py` loads one frozen `text_image` profile. It encodes every
selected caption once and every selected photo once; photo encoding uses the
same neutral text prompt, `Image.`. The image-only arm therefore includes fixed
neutral prompt tokens. The bank retains actual forward receipts, token modality
evidence, source identities, tensor digests, measured model storage, process
peak RSS and execution time. The frozen model digest must be unchanged after all
forwards. Checkpoint storage and the loaded profile's tensor storage are reported
separately.

All arms use the same 3,073-wide representation:

```text
[text(768), image(768), text * image(768), abs(text - image)(768), cosine(1)]
```

The `text_only` and `image_only` arms zero their missing channel and all
cross-modal interaction terms. The `text_image` arm supplies both channels.
This fixes input width and Head parameter budget across modality arms. Labels,
source IDs and image IDs are provenance metadata and never model inputs.
The bank is pooled-feature late fusion; it does not claim region grounding,
temporal alignment or a newly trained vision tower.

The main Head mode is preregistered as **gated**. **Linear** is the structural
control; the test set does not select the winning mode. Training, dev selection,
temperature calibration and test scoring use separate cohorts. Heads are saved,
reloaded under externally retained hashes and checked before the final report is
written. Action, value and uncertainty outputs have no corresponding labels in
this task; this experiment does not qualify a complete stateful policy.

The fixed training grid uses 200, 1,000 and 3,000 SGD steps, learning rate 0.2,
seed 7, adapter rank 4 and state width 8. Development uncalibrated negative
log-likelihood selects the step budget, breaking ties toward fewer steps.
Only calibration data select temperature from
`[0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0]`.

## Evaluation and its limits

The retained prediction ledgers contain raw logits, calibrated probabilities,
labels, predicted classes, accepted/rejected decisions, row IDs, image groups,
pair-block IDs, and Encoder/Head/data/plan identities. Confidence acceptance is
fixed at 0.70. Every reported coverage or selective-risk result must be read
together with its accepted example count.

The primary research screen is fixed before evaluation:

| Check                                                       |                                   Threshold |
| ----------------------------------------------------------- | ------------------------------------------: |
| Minimum independent test pair blocks                        |                                          64 |
| Balanced accuracy                                           |                               At least 0.70 |
| Positive recall                                             |                               At least 0.60 |
| Coverage at confidence 0.70                                 |                               At least 0.50 |
| Accepted predictions                                        |                                 At least 64 |
| Selective risk                                              |                                At most 0.20 |
| One-sided 95% cluster-bootstrap risk upper bound            |                                At most 0.30 |
| Joint gain over the better unimodal control                 |      At least 0.10 balanced-accuracy points |
| Missing text, missing image, and shuffled image sensitivity | Each at least 0.10 balanced-accuracy points |
| Gain and intervention-drop lower bounds                     |                      Each strictly positive |

Intervals use 2,000 bootstrap resamples of **pair blocks**, seed 20261022, with
the same sampled blocks in paired comparisons. Shared photos and captions make
the four rows inside each block dependent. Bootstrap intervals are finite-sample
research diagnostics and are not distribution-free guarantees. Degenerate
intervals can occur when no observed errors exist.

Missing-modality and shuffled-image ledgers reuse the trained Head, calibration
temperature and threshold. Shuffling keeps the original labels to measure
sensitivity; those labels are not relabeled ground truth for the shuffled task.
An additional `shuffled_relabelled` ledger checks source-pair consistency using
the swapped labels. It reuses the same input multiset and provides no independent
test examples.

A preregistered `minority_test` diagnostic selects 32 positive test rows by fixed
hash with seed 20261022 and retains all 128 negative test rows: 160 rows, 20%
positive. It does not retrain, recalibrate or change confidence thresholds. It
reports positive recall, average precision, coverage/risk and group-bootstrap
diagnostics. This is a correlated subset of the same test cohort, not an
independent replication. Overall `quality_qualified` requires the **gated**
complete multimodal screen to pass and this fixed minority diagnostic's positive
recall to reach 0.60. Linear results are reported without replacing that primary
decision rule.

## Reproduce the full run

Run from the repository root at the source revision being reviewed. Use a new
output directory; builders refuse conflicting existing artifacts. The commands
below download public immutable model bytes and fixed COCO sources. Review the
registered model and photo terms before supplying `--operator-accepted-terms`.

```bash
MM_ROOT=$(mktemp -d /tmp/hepta-multimodal.XXXXXX)
export MM_ROOT
python3 -m venv "$MM_ROOT/venv"
STEM_PY="$MM_ROOT/venv/bin/python"
"$STEM_PY" -m pip install --no-cache-dir --only-binary=:all: \
  --index-url https://download.pytorch.org/whl/cpu \
  'torch==2.10.0' 'torchvision==0.25.0'
"$STEM_PY" -m pip install --no-cache-dir --only-binary=:all: \
  -r qa/stem-bakeoff/requirements-real.txt
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false

"$STEM_PY" - <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, 'qa/stem-bakeoff')
from multimodal_cohorts import ARCHIVE_URL, ARCHIVE_BYTES, ARCHIVE_SHA256, fetch_file, prepare_cohorts
root = Path(os.environ['MM_ROOT'])
archive = root / 'annotations.zip'
fetch_file(ARCHIVE_URL, archive, expected_sha256=ARCHIVE_SHA256,
    expected_bytes=ARCHIVE_BYTES, limit=ARCHIVE_BYTES)
prepare_cohorts(archive=archive, output=root / 'cohorts', download_images=True)
PY

"$STEM_PY" qa/stem-bakeoff/fetch_real_checkpoint.py \
  --candidate embeddinggemma2_740m --destination "$MM_ROOT/checkpoint"
inventory_sha256=$("$STEM_PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["inventory_sha256"])' "$MM_ROOT/checkpoint.acquisition.json")
"$STEM_PY" qa/stem-bakeoff/multimodal_features.py \
  --cohorts "$MM_ROOT/cohorts" --snapshot "$MM_ROOT/checkpoint" \
  --inventory-sha256 "$inventory_sha256" --output "$MM_ROOT/bank" \
  --operator-accepted-terms --threads 4 --batch-size 2
bank_sha256=$("$STEM_PY" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$MM_ROOT/bank/manifest.json")
"$STEM_PY" qa/stem-bakeoff/multimodal_research.py \
  --cohorts "$MM_ROOT/cohorts" --bank "$MM_ROOT/bank" \
  --expected-bank-sha256 "$bank_sha256" --output "$MM_ROOT/results" --threads 4
```

Photos are downloaded directly into the cohort directory. The checkpoint also
has one local copy; no second Hub cache or converted checkpoint is created.
The dataset's 400 MB download budget excludes the model and Python runtime.
Feature extraction and Head training run sequentially so they do not keep
multiple model instances alive. Expect CPU execution time to dominate; use the
actual receipt's wall time and peak RSS when comparing systems.
Head latency records contain 1,000 measured singleton calls after 20 warmups,
including identity checks and feature copying. They exclude Encoder execution
and queueing. The 4,096-Head byte estimate is arithmetic rather than a claim
that 4,096 trained Heads were physically allocated. Energy and target-device
performance remain unqualified without a measurement on that device.

## CI completion and retained evidence

The final `results/report.json` has schema
`hepta.multimodal-research-report.v1`, `engineering_status: COMPLETE`, and a
separate boolean `quality_qualified`. The runner writes it after reload and
integrity checks. A completed experiment that fails the research thresholds
still exits successfully with `quality_qualified: false`. Execution, provenance
or integrity failures exit nonzero and cannot produce a valid completion gate.

CI independently checks the completion contract and every file in the report's
`artifact_sha256` index, including ledger arrays and trained Head weights. It
rejects missing files, extra unindexed result files, path escapes, symlinks and
hash mismatches. A separate review receipt binds the source commit, final report
SHA256 and number of verified artifacts. The GitHub job summary states both
engineering completion and research qualification.

Artifacts are retained for 14 days with `if: always()`: source SHA, logs,
checkpoint acquisition receipt, cohort source metadata and split records, the
feature bank, trained Heads, prediction ledgers, final report and review receipt.
Partial evidence is retained when an earlier step fails. Large model weights,
the annotation ZIP and raw photo payloads are excluded from artifact uploads;
their acquisition hashes and original locations remain in the evidence.

All outputs retain `authority: DENY_ALL` and
`production_activation_allowed: false`. Passing this small fixed research screen
supports the specified caption-pairing experiment only. It does not establish
open-world multimodal competence, entity-disjoint generalization, absence of
foundation pretraining exposure, or production-safe autonomous actions.
