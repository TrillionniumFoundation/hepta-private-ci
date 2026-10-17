# LoCoMo adjacent-turn evidence retrieval — exploratory source-only sidecar

This branch-scoped experiment does NOT change the existing nine-arm source-only
decision journal, the frozen reader, the production runtime, or any existing
MemoryCell acceptance authority.

## Causal comparison

The comparator is **original frozen lexical_k8**, not a weakened RAG. Before
opening support labels, the source-only process verifies all 480 original
six-arm candidate decisions against the exact public corpus. For each question:

- It reuses original sources, scope, chronology and the unchanged candidate pool.
- It uses word-level BM25 with fixed stop words and adds 0.6 times the source
  score only to directly adjacent turns in the SAME dialogue session.
- It selects at most eight complete source turns and cannot exceed that
  question's original lexical_k8 UTF-8 source-byte budget.
- It never reads benchmark answer text or support IDs when making a decision.

Selection labels open only after all decisions are durable; evaluation labels
open only after the selection report is sealed.

**This is exploratory**: multiple development settings and both public splits
were already inspected during investigation. They are not prospective blind
data. No source family here is independently authenticated.

## Local source-only replay results

| Split | Eligible native source labels | Original lexical_k8 | Adjacent-turn (bytebound) | Delivered source bytes old → new | Wins / losses |
| --- | ---: | ---: | ---: | ---: | ---: |
| Selection (2 family proxies) | 10 | 4 | 5 | 21,115 → 19,685 | 2 / 1 |
| Evaluation (2 family proxies) | 13 | 9 | 10 | 17,085 → 16,007 | 1 / 0 |

These are publisher document-ID coverage counts, NOT independently verified
semantic sufficiency, Reader answer correctness, citation entailment or cost
benefit. Source bytes are NOT actual prompt tokens, model latency or TCO.
No model was called and no Cell parameters were trained. The evaluation
result cannot justify scale-out, production adoption or statistical superiority.

The original Qwen lexical-k4 versus lexical-k8 Reader contrast is separately
scheduled. Only after that control is complete should a matched, identical
frozen-Qwen Reader comparison of the new and old evidence selection be treated
as an actual answering experiment. Retain every failure in the denominator.

## Exact public pins and reproduction

Original GitHub Actions run 38206328621:
- public histories artifact 11728164433
- original frozen six-arm decisions 11729394703
- selection targets 11728632417
- evaluation targets 11728856834

Their ZIP SHA-256 values are checked explicitly by the read-only workflow
.github/workflows/hepta-memory-locomo-neighbor.yml. The three commands are:

    PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/locomo_neighbor_retrieval.py retrieve PUBLIC OUTPUT
    PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/locomo_neighbor_retrieval.py select PUBLIC SELECTION OUTPUT
    PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/locomo_neighbor_retrieval.py evaluate PUBLIC SELECTION EVALUATION OUTPUT

No independent semantic review, fresh source-family confidence interval,
99% citation entitlement, full lifecycle cost or production qualification
is asserted. All adoption flags remain false/null.
