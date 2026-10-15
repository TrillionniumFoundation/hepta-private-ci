# P0 real pretrained four-model Reader: original SQuAD answer spans, mechanical counterfactuals, and held-label scoring

**Classification:** SHADOW / RESEARCH / DRAFT / DENY_ALL. No model selection, production invocation, new effect authority, neuron state activation, NDU, Q24 native journal, or main/CURRENT change.

## Why this exact experiment

Prior original E1 already has a real pretrained CPU path for three different frozen Encoder checkpoints, but on English AG News classification, and prior Laya421 is an archival comparison with different host/runtime/prompt costs. The source branch of PR #2075 has source-locked P0–P5 *observational* gates, not live model or Reader evidence. This increment makes a **new natural-language evidence test physically executable** without copying model loaders or promising equal quality.

Four **separate, named** reference paths are registered:

| Model | Immutable upstream identity | Role in this study | Parameter control |
| --- | --- | --- | --- |
| Granite 97M R2 | `ibm-granite/granite-embedding-97m-multilingual-r2@835ad14087e140460703cf0fae09f97d469d65c2` | frozen input Encoder + actual CPU train-only SGD | complete 770-parameter binary Head; same seeded untouched frozen control |
| mmBERT-small | `jhu-clsp/mmBERT-small@0eb3d056ec1d6333cf4e19b0966dfde342a41a3a` | real original tied-MLM loader + actual CPU SGD | complete 770-parameter Head and original full-tensor byte verification |
| EmbeddingGemma 2 text | `google/embeddinggemma-2@914f7f89142e33e77833254d9c9b90c3cef7303b` | real original restricted text-only MRL-256/Q24 loader + CPU SGD | complete 514-parameter Head, **not identical parameters** but within the same ceiling |
| Laya English 421M | `convaiinnovations/laya@c5d78730f3493e4fe16d61507ef4b78eef7318cf` | **actual new, same-task native pretrained `noul` no-change checkpoint** | checkpoint's native policy; **not** a 770/514-parameter trainable-Head comparator |

No unpinned aliases, random fallback, unverified remote code, or historical frozen Laya ZIP is silently substituted for the fourth fresh run. The original Compact and Gemma source implementations are checked out at the exact immutable Git commits already used in the original E1 pipeline. A failure to acquire or execute **any** checkpoint leaves the full four-model result unavailable.

## Data material, split, and what the four conditions actually mean

- Original human-labeled `rajpurkar/squad_v2` at commit `3ffb306f725f7d2ce8394bc1873b24868140c412`, exact train parquet SHA256 `f6da32ffb482ff463ad056477740d1bb284b96a45db3a08bee6a225ca6abf291`, validation SHA256 `0560174ab095c5ac0a8c8dc8da05f1625453c45a77e4ce9cabc6947ddfdd24cb`; upstream license CC-BY-SA-4.0.
- Prior to any model inference, deterministic hash ranking selects **24 independent training article titles, 8 different calibration titles and 12 original validation titles**. One answerable, exact original annotated answer span per title; no case is selected based on later model performance. SQuAD source selection is **NOT** a chronological future window, not Chinese/code, and not 200 independent families.
- For each (question, proposed answer), construct `(none, retrieved, sufficient, premise_removed)` using *the same* question, answer, modality, task identity, Encoder prompt, and source family. `sufficient` carries the original paragraph with an annotated answer span; `premise_removed` removes exactly the original sentence containing that span and must contain no surviving literal occurrence; `none` contains no paragraph; `retrieved` uses the measured lexical BM25 top passage among the source-group-approved **same split** documents.
- **Crucial label honesty:** human SQuAD span labels validate the original positive view. Sentence deletion and absence of a literal answer are only *mechanical* negatives; they are not independent human entailment or calibrated abstention judgments. A retrieved *different* document is **unlabeled**, not an invented failure. A retrieved original context is scored positive. No false factual observation or external reviewer signature is manufactured.
- This task can be solved by simple **lexical answer presence**. The independent scorer includes a mandatory cheap lexical answer-string baseline and prints its actual accuracy. If the learned Reader performs well, it does **NOT** establish compositional semantics, verified citation entailment, novel reasoning, a better Stem, or quality-equivalence to Laya.

## Separate roles, real operations, and costs

1. `p0_squad_materials.py`: verifies exact original parquet file hashes, reads original human source spans, constructs deterministic cohorts, and writes `fit.json` (train/calibration targets), **label-free** `blind.json`, and separately held `labels.json` (evaluation targets). It performs no model execution.
2. `p0_real_reader_cpu.py`: reuses existing original real three-Encoder E1 loader with Q24 tensors, actually trains a Torch `Linear(width, 2)` Head for 40 SGD updates on **TRAIN only**, preserves the byte-identical frozen Head, chooses calibration temperature solely on independent calibration groups, and predicts every blind held row. Separate `laya` subcommand directly loads the pinned original checkpoint and predicts on the *same held views*, with **no** local Head training. Every original model runs in an independent process and emits create-only, label-free prediction receipts.
3. `p0_reader_independent_review.py`: after models produce sealed files, a separate CI job opens `labels.json`, verifies complete original four-model censuses/model revisions, provenance, all source-view digests, cost columns, frozen-vs-trained Head identities, and recomputes Brier, binary accuracy, per-intervention outcomes, paired original-versus-removed gaps, descriptive source-group bootstrap, and p50/p95/p99 per-request **local** compute timing. It always denies winner selection, external authentication, chronological NDU/future superiority, and production.
4. Research-only GitHub Actions workflow `hepta-p0-real-four-reader.yml` pins exact predecessor checkouts and runtime, preserves failed-arm artifacts, and fails closed if any weight acquisition, inference, source selection or scoring fails. The model job downloads only `fit` and `blind` artifacts; label bytes are delivered later to the **scoring job**. These GitHub Actions roles are a research process-separation mechanism, **not** a cryptographic information-flow boundary or independent external observer.

The total wall/process CPU/peak RSS includes setup, model load, source encoding, model Heads and scoring within each model process. Request-local p99 **excludes** startup/model load and queue, cannot be called end-to-end production p99, and the historical Laya checkpoints/host are not counted as same-cost comparator. GPU energy/VRAM and correctly metered target-host signed Worker/FinalUse/Artifact CAS/WAL restart are **missing** rather than zero. Report missing power and unsupported channels as missing.

## Reproduce the deliberately separate jobs

Source-only / real SGD on explicit synthetic **features** (does not load pretrained checkpoints):

```sh
PYTHONPATH=experiments/shared_stem_cell python -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_squad_causal.py' -v
PYTHONPATH=experiments/shared_stem_cell python -O -m unittest discover \
  -s experiments/shared_stem_cell -p 'test_p0_squad_causal.py' -v
```

Then allow the existing Actions job to retrieve pinned source weights; physically acquire the two SQuAD original parquet SHA-verified files and build an immutable materials package (all options are named explicitly in the scripts). Each model invocation must write an original output artifact before the held-label scorer runs. Successful source tests only prove this transport and reviewer machinery, never real four-model performance.

## Acceptance and key open blockers

This one English natural QA source is a first **real physical P0 investigation**, not accepted Stem choice. Before any scientific go decision: demand independent human reviewed four-condition sufficient/removed premises; stronger nonlexical difficult examples including answer-preserving paraphrases, adversarial distractors and no-cue controls; consistent official Laya typed policy vs equal-training comparisons; complete Chinese/English/code, source-disjoint and **three prospective chronological future** windows; Reader negative-transfer/old-task OOD, target-host lifecycle cost; multiple seeds and matched exposure/parameters; native signed artifact/Worker/Evidence/CNS/FinalUse, source-head plus base-merge CI, security and risk review. All acceptance flags remain **DENY_ALL**.

## Physical-workflow source pin cleanup (2026-10-15)

The two external reviewed Git checkouts each require exactly one `with.ref` containing the reviewed immutable SHA. A duplicate mutable PR-HEAD `ref` alongside the immutable `ref` was caught before hosted physical acceptance and removed without changing dataset, models, labels, experiment arms, or runtime authorization. A new standard-library source regression refuses mutable or duplicate external checkout refs. This repair alone does not show that the hosted job has started or produced any pretrained efficacy result.
