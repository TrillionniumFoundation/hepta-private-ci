# E16 — Source-bound MultiRC answer-centered Head vs E15 LOPO (research only)

**2026-10-15 — DRAFT / SHADOW / DENY_ALL.** This is a child of [#2195](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2195) at its immutable E15 source HEAD `d4d71baa8c00821fe385c1a47ed7b68b4255ad6e`. It does not rewrite #2195 or the parallel original answer-training #2080 / cold re-forward #2167 branches, and does not change product NDU, Neuron, Worker, Q24/Q32, selected model, original source/authorities, FinalUse, CAS, Evidence WAL, `blocking-ci`, or `main`.

## Why E16 must run before more FBSDE

The historical **real pretrained ModernBERT with four trained frozen Readers** artifact [11946621518](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38663684650/artifacts/11946621518) contains precisely 4 MultiRC validation passage groups, 8 original questions and 33 genuinely observed candidate answers. This exact artifact ZIP has SHA-256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.

- Conditioned Reader is almost invariant among alternative answers to the same question: within-question positive probability span <=0.001 in **all 8 questions**; exactly zero for 4.
- The **no-query** Reader outputs are completely invariant to candidate answers *within* each question in the observed original archive. That column has no answer-discriminating signal if used alone.
- Mean-pool Query and No-evidence do show varying probabilities among the true candidate answer alternatives, but mere variation does NOT prove prediction relevance, semantic understanding, or causal task gain.
- On these very same archived 33 original human labels, [E14 #2178](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2178) found that the additional nonlinear stochastic System 2/FBSDE routing changed some outputs yet brought **no accuracy gain** over a cheap route and a worse Brier value. The original E14 `NO_GO` remains binding.

## Fixed alternative to E15

E15 fits a `learned_linear_5` Head on raw four Reader margins and a `learned_gated_3` Head on two centered Reader differences. E16 introduces **two new five-parameter** heads under the same 48 full-batch SGD steps, Brier objective, learning rate 0.5, non-bias L2=0.001, exact original four-passage heldout split and frozen original logits:

1. `centered_raw_5` — intercept + question-centered Conditioned, Mean-pool, No-evidence margins, plus one deterministic Mean-pool × No-evidence interaction. This replaces an exactly answer-invariant No-query column with a fixed nonlinearity. Same 5 *trainable* scalars as E15 raw linear (not necessarily same feature FLOPs).
2. `centered_scaled_5` — exact same five trainable scalars, but the four non-bias inputs are divided by bounded per-coordinate max-absolute scales **fitted only on the three TRAIN passage groups**. The scale floor is frozen at 1e-5, not tuned on actual held human labels. This tests whether the very small original answer-sensitive numeric range prevents useful SGD updates; it may just amplify model noise and induce negative transfer.

Question means require access to the full **unlabeled authentic candidate slate of each original question**. Held passage question/answer *texts and already frozen logits* are allowed at inference; held human truth is never used to fit means or normalization. The study is transductive on permitted unlabeled candidate structures, not a general streaming inference proof. No label-based source passage routing, threshold search or post-outcome architecture selection.

## Original-human outcome separation

The dedicated Actions workflow must independently run source-HEAD and synthetic-merge profiles:

- **Material owner**: opens original pinned pretrained ZIP and original validation MultiRC parquet (SHA-256 `5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada`) and generates four E15-compatible **train-only** label artifacts. Each fold excludes one complete original passage's labels. These are publicly available upstream human labels, not independently re-annotated or a privacy guarantee.
- **Blind worker**: separate job per fold; downloads only its own three-passage label artifact and original frozen pre-score Reader logits; physically fits both five-parameter models; seals candidate weights, train-only scaling, held predictions and observed Head CPU. It never downloads validation parquet or human held labels. ZIP inventory is restricted by inherited E14 source reader and rejects label-bearing original post-score entries.
- **Independent scorer**: runs only after **all four folds** have sealed their predictions; downloads original source and true human labels; independently recomputes the complete E16 train-only features, normalizers, SGD gradients and every held probability, and rechecks the *original* four Reader's 33/33 metric inventory before comparing E16 with two mathematically replayed E15 algorithms. A stand-alone reproduced E15 training algorithm is **not** misrepresented as a passing E15 hosted artifact.

The complete Reader/Encoder original model work is historical and only amortized as a reused frozen source. E16 genuinely pays all new Head training/inference CPU plus an independent verifier in its research workflow; it **does not** obtain full end-to-end online server cost, per-request p99, energy or signed target-host performance. Any source-hash/manifests are artifact provenance, not independent human-label or model-origin cryptographic signatures.

## Local executable evidence (not human-label quality)

Original ZIP is physically loaded, with **zero new pretrained forward calls**. With explicitly ***synthetic*** labels solely for algorithm/isolated fold contract tests:

```
export PYTHONPATH=qualification/shared-stem-system2-architecture
export HEPTA_E16_ARCHIVE=/approved/immutable-11946621518.zip
python -W error::ResourceWarning -m unittest discover \
  -s qualification/shared-stem-system2-architecture -p 'test_e16_*.py' -v
python -O -W error::ResourceWarning -m unittest discover \
  -s qualification/shared-stem-system2-architecture -p 'test_e16_*.py' -v
```

The first frozen source executes 22 original-ZIP-backed tests per interpreter: 4/4 actual held-out SGD folds, exact independent numeric replay, train-only scale exclusion, original ZIP pre-score inventory, correct 8-question and 33-candidate coverage, deliberate falsification of weights, predictions, source, fold, scale, authority, hash, and missing outputs. Unlike a smoke test, synthetic fold fitting actually changes weights; **it is NOT original-human task gain.** The source-HEAD and synthetic-merge hosted jobs still have to complete separately before any green claim.

## Strict admission posture

Scores are computed per authentic candidate, with per-*passage* groups retained (four independent-looking passage units are insufficient for confident population inference). Keep negative, null and missing results; do not select a winner because of one exploratory score. Exact generalization to three independent future observation windows and multiple source families, genuine multi-hop semantic/citation success, matched Reader/Decoder sufficiency, negative transfer, full model/optimizer/verification costs, original signatures and product release are **not** established. Larger nonlinear FBSDE solves stay disallowed by the inherited E14/E15 System 2 gates.

**Final acceptance:** `natural_future_task_gain=false`, `production_accepted=false`, `source_only_candidate=true`, `system2_full_fbsde_admitted=false`, `model_selected=false`, `DENY_ALL`. Keep Draft. Do not auto-merge, deploy, or bypass existing owner and blocking CI gates.
