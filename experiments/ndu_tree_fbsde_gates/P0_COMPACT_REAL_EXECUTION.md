# P0 physical Granite 97M / mmBERT-small research protocol

**Draft / read-only / DENY_ALL.** This is the missing *actual pretrained* two-model
inference+lightweight learning arm, not four-Stem model selection or a production
Neuron runtime. It reuses the existing real hosted Gemma2/Laya421 cross-sectional
panel *only as a source-and-historical-control reference*. It is explicitly not
three longitudinal future windows, nor natural System2/FBSDE reasoning evidence.

## Frozen sources (before any checkpoint load)

- AG News dataset `szhuggingface/ag_news`, exact dataset commit
  `98c532231d96ae10e176a909192ecac548949288`.
- Train parquet SHA256 `cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5`.
- Calibration/test parquet SHA256 `3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672`.
- Preexisting AG News source-panel SHA256
  `2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4`.
- GitHub Actions #38541658096 original successful physical model archive artifact
  **11886761368**, ZIP SHA256
  `e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d`.
  It contains an immutable val2 source-only-selected cohort (128 rows); the
  exact entire new-source panel SHA256 is
  `8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a`.
  Its labels are stripped from the Encoder execution input and passed only to
  the separate process scorer. Source hashes and local process records are **not
  independent authority or publisher signatures**.
- Existing immutable upstream researcher checkout: `#1775` exact Git commit
  `f8d168a7689eb3624d97c44751791badd069e521`.

## Actual checkpoint arms

| ID | Exact pretrained model revision | Frozen feature readout |
|--|--|--|
| granite97 | `ibm-granite/granite-embedding-97m-multilingual-r2` @ `835ad14087e140460703cf0fae09f97d469d65c2` | CLS, L2 normalization |
| mmbert_small | `jhu-clsp/mmBERT-small` @ `0eb3d056ec1d6333cf4e19b0966dfde342a41a3a` | nonpadding masked mean, L2 normalization |

Only safetensors, no remote arbitrary model code, no `.bin` fallback, CPU, 512
max tokens without silent truncation, exact 384D, nearest-even signed-Q24 shared
features. The head-only learner uses 40 AdamW updates and **identical training
batch indices** for the two 384D competing Encoders, with separate frozen Head,
learned gated residual Head (7,434 parameters, rank 8, 64-wide zero initial
local state) and trained linear control (770 parameters). Frozen and learned
Head initial weights are identical. Calibration-only temperature choice.

The zero Cell state makes this an **output-gating architecture test**, not a
proof of per-Cell homeostatic specialization. All 352 distinct sources each
receive a real physical Encoder forward, reused across the three Head arms;
no invented sharing of a 421M model or 4,096 physical Cells. Distinct labels
are entirely unavailable to the `execute` process for the 64+128 evaluation
rows. Predictions are create-only sealed before independent per-case scoring.

## Evidence and disqualifications

Separate-process numerical scorer requires complete model/Head arm and per-row
source bindings, original/future split, 352 physical forward **reported** count,
all 128 raw observed val2 encoder latency measurements for p99, matching source
bytes and sealed reports. It computes source-disjoint accuracy, Brier and
exploratory paired exact McNemar counts, uncorrected for multiple comparisons.
No work is padded. All real CPU/Head optimization time, pretrained model-load
wall, process-lifetime resource observations and physical file SHA256s are
retained with the task/cohort. A *reported* forward count cannot by itself prove
an independently observed GPU instruction count or authenticated execution.

The separately archived Laya/Gemma scores from #38541658096 are contextual
baselines only: different architecture, Head widths/initialization, training
regimens, model-size and lifecycle cost. **Do not call their side-by-side scores
an equal-resource four-model winner.** The original AG News panel and val2 are
cross-sectional source-disjoint within one *public dataset family*, not future
observation-time generalization. Pretraining overlap and model-origin signer
remain unverified, as do FinalUse, Worker receipts, physical batch queue,
end-to-end 4096 Cell scale, retained old-task outcomes and independent NDU.

Model downloads and external execution require hosted network. The local
runtime can only run *synthetic/mock tests*, which are never accepted as
pretrained observations. The new Action must actually finish on **the exact
current head**, with raw artifacts and failed attempts retained, before any
numbers may be published. `blocking-ci`, Architecture Convergence and
independent Evaluator remain separate, nonwaivable.

Local offline test:

```sh
PYTHONPATH=experiments/ndu_tree_fbsde_gates \
 python -m unittest discover -s experiments/ndu_tree_fbsde_gates \
 -p 'test_p0_compact_paired.py' -v
```

## Source-identical historical four-model context

The scorer optionally consumes the **exact same frozen historical ZIP**,
independently invokes the existing `real_model_artifact_replay` verifier,
checks every original Gemma/Laya probability against the 128 val2 cases and
independent local labels, and records all Granite/mmBERT-vs-Laya/Gemma paired
correctness disagreements. This enables descriptive *four-backbone* quality
replay without suggesting equal Head structure, calibration budget, total
compute, source signing or future-time model efficacy. No cross-model winner is
selected and `four_model_equal_resource_winner_eligible=false`.
