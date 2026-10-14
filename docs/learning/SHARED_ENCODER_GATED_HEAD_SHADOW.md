# Q24 compact gated Cell Head — offline-only experiment

This independent experimental script runs **real local PyTorch CPU training** of
a per-Cell, lightweight gated Head over **previously captured, unverified**
384-dimensional Q24 features. It does **not** load or execute mmBERT, Granite,
ModernBERT or any other Encoder. It cannot authenticate feature provenance,
predictive chronology, model manifests, final-use authority or target-host
resource measurements.

## Implementation

`scripts/hepta-stem-head-shadow.py` uses

```text
feature x (384D)
   -> Linear(384, rank, bias=False)
   -> Linear(rank, 384, bias=False)
   -> gated residual: x + sigmoid(Linear(384,1)(x)) * low_rank(x)
   -> Linear(384,2) -> binary class probability
```

**All** gates, low-rank adapters and the final classifier contribute to the
learnable parameter total:

`2 * 384 * rank + 3 * 384 + 3`.

| Head ceiling | Rank | Total trainable Head parameters |
| ---: | ---: | ---: |
| 2,048 | 1 | 1,923 |
| 8,192 | 8 | 7,299 |
| 16,384 | 16 | 13,443 |

The Encoder receives no gradient. The script measures **Head-only training**
on supplied Q24 data; published Encoder capabilities or weight revisions are
not evidence that the precomputed features were produced by those weights.

## Input contract

Training JSONL and prediction JSONL must contain `case_id`, `scope_id`,
`task_id`, `group_id`, `model_revision` (pinned 40-character lowercase
hex), `encoder_digest`, `tokenizer_digest`, `normalization_digest`,
`quantization_digest` (all 64-character lowercase hex), positive
`generation` and `fence`, exactly 384 bounded integer `feature_q24`
values in [-8·2^24, 8·2^24], `event_time`, `label_available_at` in UTC and
`split`.

Training records must be `split=train`, have binary 0/1 `label`, and the
label must have been released by the frozen training cutoff. Prediction
records must be `split=future|old|ood`, contain **no label key**, have
events after the training cutoff and labels unavailable at the actual
prediction time. Train/prediction group leakage, mixed Scope/model/generation
identity, missing or duplicate keys, oversized cohorts, invalid Q24
representations and any attempt to overwrite a previous output fail closed.

```sh
python3 scripts/hepta-stem-head-shadow.py \
  --train q24-train.jsonl \
  --predict q24-future-without-labels.jsonl \
  --train-cutoff 2026-10-14T00:00:00Z \
  --budget 2048 --steps 30 --seed 17 \
  --output-prefix ./shadow-cell-1
python3 -m unittest discover -s scripts/tests -p 'test_hepta_stem_head_shadow.py' -v
```

Outputs: `.manifest.json`, `.learned.jsonl`, `.frozen.jsonl`.
The prediction files use the declared schema of the independent E1
retrospective reviewer; the future labels must become available **after**
the output commitment, then come from an independent outcomes owner.

All outputs mark `DENY_ALL`, `production_promotion_permitted=false` or
equivalent non-authority. Head digests are **research SHA256** of raw FP32
parameters, not CAS signatures or trusted runtime receipts. The memory and
transient columns in prediction rows are zero placeholders, explicitly
**not measured**; do not use these rows to pass resource gates.

## Dependencies and required evidence

Requires PyTorch and NumPy in a controlled local experiment environment.
Its smoke tests use CPU only. The true mmBERT/Granite comparison requires
separately verified real Encoder weights, identical task/time splits,
compatible tokenizer and pooling policies, matched training FLOPs,
matched Head parameter budgets, sealed prospective predictions, independent
NDU evaluation and physical device resource measurements. Never interpret
a synthetic/local Head fixture as a successful E0–E4 gate.
