# V7.8: Authentic MultiRC labels, frozen split-Cell training contract, and cheap original-logit controls

**Scope: `hepta-private-ci`, child research branch of draft PR #2383.**
**2026-10-15. RESEARCH / SHADOW_ONLY / DENY_ALL / NO_MAIN_MERGE / NO_CELL_PROMOTION.**

This increments the V7.7 physical frozen BridgeReader + 1,700-parameter gated Head design. Historical V6 learning had significant *negative transfer* on the exposed natural MultiRC internal panel; training more Heads on fabricated latent labels would not establish human-task learnability. This increment separates (A) a **completed real-label, genuinely pretrained historical-logit control**, and (B) an **implemented, but pretrained-feature-blocked** original-natural-label split-Head training path.

## Historical material and source cardinality

The original archived V6 binary `hepta_bridge_learning_v6_20261015.zip` (20,928,479 bytes; SHA256 `197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a`) is **present** in the user Library and was read on this host. It includes three original, genuinely pretrained Granite-derived BridgeReader warmup checkpoints and 827 public MultiRC natural **internal-tune candidates** (194 questions, 16 *source paragraphs*), together with their authentic frozen Reader positive probabilities. These are human labels and actual saved pretrained outputs. These 16 paragraphs were already exposed in historical V4/V6 development: splitting them again does **not** create new independent/future data.

The same archived evidence binds the separate, complete natural **TRAIN** roster (3,909 human-label candidates / 64 paragraphs); old Binding TRAIN was 128 cases / 64 source hashes. Original natural internal-tune has 827 cases / 16 disjoint source hashes. All three repeat the same source set; they do not provide 3x independent examples.

## A. Completed real human-label 2-parameter calibration (negative control)

`bridge_v78_original_calibration.py` performs the following **genuine PyTorch CPU autograd + Adam** experiment, using only historically saved pretrained positive probabilities and human MultiRC labels:

1. Freeze all original Reader checkpoints; no Encoder/Reader forward or refitting.
2. Deterministically split **16 paragraph source hashes into 4 folds, exactly 4 paragraphs per fold**, with *the same assignment across all 3 seeds*.
3. Within each fold, fit 2 scalars `s,b` for 240 Adam steps on the OTHER **12 paragraph groups** using logit BCE of `sigmoid(exp(s)*logit(clamp(original_p)) + b)`. Do not use the 4 held groups to select optimizer, hyperparameters or threshold.
4. Independently compare held-group original raw `p>0.5`, always-positive (0 trained parameters), **threshold chosen from train groups only**, and the new two-scalar calibrator. Concatenate the four held groups in original row order; rescore complete 827 candidates and 194 original question groups.
5. No model is selected/promoted, and this panel was previously exposed. All 12 actual calibrator fits and their CPU times are recorded. Data is grouped by paragraph, not by the 827 answer rows.

### Actual executed three-seed aggregate (source-fold out-of-fold)

| Strategy | Mean F1a | Mean question EM | Mean accuracy |
| --- | ---: | ---: | ---: |
| Frozen real pretrained V6 warmup logits | **0.538529** | 0.049828 | 0.476018 |
| Always-positive zero-training control | **0.622814** | 0.000000 | 0.452237 |
| Train-fold selected scalar threshold | **0.601130** | 0.012027 | 0.445385 |
| **Real-label** two-parameter Adam calibration | **0.297635** | 0.030928 | 0.513503 |

Each fold/seed is source-disjoint *within the previously exposed internal panel*. The two-scalar task calibration actually underperforms freezing by **−0.240894 F1a** (3-seed means), and the cheap always-positive strategy remains highest F1a here. The calibrator improves accuracy relative to frozen raw predictions; these arms are NOT Pareto-ranked on all metrics. This negative result is a warning against treating parameter-light new Heads as automatic reasoning transfer. It is NOT an estimate of future/prospective performance or a randomized causal trial.

`bridge_v78_calibration_review.py` is a **separate standard-library-only reviewer**, executed via `python -S`: it independently opens SHA-locked original V6 bytes, reconstructs exact group folds, train-only threshold choices, all 827 × 3 × 4 out-of-fold decisions from original probabilities and sealed scalar coefficients, matches per-arm prediction SHA256, and recomputes F1a/EM/accuracy. It does not import Torch/NumPy, re-run optimizer updates, or authenticate an independent issuer. It rejects corrupted source files, reordered groups, falsified calibrator parameters, fake metrics and authority flags.

Original actual experimental report: `V78_ORIGINAL_LOGIT_SOURCE_HELDOUT_20261015.json`; distinct independent reviewer result: `V78_INDEPENDENT_LOGIT_REVIEW_20261015.json`. No raw passage text, case-level logits, training labels or pretrained weights are committed to Git.

## B. Full authentic Natural-label new Head path, implemented but not physically qualified

`bridge_v78_original_natural_head.py` extends V7.7's **single frozen original V6 BridgeReader object** with true-label admission and two matched-cost *sampler* arms, each using an independent **1,700-scalar gated Head**. The original V6 Reader remains frozen, is physically shared and used identically for both arms. Head input is the true V6 *97D pre-Head frozen feature + original logits*, never answer indices/labels.

- `roster()` opens the immutable original V6 ZIP and checks the complete ordered 3,909 natural TRAIN human-label identities, the 827 internal-tune examples, and the 128 old Binding cases. The 64/16/64 source sets must be distinct, with all 3 exact original warmup model SHAs present. **Only this byte-verified ZIP is permitted to supply training labels**. There is no free caller-supplied labels vector.
- `validate_train_cache()` binds the complete row/source roster and its content-hashed frozen Reader 97D feature tensor + logits to the correct original V6 seed, rejecting swapped/missing cases, altered latent bytes and old-task/tune-source leakage. The cache's self-described digest does not independently prove genuine Encoder origin; that assertion belongs **only to the physical model-qualified CLI**.
- `fit_original_human_task()` invokes actual CPU autograd on *only* the new Head parameters. Both `row_uniform` (V7.7 baseline) and `source_balanced` use exactly 420 Adam steps, 16 examples/step, the same Head initialization and same frozen latent cache. The second sampler selects **16 distinct original source paragraphs per step**, drawing one TRAIN candidate from each. It is a **different training-data distribution**, so fixed optimizer steps do not imply equal training FLOPs or mathematical treatment equality. Both actual sample exposures and measured optimizer state and CPU are logged. No continued updates to any frozen Reader weight are permitted.
- `score_preexposed_tune()` scores only **after** both fixed-budget Heads are trained, and compares frozen old logits, learned 1,700-param new Head, and always-positive, on the original 16 already-exposed natural internal paragraphs. No tuning data enters optimizer/early stopping/model selection.
- `run_v78_original_natural_head.py` requires the exact V4/V5/V6 byte and ancestry preflight, original Granite97 revision `835ad14087e140460703cf0fae09f97d469d65c2` and model/tokenizer/preprocessing exact file bytes, plus the true TokenBank or genuinely *new* physically measured reencoding. It checks original 128 Binding TRAIN predictions against original V6 historical probabilities (≤0.001, zero class flips) and independent V7.3 Torch-free NumPy logits (≤0.0015) **before any optimizer step**. For each seed it trains **two** 1,700-scalar Heads from the **same** actual preencoded 3,909-row physical cache, then evaluates both only after all weights freeze. The original Binding route still returns the frozen parent outputs bitwise identically.

**The original 97M Granite model and V5 cached original token-feature tensors were NOT available in this authoring container. Consequently this real-token end-to-end six-Head experiment was NOT run, and no improved MultiRC generalization or old-task semantic retention can be claimed.** The true-label Head function was exercised with the *real V6 frozen pretrained Reader weights and the real 3,909 source labels but explicitly SYNTHETIC cached 97D tensors*. Those tests prove row/source/optimizer ownership contracts only; they are **not** authentic pretrained-feature learning outcomes.

### Actual local tests

- 59/59 Python tests PASS, 59/59 Python `-O` tests PASS when the original V6 archive is mounted. Includes the prior V7.7's 36 regressions and 23 V7.8 tests. Both runs used three authentic archived V6 warmup checkpoint tensors.
- `python -S bridge_v78_calibration_review.py`: successful independent reconstruction; two executions of its sanitized JSON output had exactly the same SHA256.
- `compileall` on all new Python modules PASS. Wrong source/seed, fake original ZIP, mutated tensor bytes, duplicated row IDs, altered calibration folds/results, unknown sampler arms, fake promotion flags and simulated missing Granite material all rejected.
- The unit-test injected latents are explicitly marked **synthetic**, regardless of whether their target labels come from the original human publisher. A mocked missing-material test checks the CLI fail-closed path without claiming to have executed the original physical pretrained model loader.

### Reproduce, with the exact archives

```bash
cd qualification/stem-cell-v1
export HEPTA_ORIGINAL_V6_ZIP=/sealed/hepta_bridge_learning_v6_20261015.zip
python -m unittest -q test_bridge_split_cell_v77 test_bridge_split_v77_review \
  test_bridge_v78_real_labels test_bridge_v78_calibration
python -O -m unittest -q test_bridge_split_cell_v77 test_bridge_split_v77_review \
  test_bridge_v78_real_labels test_bridge_v78_calibration

# Real historical original Human-label low-cost control, no Encoder downloads:
python bridge_v78_original_calibration.py \
  --original-v6-zip "$HEPTA_ORIGINAL_V6_ZIP" \
  --output /sealed/new-private-v78-calibration.json
python -S bridge_v78_calibration_review.py \
  --original "$HEPTA_ORIGINAL_V6_ZIP" \
  --result /sealed/new-private-v78-calibration.json \
  --review /sealed/new-private-v78-independent-review.json
```

For full actual prepaid original-model new-Head fitting **only if** the true Granite model is available:

```bash
python run_v78_original_natural_head.py \
  --v4 /sealed/hepta_token_evidence_ndu_v4_20261015.zip \
  --v5 /sealed/hepta_binding_learning_v5_20261015.zip \
  --v6 "$HEPTA_ORIGINAL_V6_ZIP" \
  --snapshot /sealed/pinned-real-granite97 \
  --output /sealed/v78-new-natural-cells
```

Optional `--cache /sealed/original-v5-TokenBank` is permitted **only** when both actual cache files match the original V5 SHA. Missing cache triggers measured new physical source reencoding, not a historical-reuse claim. If no genuine original checkpoint and correct tensors exist, **fail closed before creating the output path**. `READY` only means eligible research execution, not a model production grant.

### Remaining scientific gates

Actual six-arm original-pretrained human-label completion, peer-independent image/audio/video frontends, 64–4096 physical Head CPU/GPU RSS+p99, independent source-disjoint **future** labels, matched total lifecycle against full-Reader updates, independent native NDU causal gain and all policy/authority owners remain unqualified. No equivalent 10T/100T generalized model, innate multimodal decoder, or direct native code execution right is inferred. **Preserve `main` and all production actions at DENY_ALL.**
