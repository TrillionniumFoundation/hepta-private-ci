# Population recovery and qualification-value consistency

This evidence belongs to the experimental Python Population owner. It preserves
the original failure attempts and a combined regression execution. It adds no
native evaluator authority, real task benefit or product adoption.

## Exact scope

- Parent: `a5bdfb5b7fbe4558fff7d8ad1ea85d3b33e21946` (#6089).
- Formatted implementation: `a194098c99e785d05a90e5e9f5a9de53df23ba96`.
- Implementation tree: `803b72533dd7157acc707503bdac8405df19c910`.
- The bounded JSON change is reused from #5937; it was absent from #6089.
- No original #5788 checkpoint, archived result, Rust file or CI workflow changes.

## Findings and resulting behavior

1. JSON containers, strings and keys must have canonical builtin types. The
   existing identity checks alone did not enforce this serialization boundary.
2. Removing or clearing every Population table must not reopen a planned owner
   as an unplanned owner while retained checkpoints still name its Population.
   Recovery now checks all retained checkpoints, stopping at the first relevant
   marker. This also covers a first checkpoint that lost its marker while later
   checkpoints still retain theirs. The original failure fixture actually adopted
   a three-update temporal candidate for an originally frozen CTRL after metadata
   loss. Refusal now leaves retained database content unchanged.
3. Qualification source, candidate and evaluation identities are canonical value
   snapshots across host validation. Noncanonical values and changed fields or
   candidate identities are refused before owner writes. Legitimate real temporal
   adoption and subsequent reopen continue to work.

The metadata-loss check assumes some original Population checkpoint evidence
remains. It is not a detector of arbitrary whole-database rewriting or rollback.
The injected host callback remains trusted. A digest and a canonical value do not
authenticate the evaluator, its held-out task custody, its result or its signature.

## Original executions

| Execution | Observed result |
| --- | --- |
| Original parent suite | 81 tests passed |
| Original parent with existing JSON regression | 4 failures in 7 methods |
| Original parent with lost-Population regression | 2 failing subtests |
| Intermediate first-checkpoint-only repair | 1 new recovery regression failed |
| Original parent with Qualification regressions | 9 failures in 12 methods; zero errors |
| Final combined implementation before formatting | **102 passed, zero failures/errors/skips**, source unchanged |
| Independent review of the Qualification implementation | 12 tests passed; same engineering cases, not extra independent tasks |

Python 3.12.14 and NumPy 2.3.5 were used with one OpenBLAS/OMP thread.
`just fmt` then passed through the repository's frozen Ruff 0.15.13. Normalized
ASTs were identical for all 26 checked Python modules. In accordance with the
repository instruction, the local tests were not repeated after formatting.
The precise pre-format bytes, complete test log and per-file before/after format
hashes are retained in `ORIGINAL_EVIDENCE.zip`. Hosted checks must qualify the
exact final head separately; these local results do not substitute for them.

From a checkout containing the final implementation:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s scripts -p 'test_hepta_cells_*.py' -v
```

`SUMMARY.json` binds every original archive member by size and SHA-256, including
the isolated baseline failures, intermediate recovery failure, test-development
attempts, source bindings, complete validation harness and tested-source ZIP.
The attempts overlap and must not be added as independent observations.

## Remaining gates

**DRAFT / RESEARCH_ONLY / HOLD / NoUpdate.** The seven lineages, 7–128 instances,
default two plastic instances and explicit 0–3 cap stay unchanged. Independent
native EVAL custody, the ordinary learning/adoption chain, cross-version hidden
state migration, actual negative-transfer-driven differentiation, held-out benefit,
retention and complete matched costs still require their own original evidence.
