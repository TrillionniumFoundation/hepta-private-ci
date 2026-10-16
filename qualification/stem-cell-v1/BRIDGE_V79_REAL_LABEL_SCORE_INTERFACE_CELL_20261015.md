# V7.9 — real-label split Cells on **genuine archived frozen Granite→Bridge scores**

**2026-10-15 · RESEARCH ONLY · DRAFT / SHADOW_ONLY / DENY_ALL · no `main` merge, FinalUse, native NDU policy or CellSplit promotion.**

## This stage is materially different from V7.7/V7.8

The genuine V7 historical package contains **three complete, actual pretrained frozen-Bridge `start-natural-train.json` score panels** on 3,909 real human-labeled Natural MultiRC TRAIN candidates from 64 original paragraphs. Original V6 contains the **three same-parent frozen-Bridge internal-tune panels** on 827 separate candidates / 194 questions / 16 paragraphs. The per-seed `model_execution_parameter_sha256` in BOTH archives agrees exactly with the original V6 frozen warmup checkpoint's SHA; complete V6/V7 original ZIP SHA256 and sizes are checked before training. This permits real-label learning on original pretrained **scores**, even though the Granite97 original *hidden states/Encoder weights* remain unavailable.

This work **DOES NOT** restore V6 TokenBank vectors, run the 97M Encoder, or learn from the original Reader's 97-dimensional pre-Head hidden tensor. The new 97D sidecar is an explicitly **hand-engineered lexical representation from public question/candidate/evidence text plus the genuine historical model scalar probability**. Calling that the original learned 97D feature would be incorrect. The old Binding path remains an unchanged historical checkpoint/score, **not** an old Reader whose inference was physically rerun this round. Reusing historical pretrained forward compute does not make it free end-to-end.

## Frozen inputs and source-separated human labels

| Historical source | Immutable SHA256 / count |
|---|---|
| `hepta_bridge_learning_v6_20261015.zip` | `197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a` (20,928,479 B) |
| `hepta_retention_transfer_v7_20261015.zip` | `199789fd66eee967269b3a137fc493c8991ecba695b8f81485a5a5b0cef9f463` (20,818,685 B) |
| Original train role | 3,909 answer candidates / 722 questions / 64 unique paragraphs; original *human* binary labels |
| Original internal tune | 827 answer candidates / 194 questions / 16 unique paragraphs; source-disjoint from train, but **previously exposed** in prior V4/V6/V7 research |
| Frozen parents | Actual V6 seeded 42,562-scalar Bridge warmup states for seeds 41,47,53; no weight updates or byte replacements |

Source IDs, question grouping and model/checkpoint SHA256 are validated; training feature constructor accesses ONLY original public question/candidate/fact strings and frozen score. Label, sentence-level gold evidence, paragraph identity and source hash never enter the 97D input. Source hash is used for split/sampling only. True human TRAIN labels enter CrossEntropy training, and internal-tune labels enter **post-training** descriptive scoring.

## Preregistered small-Cell cohort, control and matched work

For each seed, **one genuine archived frozen scalar-score feed** branches into four equal-sized **1,700-scalar `GatedNewHead`** objects (97→16 + 97→1 gate + 16→2 residual, zero-initialized residual). Update step and optimizer hyperparameters are fixed: 420 updates × batch 16, Adam learning rate `.005`, `foreach=False`, no threshold tuning and no stopping/selection on internal tune. The four arm names are:

- `score_only_row`: old real scalar logits + constant; original-row uniform minibatches.
- `score_only_source`: the same, but 16 independently chosen TRAIN paragraphs per minibatch.
- `score_text_row`: old scalar logits + bounded public lexical overlap/hash signals; row-uniform minibatches.
- `score_text_source`: the same lexical input, but 16 separate TRAIN paragraphs per minibatch.

These four arms have the same **total** 1,700 learned parameters and 420 updates (6,720 candidate exposures per arm), but **NOT equal active multiplication counts**, since `score_only` has 94 zero channels. They intentionally differ in sampled TRAIN candidate distribution; this is not full-FLOP or equivalent-label-exposure parity. A separately fitted **2-scalar sigmoid** uses 420 updates and the same row-sampling schedule. Frozen score and always-positive predictions are evaluation-only controls. No hidden historical model was optimized.

## Real physical result, historical original labels, 2026-10-15

All 12 actual gated Heads were trained by CPU PyTorch autograd on the complete original human-label TRAIN cohort, 5,040 genuine optimizer updates, with three seeds and four fixed ablations. The same complete campaign was **physically executed three times**; all **12/12** learned 1,700-parameter Head SHA256 and all **12/12** full internal-tune prediction SHA256 agreed exactly. The independent reviewer imported no Torch or producer training code, decoded each of the 12 real newly learned six-tensor Head state files and their 827×2 archived PyTorch logits, and recomputed every single score using **NumPy**. **12/12 passed** with maximum absolute logit error **7.152557373046875e-07** and zero top-class flips.

| Arm | Three-seed average original internal-tune F1a | Question EM | Accuracy |
|---|---:|---:|---:|
| Frozen genuine V6 pretrained score | 0.538529 | 0.049828 | 0.476018 |
| Original TRAIN labels, 2-scalar learned calibrator | 0.458866 | 0.054983 | 0.513906 |
| Source independent `score_only_row` | 0.042057 | 0.006873 | 0.544942 |
| Source independent `score_only_source` | 0.197800 | 0.030928 | 0.548569 |
| `score_text_row` | 0.571919 | 0.182131 | 0.644095 |
| **`score_text_source`** | **0.606229** | **0.197595** | **0.646110** |
| Always-positive baseline | 0.622814 | 0.000000 | 0.452237 |

For `score_text_source`, seed-specific F1a is **0.6426 / 0.5664 / 0.6097**. Compared with frozen V6, the three-seed average F1a increased by **0.0677** and question EM by **0.1478** on this already-exposed historical internal panel; the always-positive baseline has **higher F1a**, though much worse EM/accuracy. It would be incorrect to describe this as universal superiority.

For exploratory uncertainty, resample **16 paragraph source clusters as one aligned draw shared by all three seeds**, 2,048 prespecified deterministic bootstrap resamples. Compare F1a *per seed* on identical sampled source-group multisets before averaging deltas:

| Matched difference | Source-cluster bootstrap mean ΔF1a | 95% descriptive interval |
|---|---:|---|
| `score_text_source` vs frozen V6 | +0.06817 | [+0.00124, +0.13279] |
| `score_text_source` vs `score_text_row` | +0.03493 | [+0.01202, +0.05971] |
| `score_text_source` vs always-positive | −0.01786 | [−0.08054, +0.04556] |

**These confidence intervals are exploratory, not multiplicity-adjusted and not independent future task evidence.** The 16 paragraphs came from previously used original training-source internal-tune material; repeated random seeds do not multiply the independent source count. Hand-engineered sidecar signals and researcher history can themselves contain development-set priors. A causally controlled equal-lifecycle study and new independent prospective sources remain required.

## Resource accounting scope

Observed: 12 × 1,700 × FP32 = **81,600 B** of newly trained Head weights *for these 12 research models*; per Head **6,800 B**, **420 attempted and accepted Adam steps**, batch 16, original frozen logits accessed from prior evidence. The fitted candidate optimizer and training CPU timings are in each private `candidate.json`; aggregate train-run process CPU includes re-encoding **cheap lexical features**, parsing, initialization and independent scoring, but excludes historical Granite generation, target-host requests, actual Reader inference, full Rust/Worker/CAS ownership and GPU p95/p99. Neither the big-Encoder nor cache are compressed away by this experiment. The existing V7.7 physical 256-Cell shared-Reader experiment is distinct; this run did **not** instantiate 256 Reader objects.

## Reproduction and independent audit

This research branch already contains `bridge_split_cell_v77.py` and its exact `GatedNewHead`. Supply the **two original SHA-pinned ZIP files** via local paths; do not commit original weights or raw source text to Git.

```sh
cd qualification/stem-cell-v1
export HEPTA_V6_ORIGINAL_ARCHIVE=/sealed/hepta_bridge_learning_v6_20261015.zip
export HEPTA_V7_ORIGINAL_ARCHIVE=/sealed/hepta_retention_transfer_v7_20261015.zip
export HEPTA_V79_ACTUAL_RUN=/sealed/v79-original-human-label-new-score-cell
python bridge_v79_score_cell_train.py \
  --v6 "$HEPTA_V6_ORIGINAL_ARCHIVE" \
  --v7 "$HEPTA_V7_ORIGINAL_ARCHIVE" \
  --output "$HEPTA_V79_ACTUAL_RUN"
python bridge_v79_score_cell_review.py \
  --v6 "$HEPTA_V6_ORIGINAL_ARCHIVE" \
  --v7 "$HEPTA_V7_ORIGINAL_ARCHIVE" \
  --run "$HEPTA_V79_ACTUAL_RUN" --report /sealed/v79-independent-review.json
python -m unittest -q test_bridge_v79_archived_scores test_bridge_v79_score_replay
python -O -m unittest -q test_bridge_v79_archived_scores test_bridge_v79_score_replay
```

Validation executed **73/73 ordinary Python tests** and **73/73 optimized `python -O` tests** with actual SHA-pinned evidence; this includes the 59 inherited V7.7/V7.8 tests and 14 new source/weight/numeric-adversarial tests. The audit verifies all original model and source digests, each 1700-FP32-parameter Head file, actual 827×2 saved logits, full NumPy class parity, 12 × 420 update/source schedules, old frozen input integrity and all resulting accuracy/EM/F1a. It does **not** independently rerun SGD/Adam updates, authenticate the upstream model issuer, or prove historical inference on a hardware target. Full candidate files are private run outputs, **not** silently promoted to Git models.

For original genuine 97D hidden-state Cell differentiation and full latency claims, the next hard dependency is still exact Granite97/tokenizer/TokenBank bytes, native model-owner authorization and prospectively unseen source-group generalization. Remain `SHADOW_ONLY`, `DENY_ALL`, `NO_MODEL_PROMOTION`, `NO_MAIN_MERGE`.
