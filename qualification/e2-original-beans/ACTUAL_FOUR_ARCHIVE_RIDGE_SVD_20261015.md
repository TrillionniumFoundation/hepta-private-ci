# Original Beans natural-image four-artifact and SVD evidence

**Date:** 2026-10-15 · **DRAFT / SHADOW_ONLY / DENY_ALL** · **No production model selection**

Original [Actions run #38680856403](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38680856403) completed 4/4 successful jobs on source SHA `927bf53b184c3947db17a129834046c5f03add04`. Its exact four artifact IDs and ZIP SHA-256 digests are in `PINNED_ORIGINAL_ARCHIVES.json`. Each original archive was downloaded and checked locally against those literal digests; no hypothetical original artifact was used.

The existing independent `e2_beans_original_zip_review.py` validated original image bytes, training/TEST case and source identity, model revision and physical-feature receipts, sealed Bridge predictions, withheld-only label origin and independent score agreement. **Strict four-ZIP local audit PASS**.

The separately fitted **1,155-parameter** vision-only Ridge read only the original TRAIN and frozen DINO features, then sealed its model and 24 predictions prior to access to TEST labels. `e2_beans_original_replay.py score` and independent thin-SVD fitted the same weights without calling the producer solver, replayed all 24 predictions, then opened the four original artifacts to score against withheld labels. **Strict full SVD/label replay PASS**. The complete canonical local replay JSON SHA is `a56f25016c7a68d075ecebe5ab5b1e60c23e54f5a48370cc20786012fc848558`.

| Arm | Correct / 24 |
|---|---:|
| Granite+DINOv2 fitted Bridge | 20 |
| DINOv2 frozen visual prototype | 20 |
| TRAIN-only DINOv2 visual Ridge | 20 |
| Unaligned | 8 |
| Rotated TRAIN-label | 2 |

All 24 Bridge-vs-Ridge correctness indicators agree: 20 both right, 4 both wrong; 0 rescued and 0 harmed. Both trained models rescue 1 and harm 1 against the frozen visual prototype (19 both right, 3 both wrong). Two-sided exact McNemar and Holm-adjusted p values are 1.0. The independent SVD fit differs by at most `1.2212453270876722e-15` in weights and `8.881784197001252e-16` in bias. These facts are a **negative increment** for the Bridge's leaf classification utility on this small retrospective public TEST. They do not prove formal model equivalence.

**Production/validity guards:** The exact-head hosted replay activated on this research child must complete separately; a queued run cannot be called green. Actual archival identities are not external publisher or device signatures. No independently acquired prospective future1/future2/future3 plant/farm sources, matched complete work/parameter budgets, text/OCR/native five-arm evaluation, independent GroundTruth/Reader/NDU/Cell utility, 4096-Cell host performance, recovery, model selection, or FinalUse has been approved. No model or control owner in main was changed.

**Investment implication:** prefer the simpler frozen-visual + tiny Cell Head as the research baseline for image-only leaf classification. Move the next comparative experiment to genuinely complementary image-and-language tasks instead of repeating this same dataset. The choice is not an authorization to replace any existing production Stem.
