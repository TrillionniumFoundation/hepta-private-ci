# MemoryCell order-only matched Reader counterfactual — 2026-10-15

**Research only. No production route, deployment, unverified learned-memory gain or synthetic-model promotion.** This study is a parallel successor to the exact-Git v3 and rank-only null PRs; it does not change those frozen experiments.

## Why the experiment is warranted

On nine real Git-source mechanical function-location tasks from CPython, scikit-learn and Deno, an answer-blind selector that returns the first ranked file marker (without reading code) is correct **7/9** times. Reversing that same source list and blindly returning the first visible marker gives **1/9**, while the underlying 2–4 source files, original paths, marker identities, code bytes, question, Reader weights and tool policy remain unchanged. The large baseline shift shows source position is an important alternative explanation for model correctness.

## Versioned frozen source and outputs

- Original six-project ZIP: `a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4` (Actions artifact 11778273351).
- Original independent raw-byte reopen ZIP: `59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36` (artifact 11779107585).
- Unmodified nine-question v3 source-derived plan SHA-256: `6f5efd713be88097cdc5ed3b93786df61e5dbc1709e512884952770dc9377608`.
- New *separately versioned* source-order plan SHA-256: **`a7e0b324e93e32059ab8d85166caa0f102fa787e54a81a37f802c7667ccafa77`**. This is frozen and byte checked **before** inference. Original v1/v2/v3 protocols and results are not overwritten or pooled.
- 9 original mechanical tasks × 2 order conditions × 2 separately publisher-pinned pretrained Readers (`smol-135m`, `smol-1.7b`) = **36 planned model calls**, with 1,024 input token and 64 output token limits. No training, adapters, tool invocations or answer-conditioned retrieval.

The reader-visible v4 plan excludes the v3 mechanical-support/oracle control and any explicit target marker. It includes only task text and source snippets in source-ranked and reversed order, preserving each source marker and byte-for-byte text. The scorer, in a separate process *after generation*, reopens the original SHA-verified Git blobs, uniquely identifies original declarations, checks complete original answers and ordered native `EvidenceBundle` receipts, and computes the paired contrast under both orders. All failed calls remain in the denominator.

## Interpretation

- A Reader that follows the first displayed source will score 7/9 under lexical order and only 1/9 under reversed order. Stable task accuracy across the counterfactual is a **limited indicator of positional robustness**, not proof of abstract reasoning, independent semantic entailment or long-term memory.
- There are only **three retrospective project-name independence proxies**; no inferential `N >= 200`, independent blind human oracle, authenticated production latency, cross-host recovery, revocation, or full TCO exists. Per-root comparisons are descriptive with null statistical intervals.
- Local original-ZIP-backed regression currently exercises **11 fail-closed tests** and a 36-row purely **synthetic** dual-tier postrun CLI. It does not count as any new pretrained generation.
- Only the GitHub Actions workflow `.github/workflows/hepta-memory-real-git-order-v4.yml` may generate actual 36 new model answers on the exact submitted SHA; output must have the complete original journal, external source pins, matched per-tier model inventories and an independent postrun score before being reported as a real experiment.
- Unmeasured lifecycle costs remain unknown; `production_qualified=false`, and no model promotion or FinalUse is authorized.

### Local reproducibility (source-only)

```sh
MEMORY_REAL_SOURCE_ZIP=ORIGINAL_ZIP MEMORY_REOPEN_ZIP=REOPEN_ZIP \
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p test_real_git_order_v4.py -v
python3 scripts/memory_cell/real_git_order_v4.py prepare \
  --source-zip ORIGINAL_ZIP --reopen-zip REOPEN_ZIP --plan NEW_PLAN.json
sha256sum NEW_PLAN.json
```

## Exact-HEAD resource guard

The workflow runs full model inference only for the research branch's `push` event;
`pull_request` runs check source formatting without launching an additional 36
pretrained model calls. Its isolated source-order concurrency group cancels
outdated v4 checks when a newer v4 commit arrives. This does not affect
v3 PR #2067 or the ranking baseline PR #2156. Once generation is running,
do not change the frozen branch head merely to force another execution.
