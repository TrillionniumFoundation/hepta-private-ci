# Original shared Encoder / train-only calibrated same-Encoder centroid V7

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO / NO MAIN MERGE / NO STEM SELECTION / NO FINALUSE / NO PHYSICAL CELL SPLIT.**

This is an additive child of V6 PR #2635, base commit `0c98bcbd48b4a9bd8fcb0d2c58da0139505c6cf5`. The original V3 pretrained Encoder/Head training, V4 fixed cheap lexical controls, V5 independent original pairing and V6 train-only lexical calibration are not modified. Same historical BANKING77 fee/charge 64 fit / 32 test cohort is **already label-exposed in older analysis**; the present study is not prospective, and no p-value can select a model.

## Why this experiment

Granite47 had 30/32 both with a learned 6,914-parameter gated Head and a same-Encoder *uncalibrated* train centroid in original V3; learned Brier 0.1279 was better than centroid Brier 0.7205. Comparisons against uncalibrated cosine softmax are not fair measures of learned representation. V6 tests *non-neural* train-only calibration. V7 now calibrates **the exact same pretrained Encoder's own train centroid**, so that the learned Head's marginal accuracy and Brier improvement can be measured against a similarly train-calibrated, lower-parameter alternative.

## Exact original CPU experiment

- Frozen V1 model identities and actual safetensors weights for Granite47, Granite97 and mmBERT140, float32 CPU / 128-token source, 384-dimensional masked-mean/L2 features. Only the original source owner's SHA-pinned V3 unlabeled TEST case roster is admitted; the V7 producer never opens original TEST labels.
- Each model runs six **real, newly counted pretrained Encoder batches** for all 96 original examples; it writes one physical 96×384 F32 safetensors feature artifact and SHA-bound source/model/feature receipt. The test feats are only scored, not used to fit folds, centroids or temperatures.
- Reuse **the frozen V6 stratified four folds** over 64 TRAIN labels, with four train-class samples per held-out fold. Each 48-case fold computes its own supervised class means; choose temperature from `{0.5,1,2,4,8,16,32}` by mean 4-class Brier on the 64 out-of-fold TRAIN predictions; ties favor the smaller value. No TEST label reaches any training/tuning process, and the selected T is not expanded after seeing TEST results.
- Export each original 32-case probability vector for both **T=1 uncalibrated** and **train-only calibrated** centroids, plus original source/model/feature digest, all folds and CV-losses. This does not train any new gated Head; it compares with original V3 frozen learned-Head receipts.
- A distinct NumPy/safetensors Reviewer reopens each actual feature tensor without importing the V7 producer, recomputes every fold and TEST probability, enforces same-model original V3 T=1 probability parity, then reads independently reacquired publisher labels **after** all model artifacts have been saved. It reports accuracy, multi-class Brier and paired differences against original V3 learned Head, without selection authority.
- Per-model CPU/RSS observations are *different GitHub runners*, not matched target-host p95/p99, energy, WAL/recovery, 4,096-Cell lifecycle or independent issuer attestation. All missing resource axes remain explicitly null, no inferred savings.

## Staged implementation and honest evidence

The first PR contains only the numeric producer/independent reviewer/source-only tests. Its 8 real Torch CPU **synthetic** feature tests and 8 optimized-mode tests are **not** genuine pretrained experiments. A second stacked PR adds the original-source, matrix model and independent publisher-label GitHub workflow. Until exact-head Jobs succeed, claim only implementation/test presence. Even if they succeed, this is one retrospective single-publisher cohort, not true future-window NDU utility or optimal Stem selection.
