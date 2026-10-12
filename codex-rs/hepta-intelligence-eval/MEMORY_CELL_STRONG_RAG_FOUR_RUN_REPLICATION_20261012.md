# MemoryCell — four completed frozen-Qwen runs and exact-output replay

**2026-10-12 · Read-only reproducibility · Development evidence: NO-GO for incremental organization or production.**

This audit checks **four completed original 40-calibration + 72-nine-arm Qwen generations** each, a total of **448 actually generated responses**. All answers are from the **same eight previously exposed, authored test tasks**; repetitions do not create 32 independent questions, new source families, real future observation windows, or independent human semantic citation judgments. No new model inference or training is performed by the auditor.

## Pinned generating runs, original source and independent replay

| Run | Source commit | Actions run | Whole workflow | Original Qwen answers artifact ZIP SHA-256 | Independent replay artifact ZIP SHA-256 |
| --- | --- | --- | --- | --- | --- |
| A | `8250698244417eb14994518af05fa6f79e783066` | [38148514657](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38148514657) | Success | `7c991f0996fc24c650efb28f6266da51ed1655b78585e11b78dbc424707b7b7f` | `7e390bddfb1c59e0bb82999b01747a180eb1ec1f84d9f863a536dd036ec483f1` |
| B | `eba9af092cca1c2875552ffaea2219678143a73c` | [38146546731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38146546731) | Success | `b4cf1346ce4c5b1625cdc57845bcca33fcf82f84340433b602d76258c10c1138` | `4c64e9c01bef56d0f311e633af53c7a246102e7083a272122286fb7ff66085a3` |
| C | `c24fad24b65984a6255a8854c6714c141911ff79` | [38114667490](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114667490) | Failure: separate broad format job | `2d71f40e553e7d28cad9d8e16803f52b7a99e771b5bf54f55c89bc9468702107` | `fe710be3f987e34ec3cda48be37509e20a01b48db090907c98ce33cfff198225` |
| D | `e0e413d670be8982b9986a119696c6ca164ca518` | [38161049090](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38161049090) | Success | `d59560882e217d8772e4044ec33b8cdb10f5297f19b0a6e03e53266407c839a0` | `9a4dfb20f0ab5bb6de6ed577e7787d3faa8c02f5a842198a5b1b1eafced2ea53` |

For C, the actual Qwen **reader and independent replay jobs both succeeded**, but its separate format job failed. We do **not** relabel C's whole workflow as successful. The four original archive ZIPs contain respectively 267, 267, 38 and 300 verified SHA256SUMS-listed regular source/output files; the corresponding replay ZIPs contain 1, 1, 8 and 1 member files. Outer ZIP SHA and complete inner manifest were verified, and original unscored journal bytes were compared against scoring and independently replayed receipts. Run D was **not** in the previously published three-run comparison.

All runs bind the frozen event plan SHA-256 `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`, same model inventory digest `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`, exactly 40 calibration and 72 evaluation records per run, identical source ordering, identical delivered verbatim excerpts, and identical complete input token-ID digests for all **112 original question/arm inputs**. Every run calibrated **k=1**.

## Original same-reader task and complete-source-chain evidence

Every number below is successes **out of the same eight authored tasks**; a chain-success requires the declared program support sources to be cited and does not prove independent semantic entailment.

| Frozen intervention | Task right A/B/C/D | Task right with full declared citation chain A/B/C/D | Complete input tokens (each run) |
| --- | --- | --- | ---: |
| Calibrated Hybrid top-1 | 5 / 5 / 5 / 5 | 3 / 3 / 3 / 3 | 3,961 |
| Fixed Hybrid top-4 | 3 / 3 / 3 / 3 | 1 / 1 / 1 / 1 | 10,806 |
| Hybrid top-6 | 3 / 3 / 2 / 2 | 1 / 1 / 0 / 0 | 15,463 |
| Hybrid top-4 reversed | 2 / 3 / 3 / 2 | 0 / 1 / 1 / 0 | 10,806 |
| Original-source single-hop | 4 / 4 / 4 / 4 | 4 / 4 / 4 / 4 | 4,575 |
| Full-path entity/time filtering | **8 / 8 / 8 / 8** | 4 / 4 / 4 / 4 | 5,752 |
| Correction-aware organization | **8 / 8 / 8 / 8** | 4 / 4 / 4 / 4 | 5,179 |
| Program-declared support | 8 / 8 / 8 / 8 | 4 / 4 / 4 / 4 | 5,179 |
| No evidence | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 1,630 |

**Measured attribution on the exposed corpus:** full-path relation traversal beats single-hop by **4/8 correct answers** in each run. Correction-aware organization improves on full-path filtering by **0/8 additional task wins and 0/8 additional complete declared citation chains**. Organization sends **573 fewer input tokens (9.96%)** for the eight tasks, not measured complete ingestion, retention, revocation, recovery or deployment cost. There is **no learned/parametric intervention** in these results.

## Cross-host original answer instability

Same pinned prompt input does **not** guarantee bit-identical generated output across hosts. Across four executions, **13 of 112 distinct original question/arm inputs** vary in decoded output and/or generated-token SHA (**4/40 calibration, 9/72 evaluation**). **Two** evaluation question/arm inputs change their strict task correctness between runs: `controlled_cbfd4ba5`/`hybrid_k6` and `controlled_f0609607`/`hybrid_k4_reversed`. The fourth run does not introduce new unstable input positions beyond those already detected in the three-run report. These are **13 unstable prompts**, not 13 independent task failures, and changed outputs are never normalized or repaired.

Intra-run identical-evidence controls and cross-run prompt identity are different checks; neither can substitute for the other. Stability differences are attributed to runtime/host nondeterminism until independently characterized, not to MemoryCell learning.

## Machine reproduction and acceptance boundary

`strong_rag_fourrun_audit.py` reads eight explicitly pinned GitHub Actions ZIP files, verifies each outer SHA-256, exact safe file census, inner SHA256SUMS, original source/reader identity, raw-vs-scored journals, full independent replay receipts, the unchanged original prompted evidence, and recomputes task and citation-chain summaries and output flips. Any mismatch fails. `test_strong_rag_fourrun_audit.py` covers tamper and mismatch scenarios plus the complete four-real-archive test when `HEPTA_MEMORY_FOURRUN_ARCHIVES` points to the eight ZIPs.

The read-only `.github/workflows/hepta-memory-strong-rag-four-run-audit.yml` fetches the **eight existing artifacts**, runs these tests, independently recomputes and byte-compares the committed JSON report, and retains a SHA256SUMS receipt. No model weights are downloaded or re-uploaded, no new model inference is run, and no serving configuration is touched. This workflow is **research evidence only**, not the repository's signed production acceptance path or a replacement for required `blocking-ci`.

**Decision:** NO-GO for an incremental organizer **task/citation-chain superiority claim**, parameter-memory training escalation based on these tasks, ≥99% independent semantic citation precision or production deployment. Independent new source families, prospective time windows, task breadth, formal human entailment adjudication, full lifecycle cost, signed observer evidence and actual authorized recovery/rollback remain absent. Four repeats of the same tasks cannot establish generalization.
