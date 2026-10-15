# E2 real DINOv2 ingress: byte-pinned source-only features (2026-10-15)

**DRAFT / SHADOW_ONLY / DENY_ALL. No production Stem, Cell, Bridge or FinalUse changes.**

This research child follows [#2136](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2136) and the existing #1885 multimodal alignment/Head work. It adds actual **model-loading code**, model-weight-to-loaded-state verification, a bounded image feature producer, a train-only source/text join, 17 local negative/positive tests and a hosted *physical* original-model canary. The hosted physical outcome must be inspected; source presence is not a successful pretrained inference claim.

## Immutable model source

- Publisher: \`facebook/dinov2-small\`.
- Git revision: \`150c8e7bb7cef2d30ec31b13a517af14840ee3f7\`.
- Original \`model.safetensors\` SHA256: \`ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1\`.
- Other required source material: \`config.json\`, \`preprocessor_config.json\`, separately byte-pinned by the operator and included in the receipt.
- Strict three-file physically staged snapshot: unlisted files, pickle weights, symlinks, wrong architecture/384D, Meta/missing/random or mutated weights must fail before output.
- The only running inference entry is \`e2_real_vision_features.py run()\`, using stock \`AutoModel\` and slow \`AutoImageProcessor\`, \`trust_remote_code=False\`, local-only, one actual forward per image, CLS pooling and L2 normalization. All source weights are compared to original tensors and rehashed after inference. This is **not** equivalent to independently authenticated publisher provenance.

## Source-only input

Each \`train\` or \`future\` JSONL line has **exactly**:
\`case_id,group_id,scope,observed_at,split,condition,image_path,image_sha256,question,source_sha256\`.

\`source_sha256\` = SHA256 of canonical JSON bytes for:
\`["hepta.e2.image-case.v1",case_id,group_id,scope,observed_at,condition,image_sha256,question]\`.
Canonical JSON is sorted keys, compact separators, \`ensure_ascii=True\`, \`allow_nan=False\`, ending in one newline.

Source-only files may not include \`label\`, \`answer\`, \`target_text\`, or any extra key. Images must be real, locally staged, individual PNG/JPEG/WEBP bytes, with verified SHA256. No filename traversal or symlink is accepted. Cross-scope source input is denied. \`visual_evidence_removed\` is deliberately *not* accepted as an actual vision forward: it belongs to the no-image baseline and must not receive a fabricated visual embedding. This source runner does not independently adjudicate whether the image, question or intervention is semantically valid.

## Train-only pairing and future isolation

Run the physical vision producer for TRAIN and FUTURE separately. Its output is \`features.jsonl\` plus a read-only \`receipt.json\` including the exact origin weights, SHA256 of produced features and observed number of physical model forwards. Any loader error leaves no success receipt and must not trigger a fake-model fallback.

The independent joiner \`e2_real_vision_bridge_ingress.py\` accepts a SHA-pinned physical image-feature output and receipt. TRAIN additionally requires **TRAIN-only** \`target_text\` anchors with exact case/source/group/timestamp matching. It emits the input understood by existing \`multimodal_real_encoder.py\` TRAIN, which invokes Granite/mmBERT's verified text feature loader; the existing \`multimodal_alignment.py fit\` then learns a train-only ridge Bridge. FUTURE never admits \`target_text\`: its image-only output is compatible with existing \`multimodal_alignment.py predict\`. Future labels remain solely with an independent scorer after prediction bytes are sealed.

A successful model forward or improved cosine geometry still does **not** establish real image-dependent end-to-end task success. Feed fully verified five-arm task predictions only into #2136's \`e2_semantic_outcomes.py\`. Missing \`native_multimodal\`/OCR or any other arm means **no five-arm score**, not a substituted synthetic prediction.

## Execution

Contract tests (no model weights required):

\`\`\`bash
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p test_e2_real_vision.py -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p test_e2_real_vision.py -v
\`\`\`

Genuine physical model runner (requires operator-staged complete original three files and approved/verified input):

\`\`\`bash
python experiments/shared_stem_cell/e2_real_vision_features.py \
  --snapshot /staged/pinned-dinov2 \
  --images /staged/image-bytes \
  --input /staged/train-sources.jsonl \
  --input-sha256 "$TRAIN_SOURCE_SHA" --phase train \
  --config-sha256 "$PINNED_ORIGINAL_CONFIG_SHA" \
  --processor-sha256 "$PINNED_ORIGINAL_PROCESSOR_SHA" \
  --output-dir /new/physical-train
\`\`\`

The paired-future and train joiner accepts pinned outputs:

\`\`\`bash
python experiments/shared_stem_cell/e2_real_vision_bridge_ingress.py \
  --phase train \
  --vision /new/physical-train/features.jsonl --vision-sha256 "$VISION_SHA" \
  --receipt /new/physical-train/receipt.json --receipt-sha256 "$RECEIPT_SHA" \
  --train-text /sealed/train-anchors.jsonl --train-text-sha256 "$ANCHOR_SHA" \
  --output /new/pinned-train-text-inputs.jsonl
\`\`\`

The hosted workflow \`.github/workflows/hepta-e2-real-vision-source-contract.yml\` exercises contract tests first, then attempts a **real original pretrained** DINOv2 CPU forward on two explicitly SYNTHETIC images. The image canary is a physical material/forward test **only**. It is not a natural-image task, supervised classifier result, 4-way semantic counterfactual or future learning outcome.

## Explicit blockers

1. Actual latest-head GitHub Actions contract success and unmodified real DINOv2 physical receipt; failure or queued is not success.
2. Physically verified Granite train text features; source-disjoint train-only Bridge fit; real held-out image/task predictions with no target access.
3. Actual OCR baseline and native EmbeddingGemma 2 multimodal forward, matched original case/arm identities, independent adjudicated visual necessity, correct \`visual_evidence_removed\` no-image semantics.
4. Complete four-condition paired real future1/2/3 source windows, negative transfer, fair total costs, independently reviewed no-change, failure/recovery and target-host CPU/GPU/RSS/p95/p99.
5. \`blocking-ci\`, original owner, model provenance and FinalUse contracts before any selection, mainline merge or production.

**No experimental result in this child authorizes model selection or production.**
