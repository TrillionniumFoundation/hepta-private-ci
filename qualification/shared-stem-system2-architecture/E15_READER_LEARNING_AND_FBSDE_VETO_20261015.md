# E15: Original-Reader Answer Signal / Tiny Cell Head Learning — Research Only

**2026-10-15 • DRAFT / SHADOW / DENY_ALL**. Branch off **#2178 E14** at the pinned source HEAD `accc43e06cb2a860eecaf15aee93a1be408d2499`. Do **not** modify the original MultiRC #2080/#2167 owner branches, model selection, live NDU, native Worker, CAS, Q24/Q32 wire, original permission/final-use, existing CI acceptance, or `main`.

## Why this experiment is discriminating

E14 used authentic human MultiRC candidate labels for four passages and observed **15/33** correct from its expensive nonlinear FBSDE route, the same as a cheaper one-map route, with worse Brier. The original four pretrained ModernBERT Reader arms are source-pinned to **GitHub Actions artifact 11946621518**, SHA256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.

In the EXACT original frozen logits, the `conditioned` Reader has **4/8 questions whose authentic alternatives have literally identical predicted positive probabilities**; all **8/8** have an answer-conditioned posterior span at most `0.001`. A `no_query` Reader has eight exact within-question ties; original `mean_pool_query_fused` and `no_evidence` show noticeably different (but not necessarily useful) answer variation. A tiny numerical variation is not semantic grounding, and an exact constant does not establish input truth. Without a validated task value/sufficient-evidence Reader, no complex stochastic solve can claim a demonstrated net task gain.

### Label-free hard constraint

`answer_signal_gate` computes only source-scoped, per-question pretrained posteriors, never actual human labels. It emits **`system2_full_fbsde_admitted=false`** on this registered study and never issues a positive grant. The 0.001 is the existing fixed, **descriptive** source threshold, not a post hoc correctness predictor. Small spread can coexist with a useful ranking, so it is **NOT** a theorem that the Reader cannot reason; it simply cannot certify semantic adequacy or justify paying for a production System 2.

### E15 actual small-Head learning experiment

This study carries out real **CPU full-batch parameter SGD**, not dummy training, on the **original four pretrained Reader logits**. The original pretrained models are NOT re-forwarded in E15; their historical work is reused and distinguished from the actual CPU learning cost. Two narrowly scoped trainable Cell readouts are frozen before any held-original-human label access:

| E15 arm | Actual parameters | Inputs | Training |
| --- | ---: | --- | --- |
| `learned_linear_5` | 5 | intercept + four original frozen Reader logit differences | 48 full-batch SGD Brier steps |
| `learned_gated_3` | 3 | sigmoid gate for convex mixture conditioned/mean-pool; intercept + two original within-question centered answer signals | same 48 Brier SGD steps |

The gate can interpolate existing evidence but **cannot synthesize absent semantic information**. Both train with lr `0.5`, L2 `0.001` for non-bias weights, zero initialization, train-only groups, and deterministic case order. Compare them against all four original unchanged Readers; do not claim parameter-, activation-, or model-training-budget parity just because they share 48 steps. Cost reports cover actual E15 trainer and held readout CPU; pretrained Encoder/Reader work is archived historical work, and a full online TCO including independent score/signer is still unknown.

## Source-group separation, strict sequencing

Original public source: `aps/super_glue` MultiRC pinned revision `4e14482c58d790d467ecfb29b6790e1917bf8756`, validation parquet SHA256 `5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada`. These existing validation passages are **retrospectively cross-fitted**, NOT fresh independent chronological future windows; 33 correlated alternatives correspond to only **4 distinct original passages / 8 questions**.

1. Material owner separately downloads ORIGINAL validation Parquet, recovers exactly 33 original labels using the E14 candidate-ID reconstruction, and for each of **four leave-one-passage-out (LOPO) folds** writes an exclusive, source-sealed input containing **only other three groups' training labels**. It does not publish held truth in a fold's input.
2. Each isolated training job receives one fold-only training-label artifact, the historical source-locked pretrained prediction archive and nothing from the original validation parquet. It trains both Heads and writes create-only held predictions, weights, paid CPU counters, scope and fixed-revision digests. No zeroed fees or synthetic model inference.
3. Only after all eight profile×fold sealed predictions are uploaded, an independent read-only scorer re-downloads original human Parquet and exact model archive, recomputes held candidate/source/answer IDs and historical four-Reader accuracy/Brier. It independently **re-fits both SGD Heads** from three train-source groups using a separate numeric implementation and rejects weight, prediction, training-label digest, coverage or cost corruption. Held labels do not enter a fold's fit.
4. Score reports candidate-level and each **passage-group's** accuracy/Brier, the original conditioned answer-tie census, training/inference CPU, all negative results and hard production nonadmission.

This is **process/job boundary isolation**, not independently authenticated/cryptographic dataset-owner isolation; the publicly retrievable original labels remain accessible outside this controlled workflow. Running LOPO on four selected passages is severely underpowered, potentially selected by earlier research, and may suffer source-family contamination. Therefore even a favorable result is **exploratory**, does **not** prove causal new-task learning and cannot select the Head or System2.

## Tests and genuine-source limits

Standalone source tests call the unchanged real ZIP and run physical 48-step CPU training in all four folds, but use **explicit synthetic labels for algorithm/fault testing only**. Never report their fake-label scores as natural human-label performance. These tests check original source SHA, loss of source group, train-label leak, 3 vs 5 real parameter geometry, independent SGD replay, unsupported Model promotion, original read allowlist, signed-byte receipt mutation, fake actual timers, and create-only output. Run **normal and `python -O`**; exact hosted source-HEAD and synthetic-merge jobs must complete independently before a hosted pass claim.

A NEW actual-original-human result is valid only after the independent scorer has consumed all four sealed fold predictions, verified the original human-source SHA, replayed every real fit and reproduced every archived Reader control. Reporting 33 examples as 33 independent experiments, treating an in-sample fold as prospective future data, or invoking a full FBSDE because a tiny Head fit runs are expressly forbidden.

## Next real GO gate (not satisfied by E15 alone)

**P0 Reader:** Enough evidence vs no evidence, question-only, native-answer supervision and original-vs-altered-premise semantics on **new source families and at least three independently observed future generations**, with raw original model reforward integrity (#2167) and revised training (#2080).

**P1 shared Encoder:** physically matched 421M shared and replicated controls, Granite/mmBERT/EmbeddingGemma2 real-multimodal, 64/256/1024/4096 Head fan-out, exact feature ownership, revocation, CAS, and target-host p95/p99/RSS.

**P3/P4/P5 System 2:** Only after Reader adequacy, compare equal input and complete paid compute/Verifier/Head-training cost vs no-search, cheap exact Bellman, learned Critic, fixed tree, direct BSDE and fully audited coupled FBSDE. Apply true whole-tree boundary and martingale checks, not local residual or correct-leaf shortcuts. External independent task outcomes, no-change, old-task retention, OOD, identifiability, and actual negative controls govern any knowledge distillation.

**Final selection:** unchanged objective/owner, independent evaluator, original authorized model/Reader, three real future windows, hardware, correctness, permission/revocation/unlearning and exact-head plus prospective-merge `blocking-ci`; never activate on this source.

`model_selected=false`, `system2_full_fbsde_admitted=false`, `natural_task_System2_gain_established=false`, `production_accepted=false`, `DENY_ALL`.
