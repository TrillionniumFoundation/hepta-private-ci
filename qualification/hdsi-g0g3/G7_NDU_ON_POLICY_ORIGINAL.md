# G7 — Original on-policy retrieval allocation: STOP / BM25 / paid RRF

**RESEARCH_ONLY · DRAFT · SHADOW_ONLY · HOLD_NO_GO · DENY_ALL.** No model, Cell, topology, or FinalUse promotion; no `main` integration. This is an additive child of G6 [#2637](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2637), which itself depends on G5 [#2627](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2627) and G0–G3 [#2617](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2617).

## Task and operator

The experiment does **not** solve a natural-language answer task and is **not** a nonlinear/stochastic FBSDE proof. It is a tightly constrained, finite-horizon, deterministic **Episode-NDU special case**: select `STOP` (abstain after the BM25 scan), `BM25` (submit the top five cheap evidence snippets), or `RERANK` (pay to run a frozen, original pre-trained MiniLM on the submitted query and the BM25 top-64 candidate union). It may not produce an external effect.

One immutable source/root snapshot contains 24 questions. The episode controls at most 8 paid RRF questions per root and must remain in the original source boundary. Shared BM25 evidence preparation is **charged to every route**, including STOP; it is mathematically omitted from marginal action comparison because it is common to all actions. RRF is charged once in the registered reward (not twice):

```
Hit@5:                 +10000 preference units
Miss after submission: -3000 preference units
STOP:                       0 incremental reward
RERANK additional cost:  -900 preference units per selected question
```

These units are **declared experimental preferences**. They are not dollars, real calibrated energy, or sufficient evidence of optimal personalized utility. The registered linear profile, zero diffusion, freeze-the-preference assumption, full known 24-question episode, and fixed terminal utility are a limited NDU instance; no new mathematical subject class or biological equivalence is established. A standard, independently implemented forward finite-budget Bellman knapsack **must** produce identical choices to the backward NDU implementation for every original episode. Any mismatch rejects the experiment.

## Genuine model / source custody

- Original BF16 MiniLM six-layer checkpoint and tokenizer are loaded **only after verifying complete original SHA-256**; official Hugging Face model/tokenizer numerical parity is not claimed.
- Original `locomo.json` publisher archive is byte-verified against SHA `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`. The source-owner job creates a *label-free HELD* packet and removes the raw publisher QA before model-worker handoff. Training outcomes may be used only for the six original TRAIN conversation roots; none of the four HELD human evidence labels may enter the planner, Encoder, value profile or training stage.
- Training computes **real** original frozen MiniLM features on 6 × (256 source docs + 24 questions) = **1,680 physical six-layer forwards**, 108 mini-batches. Both BM25 and frozen cosine/RRF TRAIN hit/miss observations enter a three-band (observable top-document lexical overlap) Laplace-smoothed value profile. The entire TRAIN 144-question record is SHA-bound and source-grouped (only 55/144 training questions have reference support within the original 256-doc subset).
- Route is SHA-sealed **before** any HELD neural inference. The independent model-runner takes a new original model load and physically computes frozen MiniLM only on the NDU-selected questions and a separately executed fixed-eight-question-per-root comparator. There is **no free sharing of GPU/CPU feature forwards between these two paid arms**, even when the same question or source appears. Ordinary Bellman/NDU parity reuses one output *only as a mathematical identity*, never as a separately charged physical model experiment.
- The model-free independent original human reviewer does **not import the G7 producer, G7 trainer or G7 policy**. It reopens original publisher data, independently reconstructs the 10 source roots and complete BM25 ranking for all 96 HELD questions, checks all Train outcomes against original human TRAIN evidence, independently reruns ordinary forward Bellman, audits action selection against the earlier SHA-sealed plan and physically paid encoder batch/sequence/token counters, and scores original HELD human evidence.
- Historical and publicly labeled LoCoMo questions are **not prospective new data**. Seals and GH Actions timestamps do not constitute independent hardware attestation or human evaluator signature.

## Actually executed original local CPU experiment (2026-10-17)

- Exact historical six TRAIN roots / four HELD roots, 24 HELD questions each (96 original questions). No cross-publisher or future-time cohort.
- Original TRAIN model: **1,680** actually completed six-layer forward sequences, **108** physical mini-batches; research-host self-reported CPU/wall **19.54/19.55 seconds**.
- Original HELD selected-model phase: **1,342** additional complete six-layer forward sequences, **89** physical mini-batches; research-host self-reported CPU/wall **26.60/26.62 seconds**. The original 58,728 full-corpus BM25 question/document pair scores remain separately counted, common to all arms.
- NDU physically selected just **3 RRF** questions and made **195** model sequence forwards (three independently scoped batches of 65; 15 model batches). The separately physically paid fixed-eight comparator selected **32 RRF** questions and made **1,147** model sequence forwards. Their combined 1,342 agrees exactly with model-runner counters. Within this pilot, the *first complete NDU training+inference forward budget* is **1,875 sequences** (1680+195), **more** than fixed-eight's 1,147 inference sequences without profile training. This is an honest count of actual model work, not a cross-host measured service TCO/dollar cost.

### Independent original human evidence results

| Policy | Original Hit@5 / 96 | Actually paid RRF questions | STOP decisions | Experimental observed net preference units |
| --- | ---: | ---: | ---: | ---: |
| BM25-only | **48** | 0 | 0 | 336,000 |
| Fixed-eight-per-root RRF/BM25 | **48** | 32 | 0 | 307,200 |
| Independent ordinary Bellman | **26** | 3 | 54 | 209,300 |
| Deterministic NDU | **26** | 3 | 54 | 209,300 |

`STOP` is an *abstention*, **not** a correct answer. The NDU policy rescues only 1 original evidence-hit case while harming 23 compared with BM25, mostly through excessive learned abstention under a distribution shift between sparse TRAIN supports and the full held-out evidence corpus. Fixed-eight yields 2 rescues and 2 harms, with additional inference cost. This is a **NO-GO**, not an NDU improvement. Only **four correlated held-out conversation roots** are available; the per-question numbers are descriptive and are not a source-independent causal confidence bound.

All **35 physically paid RRF question executions** (3 NDU + 32 fixed) were compared to the exact original G6 archived full-RRF pretrained model predictions in local review: **35/35 identical Top-10 ranks**. This numerical parity is source/model/profile specific; it does not imply cross-host bitwise parity or official tokenizer parity.

The first independent scorer version rejected the sealed output because its own source-order implementation disagreed with the policy's canonical question-ID sorting. The reviewer was repaired without modifying any prelabel bytes, weight identities, route budgets or model outputs, and then **independent original-human scoring passed**. No historical result was relabeled or used for policy fitting. G7 source/adversarial conformance: **35/35** both ordinary Python 3.13 and `python -O`, and **35/35** under `python -O -S` with original material; optional original-only tests skip cleanly in source-only CI. Byte-identity of source files must be rechecked remotely.

## Irrevocable no-go boundaries

- Learned preference profile/Head benefit is **not** established; `ndu_specific_task_gain_verified=false` and `production_authorized=false` unconditionally.
- Original LoCoMo held questions remain historically exposed; no independent future-source, multi-publisher or longitudinal advantage.
- The NDU solver equals ordinary Bellman under the same fixed linear objective. No claims of FBSDE global uniqueness, stochastic NDU optimization, 10T equivalence, autonomous structural fission/fusion, audio/video generation, self-evolution or external effects.
- CPU time, energy, GPU performance, target-host p95/p99, concurrent 4,096-Cell throughput, state checkpoint WAL/rollback, model-issuer signatures and full lifecycle TCO remain unqualified.
- The full `blocking-ci`, Rust ownership and architecture gates must succeed for exact reviewed source before any code can merge; experimental source or original model success is **not** production promotion.

The next *scientifically meaningful* investment is to improve **source coverage and utility calibration** using genuine later independent sources, then re-run a prospective online, cost-matched `STOP/BM25/RRF` competition. More solver iteration steps, physical Cell Split, or a deeper DAG without those prerequisites would not repair this observed bottleneck.
