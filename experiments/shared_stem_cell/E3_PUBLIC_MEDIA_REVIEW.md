# E3 public image/text real-weights numeric receipt — 2026-10-14

**Source:** [GitHub Actions run 38532887290](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38532887290), at source commit `0694e6b7f3882ff5823ce6a90bdb3c30aaf604de`. The **overall run failed**. Its independently identifiable `public-image-text` job `115749269718` completed **successfully**; the relevant generated artifact `11881821872` remains downloadable. Other jobs in the workflow failed, so this document does not call the full Action green.

**Pinned artifact:** ZIP SHA-256 `1836173b1f92f21bb26296ccf06e929646ff60ff933e3880716dcce62faf3f53` (530,399 bytes). No raw images, pretrained model weights or personal data are copied into this PR.

Run:

```sh
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e3_public_media_receipt_audit.py' -v
python experiments/shared_stem_cell/e3_public_media_receipt_audit.py \
  --source-zip /approved/hepta-public-media-38532887290.zip \
  --output /sealed/e3-numeric-audit.json
```

The read-only auditor refuses changed archive SHA, duplicate ZIP entries, path traversal, duplicate JSON keys, NaN/non-normalized probabilities, missing/duplicated holdout case IDs, cross-cohort source-group and image-byte reuse, changed published prediction digests, incorrect label-derived scores, and invalid mask/rotation source identities. The source ZIP is not authenticated by a publisher signature; SHA-256 only binds the archival bytes. Every output is `DENY_ALL`, with `production_promotion_permitted=false`.

## Actually recomputed public holdout results

| Cohort | Cases | Example arm | Correct |
| --- | ---: | --- | ---: |
| hepta-public-media | 32 | image+text | 8/32 |
| hepta-public-media | 32 | image+text frozen | 11/32 |
| hepta-calibrated-media | 64 | image+text | 20/64 |
| hepta-calibrated-media | 64 | image+text frozen | 22/64 |
| hepta-calibrated-media | 64 | mask:text | 10/64 |
| hepta-calibrated-media | 64 | mask:image | 23/64 |
| hepta-choice-media | 64 | text_only:frozen | 12/64 |
| hepta-choice-media | 64 | visual_prior:final | 16/64 |

This is a diagnostic observation of one CLIP/ScienceQA route, **not** an E3 Granite+DINOv2 vs EmbeddingGemma2 natural-data comparison. The mask:text change is 3 gained, 13 lost; mask:image is 8 gained, 5 lost relative to 20/64 as-observed on that same cohort. These are small, unadjusted, source-family-limited paired readouts and cannot be relabeled as validated causal learning or inference-time intervention benefits. The two cohorts have differing sampling and training; do not pool them to boost significance.

**Exact locally checked source:** `e3_public_media_receipt_audit.py` Git blob `3c8751b498e481f7aeef3fa923c47245f704caf4`; 15 synthetic fault tests in blob `07bf13ead58d8c0da01831c0cf4b1a0b04604693` passed against the separate pinned real ZIP. Exact PR HEAD Actions and global `blocking-ci` still need to complete independently.

## Remaining causal gates

True new-source time-separated E3 tasks with OCR-only/no-image/hard-negative controls; distinct, actually pinned and locally verified Granite, DINOv2, and EmbeddingGemma 2 weights; identical task/source/budget; train-only bridge fitting; independently sealed predictions and label outcomes; Reader four conditions; Q24 production-native Worker/FinalUse/CAS/WAL/revocation; OOD/retention and NDU effect; measured load/encode/bridge/train/serve/lifecycle cost; exact-SHA security and release approval.

This package does not select models or promote any Stem/Cell. Its capability and production acceptance remain **false**.
