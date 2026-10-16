# V16: Human-question Cell-Group evidence STOP and ordinary-DP parity

**RESEARCH / DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO MAIN MERGE.**

## Objective and ancestry

Stacked only on V15 natural HotpotQA [PR #2463](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2463), retaining its exact original-source hash, 7,405 human-written questions, 10 published distractor contexts per question, and secret/public split. **No pretrained Reader is executed; this study evaluates evidence retrieval and dynamic citation-context allocation, not original question-answer correctness or natural learned reasoning.** Real source runs need a finished exact-HEAD Action and postseal artifact review; synthetic local fixtures do not prove source performance.

A typed finite proxy of a Cognitive Organ is implemented:

1. `BIND`: choose actual original article/sentence IDs. Sentence-address identity must be unique.
2. `COMPOSE_LEXICAL_EDGE`: only when an original selected sentence literally mentions the second article's title. This is a syntactic bridge, **not** trained entity binding, independently verified semantic entailment or general cross-hop reasoning. The graph-lesion control deliberately scrambles links.
3. `VERIFY_TOP2`/`VERIFY_FINAL`: exactly identify the actual delivered source bytes and citation set; later independent algorithmic replay must reproduce it.
4. `STOP` or `EXPAND_3`: after top-two evidence, allocate three more **citations** at a fixed public surrogate cost, never future human labels. All original candidate sentences have already been scanned, so stopping saves only evidence-selection/delivery size, not Encoder/BM25 scanning or proven model decoding cost.

## Prespecified eight paired strategies

Every question has `bm25_2`, `bm25_5`, `graph_5`, `lesion_5`, `hash_5`, `ndu_shadow`, `ordinary_same_profile`, and `hash_budget`. The last strategy uses immutable question-ID SHA to assign 2 versus 5, not gold labels. Equal outcome/cost comparisons require using the actual observed slots and bytes; same-question pairing does **not** make source families independent.

`ndu_shadow` considers an additive source-only *proxy*, not learned utility:

```
proxy = 60 * min(3, count_unique_article_titles)
      + 40 * covered_query_terms // max(1, count_query_terms)
net   = proxy - 18 * selected_citation_slots
```

The shadow controller expands from 2 to 5 only if the source-derived gain is **strictly greater** than 54 units; ties stop. `ordinary_same_profile` independently enumerates net(2) and net(5) with STOP on ties. Both must produce **exactly identical citations, outputs, operations, and postseal support scores on every case**. A claimed additional NDU gain over this mathematically equivalent ordinary reference is a source/protocol defect, not a discovery. This is a finite deterministic special case, **not** the NDU preference SDE, neural `Z` head, FBSDE solver, real reward or learned stopping policy.

## Source chain and falsification

- V15 source owner downloads only the SHA-locked official CMU original file; source & hidden publisher answer/support truth are split into separate artifacts. Original gold has to refer to supplied sentence addresses.
- V16 separate planning job freezes complete source/owner digests, executable Python file hashes, eight actions, exactly two slot depths, tariff and reject flags before running the 7,405 original questions.
- Blind execution never downloads hidden labels; it writes create-only sealed source evidence IDs, exact source excerpt digests, finite proxy values, typed action traces and physical Python `process_time_ns`. No full question, passage, label or answer string enters Git commits.
- A second independent Python reviewer reimplements BM25, title-link composition, scrambled lesion, SHA-null, budget choice, proxy valuation and action traces **without importing either V15 ranking or V16 producer**, checks every original sentence and output against its own source recomputation, and scores original publisher supporting facts *after seal*.
- Every strategy is evaluated on exactly the same original full 7,405 questions, with document/support recall, support F1, exact support, citation slots/bytes, source scans, and original publisher type/difficulty. Repeated Wikipedia articles may overlap across questions. No confidence interval should treat 7,405 cases as 7,405 independent source families.
- 15 local synthetic mechanism/adversarial tests run in both ordinary Python and Python `-O -S`: no hidden labels, no forged article/offset/hash, no fabricated NDU gain, fail closed for altered original gold or cost, no missing cases, no ability promotion, exact replay of an 8-case synthetic fixture. The original real-data study remains unverified until its **own** GitHub hosted run completes.

## Scientific and infrastructure blockers

- No learned Cell weights, Reader original answers, semantic entailment, causal task win, physically measured GPU/RSS/energy or actual NDU FBSDE solve.
- No independent prospective time windows, fresh unexposed model tasks, signed human evaluator or historical V6 seed-41 retention repair.
- Source questions may have shared article families. The 2/5 *citation* budget is not a matched actual token-cost or LLM-decoding experiment.
- No source-only or hosted test success authorizes model selection, Cell Split, FinalUse, CNS/CAS modification, production authority, or `main` merge.

**Scientific next gate:** independently demonstrate that the fixed Reader can correctly answer a source-grounded, human-certified sufficiently evidenced question, then compare fixed-depth and adaptive action policies using **actual sealed identical-input Reader calls and full charged compute**. Only then advance to recurrent learned Bind/Compose/Verify and stochastic NDU coefficients.

## Reproduce source-only tests

```
PYTHONPATH=qualification/stem-cell-v1 python -S -m unittest -v test_v16_hotpot_group
PYTHONPATH=qualification/stem-cell-v1 python -O -S -m unittest -v test_v16_hotpot_group
```
