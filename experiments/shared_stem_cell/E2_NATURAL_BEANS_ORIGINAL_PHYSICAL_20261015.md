# E2 natural Beans original-source paired study — research-only / DENY_ALL

This experiment follows #2177 (the independently audited synthetic DINOv2↔Granite
Bridge). The synthetic pilot was a valid physical pipeline but no evidence of
natural-image utility. This child adds **real JPEG/PNG field photos** from the
public Makerere AI Lab Beans dataset. All outcomes must be treated as
**retrospective source-split observations**, not chronological future windows.

## Exact source and original task

- Dataset: `AI-Lab-Makerere/beans` at immutable commit
  `27aa014ce09b193e1a6f58112d4a66e0eddb69c5` (MIT), original embedded
  Parquet image bytes, no external-path or image-code execution.
- TRAIN original byte SHA-256:
  `7f905a7323966a58e89b8e839ed656bb869fc82d16a3fadc7dce40972a5f8b19`.
- TEST original byte SHA-256:
  `534a6b0648f585d69b7ec0ad7a7540720d60c8db8106dc6d0508296316f6cb27`.
- Original 3 labels: angular leaf spot, bean rust, and healthy. Domain labels
  come from the dataset; the 3 lightweight caption templates are **constructed
  by our source-authoring code**, not human independent caption annotation.
- Fixed label-stratified 36 TRAIN (12 per class) and 24 original TEST (8 per
  class), sorted deterministically by hashed independent image bytes. No row
  overlap, no identical image bytes; ordinal phase markers are NOT capture time.

## Real pretrained path and controls

1. Standalone source-authoring job verifies the full original Parquet byte SHA
   before reading or opening any image. It writes producer-visible source-only
   image/caption/TRAIN class manifests; withheld TEST class and caption targets
   plus their SHA-256s go to a **different, evaluator-only artifact**. No TEST
   Parquet is uploaded or supplied to the model job.
2. Frozen original DINOv2-small, SHA-pinned publisher safetensors, physically
   encodes 36 TRAIN + 24 TEST image bytes (not generated patterns).
3. Frozen original Granite 97M R2, strict V8/V9 publisher-revision handoff,
   physically encodes TRAIN caption anchors. TRAIN-only ridge projection fits
   the aligned and training-target-rotated Bridges. Fit metadata binds all
   original image and text model/preprocessor versions and source identities.
4. Predict original TEST visual features without target data. Seal three
   candidate Bridge outputs and add a strong **frozen visual-prototype**
   baseline, with prototypes fitted only on TRAIN visual features and labels.
   Four complete arms: fitted Bridge, shuffled-caption Bridge, unaligned
   visual input, and frozen DINOv2 nearest-prototype classifier. The latter
   is indispensable to avoid claiming success over an artificially weak
   projection-only control.
5. Only after sealing does a separate scorer receive original TEST classes,
   recompute exact-match class accuracy and paired rescues/harms against frozen
   DINOv2 visual prototypes; independent heldout Granite future-caption
   extraction computes descriptive geometry. Missing arm, source ID, class,
   full coverage, or required seal fails closed, including `python -O` tests.

The four arms here are **not** the original E2 *five-arm*
(text-only/OCR/unaligned/learned-Bridge/native multimodal) science panel. It
neither executes OCR nor Google's native EmbeddingGemma 2. Dataset JPEGs may
contain disease knowledge from pretraining; this is not an independent new
source collected after model release, nor proof of a genuinely future-time
source-chronological effect. Public retrospective TEST labels can be recovered
from the dataset outside this workflow. No predictor capability in this
experiment may authorize any downstream model promotion or FinalUse.

## Mandatory future investment gates

- Genuine 3 independent future acquisition windows, source-family novelty,
  approved labeling / ownership, natural image counterfactuals, OCR/native
  five-arm parity with equal task/Head/Reader budget.
- Compare fitted Bridge not only with shuffled/unaligned controls but with
  frozen visual-prototype and matched-capacity learned vision Head, showing
  statistically defensible improvements and no negative transfer.
- Full CPU/GPU RSS/p95/p99/energy and relevant 64/256/1024/4096 Neuron Cell
  target-host native resource and durable FinalUse/revocation tests.
- Original real-model and target-host independent provenance, exact-head and
  prospective-merge `blocking-ci`, and external Owner permissions.

**All values remain DRAFT / SHADOW_ONLY / DENY_ALL; no source code or Actions
outcome grants production model selection, Cell splitting or deployment.**
