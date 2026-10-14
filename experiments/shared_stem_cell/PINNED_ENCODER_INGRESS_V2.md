# P1 / V2: verified offline text-stem ingress (research only)

The next real-model gate extends the existing V1 **train → sealed predict →
independent evaluate** experiment. Do not attach new authorization to a SHA,
replace the Neuron Q24 journal, or treat a local output vector as a language or
vision quality claim.

## What is implemented

- An exact, create-only profile declares a **stock** encoder/MLM snapshot,
  immutable 40-hex revision, all model/tokenizer/processor file SHA-256s,
  output width (1..512), `attention-mask-mean` pooling, optional `unit_l2`
  normalization, maximum tokens (8..8192) and physical batch size (1..32).
- `multimodal_real_encoder.py train` reads **TRAIN-ONLY** non-text source
  feature + raw text target pairs. `multimodal_real_encoder_evaluator.py` runs
  in a separately provisioned future-target context and does not import the
  bridge fitting module. Neither is a security sandbox; corpus access remains
  an external owner obligation.
- No direct Hub download or random fallback is permitted. The runner reuses
  `experiments/shared_stem_cell/execution.py::LocalEncoder`, which verifies
  pinned files, loads `trust_remote_code=False`, `local_files_only=True`,
  insists on a complete state-dict match, rejects unauthorized tensor aliases,
  and rechecks the snapshot after inference. Unsupported architectures fail
  closed. Model snapshots and input corpora must be provisioned before calling.
- Actual CPU f32 tensor shape/dtype/finiteness, forward count, normalization,
  source/scope/phase and content identity are checked. Every output target
  includes the *actual profile + material + pooling + normalization* identity;
  two candidates cannot masquerade as one shared Feature generation.
- The train output is exactly V1's paired JSONL shape (`source`, `target`).
  The future targets output contains only independent source identity and
  target vectors, never the source feature or model inference predictions.
  The existing `multimodal_alignment.py predict` sees **source only**, and
  the existing `multimodal_alignment_evaluator.py` sees **sealed predictions +
  independent targets**.

## Exact reproducible operator commands

All input files are already present, independently consented, externally
verified, not symlinks, and pinned by SHA-256. A profile is a single canonical
JSON document (sorted keys, compact separators, one trailing newline). Example
values below are placeholders, not model-material evidence.

```sh
# Train operator; stage the actual tokenizer + model snapshot into $STEM_DIR.
python experiments/shared_stem_cell/multimodal_real_encoder.py train \
  --profile "$PROFILE_JSON" --profile-sha256 "$PROFILE_SHA256" \
  --model-snapshot "$STEM_DIR" \
  --input "$TRAIN_RAW_JSONL" --input-sha256 "$TRAIN_SHA256" \
  --output-dir "$TRAIN_ENCODING_DIR"

# *Independent future evaluation owner*, with separately held future text.
python experiments/shared_stem_cell/multimodal_real_encoder_evaluator.py \
  --profile "$PROFILE_JSON" --profile-sha256 "$PROFILE_SHA256" \
  --model-snapshot "$STEM_DIR" \
  --future-targets "$FUTURE_TEXT_JSONL" \
  --future-targets-sha256 "$FUTURE_TEXT_SHA256" \
  --output-dir "$FUTURE_ENCODING_DIR"
```

`$TRAIN_ENCODING_DIR/encoded.jsonl` feeds the existing Bridge `fit` stage;
`$FUTURE_ENCODING_DIR/encoded.jsonl` is available only to the independent
Evaluator. The paired train rows and future targets use distinct exact keys
and reject opposite-phase content. The separate source-only future JSONL
still feeds `predict`, as in V1.

## The raw input formats

TRAIN input fields **exactly**:

```json
{"case_id":"t01","group_id":"train-root","scope":"scopeA","observed_at":1,"split":"train","source":{"modality":"image","input_sha256":"<64 lower-case hex>","encoder_sha256":"<64 lower-case hex>","values":[0.1,0.2]},"target_text":"A photo caption"}
```

FUTURE_TARGETS input fields **exactly**:

```json
{"case_id":"f01","group_id":"future-root","scope":"scopeA","observed_at":100,"split":"future","source_input_sha256":"<64 lower-case hex>","target_text":"Future caption withheld from the predictor"}
```

No phase accepts ground-truth class labels, hidden prompts, arbitrary model
URLs, `trust_remote_code`, silent truncation, changing Width, unpinned files,
or null/NaN features. Duplicate cases and mixed scope reject. Train requires
at least eight examples and two source groups; the V1 fit/predict/evaluate
pipeline separately ensures chronological group exclusion.

## Why this is not yet A0/A1/A2 acceptance

- There is **no** supplied official mmBERT-small or Granite-97M checkpoint in
  this patch, and no claim of having executed either model here.
- `attention-mask-mean` is a controlled common pooling baseline; it may not
  be each model's recommended pretrained embedding recipe. Compare official
  pooling as separate, clearly identified arms, without conflating them.
- The tests inject a deterministic, clearly unverified fake backend to cover
  ingress invariants; they do **not** prove language quality. Only the real
  CLI loader may set `model_checkpoint_locally_verified=True`, **after** the
  strict model material check and successful real forwards/revalidation.
- A local checkpoint SHA is not an independently authenticated publisher
  identity, selected artifact, original acquisition consent, or deploy grant.
- The model, unlearning lineage, resource costs, held-out utility and OOD
  calibration must be reviewed by independent owners. Target-host RSS,
  GPU, energy, p95/p99 and cell-scaling receipts remain absent until measured.

## Next hard gates

1. Operator-stage **two independently identified 384D pretrained checkpoints**
   with exact tokenizer/weight manifests (mmBERT-small vs Granite Embedding
   97M Multilingual R2) and frozen train/calibration/future partitions.
2. Run each model at the same token lengths, training budget, batch, and
   versioned pooling recipe; retain actual physical forwards, RSS, CPU/wall,
   checkpoint bytes and failure witnesses. No implicit downloads.
3. Compare no-change, linear Head, state-gated Head, shared family Adapter,
   original 421M benchmark at equal task/budget; keep evaluator and selector
   independent and report NDU future utility, calibration, negative transfer.
4. Add pinned DINOv2 and an audio model through separate actual sensor
   encoders and train their bridges only on paired train data. Stage no
   model directly into production Worker until final-use and migration gates
   have real independent receipts.
