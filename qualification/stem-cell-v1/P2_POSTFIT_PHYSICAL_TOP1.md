# P2 true physical postfit Top-1: equal-parameter cost reality

**Research-only / DENY_ALL / NOT production.** This is a direct child of #2180 and uses **unchanged trained weights and frozen predictions** of the existing exact P2 five-arm study. It does not change the model loader, source corpus, Head training, split decision, owner permissions, NDU, production Cell Split or `main`. Its sole scientific purpose is to distinguish a routing *decision* from physically sparse execution and quantify actual work **without falsely treating parameter parity as compute parity**.

## Precise flaw in the prior comparison

The original P2 `TwoHeads.forward` computes logits for both 7,434-parameter Heads for *every* sample. Its `fixed_two_cell` / `adaptive_train_only` router subsequently **selects one** of those already-computed outputs. Thus a prediction can be expert-specific **without having saved any actual Head-row compute**. Earlier P2 outputs establish equality of 14,868 resident parameters, matched sample exposures and a limited descriptive quality comparison; they do not establish physical Top-1 savings, equal active FLOPs, general reasoning, or future transfer.

This continuation restores the original trained FP32 tensor bytes for all five arms, numerically replays original logits, and uses an explicit grouped subset computation that evaluates **only the chosen expert** for fixed/adaptive routes. It does **not retrain** or cherry-pick weights. Every task and answer remains the original 96 unchanged, label-blind calibration/test cases. No original heldout labels are loaded before the postfit physical predictions and their new receipt are sealed.

## Arm-by-arm work semantics

The following are **dense linear multiply–accumulate (MAC) terms**, not full FLOPs: matrix products include 384×8 down, 64×8 gate, 8×384 up, 384×2 readout = **7,424 MAC/sample/expert**. Sigmoid, SiLU, biases, routing, memory movement, allocator overhead, pretrained Encoder, training and verifier work are not included. The registered rank-16 wide single Head plus its extra affine skip uses **14,848 MAC/sample**.

| Unchanged original trained arm | Dense P2 evaluated Head rows per 96-case batch | Postfit physical active Head rows | Linear MACs dense → postfit |
| --- | ---: | ---: | ---: |
| Frozen two-Head no-change | 192 | 192 | 1,425,408 → 1,425,408 |
| Unrouted equal-parameter two-Head | 192 | 192 | 1,425,408 → 1,425,408 |
| True rank-16 wide single Head | 96 | 96 | 1,425,408 → 1,425,408 |
| Fixed Top-1 Router | 192 | **96** | 1,425,408 → **712,704** |
| Adaptive train-only split | 192 | **96** | 1,425,408 → **712,704** |

`adaptive_train_only` may have declined to split. In that case Top-1 evaluates **only parent Head 0** rather than computing dormant Head 1; the output must still match the original un-split adaptive prediction. Both decisions remain immutable from train-only evidence.

The routed arms have **half the stated dense linear MACs** at fixed resident parameter capacity but **half the active linear compute of the wide single Head**, so this is NOT an equal-compute superiority comparison. Only if a *separately trained, genuinely single-active, equal-exposure/compute Head* baseline is added and prospective task utility is measured can cost-adjusted Cell Split superiority be considered. Two retained Head copies still require resident weight bytes; Top-1 by itself compresses neither weight storage nor shared pretrained Encoder cost.

## Measured execution and independent review

`p2_postfit_sparse_top1.py` performs real CPU Torch `@`/indexing on the selected original Head weights. It executes both the prior dense P2 path and new active-only path in alternating order for 100 full-batch measurements per arm after five warmups, holding the P2 model and 96 source feature rows fixed. Each batch is a **96-row request**, not 96 independent p99 samples. It records raw per-full-batch wall and CPU samples, physical selected Head indices, batch matmul calls, the source identity and complete logits. It does **not** re-measure the expensive original 224 Granite Encoder forwards, load time, all SGD optimizer work, or independent device/energy costs. Timing ratios (especially on tiny Heads) can be negative or environment-specific and must remain visible.

`p2_postfit_sparse_review.py` imports **neither Torch, the original trainer nor the sparse executor**. It independently reuses the original published NumPy P2 five-arm weight decoder / source/label reviewer, re-computes every new output from original FP32 weight bytes and Q24 source vectors, derives each route from the immutable trained cutoff, checks all original 96 source/candidate identities, recomputes all MACs and physical expert-row counters and rejects forged latencies, drifts, extra authority fields and rehashed swapped results. Original human labels are opened **only at independent review after both model observations are sealed**. The reviewer preserves original quality results verbatim and always denies model selection.

### Local three-seed outcome

Three complete mock-Stem CPU mechanism runs on seeds 41/47/53, with 100 dense and 100 postfit batches per registered Head arm, passed independent numerical replay. In these particular local self-timed runs the fixed/adaptive Top-1 median full-batch time ratios were roughly **1.11× to 1.14×**, rather than 2×. This is a **single CPU host, synthetic source features, retrospectively reused original P2 trained toy weights**, not real Granite97, independently measured worker p99, a scientific confidence interval or an established production speedup. The unrouted/frozen/wide cases report **zero saved MACs**, and unfavorable timing observations are retained. The detailed original local summary is stored under `P2_LOCAL_POSTFIT_SPARSE_TOY_20261015.json` with explicit disqualification flags.

### Reproducibility

~~~sh
# Research source-only paired physical tests: actual Torch, no downloaded models
python -m unittest discover -s qualification/stem-cell-v1 \
  -p 'test_p2_postfit_sparse_top1.py' -v
python -O -m unittest discover -s qualification/stem-cell-v1 \
  -p 'test_p2_postfit_sparse_top1.py' -v

# In the existing pinned Granite P2 hosted run, *after* all five original
# original-weight computations and BEFORE any heldout owner labels are opened:
python qualification/stem-cell-v1/p2_postfit_sparse_top1.py \
  --p2-report "$ROOT/predictions-unscored.json" \
  --output "$ROOT/postfit-sparse-unscored.json" --repetitions 100

# Then open the original labels only in a separate independent review step:
python qualification/stem-cell-v1/p2_postfit_sparse_review.py \
  --original-panel "$ROOT/panel.json" \
  --train-material "$ROOT/material/train.json" \
  --blind-material "$ROOT/material/blind.json" \
  --owner-labels "$ROOT/material/owner-labels.json" \
  --p2-report "$ROOT/predictions-unscored.json" \
  --sparse-report "$ROOT/postfit-sparse-unscored.json" \
  --output "$ROOT/postfit-sparse-independent-review.json"
~~~

The CI workflow retains the **sanitized reviewer output and SHA/dependency/job logs only**, never private text, original Q24 representations, trained Head FP32 bytes or full P2 predictions. Any missing, queued, failed or superseded exact-head job is a **blocked real experiment**, not a pretrained success. An offline input/report SHA is an integrity consistency check, **not an independent model-origin signer**.

**Unclosed gates:** real pinned Granite97 full-workflow completion, independent model/source attestation, genuine future-window task utility and old-task retention, matched active-work *trained* single-Head baselines and unmodified source/label owner, full serving-model load + queue + p50/p95/p99/RSS/energy, original `blocking-ci`, NDU/FinalUse and authorized Cell Split cutover. This PR does not support 10T/100T general capability equivalence, multimodal generation or general FBSDE optimality.
