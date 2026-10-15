# P2 trained Top-1 against single-active Head — real public Granite97 research gate

**Authority: DRAFT / DENY_ALL.** Stacks *additively* above #2199, using the original #2180 public Granite97 P2 material and the existing official V1 source/model owners. No production Cell Split, NDU authorization, FINAL-USE, `main`, model selection, cache or serving activation is changed. The prior P2 null/negative findings are preserved.

## Which scientific gap this resolves

#2180's post-training Top-1 path in #2199 executes one selected Head after both experts were trained with a dense, double-Head objective. That does not establish what happens if **the training itself** uses only one selected Head per sample and is compared to a strong single-active baseline. This stage fits three separate, freshly initialized matched physical sparse arms, not a postfit rewrite of historical model outputs:

| Arm | Total resident Head params | Active Head per sample | Train-only router | Original 40-stage SGD exposures |
|---|---:|---:|---|---:|
| `single_active` | 14,868 | 1 × 7,434 | Always parent 0; second resident slot dormant | 3,840 |
| `fixed_top1` | 14,868 | 1 × 7,434 | Predeclared median of first training feature | 3,840 |
| `adaptive_top1` | 14,868 | 1 × 7,434 | First 20 steps parent only; clone and route if old-to-new *train-only* Brier excess > 0.03 | 3,840 |
| `frozen_single` | 14,868 | 1 × 7,434 | None | **0** (no-change control; not a training work match) |

The earlier fully trained **unrouted twin** and **real rank-16 wide monolith** remain in #2180 and are numerically replayed by the independent reviewer, but have **higher active online Head MAC** and therefore are *not* incorrectly counted as equal-active-compute rivals. Original #2199 dense/postfit timing receipt is unchanged.

Every trainable arm runs **20 × 64 old-cohort** + **20 × 128 all-train-cohort** updates, exactly 3,840 independent train-input exposures and 3,840 physically selected expert rows, at 7,424 declared per-row linear MAC. No branch invokes `TwoHeads.forward` to secretly calculate both experts. The implementation dispatches only nonempty expert subbatches through autograd-compatible Tensor indexing, and tests demonstrate dormant Head 1 receives zero gradients and unchanged bytes.

Each arm also pays for a matching 128-row *train-only* old-vs-new Brier diagnostic, a 96-row exact heldout inference, all initial model materialization and resident 14,868 × 4 weight bytes. Adaptive cloning, if selected, is charged an extra **29,736 copied FP32 bytes**, **8 parity-check Head forwards**, and two real subgroup calls. The baseline is **matched on selected forward training rows and source exposure**, not proven matched on backward FLOPs, CPU cache effects, dynamic router overhead, checkpoint loading, training time or full lifetime costs. Per-arm actual process CPU/wall and eval call timings are retained; negative/counterintuitive results are not rejected.

### Exact original source, checkpoint and sealed evaluation

Use original pretrained `ibm-granite/granite-embedding-97m-multilingual-r2` commit `835ad14087e140460703cf0fae09f97d469d65c2`, with audited local-only CLS/L2 384D Q24 interface. The hosting workflow already pins whole safetensors+LFS revisions through existing owners. The original AG News canonical panel is `2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4`, with 128 real public retrospective train, 32 calibration and 64 test cases. Original labels exist publicly, but the new training entrypoint accepts only the exact **labeled train** and **label-free evaluation** bundles; `owner-labels.json` is opened only by the **separate NumPy-only scorer after both original P2 and new predictions have been written**. No blind/test labels enter loss, split rule, feature selection or stopping.

The new experiment intentionally **loads Granite97 a second time in a separate process** and executes **224 additional pretrained Encoder calls**. It rechecks that frozen model SHA/count, initial Head SHA, training-derived Router cutoff, all original 96 source identities and all exact 96 Q24 features match the sealed original #2180 P2 report. This extra load/materialization is **not free** or mistaken for cache savings. Once new predictions are emitted, the standalone review imports no Torch, no new trainer and no real model loader. It independently verifies the old P2 report with the old P2 NumPy reviewer, decodes all new raw FP32 parameter bytes, recomputes all 4 × 96 logits, route identities and original-label accuracy/Brier, and reports paired wins/losses against the one-active baseline. Model weight/Q24 SHA checks do **not** authenticate a publisher, a device, or a prospective observational source.

### Reproducibility (same exact P2 data-owner outputs)

Run after the existing #2180 `p2_real_cell_split.py` has produced the immutable `predictions-unscored.json`:

~~~sh
python qualification/stem-cell-v1/p2_train_sparse_equal_compute.py \
  --train-material "$ROOT/material/train.json" \
  --blind-material "$ROOT/material/blind.json" \
  --compact-source pinned-compact \
  --original-p2-report "$ROOT/predictions-unscored.json" \
  --output "$ROOT/trained-top1-unscored.json"

# Only after both P2 + new label-free prediction artifacts exist:
python qualification/stem-cell-v1/p2_train_sparse_equal_compute_review.py \
  --original-panel "$ROOT/panel.json" \
  --train-material "$ROOT/material/train.json" \
  --blind-material "$ROOT/material/blind.json" \
  --owner-labels "$ROOT/material/owner-labels.json" \
  --original-p2-report "$ROOT/predictions-unscored.json" \
  --trained-top1-report "$ROOT/trained-top1-unscored.json" \
  --output "$ROOT/trained-top1-independent-review.json"
~~~

Hosted CI publishes only **source SHA, dependency list, sanitized independent reviews and bounded logs**, never private or public weight dumps, text, original features or labels. Files are create-only; any earlier or partial report must remain intact.

### Local evidence, exact scope

- 32 new direct CPU Torch/NumPy adversarial and paired physical method tests run both normally and under `python -O` (no model weights downloaded for the local test). Tests include fully unexecuted expert gradients, FP32 weight mutation despite resealed hashes, original P2 frozen-source rebinding, cross-group swapped Q24, label isolation, train-exposure counts, route tampering, and properly paid migration parity work.
- The saved three-seed local **toy** observation receipt contains both positive and negative outcomes; it is `SYNTHETIC_NOT_PRETRAINED` by construction. Seeds 41/47/53 all use the same seeded fake 147,840-parameter physical Stem, not Granite97. No seed is selected for test accuracy.
- The real hosted job, `blocking-ci`, genuine independently sourced future task families, readout sufficiency, actual matched optimizer FLOPs/energy and target-native Worker telemetry are **required and pending** until exact-SHA runs complete. An English public AG News cross-section cannot constitute chronological old-task retention, video/audio/image multimodal synthesis or NDU/FBSDE utility gains.

**Acceptance:** Numerical mechanism checks and source-only CI can validate the architecture, but cannot authorize model selection. Preserve every negative/null result, `main` stays unchanged and the research reports always return `model_selection_authorized=false` and `production_promotion_permitted=false`.
