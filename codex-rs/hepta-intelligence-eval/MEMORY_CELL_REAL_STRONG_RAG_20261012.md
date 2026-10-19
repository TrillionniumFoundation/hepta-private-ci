# MemoryCell: real, pinned Qwen calibrated-RAG closure — October 12, 2026

**Disposition: a real experiment and a separate-process replay both passed; the
current evidence is NOT sufficient to admit a learned/parametric MemoryCell or
production deployment.** This is a frozen, *authored and previously exposed*
eight-question development corpus, not new independent project histories.

## 1. Immutable provenance and execution

- Generating commit: [`6304b451268c73f3d1a605985226b102df841bbf`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/6304b451268c73f3d1a605985226b102df841bbf).
- [GitHub Actions run 38224780900](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900), completed on **2026-10-12**, attempt 2: `experiment-format`, `reader`, and `independent-replay` all **success**.
- Frozen original event plan SHA-256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`; original inputs ZIP SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`.
- Actual [reader artifact 11743043427](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900/artifacts/11743043427): ZIP SHA-256 `7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8`.
- Separate-process [replay artifact 11748040166](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38224780900/artifacts/11748040166): ZIP SHA-256 `2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071`.
- Recalculated SHA-256 of all **35 original, 43 reader and 8 replay manifest members** (86 total), with complete ZIP member census, unique file names and no silent omissions. All passed.
- Frozen research-only **Qwen/Qwen2.5-3B-Instruct** revision `82f42baa094a9600e39ccd80d34058aeeb3abbc1`; one actual CPU host reported BF16 support (AMD EPYC 9V45), PyTorch 2.5.1+cpu, two intra/inter-op threads. There is no precision/model substitution and no optimizer execution.

**The full original model census is real:** **40/40 calibration** and **72/72 evaluation** generations succeeded. The second job reloaded the original archive, recomputed bounded procedure results, checked exact source bytes, prompts/citation roots, per-arm scores and paired effects, without new model answers. It does **not** constitute an external human judgement or prospective validation.

## 2. What actual frozen-reader evidence proves

The calibration criterion first maximized strict task success, then minimized
measured prompt tokens and k. k=1,2,3,4 were each **4/8** on calibration;
k=6 was **2/8**. Thus the frozen choice **k=1** was a **cost tie-break**, not a
robust accuracy winner. Leaving out one question changed the choice to k=2 in
1/8 folds. These folds overlap and are not independent experiments.

| Qwen fixed evaluation arm | Exact task success | Complete program-declared source chain cited among correct answers | Input tokens (8 reads) |
| --- | ---: | ---: | ---: |
| `empty` | 0/8 | 0 | 1,630 |
| `selected_k` (calibrated k=1) | 5/8 | 3/8 | 3,961 |
| `hybrid_k4` | 3/8 | 1/8 | 10,806 |
| `hybrid_k6` | 2/8 | 0/8 | 15,463 |
| `hybrid_k4_reversed` | 3/8 | 1/8 | 10,806 |
| `single_hop` | 4/8 | 4/8 | 4,575 |
| `entity_time` (complete path, no correction pruning) | **8/8** | **4/8** | 5,752 |
| `organized` (explicit correction pruning) | **8/8** | **4/8** | 5,179 |
| `program_support` (authored program support, not a human oracle) | **8/8** | **4/8** | 5,179 |

The citation metric here means **the model cited all sources listed by the
authored test program and the formal public event chain passed the structural
check**. It does **not** establish semantic entailment or independence of
those program-designed support sets. Final-answer success and chain completeness
must always be reported separately.

**Paired attribution on exactly these eight authored cases:**

- `selected_k` minus `hybrid_k4`: **2 wins / 0 losses / 6 ties**. Of five k=1 correct answers, **two were produced without retrieving the full program-declared support set**. These must not be counted as proven grounded parameter memory.
- Full path `entity_time` minus `single_hop`: **4 wins / 0 losses / 4 ties**. The four recovered questions were the authored composition/procedure cases. This supports a **within-fixture traversal effect**, not broad generalization.
- `organized` minus `entity_time`: **0 wins / 0 losses / 8 ties**. Explicit correction pruning changes the selected evidence on two correction cases, reducing aggregate input tokens by **573 (9.96%)** with no extra correct answer. Both were 8/8 already.
- Original reader-level seconds totaled **79.20** (`entity_time`) versus **73.52** (`organized`) across eight outputs. They are not p95 latency, billed CPU/GPU cost or full lifecycle expense; the index, source storage, maintenance and revocation are not fully accounted for.
- **39** pairs of identical question and ordered evidence were re-audited: zero decoded-answer or generated-token disagreements. That is repeatability in these archived deterministic calls only.

## 3. Independent local cross-check (new receipt)

[`scripts/memory_cell/archived_rag_disposition.py`](../../scripts/memory_cell/archived_rag_disposition.py)
independently reconstructs both cohorts from the *three externally pinned ZIPs*
and the original 108 sources / 16 labels. It refuses missing or extra ZIP
members, modified raw answers, mismatched evidence excerpts/roots, unknown
selection order, missing citation links, wrong bounded program execution,
tampered cost totals, wrong top-k, changed leave-one-out folds and mismatch with
the separate-process replay summary. It does not call Hugging Face, load model
weights, train a head, or assert that authored support is a human truth judge.

The machine-readable result is
[`scripts/memory_cell/data/strong-rag-38224780900-verified.json`](../../scripts/memory_cell/data/strong-rag-38224780900-verified.json).

Run with the exact original source ZIP and the two named Actions artifacts:

```sh
PYTHONPATH=scripts/memory_cell python3 \
  scripts/memory_cell/archived_rag_disposition.py \
  ORIGINAL_INPUTS.zip REAL_READER.zip SEPARATE_REPLAY.zip NEW_REPORT.json
PYTHONPATH=scripts/memory_cell python3 -m unittest -v \
  scripts/memory_cell/test_archived_rag_disposition.py
```

`test_archived_rag_disposition.py` contains 14 self-contained model-free tests.
The archived model was executed only in the original Actions run; the new
verifier merely independently replays recorded deterministic facts/metrics.

## 4. Promotion decision and next controlled experiment

**Parametric-learning promotion: REJECT / NOT QUALIFIED.**

The organized reader has no demonstrated additional task-success gain over
full-path filtering on these exposed eight questions. The current 4/8 complete
citation-chain rate falls short of any plausible 99% citation requirement,
and *no independent future source family*, longitudinal retention/revocation,
or deployed lifecycle cost has been supplied. Nothing here establishes a 10T
or 100T-equivalent model from Cell splitting.

The next experiment should **first diagnose the reader's missing citation
chain under genuinely sufficient evidence**, without adding Cell parameters:
keep exactly the same Qwen reader, original sources, strict budget and tools;
pre-register (i) baseline unchanged answer prompt and (ii) an explicit
*source-chain citation instruction* as an input-format intervention, and
independently check that a complete chain is actually cited (without
post-processing citations). Test on **new, separately collected source families**
with human-reviewed evidence sufficiency. Only after that read-path baseline
should a learned small Head be compared against frozen encoder + deterministic
selection at equal model/read/maintenance cost. The production and `blocking-ci`
gates remain authoritative, not bypassed.
