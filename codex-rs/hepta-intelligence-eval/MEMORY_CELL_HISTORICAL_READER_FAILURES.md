# MemoryCell — strict-answer vs reader-failure attribution (2026-10-11)

This is **read-only diagnosis of 96 already generated responses**, not an additional language-model run. Every source and model archive is pinned and its outer SHA-256, inner SHA256SUMS and exact model source commit are checked before analysis. No writer, model weights, task labels, new parameters or citation claims are produced by the script.

## Exact historical provenance

- Original frozen event source artifact: `11669174727`, ZIP SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`; original 8-question plan SHA-256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.
- Original Qwen2.5-3B reader artifact: `11674741321`, ZIP SHA-256 `831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98`.
- Original SmolLM2-1.7B reader artifact: `11674486085`, ZIP SHA-256 `67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae`.
- Original generation commit `59f9eadd5cc919359079e04442f7343838a60057`, successful original workflow `38063870516`. Each model has **48 distinct model generations**: 8 previously exposed authored tasks × 6 conditions.

## Observed failure taxonomy

| Reader and original evidence condition | Strict correct | Single wrong identifier | Correct gold literal but invalid strict grammar | Explicit abstentions | Other responses lacking an answer identifier |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen / hybrid top-four | 3/8 | 4/8 | 1/8 | 0/8 | 0/8 |
| Qwen / entity-time full traversal | 8/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| Qwen / organized | 8/8 | 0/8 | 0/8 | 0/8 | 0/8 |
| Smol / hybrid top-four | 1/8 | 0/8 | 0/8 | 7/8 | 0/8 |
| Smol / entity-time full traversal | 2/8 | 0/8 | 0/8 | 6/8 | 0/8 |
| Smol / organized | 3/8 | 0/8 | 0/8 | 5/8 | 0/8 |

**One exact example:** In the original Qwen `hybrid` correction question `controlled_cbfd4ba5`, the frozen reader returned `[site_2749e2c9]`. The original gold identifier was `site_2749e2c9`, but the predefined strict grammar requires a bare identifier with optional legitimate evidence markers, so the archived `strict_task_success` is **false**. This is described as *gold literal present but invalid strict grammar*, **not credited as a corrected task answer**. It also has no valid citation marker.

The other four Qwen hybrid strict failures returned **wrong site identifiers**, not missing source coverage: the published original hybrid `required_sources_covered` flag is true on 8/8 cases for both reader families. SmolLM2's seven hybrid failures explicitly abstained despite the corresponding annotated sources being in the original retrieved set. These results support investigating reader distraction and reference-following; they cannot uniquely attribute a causal effect to graph organization or parameter memory.

## Audit semantics and hard limits

`historical_reader_failure_modes.py` validates both complete model-output censuses, checks that scored records preserve every raw-generation field, preserves the **original strict score**, and classifies only a bounded literal output pattern. An identifier *appearing* in an answer can be misleading or unentailed, so the auxiliary `gold_literal_without_strict_grammar` category is **never promoted to task success**. Multiple conflicting identifiers stay unadjudicated. Procedure pass/fail is inherited from the original bounded worker and is not independently re-executed here.

This taxonomy is a post-hoc **development diagnostic** on eight authored, publicly exposed scopes. It is not a blinded independent source-family evaluation, confidence interval, semantic citation judgement, production lifecycle-cost estimate, model retraining gain or deployment qualification. The original historical attribution stays unchanged. Production acceptance remains false.

Reproduce after downloading and verifying the exact archives:

```sh
python scripts/memory_cell/historical_reader_failure_modes.py \
  event-inputs-20261010.zip event-reader-actual-48.zip \
  event-reader-smol-48.zip historical-reader-failure-modes-20261011.json
```

The newer strong-RAG experiment's **40 real top-k calibration generations + 72 nine-arm evaluation generations + independent replay** must complete before additional efficacy claims. Its strict predeclared scoring policy must remain unchanged by these exploratory categories.
