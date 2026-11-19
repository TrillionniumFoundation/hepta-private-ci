# HDCF V13 — original frozen-feature class-withheld transfer falsification

**DRAFT · RESEARCH_ONLY · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL · NO STEM WINNER · NO CELL SPLIT · NO FINALUSE · NO MAIN MERGE**

## Exact lineage and purpose

Additive child of V12 [#2665](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2665), exact parent `b265a688fc205e965d05cd587cc819be8abbfa9f`. V12's exact-head original-data workflow [39026027453](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39026027453) succeeded. V13 leaves **all original V8–V12 and production code unchanged** and adds an independent research analysis, adversarial tests, a read-only push-only workflow and this runbook.

Unlike V12's 36-train three-class study (20/24, tied with strong DINO), V13 **withholds each one of the three disease classes from Organ training in turn** and uses only the 24 original TRAIN images of the remaining two classes for actual rank-8 SGD. Each fold retains all three existing original Granite97 text cue embeddings at test time. The intentionally withheld label never contributes to an SGD loss or gradient. The original historical 24 TEST images and their labels are kept separate until source/feature-only predictions are sealed.

Original public E2 source & frozen model: [Actions 38680856403](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38680856403), original Beans `AI-Lab-Makerere/beans@27aa014ce09b193e1a6f58112d4a66e0eddb69c5`, original image features from pinned `facebook/dinov2-small@150c8e7bb7cef2d30ec31b13a517af14840ee3f7` and original text features from pinned Granite Embedding 97M R2 at `835ad14087e140460703cf0fae09f97d469d65c2`. Original outer GitHub ZIP SHA-256: source `49ee4b855879e8ad463fb3f0ffb21e30b332fb24d1626360aa8f382d16ef82ad`, frozen features `92536c949e16ee0722357ccb1d881f371707df3c26424cd93dd2bfc96e49511e`, withheld targets `946101fe7e57a151ce5ae9ec314fc6e01b7244aeac48f49034ee0a581e09c67d`. The actual original frozen DINO model forwards (36 TRAIN + 24 TEST) and the original Granite features were executed **earlier**; V13 performs **zero new pretrained forwards**.

## Physically trained three-fold experiment

- Three distinct real NumPy/BLAS FP64 Organ fittings, each with **6,144 trainable weights, 160 complete full-batch SGD updates, and exactly 24 original labeled TRAIN images**. The held-out class has zero samples in the training loss and no gradient contribution. Identical rank/seed/learning rate/L2 and original text prototypes across all folds. Per-fold 983,040 estimated scalar parameter update touches; total 2,949,120 across the three Organs, not a complete GPU/CPU service cost.
- Source-only prediction file binds exact case, group, image SHA, model/input ZIP SHA, TRAIN-label/source-prototype digests, per-fold held class, optimizer work, actual learned tensor SHA, complete 24×3 original held-score vectors, and `production_authorized=false`. This file is created before withheld TEST targets or publisher TEST Parquet are downloaded. The independent readout **refits all three models from real TRAIN data** and byte/score-checks the submitted weights/predictions before joining held labels.
- Separate privileged historical reference: original **fully three-class trained Organ**, TRAIN-only visual Ridge, and original frozen DINO visual prototype (each used all three disease classes). These are useful diagnostic ceilings but are **NOT compute- or training-label-matched zero-shot controls**. No claim of fair like-for-like parameter equivalence to a 421M model.
- Publish only a sanitized aggregate. Original images, class labels, per-image held predictions, full model feature tensors, Head weights, pretrained safetensors and ephemeral TRAIN model matrices never leave the private runner output files.

## Genuine local historical TEST observation

Three class-exclusion folds evaluated on the **same 24 historical public TEST images, exactly eight per original class**. A fold's “unseen class” denominator is therefore eight, not 24, and three folds × 24 images are **correlated observations from one publisher**, not 72 independent datasets.

| Class absent from actual supervised Organ TRAIN | Correct on 8 withheld-class TEST images | Correct on all 24 historical TEST images |
|---|---:|---:|
| `angular_leaf_spot` | **1/8** | 16/24 |
| `bean_rust` | **1/8** | 16/24 |
| `healthy` | **0/8** | 13/24 |

Across three folds there are **2/24 correct unseen-class/image fold observations** (the 24 observations are 8 per distinct disease class, all from the same original public publisher). The 36-example, three-class, fully trained V12 Organ, visual Ridge and privileged frozen DINO prototype all remain **20/24** on this original task. Fewer per-fold training examples and the excluded training label are confounded; none of this proves representation capacity limits or that a future image/text Organ could not generalize.

**Critical limitation:** the text cues are the same three historically frozen, labeled-source class descriptions as V12, not freshly encoded paraphrases or human-independent natural-language questions. Although a fold's *classification label* is never trained, its text prototype is an original TRAIN-derived frozen feature, so this is **a conditional hold-out stress test, not pure zero-shot semantic proof**. Original DINO pretraining, same-publisher source overlap, historical TEST reuse and source-family/temporal leakage boundaries prevent conclusions about truly independent new classes. `independent_source_issuers_verified=false` and `unseen_class_learned_semantics_proven=false` are unconditional.

## Actual local source checks and hosted handoff

Local Python 3.13/NumPy 2.3.5 uses authentic original ZIPs only. `HDCF_V13_SOURCE_ZIP`, `HDCF_V13_FEATURE_ZIP`, and `HDCF_V13_TARGET_ZIP` must point to the three complete byte-SHA-frozen original archives; no synthetic fixture fallback. Reproduce:

```sh
cd qualification/hdcf-research
OPENBLAS_NUM_THREADS=1 python3 -m unittest -v test_class_withheld_transfer_v13
OPENBLAS_NUM_THREADS=1 python3 -O -m unittest -v test_class_withheld_transfer_v13
```

The read-only `hepta-hdcf-class-withheld-v13.yml` exact branch workflow stages original source + frozen model feature ZIPs, fits all three Organs before original TEST labels are acquired, stores a SHA-256 seal, **then** downloads the pinned withheld ZIP and separately obtains whole-byte pinned publisher TRAIN/TEST Parquet. It runs the complete real-source tests and calls the independently reusable V9 publisher re-selection/label byte verifier before emitting sanitized aggregate. It cannot alter live authorization, Rust Neuron/Worker/NDU/CAS/CNS, selected Stem, CellSplit, FinalUse or `main`.

A successful research job certifies only that this historical experiment was executed/replayed under the declared sources. Full mandatory `blocking-ci`, architecture checks, independent prospective source families, genuine unseen natural question semantics, cost-matched training/inference, target-device RSS/p99/GPU/energy, old-task retention, deletion/rollback and operator approval remain separate unclosed gates. **Always `HOLD_NO_GO_DENY_ALL`, no promotion or release.**
