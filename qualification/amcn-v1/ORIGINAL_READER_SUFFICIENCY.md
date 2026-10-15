# Original LoCoMo Reader ability before MemoryCell expansion (research DENY_ALL)

2026-10-15 · Research branch `research/amcn-causal-three-axis-20261015`, stacked PR #2085. This is an **isolated analysis-container**, not the user's dot host; production MemoryCell must remain restricted to its assigned original owner. This pilot does not modify source custody, HNMF/NeuronCell selection, model promotions, revocation, Artifact owner, `main`, or blocking CI.

## Decision question

Before increasing Cell count, training a graph, or claiming parameter learning, ask whether **the same existing 30-layer / ~135M original pretrained Llama Reader** can complete original LoCoMo questions with four distinct evidence presentations:

1. `no_evidence`: same system and natural-language question, no retrieved evidence. There are intentionally **zero** final evidence sources.
2. `original_bm25_top3`: three original corpus dialogue turns previously selected by the E3 frozen BM25, no publisher answer or source labels in the Reader process.
3. `publisher_annotated_witness`: the originally publisher-annotated *single* dialogue ID, plus the top two original BM25 distractors. This is **NOT a human-verified sufficient evidence packet**, only an optimistic publisher-weak-witness upper-bound diagnostic.
4. `publisher_witness_lesion`: retain the same two distractors and substitute one other original source for the annotated witness. Do not delete or synthesize source text, forge revisions, or contaminate another source root.

All nonempty regimes use 3 untouched original source turns. Greedy generation is fixed to at most **24 generated tokens**, Reader safetensors SHA `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`, original tokenizer SHA `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c`. Unlike a full equal-total-compute causal comparison, the actual prompt **input tokens differ**, and the no-evidence regime has no final evidence slots. Official Hugging Face Tokenizer/operator numeric parity remains unverified; this physical execution uses the same original archived weights and an explicitly research-only manually implemented FP32 numerical candidate from #2085.

## Two ORIGINAL cohorts (80 real model invocations)

Both groups take four **historical** LoCoMo source families `conv-47`, `conv-48`, `conv-49`, `conv-50`. They share two questions across cohorts, so the 20 cohort case slots represent only **18 unique original question IDs** and **four source-family roots**, NOT 20 independent trials or real future calendar windows.

### A. Annotation-only fixed cohort (12 questions × 4 arms = 48 physical calls)

A label-blind source/ranking packet, the immutable publisher *source IDs only*, and a deterministic SHA-256 of each question ID are used to prechoose three cases per family where original BM25 Top-3 **misses** the single annotated source. The Reader cannot read publisher answer text or any gold correctness field. A reference to a publisher ID is not an independent human sufficiency attestation.

| Original archival measurement | No evidence | Original BM25 Top-3 | Publisher source added | Witness lesioned |
|---|---:|---:|---:|---:|
| Reader calls successful | 12/12 | 12/12 | 12/12 | 12/12 |
| Publisher weak-source ID in Reader evidence | 0/12 | 0/12 | 12/12 | 0/12 |
| Exact original answer string | 0/12 | 0/12 | 0/12 | 0/12 |
| Original answer appears **as a substring** (weak, not semantic) | 0/12 | 0/12 | **1/12** | 0/12 |
| Input tokens actually counted | 616 | 1,897 | 1,978 | 1,880 |
| Output tokens actually counted | 273 | 261 | 260 | 265 |
| Output reached 24-token cap | 8/12 | 9/12 | 8/12 | 9/12 |

Seven questions have ordinary benchmark answers, five carry `adversarial_answer`; after sealing, the original publisher-answer string appeared verbatim in the marked source on **only 2/7 ordinary questions**. This is not a sufficient-evidence capacity oracle. Ordinary and adversarial scoring stay distinct in the receipt.

### B. Explicit gold-dependent verbatim stress (8 questions × 4 arms = 32 physical calls)

From the SAME four historical families, a SEPARATE preprocessor **does inspect original ordinary publisher answer strings**, and selects only cases where that exact string (at least four characters, not trivial yes/no) occurs within the originally publisher-annotated dialogue source. Two cases per family are frozen by question-ID hash. This is deliberately **answer-based cohort selection** and is unsuitable for an unbiased task-success estimate. Reader **does not receive the answer text as a label**; the visible original evidence itself of course may quote it.

| Original archival measurement | No evidence | Original BM25 Top-3 | Publisher source added | Witness lesioned |
|---|---:|---:|---:|---:|
| Reader calls successful | 8/8 | 8/8 | 8/8 | 8/8 |
| Publisher weak-source ID in Reader evidence | 0/8 | 0/8 | 8/8 | 0/8 |
| Exact original answer string | 0/8 | 0/8 | 0/8 | 0/8 |
| Original answer appears **as a substring** (weak, not semantic) | 0/8 | 0/8 | **4/8** | 0/8 |
| Input tokens actually counted | 413 | 1,181 | 1,425 | 1,266 |
| Output tokens actually counted | 182 | 160 | 161 | 178 |
| Output reached 24-token cap | 7/8 | 5/8 | 5/8 | 7/8 |

This more diagnostic upper-bound cohort finds **some capacity to copy or mention the given answer**, but **no exact full-answer completions** with this prompt/budget/model. String inclusion still cannot certify semantic correctness, citations, absence of hallucination, or true utility.

## Exact original material and independent byte recount

- Original LoCoMo JSON: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Prior read-only E3 `public-original.json`: `dac70024f437d81a85b99e7b143fbdf2b79d8951ce5960fb390d1d214a62c34a`.
- Prior label-blind `original-all-1986-ranks.json`: `4cf24c16576e2d4d086fad0acd8f1eccf854258611e2e83a7b12791226bcb40c`.
- Segregated original publisher annotated evidence IDs: `491abd3c4fb831de247b726ff7353addeda222ca422c80b1be45e619d94734fd`.
- 48-invocation plan SHA: `7b410e2e05b66767d8c5a67c97eee354f294b1ce8e4c8954e87cdb4ee7db4cb7`; sealed original journal receipt SHA: `8ba6e315dfcd70158c2d7b1c220411b2deee5cad062c0634c5dae66404f16692`.
- 32-invocation verbatim-stress plan SHA: `8810ac2a88190fb27aded5f25920c8e0ea48ad08c1369ae67b5aed4723087b41`; sealed original journal receipt SHA: `6cdb9eb4ce4dd94eaf008f4fc85e7dc387bcec432105388ba6e2eea8c8842a89`.
- Independent post-seal scorer recounts every start, response, status, original Token ID, output text and each actual input/output token count, and rejects edits or omissions against EXTERNALLY passed plan and seal SHA. Original answer and publisher source text are retained in a private analysis work folder, **not committed or uploaded** to GitHub. The static research SHA is not an authenticated human/model-host signer.
- Sanitized `ORIGINAL_READER_SUFFICIENCY_20261015.json` SHA: `7ed4ddc5ad8defb780b0931c5e9ed6c0330e01f1097a4f0196bf0128161a9864`. This source-only negative receipt and all 16 fast standard-library rejection tests are replicated in CI. The original external models and data are REQUIRED for actual physical rerun; source-only CI never claims a model forward.

## Reproduce physically on the assigned dot host (not in general Hepta cloud)

Use already authenticated original files and SHA-pinned model material, Python 3.11+, `torch`, `safetensors`, `regex` and the original `amcn_original_text_reader.py` from the same PR. The archival data were obtained in an isolated host; this work itself was **not run on dot**.

```sh
# SOURCE/annotation stage: publisher SOURCE IDs, but no answer text.
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_reader_sufficiency.py prepare \
  --public "$PRIVATE/public-original.json" --public-sha dac70024f437d81a85b99e7b143fbdf2b79d8951ce5960fb390d1d214a62c34a \
  --rank "$PRIVATE/original-all-1986-ranks.json" --rank-sha 4cf24c16576e2d4d086fad0acd8f1eccf854258611e2e83a7b12791226bcb40c \
  --weak "$PRIVATE/original-withheld.json" --weak-sha 491abd3c4fb831de247b726ff7353addeda222ca422c80b1be45e619d94734fd \
  --reader "$PRIVATE/reader" --plan-out "$PRIVATE/annotation-12-plan.json"

# PHYSICAL READER process: plan has no publisher answer field; no gold file argument.
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_reader_sufficiency.py run \
  --plan "$PRIVATE/annotation-12-plan.json" --plan-sha 7b410e2e05b66767d8c5a67c97eee354f294b1ce8e4c8954e87cdb4ee7db4cb7 \
  --reader "$PRIVATE/reader" --output "$PRIVATE/original-reader-48-create-only"

# POST-SEAL external scorer accepts original gold ONLY AFTER final journal seal.
PYTHONPATH=qualification/amcn-v1 python3 qualification/amcn-v1/amcn_reader_sufficiency.py score \
  --plan "$PRIVATE/annotation-12-plan.json" --plan-sha 7b410e2e05b66767d8c5a67c97eee354f294b1ce8e4c8954e87cdb4ee7db4cb7 \
  --journal "$PRIVATE/original-reader-48-create-only" --seal-sha 8ba6e315dfcd70158c2d7b1c220411b2deee5cad062c0634c5dae66404f16692 \
  --reader "$PRIVATE/reader" --weak "$PRIVATE/original-withheld.json" \
  --weak-sha 491abd3c4fb831de247b726ff7353addeda222ca422c80b1be45e619d94734fd \
  --original "$PRIVATE/original/locomo.json" --out "$PRIVATE/original-postseal-score.json"
```

The verbatim cohort uses `prepare-verbatim --original "$PRIVATE/original/locomo.json"` instead of `prepare` and its second plan/seal pins. NEVER silently replace source text, or retry over a failed attempt as if it never happened.

## Decision / next investments

This is a **negative Reader representation/prompt diagnostic, not a proof the underlying model lacks all capability**. The publisher source is not independently human-certified sufficient. The 24-token output ceiling causes many truncated completions; the manual original-weight Reader has **unverified official HF numerical parity**; exact literal/substring matches are proxies, not independent semantic task correctness. There is no independently judged stronger reference Reader. Four retrospective source roots are far from the required prospective cohorts and two actual future calendar windows.

Do not attribute replacing Reader/prompt with a stronger model to MemoryCell. The next scientifically useful tests are (1) externally verified sufficient evidence for fixed tasks; (2) a matching prompt and output-budget feasibility ladder for the same original Reader; (3) stronger reference Reader run with exactly the same frozen evidence; (4) only after reader sufficiency, equal-total-compute Head/graph comparisons with genuine independently adjudicated task completion. **DO NOT enable automatic cell split/fuse, model promotion or production FinalUse**. All statuses remain Draft / SHADOW / DENY_ALL.
