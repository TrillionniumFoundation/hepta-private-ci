# Original Beans natural-image E2 — second opinion and uncertainty gate

**Research only · DRAFT / DENY_ALL**. This is a child of #2200 / #2189, not a
selected model or a replacement for the first independently scored model job.
The baseline is the **real frozen DINOv2 vision nearest-prototype classifier**,
not an artificially weak unaligned text/image vector comparison.

`e2_beans_paired_uncertainty.py` reads exactly six SHA-256-pinned input
files: source manifest, separately withheld target manifest, future source-only JSONL,
independent future class labels, sealed 4-arm future predictions, and the
earlier independent class readout. A target SHA by itself is **not** sufficient:
the withheld manifest must bind the original test Parquet SHA and the exact
source-only manifest before the scorer may load class labels. It never imports the producer, trainer, model or first scorer. It
independently matches all 24 case/group/scope/time/image byte digests and each
predicted class; recomputes original score totals, source class coverage (8 per
class), four-arm accuracy, per-class results and the paired rescued/harmed
counts against the frozen real vision-prototype arm. Changed labels, missing
arms, duplicate cases, false future-time statements, result fabrication and
production authority claims fail closed.

Under the retrospective-public Beans source, the statistical screen reports
Wilson 95% binomial confidence intervals for each 24-case marginal accuracy,
exact *two-sided* paired McNemar p-values from `(rescued,harmed)` and the
Holm correction over the three declared comparisons. Intervals and p-values
are **descriptive only**, not family/source-independent causal qualification.
Even a low corrected p-value does not permit a Stem winner or FinalUse,
because the samples are tiny, stratified, retrospectively labeled, source
families and original future acquisition windows are not independent, and
model, Reader and cost budgets are not all matched.

Usage (original archive files must first be downloaded by an independent
operator from the exact completed natural Beans workflow):

```sh
python3 experiments/shared_stem_cell/e2_beans_paired_uncertainty.py \
  --source-manifest source-manifest.json \
  --source-manifest-sha256 "$SOURCE_MANIFEST_SHA" \
  --target-manifest target-manifest.json \
  --target-manifest-sha256 "$TARGET_MANIFEST_SHA" \
  --future-source future_images.jsonl \
  --future-source-sha256 "$FUTURE_SOURCE_SHA" \
  --future-targets future_class_targets.jsonl \
  --future-targets-sha256 "$WITHHELD_TARGET_SHA" \
  --sealed-predictions sealed_class_predictions.json \
  --sealed-predictions-sha256 "$SEALED_PREDICTIONS_SHA" \
  --original-readout independent_class_readout.json \
  --original-readout-sha256 "$ORIGINAL_READOUT_SHA" \
  --output new_second_opinion.json
```

The accompanying workflow also checks the repaired inherited V11 MLM workflow
with a real YAML parser and `bash -n`, without watering down its full stock
pretrained and no-skip tests. Completing a code-only check does not establish
actual model training or natural-world performance.

**Outstanding scientific gates:** successful exact-source natural-image
physical producer and independent withheld-label readout; independent original
archive rehash/attestation; adequate source-group dedup, stronger text/OCR/native
multimodal controls, equivalent training/compute budgets, independent future
1/2/3 windows, actual 64/256/1024/4096 Cell target-host RSS/p95/p99 and
revocation/recovery, original owner `blocking-ci` and FinalUse. No promotion.

The paired evaluator V2 strict-entrypoint refuses to score if source and withheld
manifests do not match the pinned original Beans train/test Parquet revisions
and the exact future source/target file byte digests. This extra target-owner
lineage check is byte integrity, **not** cryptographic ground truth ownership.
