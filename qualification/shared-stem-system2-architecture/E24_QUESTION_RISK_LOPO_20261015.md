# E24 — Matched-five-parameter MultiRC question-risk vs candidate Brier

Date: 2026-10-15. **DRAFT / SHADOW / DENY_ALL.** Child of E23 #2318 on frozen source
`78952e0cc6167559466a8b1834565eaccb2108f7`. No production Reader,
Neuron/CNS/NDU/FinalUse/Q24/Q32/CAS/WAL changes; no `main` merge.

## The scientific decision problem

E16 learned a real 5-scalar Head (four source-held 48-step SGD trainings), with
20/33 original human-labeled MultiRC candidate answers but **0/8 entire original
questions**. E23 independently reproduced those weights from genuine original
train-only human labels and verified both source-head / synthetic-merge original
E15 and E16 score receipts. The existing nonlinear FBSDE E12–E14 route likewise
has **no cost-adjusted natural-question efficacy**. Instead of increasing FBSDE
steps, this child compares candidate Brier against question-group risk under
identical frozen pretrained Reader source and five-parameter capacity.

**Original source:** publicly pretrained ModernBERT + four frozen trained Reader
original hosted archive `11946621518`, SHA-256
`1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`;
4 actual human-annotated MultiRC passages, 8 source questions, 33 genuine
binary candidate alternatives. This is a **single historically exposed family**.
Four E15 and four E16 label-owner artifacts both derive from the **same** pinned
human validation Parquet SHA-256
`5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada`.
The two uploads are NOT two independent human raters. Each training fold
exposes labels from **three** passages only. The held labels are opened only
later by the independent scorer; the original source itself is publicly obtainable,
so this is an auditable process boundary rather than cryptographic secrecy.

## Matched optimization protocol

Four arms, exactly **5 physically trained scalar parameters**, 48 full-batch
SGD updates, learning rate 0.5, non-bias L2 0.001, same train-only four-feature
normalizer, same three source-held passages, frozen original model outputs,
zero new pretrained Encoder forwards. Center the four original Reader-margins
within each original complete candidate slate without using answers or labels;
features are conditioned / mean-pool / no-evidence centered margins and the
fixed product of mean-pool and no-evidence centered margins, plus intercept.

- **Original E16 control:** mean of candidate Brier `(p-y)^2` across all training
  candidates, exactly replayed against E16 independent original human results.
- **E24 group-risk:** equal-weight six original training questions. For question
  `q` with `m_q` candidates and `tau > 0`, minimize

  `L_q = tau * log( (1/m_q) * sum_i exp(((p_i-y_i)^2)/tau) )`.

  The derivative gives the hardest wrong candidates the greatest gradient,
  instead of letting larger candidate slates dominate by sheer row count.
  Fixed exploratory temperature grid: `tau ∈ {0.01, 0.10, 0.50}`; **this grid
  is tested after historical source family and many previous labels/results
  were already examined. It is not preregistered prospective hypothesis
  evidence. Do not select a production winner based on this sweep.**

The task requires the **complete unlabelled candidate slate** for each question.
Its buffering, original pretrained Encoder, Reader, tokenizer, extraction,
Head training, scoring, independent review, transport and energy are NOT
covered by the local Head-only CPU samples. The same number of parameters
and SGD steps does **not** imply matched FLOPs, energy or end-to-end cost.

## Independently reproduced local original-human observations

| Arm | Original candidate correct | Complete questions | Complete passages | Two-class Brier |
| --- | ---: | ---: | ---: | ---: |
| E16 5-param scaled Brier | 20/33 | 0/8 | 0/4 | 0.4679101348 |
| Soft-worst tau=0.01 | **21/33** | **2/8** | 0/4 | 0.4774738458 |
| Soft-worst tau=0.10 | 19/33 | 1/8 | 0/4 | 0.4675527211 |
| Soft-worst tau=0.50 | 19/33 | 0/8 | 0/4 | **0.4616769843** |

Both E24 successes at `tau=0.01` belong to **two of four original passages**,
with no passage having both questions correct. Four-source group sign flip vs
E16 `p=1/2` before correction and `p=1` after 3-way Holm correction,
**descriptive only**, not a confirmatory p-value; test-set re-use, model
multiple comparisons and a tiny n=4 prohibit superiority claims.

The apparent whole-question gain comes with **worse Brier calibration** at
tau=0.01. No qualitative future generalization, independent source-family
holdout, multi-modal reasoning, deployment, total service gain or production
Reader promotion is established. Until a source/time-disjoint genuinely new
human-labeled panel with sufficient independent Reader is available, the
correct model-selection decision is **NO_GO / DENY_ALL**.

## Reproducibility and independent provenance

1. `e24_question_risk.py blind` reads **only** the archived pretrained
   pre-score model panel and seals source group/task inventory, no historical
   score member or validation labels.
2. Four separate `train` calls each receive **only** one original SHA-pinned
   E15 `training-fold-i.json` from the historical owner; they perform real
   48-step CPU SGD for all four arms, publish five-scalar weights, source-bound
   held probabilities, and observed physical local CPU; no held label.
3. `e24_independent_review.py` after all four predictions are sealed: loads
   BOTH exact original owner-label sets; independently reopens and checks
   original validation Parquet in hosted CI; recreates all 48 gradient steps
   in a separate numeric implementation (source `math.fsum` vs producer
   incremental sum), full train-only normalizer, all original decisions and
   eight complete questions. Any mismatched weight, prediction, original
   identity, label, CPU record or permission flag **fails closed**.
4. Source-HEAD and prospective synthetic-merge CI are separate. The completed
   checks, original failure logs, material hashes, learning and scoring
   receipts are retained as GitHub Actions artifacts. Inherited `test_*.py`,
   original E7 human scorer, `blocking-ci` and Architecture are **unchanged**.

**Unqualified hard flags:** `production_accepted=false`,
`model_selected=false`, `system2_fbsde_permitted=false`,
`statistical_superiority_or_independent_future_benefit=false`,
`complete_question_task_ready_for_production=false`. Do not auto-merge or
activate any NDU/Model/FinalUse path on this retrospective result.
