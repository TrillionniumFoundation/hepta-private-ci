# MEM8 checkpoint repair V14

## Qualification boundary

The new V5 **source-only gates and exact-source Bazel module-lock check passed**. Their exact formatter output has been reviewed, materialized as a pure source commit, and published to the draft integrated source PR. New full native CI is running on that source. Its Blob/Fence job has already failed before checkout, so the required hosted CI gate remains open. These source and lock results do not close the provider, owner, independent trust, or memory-benefit adoption gates. This checkpoint does not authorize deployment or claim all blockers closed.

The evidence below distinguishes the original `189711` runs from the new V5 source operation. Historical failures, missing terminals, and unknown admissions remain part of the record.

## New source operation: actual result

| Identity or result | Exact value |
| --- | --- |
| Original successful source-only run | [43015979473](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43015979473), job `130507034042`, attempt 1 |
| Workflow commit | `720f7ff5042a66490e2433bf4652c2eef93e4b7d` |
| Pure source checked out | `c842e995b047eb2ee7d81c073f14fb2fcaa6bff2` |
| Initial source tree | `e9ba2746237562d68b1c732bee0f86df9e352cde` |
| Formatter output tree | `c77785ecb368c44ea699769001a47402c9f50591` |
| Reviewed formatter output materialized as | `9bd2f589debdba4a93baa363817c3669cb103721`, parent `c842e995b047eb2ee7d81c073f14fb2fcaa6bff2` |
| Original time budget | 600 seconds |
| Actual driver interval | `2026-11-11T11:56:16.122508+00:00` to `2026-11-11T12:02:50.118524+00:00`, 393.996016 seconds |
| Complete overlay | 103 paths against `2ae5215beaf8d7b7df111a090b82134beae2683d`; 14,048 final tree entries |
| Format changes | 21 paths, reviewed in full; Rust formatting/import ordering and BUILD load/keyword ordering, plus final newline |
| Whole tracked-tree old-name scan | All 13 old case names scanned, zero hits, no path exclusion |
| Caller proof | 6,200 Rust files; `PASS_HEPTA_CALLER_CLOSED_SET`; `authorityGranted=false` |
| Locks | Cargo and Bazel lock bytes unchanged by source gates |
| Native project tests / real model requests | 0 / 0 |

The source checkout was initially clean. At completion the original source HEAD and its tree were unchanged, with exactly 21 formatter changes staged. It is incorrect to call that a clean-after checkout. The new pure formatter commit was created only after independent review; no source ref was changed by the CI driver.

Root independently verified the entire original 6,299,090-byte ZIP (337 regular members and CRCs), its 1,783,500-byte records archive (335 members), all manifest bytes, and three complete Git Merkle trees. All 103 pre/postimages and all 21 full Git readbacks of the new formatter commit match. See [the root source audit](v14/ROOT_SOURCE_CI_V5_AUDIT.json), [its verifier](v14/verify_source_ci_original.py), [the full formatter diff](v14/FORMAT_ONLY.patch), and [the pure-source publication receipt](v14/FORMATTED_SOURCE_PUBLICATION.json).

The earlier source workflow run `43015488785` on `803e7e48b06a237a98abbf0248422040f82c06c5` completed with failure and **zero jobs**. Static review identified `runner.temp` references in an unsupported job-level `env` expression context; the correction moved those three paths into a step and wrote their values to `GITHUB_ENV`. The original parser annotation was not obtained, so no fabricated literal error is recorded. The successful run is a separate changed-workflow execution, not a retroactive reinterpretation of the zero-job failure.

## What the source contains

The candidate retains the previously reviewed source repairs and adds the following bounded changes, each with its own scope:

- A fresh-owner qualification clock for selected lease-expiry tests, with ordinary production clocks and expiry checks retained. Native and Bazel build validation are still required.
- Corrected model-list wire/cache comparison and remote-control test fixtures; failure-stage observations for startup, Matrix, neuron, and plugin cache paths retain the original assertions and deadlines.
- Corrected the pinned Nextest JUnit location. The earlier MEM guard failure remains an original failure; its exact runtime branch was not traced.
- A typed Windows restricted filesystem-write check that uses the same opened handle, requires a regular file with exactly one hard link before truncation, and preserves the unrestricted path. This does not establish shell/delete isolation or protect against all concurrent alias races.
- Ordinary-host Windows delete diagnostics that observe existing token privileges, volume ACL capability, and same-object access results. These are diagnostics, not a deletion-isolation repair.
- Explicit retirement of a durable-holdout file lock, following the already-used retained-file ownership pattern. The original Apple `Busy` failure is consistent with a retained open-file-description mechanism, but no specific fork/duplicate source was proved.

## Original `189711` CI: full evidence retained

The old source was `189711e3563ea13a5328d52e99a286f082045b98`, tree `e253b99e0a5c3b3a680569da0d224fabff0781ba`. Its results must not be attributed to the new formatter tree.

| Original lane | Verified result and limit |
| --- | --- |
| Blocking CI, run `43002359918` | 37 jobs: 23 success, 10 failure, 4 skipped. Native failures and the required aggregate remain failures. |
| Failed-job retry | Only Blob policy job `130483156553` and required aggregate `130483324196` were actual new executions. Other representative job IDs reused the original execution timestamps; skipped jobs are not native executions. |
| Blob/Fence, both actual executions | `local_control_inventory_unavailable` before checkout. Static inspection found no missing required workflow inventory input. The exact unavailable runtime observation remains unknown. No mode or policy relaxation is introduced. |
| macOS Intel | 120 final Bazel target summaries, 10 nonpassing targets. Printed repeated failure names are not independent case counts. |
| macOS ARM | 114 final Bazel target summaries, 4 nonpassing targets. |
| Windows-current, run `43002359812`, job `130461336393` | Cancelled. 15 of 19 groups completed: 139 distinct package/case terminals, 137 PASS, 1 LEAK, 1 FAIL. 13 groups passed strictly. 28 expected cases have no terminal. No source-after or final aggregate exists. |
| MEM native / Python / integrity | 17 native cases, 119 Python cases, and 35 integrity cases passed in their respective lanes; the native qualification guard failed before protocol and fix stages. These are separate denominators. |
| Architecture | Base-merge lane: 136 Python cases. Source-head lane: 526 Rust cases and 138 Python cases. They are not a single unique actor-benefit count. |

The Windows-current failure classification is corrected explicitly: the ordinary-host four-cell delete check passed in that run. The explicit elevated child then deleted outside-root file and directory objects in TargetOnly, ParentOnly and Both; Neither remained. The original all-false outside-root assertion failed. A separate output test reported LEAK. This is different from the earlier Bazel Windows ordinary-host Neither precondition failure.

Full original archives and manifests are under `v14/original-ci/`. Root rechecked all four additional archives, their complete manifests, 13 full Fence primary sources, seven terminal logs, the 22-member Windows ZIP, and all 139 pre-summary native case terminals. See [the archive audit](v14/ROOT_ORIGINAL_ARCHIVES_READBACK_AUDIT.json) and [its verifier](v14/verify_original_archives.py). The MEM/Architecture multipart archive, its complete original ZIPs and command receipts have a separate [root audit](v14/ROOT_MEM_ARCH_READBACK_AUDIT.json).

## Unknown operations and recovered preparation evidence

The earlier V3 source-process admission remains UNKNOWN. No different-key replay is authorized or counted. V4 had timed-out file-upload requests but **zero source-process start requests**; upload effects are unknown, not an admitted V4 source execution. V5 used the independent exact-source CI operation above.

The transient local environment reset during preparation. The immutable Git evidence, original CI artifacts, and retained tool results allowed recovery of the full source inputs, host/CI drivers and primary receipts. Root fully read both remote archive parts and verified all 28 regular members, the losslessly embedded V4 input, 204 complete V4/V5 source rows, three drivers, and both workflow revisions. All 101 V4 rows are byte-identical in V5.

Exact-byte recovery is distinguished from newly reconstructed indexes. **Fifteen original local preparation files were not recovered**, including assemblers, intermediate indexes/diffs and a local-only 12,117-byte formal peer-review draft that had not been uploaded. Known hashes or remembered conclusions do not replace those files. The [preparation publication index](v14/source-preparation/PUBLICATION.json) lists every missing original; the [root readback audit](v14/source-preparation/ROOT_READBACK_AUDIT.json) preserves `original_artifact_recovery_complete=false`. This recovery of source and primary evidence is not complete recovery of every preparation file, and is not the deployed full-owner/effect cold-recovery milestone.

## Exact-source Bazel module-lock operation

The older V2 Bazel lock check passed on its own tree. It does not qualify the new V5 dependency graph. A separate exact-source lock operation was admitted at `2026-11-11T12:25:22Z`: workflow head `8ead9735ecd78721f306f03e49dbd57894a474d0`, [run 43020198388](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43020198388), job `130521184483`. The run failed in the version preflight with **zero lock-command phases started**. Its combined output contained the Bazelisk download notice and the correct `bazel 9.3.0` version; the probe itself exited 0 after 0.616122 seconds, without timeout. Comparing the combined streams to the exact version string caused the driver failure. Source-before was the exact clean `9bd2f589debdba4a93baa363817c3669cb103721`; no source-after record exists and no clean-after claim is made.

The correction separates and preserves stdout/stderr, while retaining the exact stdout version check, the 30-second probe deadline, and the original 1,200-second single `just bazel-lock-update` budget. The changed-workflow revision `d03aa4c87d4f9fe9c1f99fbe319f829d9eef6158` was admitted at `2026-11-11T12:30:31Z`. Its original [run 43020939762](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43020939762), job `130523679401`, executed one actual lock command from `12:31:12.445078Z` to `12:31:38.908320Z`: **26.462319 seconds, exit 0, no timeout or output overflow**. The exact source `9bd2f589debdba4a93baa363817c3669cb103721`, tree `c77785ecb368c44ea699769001a47402c9f50591`, was clean and unchanged before and after.

Both lock files were byte-identical: Cargo.lock, 421,005 bytes, SHA-256 `98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69`; MODULE.bazel.lock, 1,788,299 bytes, SHA-256 `783b3ad329fa53bd4a0e48be6907d38259fa2880d61bd1994b863d7f78bbca57`. Original module-resolution and crate-annotation warnings remain in the 3,211-byte command log; no check or warning was disabled. This is module-lock qualification, not a native test result.

Root verified both complete original Bazel ZIPs and records archives, the failed preflight's zero command phases, the successful run's one command phase, source identities, command receipts and both pre/post lock pairs. See [the original admission](v14/BAZEL_V5_ADMISSION.json), [revision 2 admission](v14/BAZEL_V5_REVISION2_ADMISSION.json), [root actual-run audit](v14/ROOT_BAZEL_V5_AUDIT.json) and [verifier](v14/verify_bazel_v5_original.py). The first failure is retained separately and is not relabelled as a pass.

The complete source-only and two Bazel original runs are also durably preserved in their [source archive index](v14/source-ci-v5/PUBLICATION.json) and [Bazel archive index](v14/bazel-ci-v5/PUBLICATION.json). Root independently fetched every one of the 18 remote raw archive parts, verified all three original ZIPs including CRCs, all inner members and their manifests, and retained [the full archive readback audit](v14/ROOT_FULL_CI_ARCHIVES_READBACK_AUDIT.json). Multipart transport is an archive mechanism, not a new execution.

## Published source and new native runs

The source ref update at `2026-11-11T12:36:36Z` used an expected-head lease from `189711e3563ea13a5328d52e99a286f082045b98` to `9bd2f589debdba4a93baa363817c3669cb103721`. Independent ref and PR readbacks confirm the new source and that [PR #5935](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5935) remains a draft. The [publication receipt](v14/SOURCE_V5_PR_PUBLICATION.json) preserves the exact request and readbacks. No merge or deployment was performed.

| New original run | Scope |
| --- | --- |
| [43021840778](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43021840778) | Ordinary blocking CI |
| [43021840252](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43021840252) | Private core qualification |
| [43021840437](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43021840437) | MEM Python, episodic/source-memory and native qualification |
| [43021840388](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43021840388) | Architecture base-merge and source-head lanes |
| [43021840561](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43021840561) | Windows-current original 167-case scope |

The new blocking run's Blob/Fence job `130526677869` failed with `local_control_inventory_unavailable` before checkout. Root preserved and inspected its full original 3,859-byte decoded log, SHA-256 `f50cdc9fa4044764eaa7a79468bec7e0dae90b2aa103ec231bfced4d19267f00`; no product test was executed by that failed job. The exact missing runtime observation remains unknown. The policy and checker stay unchanged; no retry was admitted. See [the initial original API/log archive manifest](v14/new-source-initial/MANIFEST.json). Other native lanes were still running when this checkpoint was prepared. Their completed original artifacts are being audited separately; neither old `189711` counts nor a successful step are copied into a new native pass count.

The ordinary blocking merge commit `8644d1044c50c7d4bfa47834f2602d133433300d` has the same full tree as source `9bd2`, with base/source parents `96038ccf0660154fac143ba6cbe4be81e00813e8` and `9bd2f589debdba4a93baa363817c3669cb103721`. Tree equality is recorded without collapsing distinct workflow, checkout and execution identities.

## Windows product and execution boundaries

The elevated outside-delete product review is preserved separately as [22 full exact sources plus original ACL evidence](v14/windows-elevated/PUBLICATION.json). Root read the full source review, verified the entire remote archive and independently decoded all 12 original ACL objects. Removing broad restricting identities alone does not close the original parent-delete counterexample or the read, desktop/WinSta0, and WFP compatibility obligations. No unqualified partial production patch or disabled-feature result is presented as recovery; see [the full review](v14/windows-elevated/REVIEW.json) and [root audit](v14/windows-elevated/ROOT_READBACK_AUDIT.json).

A separate [conditional successor plan](v14/windows-successor-plan/REPORT_V2.md) retains every one of the original 167 package/case identities and proposes three existing restricted-write helper cases in a separate supplemental group. Current Windows CI still runs **167**, not 170. The four proposed partitions would have 93, 14, 41 and 22 cases, each original group included once; four separate original 65-minute budgets would be an explicit new scheduling topology with a 260 job-minute upper bound, not an extension of the cancelled old run. No successor harness or additional native execution was created for this plan. Cold-build completion is not guaranteed. The enabled core hard-link integration regression is outside that 170-case list and requires its own original blocking/private evidence.

The original packet is preserved byte-for-byte. [A narrow erratum](v14/windows-successor-plan/BUDGET_ATTRIBUTION_ERRATUM.json) replaces an overstrong cancellation-cause sentence: API `cancelled` and log `KeyboardInterrupt` are observed; timing consistent with the 65-minute job configuration supports an inference only. The scheduler's cancellation reason is still unknown. Root verified the complete 23-member remote packet and all four v2 text readbacks; the only plan change adds that evidence distinction. The old static plan audit remains attached to its original bytes and is not presented as a newly executed v2 validator.

## Remaining adoption gates

All ten adoption gates remain open: working-state scientific benefit; ordinary owner bridge; provider runtime binding; unseen episodic benefit; matched strong baselines/association; source ownership/exposure/independent trust; deletion/external effects; full-owner effect cold recovery; complete cost/slow consolidation; hosted required CI.

The retained-memory estimate is still the existing MEM6 result: 30/84 versus 28/84, two wins and 82 ties, with 16 initial no-ops per arm. The source-balanced lower bound does not meet adoption. There are no new scored actor episodes or real model requests in this checkpoint. Exact KV, BM25/RAG, ICL and uniform replay fixtures do not substitute for matched native actor evidence.

The original unknown real-provider admission is retained under its original identity. No new real-provider generation, no different-key replay, and no Provider G execution is introduced. Full closure still requires the actual owner/runtime/store and authority inputs, reviewed source-exposure records and an admissible unseen cohort, independent final-use trust and revocation evidence, the original provider terminal/journal, matched successor-task outcomes, and full-effect recovery/cost evidence. Those inputs cannot be manufactured by adding tests or growing an evidence archive.
