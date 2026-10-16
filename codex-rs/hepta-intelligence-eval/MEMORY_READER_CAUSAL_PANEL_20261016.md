# Hepta MemoryCell — genuine original Reader six-arm causal panel

**2026-10-16 · RESEARCH / DRAFT / DENY_ALL / NO MAIN / NO FINALUSE**

Additive child of Meta-Graph PR #2491 and associative Cell PR #2365. This is not an authorized memory writer, semantic citation judge, model selector or replacement serving spine.

## Frozen experiment

- Real SHA-pinned LoCoMo source: Actions run `37862780268`, artifact `11586991191`, original SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Historical questions: 2 SHA-selected questions per original dialogue family, 10 families, 20 fixed questions; source-only ranking inherited from PR #2491.
- Frozen original SmolLM2-135M weights SHA-256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`; original tokenizer SHA-256 `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`. Model implementation is the existing byte-pinned `offline_smol_reader.py` custom FP32 profile **without official HF/BF16 parity**.
- Same evidence-aware system prompt, greedy decoding, 32 generated-token budget, 2,048 input-token limit, 384 original source characters per excerpt. No adapter training or model weight updates.
- Six arms: `empty`, `bm25`, `temporal_window`, `graph`, `annotated`, `annotated_lesion` (remove one publisher-annotated source). Annotated arms are **retrospective privileged diagnoses**, not deployable retrieval and not independently verified sufficient evidence.

### Trust / lifetime

The privileged plan producer validates the original source and seals an **answer-free** plan. The independent offline Reader process consumes only the sealed plan and pinned weights, emits exact original model responses and an fsynced append-only progress journal, and only seals its complete output after terminal response census and frozen-weight revalidation. A distinct postseal reviewer rebuilds the entire question/evidence plan from the pinned source and original annotation file before scoring. One error or unavailable evidence remains an explicit row; it is not silently discarded.

This locally demonstrates **separate processes and input files**, not a separately administered trust principal, independently signed model execution or fully isolated operating-system sandbox. Output hashes alone cannot authenticate an untrusted producer.

## Executed original CPU result (not simulation)

**120/120 planned, 118 original generations, 2 explicit unavailable, 0/118 citation-marker emission and zero strict-exact answer strings in all arms.**

- Plan SHA-256: `a7ad39c6548b06dc0fd752cd77149deaeb46875b3307696fe2857ef0cd1fc3e9`.
- Complete unscored journal SHA-256: `0797d8b1a4d9b9e3d7d68925bf4001666f253191d2bac46d90a0af11c78f0d76`.
- Postseal model review SHA-256: `fbc1ab204019caa22e67cd857fc9edb4294584aeaac59b1b1c90b99a83f80dbf`.
- Common-denominator paired review SHA-256: `316a1448bcc536489831b6a5e895da6f1853860997bcc1b972ea51e6b88ec0c0`.

| Arm | Conditional scorable questions | Conditional mean diagnostic Token-F1 | Real summed Reader CPU model seconds |
|---|---:|---:|---:|
| Empty | 15 | 0.046318 | 40.3561 |
| BM25 | 15 | 0.038982 | 86.4647 |
| Temporal window | 15 | **0.062391** | 97.3754 |
| Meta-Graph | 15 | 0.049747 | 85.6057 |
| Publisher annotated (privileged) | 14 | 0.128421 | 50.5013 |
| Publisher annotated minus one source | 14 | 0.081273 | 42.0643 |

The independent paired scorer also evaluates **exactly the same 14 jointly scoreable questions** in all arms:

| Arm | Matched-14 mean Token-F1 |
|---|---:|
| Empty | 0.049626688 |
| BM25 | 0.041766375 |
| Temporal window | **0.066847328** |
| Meta-Graph | 0.053300862 |
| Publisher annotated | 0.128420581 |
| Annotated minus one source | 0.081273252 |

Meta-Graph minus temporal window = **−0.013546467** paired mean (**1 win / 3 losses / 10 ties**). This is not evidence of graph or parametric-learning superiority. Input-token totals by arm: empty **2,085**; BM25 **8,934**; window **9,365**; graph **9,242**; annotated **3,549**; lesion **2,505**. These are unequal evidence-length real inputs and do **not** equalize full lifecycle compute, storage, index cost, privacy, or energy.

## Code and qualification

- `scripts/memory_cell/memory_reader_causal_panel.py`: closed-world, source-pinned plan producer; bounded, checkpointed actual Reader worker; postseal independent review.
- `scripts/memory_cell/memory_reader_paired_review.py`: no common-denominator tricks; validates journal/plan SHA and re-evaluates same 14 answers on all six arms.
- `scripts/memory_cell/test_memory_reader_causal_panel.py`: **9/9 actual local regressions passed**, including one against the original authenticated 2.8MB source. Hosted no-source CI runs eight and truthfully skips the opt-in original-sample test.
- Opt-in hosted workflow separates original-source plan, original Reader file staging, model execution and grading into distinct jobs, without automatically adding a 120-call model load to every pull-request run. It does **not** bypass `blocking-ci`.

Reproduction:

```bash
PYTHONPATH=scripts/memory_cell python3 -m unittest discover -s scripts/memory_cell -p 'test_memory_reader_causal_panel.py' -v
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/memory_reader_causal_panel.py prepare ORIGINAL PREPARED GRAPH_RUN NEW_PLAN 2
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/memory_reader_causal_panel.py worker NEW_PLAN PINNED_READER_FILES NEW_RUN
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/memory_reader_causal_panel.py review ORIGINAL PREPARED GRAPH_RUN NEW_PLAN NEW_RUN NEW_REPORT
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/memory_reader_paired_review.py ORIGINAL NEW_PLAN NEW_RUN NEW_PAIRED_REPORT
```

## Decision

**HOLD / NO-GO on autonomous Cell Split, Meta-Graph promotion and parameter-only memory superiority.** On this original 135M Reader, even publisher-labelled evidence failed to yield reliable referenced answers (zero emitted citation markers). A stronger *fixed and authenticated* Reader must first answer independently reviewed sufficient-evidence tasks, then compare identical sources, contexts, budgets and costs on future disjoint source families, with verified citation entailment and independent external acceptance. No production rights, current Memory owner changes, learner promotion or main merge arise from this research result.
