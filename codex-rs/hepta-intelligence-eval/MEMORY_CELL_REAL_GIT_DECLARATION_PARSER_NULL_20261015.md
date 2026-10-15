# MemoryCell original-Git declaration parser: stronger zero-parameter control

**2026-10-15 — research only.** This result uses *real original Git source bytes*,
not new pretrained model inference or an independently judged semantic QA set.

## Why the existing 7/9 rank null is not the strongest baseline

For the nine explicitly authored, retrospective file-location questions in the
v3/v4 source Reader study, a source-free top-rank strategy succeeds on **7/9**
under the original lexical ranking (and **1/9** after reversing that order).
Those numbers are useful position-bias diagnostics. They are not a fair ceiling
for a strong nonparametric method allowed to read the **same source excerpts**
that the Reader sees.

`real_git_declaration_null.py` parses the *public function name in the question*
and scans only the **frozen snippets actually delivered to the Reader**, not the
full Git corpus, answer keys, privileged labels, or private source fields.
It matches a literal Python/Rust function declaration (not calls, comments or
partial names), outputs the matching file marker plus its actual `[Ei]` label,
and abstains for no/multiple matches. Original SHA-verified Git objects and
source-committed plans are reopened **only after prediction** to score results.
No neural weights, training data labels or model inference are accessed.

## Immutable source and audit identity

- Original six-project ZIP: `a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4` (historical artifact `11778273351`).
- Separately independently reopened archive: `59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36` (historical artifact `11779107585`).
- Frozen **v3** full-source-lesion plan: `6f5efd713be88097cdc5ed3b93786df61e5dbc1709e512884952770dc9377608`.
- Frozen **v4** source-order-only plan: `a7e0b324e93e32059ab8d85166caa0f102fa787e54a81a37f802c7667ccafa77`.
- Complete 54-row audit JSON: `dcb07251773e5203319d462e56d9077c130d1540a1fa08c3a946ebf3e868c3ae` SHA-256 (trailing newline retained).

| Exact received evidence condition | Syntax declaration null | Abstentions | Notes |
| --- | ---: | ---: | --- |
| v3 no evidence | **0/9** | 9 | No source supplied |
| v3 `hybrid_k4` | **9/9** | 0 | Same visible retrieval as Reader |
| v3 one-source mechanical support | **9/9** | 0 | Diagnoses simple literal decoding |
| v3 full symbol lesion | **0/9** | 9 | All literal query mentions removed |
| v4 lexical source order | **9/9** | 0 | Read unchanged source excerpts |
| v4 reversed source order | **9/9** | 0 | Correct `[E]` label moves with order |

These are **mechanical declaration-identification** results, not verified
semantic entailment, graph traversal, code repair, future-task learning or
MemoryCell utility. The parser uses a deliberately task-specific regular
expression; it is not claimed to solve open-ended programming problems.

**Effect on model interpretation:** Even a future Reader at 9/9 would only
tie this nonparametric syntax-aware baseline. It cannot by itself support
claims about System-2, learned heads, persistent Cell memory or parameter
advantage. Strong RAG/simple source traversal should remain in the future
pre-registered independent task comparison, alongside prospective human-
reviewed evidence sufficiency and actual executable program outcomes.

## Reproduce without weights

```sh
export PYTHONPATH=scripts/memory_cell
export MEMORY_REAL_SOURCE_ZIP=/path/original-six-project.zip
export MEMORY_REOPEN_ZIP=/path/independent-original-reopen.zip
python3 -m unittest discover -s scripts/memory_cell -p 'test_real_git_declaration_null.py' -v
python3 scripts/memory_cell/real_git_declaration_null.py \
  --source-zip "$MEMORY_REAL_SOURCE_ZIP" \
  --reopen-zip "$MEMORY_REOPEN_ZIP" --output NEW_UNWRITTEN_REPORT.json
sha256sum NEW_UNWRITTEN_REPORT.json
```

The source-only GitHub workflow obtains the original two ZIPs with the fixed
sha256 pins, runs 12 mutation/verification regressions and recomputes the
committed result byte-for-byte. It never downloads, stages or runs a Reader.
Do **not** replace 72 pending v3 or 36 pending v4 inference outcomes with this
zero-model source test, and do not alter the parent Reader branches or their
mandatory CI checks. `production_qualified=false`.
