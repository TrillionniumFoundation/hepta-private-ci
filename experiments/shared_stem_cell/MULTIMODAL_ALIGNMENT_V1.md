# Shared multimodal stem — source-disjoint alignment V1 (research only)

This adds **actual CPU ridge fitting** of externally supplied, frozen, *paired*
features. The previous manually specified projection and shared-feature runtime
remain unchanged. This does **not** load DINOv2, Whisper, mmBERT, Granite or
Laya checkpoints, measure real-world multimodal competence, verify model
provenance, or grant inference/selection/production authority.

## Three independently pinned stages

1. **Fit:** `multimodal_alignment.py fit` accepts **train-only** JSONL records
   with image/audio/video/sensor source vectors and corresponding text-stem
   target vectors. Exact source-file SHA-256 is supplied externally; example
   fields include case ID, independent group ID, authorization scope,
   observation timestamp, and pinned per-source/per-encoder digests. Ridge
   regression in CPU f64 fits a frozen linear bridge (train data only). It also
   fits a train-label-rotated negative control and constructs a deterministic,
   never-trained identity/truncation baseline. Neither future source vectors
   nor future target vectors are passed to the fitting function. Learned
   weights are serialized and digested using the existing bridge representation.
2. **Predict:** `multimodal_alignment.py predict` reads only an SHA-pinned fit
   artifact and future **source-only** records. Any target-bearing row is
   rejected. Enforce exact scope/modality/encoder, strictly future observation
   time, independent group IDs, nonreused source identities, complete arm
   output, fixed projection dimensions and bounded numerical outputs. Write
   predictions once, and obtain the SHA-256 of the sealed file before opening
   any future targets.
3. **Evaluate:** `multimodal_alignment_evaluator.py` is a separate entrypoint
   and imports only the shared data contract, not the fit implementation. It
   receives the *already sealed and pinned* predictions and an independently
   pinned, **target-only** future dataset. It checks exact row coverage, source
   identities, target encoder identity, future timestamps, group separation and
   target nonreuse. Reports mean cosine, MSE and within-cohort retrieval top-1
   for fitted, train-label-rotated and unaligned baselines. These are **feature
   geometry metrics**, not task accuracy or future NDU utility.

### Input row schemas

`train.jsonl` contains one JSON object per line, e.g.:

```json
{"case_id":"c1","group_id":"source-g1","scope":"scope_A","observed_at":1,"split":"train","source":{"modality":"image","input_sha256":"<64 lowercase SHA-256>","encoder_sha256":"<64 lowercase SHA-256>","values":[1.0,0.0]},"target":{"modality":"text","input_sha256":"<64 lowercase SHA-256>","encoder_sha256":"<64 lowercase SHA-256>","values":[0.0,1.0]}}
```

`future.jsonl` contains the same outer fields with `split="future"` and
**source only**. `targets.jsonl`, unavailable until predictions are sealed,
contains `case_id`, `group_id`, `scope`, `observed_at`, `split="future"`,
`source_input_sha256` and the **target only**. All files need independently
supplied exact byte hashes; an arbitrary digest does not prove actual feature
or target provenance. Existing `ModalityFeature` checks each float32 vector is
finite and in [-8, 8].

### Run (local, operator-pinned files)

```sh
python experiments/shared_stem_cell/multimodal_alignment.py fit \
  --train /staged/train.jsonl --train-sha256 "$TRAIN_SHA" \
  --output /results/fit.json
# Pin the exact SHA-256 of fit.json *before* predict.
python experiments/shared_stem_cell/multimodal_alignment.py predict \
  --fit /results/fit.json --fit-sha256 "$FIT_SHA" \
  --future-inputs /staged/future.jsonl \
  --future-inputs-sha256 "$FUTURE_SHA" \
  --output /results/predictions.json
# Independent evaluator receives sealed predictions + future targets *only now*.
python experiments/shared_stem_cell/multimodal_alignment_evaluator.py \
  --predictions /results/predictions.json \
  --predictions-sha256 "$PREDICTIONS_SHA" \
  --future-targets /independent/targets.jsonl \
  --future-targets-sha256 "$TARGETS_SHA" \
  --output /results/evaluation.json
```

The CI executes a **synthetic** rotation task with completely different future
row identities and groups. It preserves all source hashes, fitted bridge,
sealed predictions, evaluator metrics and explicit `production_accepted=false`.
The test validates that the train-only fit differs causally from shuffled and
unaligned controls **on that toy task**; it does not estimate generalization on
natural images, multilingual language, audio or video.

## Remaining external acceptance requirements

- Authenticated, actually installed pretrained Encoder/ASR/vision weights and
  preprocessing (model manifests + file inventory + runtime load receipts).
- Curated train/selection/untouched future sources and timestamps; independent
  authorization, ground-truth owner and whole-dataset deduplication. In-process
  SHA-256 fields do not prove source authenticity.
- Multiple seeds, controlled learning budgets, negative-transfer, calibration,
  forgetting and real decision/NDU utility relative to frozen/no-change paths.
- Current-version generation/fence-scoped final-use, genuine worker batches,
  real shared buffer handles, Rust Q24 binding, durable recovery and target-host
  p95/p99/RSS/GPU/energy evidence. No existing production journal is modified.

**Disposition:** research experiment only, never activate on toy geometry.
