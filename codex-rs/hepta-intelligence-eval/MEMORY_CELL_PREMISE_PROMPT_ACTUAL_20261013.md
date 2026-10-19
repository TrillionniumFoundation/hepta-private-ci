# Completed 64 real frozen-Qwen premise-citation prompt pairs — NO-GO

**13 October 2026 · Real model answers, not a simulation or new training.**

Original GitHub Actions run [38385138211](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38385138211) **completed successfully** (both prompt-contract and actual-frozen-reader jobs). The generating commit is `fd7e19ccc7bee86afe6bf49f3eab9a75fc1badd9`. The exact original answer artifact is **11807202555**, whole ZIP SHA-256 `6743f0e054b44eea6a7e1eadf7e27651ced94df7885b95e6da81fd82a3075cff`, containing **64/64 real model generations** and **19/19 authenticated original member files**. No answers were repaired, replaced or newly generated for this analysis.

The unchanged original eight-case source plan came from artifact **11669174727**, ZIP SHA-256 `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b`; all **35** original member hashes verified, with frozen plan SHA-256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`. Fixed Qwen inventory digest `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`. Within each paired task the reader, exact ordered original evidence and greedy-generation ceiling remain the same; only the system-level premise-citation instruction changes.

| Frozen same-reader condition (8 matched questions) | Original strict right | Revised prompt strict right | Original right with full formally declared citations | Revised right with full formally declared citations | Extra input tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hybrid top-4 | 3/8 | 4/8 | 1/8 | **0/8** | +632 |
| Organized correction-aware | **8/8** | **3/8** | 4/8 | **2/8** | +632 |
| Program-declared support (privileged diagnostic) | **8/8** | **3/8** | 4/8 | **2/8** | +632 |
| Deliberate one-premise omission | 4/8 | 4/8 | 0/8 | 0/8 | +632 |

All 32 matched pairs add **2,528 input tokens** (23,967 to 26,495, about **10.55%**) under the revised instruction. Across organized and program-support conditions, five outputs per condition truncate the identifier to `site_` or `mode_` (same five underlying questions, not ten independent failures), yielding **five losses and zero wins** in each. The revised prompt does not increase complete declared-source citations even on the hybrid condition despite one additional correct answer. The changed output-token totals are 398 to 314 for the full 64-call paired intervention.

An independent standard-library checker downloaded the two original ZIPs, verified their **outer and every inner SHA256**, loaded the unchanged source plan and original answer journal, rebound selected original source bytes to delivered Reader evidence and citation requests, rechecked the registered strict identifier grammar and executed bounded procedure semantics from original recipes, compared each unmodified raw answer with scored output, and recalculated source-chain coverage, paired wins/losses and token costs. The accompanying local tamper regression suite passed **12/12** tests: mismatched ZIP/manifest/source, modified raw/scored answer or prompt digest, missing attempts, unsafe procedure modes and malformed JSON are rejected. These mechanical validations are not human semantic entailment judgements.

The machine-readable [observed-premise-prompt-38385138211.json](../../scripts/memory_cell/data/observed-premise-prompt-38385138211.json) contains pinned provenance and aggregate counters only; it does not copy model answers, private targets, or model weights into source control.

**Disposition:** `prompt_promotion_qualified=false`, `parametric_memory_training_qualified=false`, `independent_semantic_entailment=false`, `production_accepted=false`. This *specific* prompt suffix is a research NO-GO: it harms even the stronger evidence baselines and consumes more input tokens. It does not establish that every possible citation method fails. Further qualifying tests require genuinely new source-family questions, independently reviewed sufficient premises, unchanged frozen Reader, prespecified answer AND full-citation metrics, and observed operating costs. No `blocking-ci` bypass or production write/adoption follows.
