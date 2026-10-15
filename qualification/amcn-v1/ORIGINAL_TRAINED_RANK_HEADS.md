# Original LoCoMo physical tiny rank-Head pilot — E1/E2, research DENY_ALL

**Owner:** existing #1777/#1968/#2001 MemoryCell research; stacked PR #2085. No second Memory OS, model Selector, Ledger writer, production promotion or FinalUse.

## Scientific question / registered controls

Can a *real trained*, tiny per-Cell ranking Head improve final Top-3 publisher-weak source recovery over the best existing BM25 control? Does **query-type specialization** independently beat an **equal-total-parameter** untyped model bank?

Frozen inputs: the original SHA-256-verified LoCoMo artifact (`11586991191`), 10 original conversations / 5,882 source turns, 1,986 questions. Use the 1,986-question prior **actual MiniLM** complete rank packet; no new Encoder is trained or backpropagated. Source and rank SHA locks are in the source module and preserved below.

Six original conversation roots TRAIN (1,157 questions). Type is fixed *before* accessing publisher evidence: `episodic` only for lexical temporal questions (`When`, `How long`, etc.), `semantic` otherwise. Two original roots SELECT (429 questions), and two untouched original roots RETROSPECTIVE_HELDOUT (400 questions). SELECT labels are not used in this fixed configuration. Neither SELECT nor heldout publisher evidence is provided to TRAIN/INFER process; gold is opened only in PREPARE-TRAIN or after all heldout predictions are persisted and an independent physical model replay has succeeded.

Physical rank feature per eligible source = `[frozen_BM25_rank_in_top16, frozen_original_MiniLM_rank_in_top16, appears_in_both]`, with source-ID stable ties. Each Head is `Linear(3,1,bias=False)` trained by **actual CPU PyTorch AdamW** using TRAIN weak-positive listwise likelihood, exactly **160 steps × 24 sampled questions** per Head. Three separate 2-Head banks: unspecialized (two pooled-data Heads), typed (two type-restricted Heads), label-shuffled TRAIN-only negative. Each bank has exactly **6 float32 learned scalar parameters**, identical Head geometry/initialization per route, total optimizer steps, minibatch accounting and one live Head per question. An unchanged frozen Head reproduces BM25. Original six physical weights are saved as safetensors and SHA-pinned; the post-seal scorer independently reloads **all six** and recomputes **3,316** physical inference logits over every original SELECT+HELDOUT case, *before opening withheld targets*.

The shared frozen Encoder and original retrieval candidate computations are already paid for by the original frozen-rank experiment. Each trained Head only reranks the **union of original Top-16 BM25 and Top-16 MiniLM** (at most 32 candidates), then delivers final **Top-3** source references. Its extra dense-Encoder and rerank costs mean the original BM25-only pipeline does **not** have matched total compute and cannot serve as a strict equal-compute causal baseline. The untyped-vs-typed bank contrast *does* match trainable parameter count, optimizer/minibatch budgets and per-query Head calls. This is source-selection research only: no natural-language Reader calls, independent citation QA, verified HF parity, authentic strong hybrid RAG, calendar-future observations, or measured compression gain.

## Actual isolated-host original-weight experiment (October 15, 2026)

Local Python 3.13 / CPU Torch / safetensors executed six Head updates on original archived pretrained retrieval features. Physical label/Torch split: 933/1,157 TRAIN questions had at least one publisher-annotated positive in the common 32-candidate frontier. All other TRAIN questions remain registered (not secretly scored as positive). Heldout reporting contains **every** 196+204 original question, including source-missing/zero-support cases.

| Retrospective heldout source-family groups (400 original questions) | Weak any-support@3 | Weak all-support@3 |
|---|---:|---:|
| BM25 frozen | 182 / 400 | 155 / 400 |
| Original dense MiniLM only | 91 / 400 | 70 / 400 |
| Original RRF(60) | 156 / 400 | 126 / 400 |
| **Trained unspecialized two-Head bank** | **192 / 400** | **164 / 400** |
| **Trained typed two-Head bank** | **192 / 400** | **164 / 400** |
| Typed bank with incorrect type route | 192 / 400 | 162 / 400 |
| Trained Head with scrambled TRAIN labels | 80 / 400 | 63 / 400 |

On individual retrospective questions, the unspecialized/typed Head each gained **24** BM25-missed cases and lost **14** BM25-hit cases (net **+10**, not 24). The naive unclustered two-sided paired McNemar/binomial p-value is approximately **0.143**, *even before* accounting for the fact that the 400 questions came from only **two distinct conversation roots**. It is **not** a statistically qualified improvement or an independently verified memory-system task result.

Both true-type and unspecialized controls are tied. Incorrect type routing is also tied on weak Hit@3. So **E2 type differentiation is NO-GO**; E1 shows a promising *descriptive proxy only*, with NO independently established whole-task lift. E3 learned graph incremental whole-task benefit is unmeasured. Do not increase Cell count, split/fuse based on this evidence, or use any of these models for FinalUse.

## Exact original local material hashes

- SOURCE-only public: `ac5f95085e5b223f81e888236e2c162f1ef45a3d1f52ad3e903fde48a629a633`
- Original frozen MiniLM/BM25 ranked 1,986 questions: `25bd9754e1da4ee5ddf620e7f3c734f06650568278c6aab51916d55046baef99`
- Original publisher weak support (never passed into TRAIN/INFER): `758d951c2fb296c3ba23ef539e3f243fb8464d52ed0d42c8d0981943ac907a06`
- TRAIN-only public publisher weak-support extraction: `c2256994e86c0bdbeabce22c4b9b3d8d6617ccd88d5b535dfa4655c771ba629c`
- Physical 6-head bank manifest: `88dbb2c9feffea97058c455f9a1292d21601a39449b6fee47169b540d6759fb6`
- Final label-blind 829-case source rank packet: `a937d4fd91e0c75cf4ddd265760c0b6c4cf1ed0947ad0c5be323686aca7391a3`
- Independent scorer physically reloaded all saved Heads, 3,316 forward calls; scored receipt: `5ac745b674a4f95942d3522342027f487a740c8de308d5c3ff175eef03311b33`

SHA matches protect static byte identities, **not publisher label truth, independent issuer signatures, proof of no data contamination outside this process, or official HF operator parity.** The model binary, raw source dialogues, per-question answers and withheld weak labels must **not** be committed or uploaded as Actions artifacts.

## Execution contract

Use Python 3.11–3.13, `torch`, `numpy`, `safetensors`. CLI stages in `amcn_original_trained_rank_heads.py`:

1. `prepare-train`: original SHA-pinned `public`, `rank`, and privately withheld original publisher support. Export *only six training roots* into a new immutable TRAIN-only label file.
2. `train`: physically update three matched two-Head banks, read **only TRAIN-only labels** and source/frozen rank bytes, seal safetensors+manifest, **never** open original publisher heldout data.
3. `infer`: reload each actual SHA-pinned safetensors Head, generate every SELECT/HELDOUT source ranking, write a create-only original 829-question prediction packet, without any publisher targets.
4. `score`: independently reload saved physical Heads, verify **3,316 exact original source Head outputs** first, then and **only then** open publisher gold in a separate scoring process and retain all negative/missing cases in denominator.

The workflow `hepta-amcn-original-trained-rank-heads.yml` executes the full original CPU archived pretrained feature generation plus each stage on a separately pinned original archive. If the original rank bytes differ due to model/runtime drift, it MUST stop instead of substituting a historical or generated ranking. Exact commit/tree, source checksums, environment, tests and sanitized negative-receipt are retained; no unreviewed private corpus or pretrained model tensors are uploaded.

## Next scientific gates — do not declare GO prematurely

- Official Transformers/Tokenizer parity accepted for the original frozen MiniLM and Llama weights.
- Real **equal-compute**, equal-final-Reader-token four/five-arm trials with independently authenticated original Reader answers, citation entailment and failure-sensitive full task completion.
- At least 200 *independent* source groups and actual forward calendar windows rather than only two retrospective heldout families.
- Correct TRAIN family source lineage, retained old tasks, revocation/removal semantics, task success, maintenance cost, independent evaluator and intact `blocking-ci`/Architecture.

**Status:** SHADOW / DENY_ALL. Strictly no production promotion or main merge.
