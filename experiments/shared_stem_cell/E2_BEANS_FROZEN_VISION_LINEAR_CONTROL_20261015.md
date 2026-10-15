# E2 frozen DINO vision-only Ridge control — research, SHADOW / DENY_ALL

## Why this additional control is indispensable

The original natural-Beans E2 #2189 has four arms: a fitted Granite-space
DINOv2 Bridge, a TRAIN caption-rotated negative, an unaligned-space negative,
and a **frozen** DINO vision nearest-prototype classifier. The frozen prototype
is a strong reference, but it is **not** a supervised trainable vision-only
linear model. If a cheap visual classifier learns as much as the Granite Bridge,
then apparent improvement cannot be attributed to cross-modal alignment.

This adds one separately sealed, **vision-only linear Ridge** diagnostic
without changing any of the original four arms, original material owners,
model weights, validation rules, or production paths.

## Registered fixed comparison

- Original data: exactly 36 TRAIN leaf images / 24 retrospective TEST images,
  12/8 per class, exact model and dataset revisions inherited from #2189.
- Input: original DINOv2-small frozen, unit-L2 384D features already in the
  original producer ZIP. No new image Encoder or Granite forward permitted.
- Train target: original TRAIN-only disease class; no test targets, text caption,
  OCR or per-class prototypes from future images enter fitting.
- Fixed alpha = 0.1, **not tuned** on validation/future labels. Train-centered
  dual ridge of one-hot 3-class targets, converted into 384x3 weights + 3 biases
  (**1,155 effective trainable coefficients**). All preprocessing and
  training/probe costs are separately declared, not hidden in encoder cost.
- Freeze and SHA-pin both `probe_model.json` and `probe_predictions.json`
  **before** independent evaluation can open the withheld target ZIP.
- Independent reviewer requires all four exact GitHub ZIPs through the original
  #2211 auditor, recomputes ridge training from the original 36 DINO features,
  checks every 24 held-out inference predictions and every label, compares
  with original fitted Bridge and original frozen vision prototype and reports
  exact two-sided McNemar + Holm adjustment for two predeclared comparisons.

### Execute producer *without* withheld target access

Acquire all four ZIPs from **one exact successfully completed** [#2189
Actions](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2189)
physical run. Independently record ZIP SHA-256 and source run SHA first.
Never substitute prior synthetic-run ZIPs. Each command requires exact
literal SHA-256 pins; replace file names and digests with observed identities.

```bash
python experiments/shared_stem_cell/e2_beans_frozen_vision_linear_probe.py \
  --source-zip original-source.zip --source-sha256 "$SOURCE_SHA" \
  --producer-zip original-producer.zip --producer-sha256 "$PRODUCER_SHA" \
  --output-dir sealed-vision-only-probe

# Separately SHA-pin both completed, write-once seal files before opening labels.
sha256sum sealed-vision-only-probe/probe_model.json \
          sealed-vision-only-probe/probe_predictions.json
```

### Execute separate label-bearing evaluator after sealing

```bash
python experiments/shared_stem_cell/e2_beans_vision_probe_independent_score.py \
  --source-zip original-source.zip --source-sha256 "$SOURCE_SHA" \
  --producer-zip original-producer.zip --producer-sha256 "$PRODUCER_SHA" \
  --withheld-zip original-withheld.zip --withheld-sha256 "$WITHHELD_SHA" \
  --independent-zip original-independent.zip --independent-sha256 "$INDEPENDENT_SHA" \
  --model sealed-vision-only-probe/probe_model.json --model-sha256 "$MODEL_SHA" \
  --predictions sealed-vision-only-probe/probe_predictions.json \
  --predictions-sha256 "$PREDICTIONS_SHA" \
  --output new-independent-vision-ridge-readout.json
```

The research-only CI workflow tests mechanics and tampering on original-schema
**synthetic archive fixtures**. It does not claim a real Beans experiment before
all four original natural-image ZIPs exist and the independent command succeeds.

## Non-claims and safety boundaries

The 1,155-parameter trainable visual Ridge probe and the 384x384 fitted
crossmodal Bridge **are not equal parameter or total-work controls**; the
extra baseline diagnoses the attribution problem but does not establish a
cost-matched model winner. Class labels are public-retrospective labels, not
independent human adjudication. The 24 TEST images are not three prospective
future cohorts. Original source group identifiers are dataset row-specific,
not independent plant or date-of-capture witnesses. All tensor/weight archives
are self-consistent only, not independent publisher or worker signatures.

No real-model effect, new model selection, model promotion, FinalUse, Q24
production state change, or main merge is authorized by this experiment.
**DRAFT / SHADOW_ONLY / DENY_ALL / no production promotion.**
