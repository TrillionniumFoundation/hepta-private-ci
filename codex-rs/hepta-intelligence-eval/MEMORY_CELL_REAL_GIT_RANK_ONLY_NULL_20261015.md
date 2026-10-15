# Rank-only null: exact-Git-source Reader v3 (2026-10-15)

**Research-only; zero pretrained Reader calls, zero training, zero independent human semantic judgments, and no production promotion.** This sidecar is intentionally stacked on the existing PR #2067 branch, rather than modifying its exact-head model experiment and cancelling queued Actions.

## An executable zero-model control

Original publicly accessible, SHA-bound six-repository archive: artifact `11778273351`, ZIP SHA-256 `a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4`. Independent byte-reopen archive: artifact `11779107585`, ZIP SHA-256 `59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36`.

Frozen **v3** nine-case plan SHA-256: `6f5efd713be88097cdc5ed3b93786df61e5dbc1709e512884952770dc9377608`. Earlier v1/v2 plan identities remain retired. They are not pooled.

For every question, the null policy outputs **the first retrieved file marker followed by `[E1]`**. It reads no code bytes, target declaration, oracle support, Reader model weights, or sealed human label at prediction time. Separately, the auditor reopens every original Git blob and reconstructs the one actual declaration-bearing file; only then does it score the fixed prediction. Source/materialization tampering, duplicate/changed plans, mismatched source file order, leaked symbols in the ablated control and wrong plan versions are rejected.

| Real source population | Rank-1 correct | Questions |
| --- | ---: | ---: |
| CPython | 2 | 3 |
| scikit-learn | 2 | 3 |
| Deno | 3 | 3 |
| **Total** | **7** | **9** |

The null policy can also produce a syntactically valid target-file citation (`[E1]`) in the same seven cases, without reading source content. This is **not** verified semantic citation entailment. In two cases the correct file is at lexical rank two. All nine are retrospective, publicly exposed mechanical function-location tasks; the source-reader's plan includes the function name. Repository-name proxies (three) do not yield independent effective statistical N>=200.

## Consequences for the causal experiment

1. A Reader succeeding on <=7/9 of these tasks does not demonstrate it has *read code*, understood a declaration, or improved MemoryCell. A positive causal claim must compare matched per-case outcomes against this zero-model top-rank control, not merely against `none`.
2. Even if a Reader exceeds this baseline, that only shows an incremental mechanical file-identification effect on this registered exposed cohort. It is **not** independent proof of rich semantic comprehension, prospective memory retention, graph advantage, parameter updates or a deployable production gain.
3. The `removed_declaration` arm preserves original retrieval ranks, and thus preserves the 7/9 potential rank shortcut even though its delivered text no longer contains the literal queried symbol. Correct output after the lesion is *not* proof that evidence or prerequisites are causally unnecessary.
4. Do not treat this source-only rank null as 72 new pretrained inferences or as independently verified real-world program success.

## Reproduction

```bash
PYTHONPATH=scripts/memory_cell MEMORY_REAL_SOURCE_ZIP=/path/original-six-project.zip \
  MEMORY_REOPEN_ZIP=/path/separate-reopen.zip \
  python3 -m unittest -v test_real_source_rank_null

PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/real_source_rank_null.py \
  --source-zip /path/original-six-project.zip \
  --reopen-zip /path/separate-reopen.zip \
  --output NEW_NULL_REPORT.json
```

Both paths must be original ZIP archives with exact whole-archive SHA-256. The audit writes the output exactly once. Missing terms for real storage, revocation, maintenance, rollback and recovery remain `null`, not zero; `production_qualified=false`.