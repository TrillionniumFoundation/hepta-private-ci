# MemoryCell — completed frozen strong-RAG reader result and research disposition

**2026-10-11 · Exact source commit `c24fad24b65984a6255a8854c6714c141911ff79` · NOT production acceptance**

This is the first **completed, source-pinned 40-call calibration + 72-call nine-arm Qwen research run** in this experimental line. It covers eight previously exposed *authored* calibration questions and eight previously exposed *authored* evaluation questions. The result is real pretrained reader inference, not a mocked unit test or historical six-arm extrapolation.

The [GitHub Actions run #38114667490](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114667490) completed its source-scoped format checks, actual Qwen reader and **separate-process read-only independent replay** successfully. The workflow as a whole is **failure**, because its separate **PR-wide formatting** job failed. A green reader/replay does not imply a green PR, independent human review, or readiness to merge or deploy.

## Frozen sources and verification

| Original object | GitHub identifier | Exact ZIP SHA-256 | Manifest files verified |
| --- | --- | --- | ---: |
| Authored event input/plan | artifact `11669174727` | `23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b` | 35 |
| Actual Qwen calibration and nine-arm output | [artifact `11696514149`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114667490/artifacts/11696514149) | `2d71f40e553e7d28cad9d8e16803f52b7a99e771b5bf54f55c89bc9468702107` | 38 |
| Separate-process read-only replay | [artifact `11696898778`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38114667490/artifacts/11696898778) | `fe710be3f987e34ec3cda48be37509e20a01b48db090907c98ce33cfff198225` | 8 |

Original plan SHA-256: `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.

An additional offline audit independently checked **all 81 inner manifest files**, the immutable original plan, the exact model and auditor generating commit, the complete 40+72 raw and scored answer census, unmodified original answer/receipt fields, per-arm scored success and measured prompt-input token sums, the frozen calibration policy, and the separate process's recomputed citation and paired results. There were **zero** missing or failed model generations.

## True pretrained-reader calibration

| Frozen hybrid top-k | Correct / 8 calibration tasks | Prompt-input tokens |
| --- | ---: | ---: |
| k=1 | 4 | 4,045 |
| k=2 | 4 | 6,328 |
| k=3 | 4 | 8,698 |
| k=4 | 4 | 10,970 |
| k=6 | 2 | 15,708 |

The predeclared success-first/token-second selection rule froze **k=1** before the final evaluation. However, removing each calibration example and reselecting yields **k=1 on seven folds and k=2 on one fold**. This is **not a leave-one-out stable selection**; the held-out LOO outcomes are selected-k **3/8** versus fixed k=4 **4/8**. These overlapping folds do not provide an independent confidence interval.

## Nine-arm Qwen evaluation — eight authored questions per arm

| Condition | Correct | Correct with all program-declared source citations | Delivered sources cover authored support | Complete prompt-input tokens | Recorded reader seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calibrated hybrid top-1 | **5/8** | 3/8 | 3/8 | 3,961 | 58.962 |
| Fixed hybrid top-4 | 3/8 | 1/8 | 8/8 | 10,806 | 118.435 |
| Hybrid top-6 | 2/8 | 0/8 | 8/8 | 15,463 | 163.135 |
| Hybrid top-4, reversed | 3/8 | 1/8 | 8/8 | 10,806 | 117.895 |
| Actual single-hop | 4/8 | 4/8 | 4/8 | 4,575 | 61.750 |
| Full-path entity/revision filter | **8/8** | **4/8** | 8/8 | 5,752 | 74.147 |
| Correction-aware organized | **8/8** | **4/8** | 8/8 | **5,179** | 69.174 |
| Program-declared support | **8/8** | **4/8** | 8/8 | **5,179** | 69.182 |
| No evidence | 0/8 | 0/8 | 0/8 | 1,630 | 33.500 |

All 72 evaluation attempts succeeded. For the same question and identical ordered evidence, the **39 matched prompt pairs** showed **zero** answer, token-output or task-result disagreements. The independent replay recomputed these results without generating new model answers.

**Controls and interpretation:**

- Full-path entity/revision filtering versus single-hop: **four paired wins, zero losses, four ties**. Those four wins are concentrated in the two-hop composition and constrained procedure cases; this identifies a *controlled authored-task* benefit of complete path context, not an independently generalizable memory gain.
- Correction-aware organization versus full-path entity/revision filtering: **zero wins, zero losses, eight ties**; the organizer saved **573 input tokens, or 9.96%**, across the eight tasks. It did **not** improve answer accuracy or formal cited-chain completeness.
- Calibrated top-1 versus fixed top-4: **two wins, zero losses, six ties** on the final authored eight tasks, but calibration is LOO-sensitive and the selected top-1 only covered the *program-declared* complete support set on 3/8 questions even though it answered 5/8 correctly. This underscores the limits of treating program-declared support as necessary and the risk of shortcut success.
- Fixed top-4 RAG already contained all program-declared source IDs on **8/8** questions yet only answered **3/8** correctly. This implicates distractor/prompt/read-use behavior, not simply missing retrieval recall.
- Full-path and organized both answered **8/8** correctly while completely citing the program-declared sources on only **4/8**. This is **not** a human semantic entailment verdict; it also cannot establish ≥99% citation quality.

## Explicit research disposition

**Stage 1/2:** Frozen-reader evidence availability, calibration, nine-arm matched development outputs and mechanical independent replay have completed **for this exact authored development census**. The organizer **does not dominate** the simpler full-path filter on task accuracy; it has only an observed token-saving effect at this scope. All costs omit deployed ingestion, retention, indexing maintenance, revocation, disaster recovery, and independent operational observation.

**Stage 3:** Neither learned read policy nor source-written parametric memory is qualified for a claimed gain on the basis of these results. Before escalation, require independently sourced future evaluation and a same-reader/same-tools comparison against the strongest simple full-path baseline and the actual calibrated RAG policy. LOO stability must be addressed and full citation-chain/semantic review reported separately from end-answer correctness.

**Stage 4/production:** Not qualified. Source necessity is still a program-authored assumption rather than independent human judgment; independently sampled source families = 0; citation entailment precision is unadjudicated, statistical superiority is unproven, production cutover/rollback and lifecycle costs are unobserved. The separate PR-wide formatting and required CI gates have not passed for this source.

**Machine-readable receipt:** `scripts/memory_cell/data/actual-strong-rag-38114667490.json`, generated from the three SHA-pinned GitHub Actions ZIPs. The checks and all numeric summaries are frozen to generating commit `c24fad24`; they must not be relabeled as results of a later PR head.
