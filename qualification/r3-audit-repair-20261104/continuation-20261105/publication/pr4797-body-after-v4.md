## Current continuation candidate — original platform qualification open

The latest original CI exposed a duplicate musl platform label, pinned-format differences, spelling findings inside immutable evidence, a staged V8 feature mismatch, and a Mac Bash empty-array failure. This continuation fixes those evidenced causes and adds bounded test-only observation for the unresolved Intel PTY failure.

This PR remains **Draft** on the same integration base. The branch was updated on **2026-11-05 09:02:20 UTC**, and the head/base/Draft readback was verified at 09:02:33 UTC.

| Identity | Value |
|---|---|
| Published head | `5b6331250ff459033bd44d1a95daec70131277cc` |
| Published tree | `b26598d0d97d8d51e723bb5582137315f2174d35` |
| Previous published head | `0e139b599f0fe451f80fb7db4b2913bb9c679dce` |
| Unchanged base | `63652be658ebed8d3052eb789b951793384fd5e4` |
| Scope since previous head | 7 sequential commits, 10 paths |

### What changes

- Deduplicate identical canonical musl platform labels while retaining empty/conflicting-label and actual product build/ELF/CLI gates.
- Apply the exact Rust 1.95.0 formatting correction to the Windows permission fixture.
- Exclude exactly 153 verified frozen evidence paths from Codespell; add no ignored words or directory wildcards. Seven mixed JSON receipts are excluded as whole named files.
- Disable default features only in staged V8 smoke invocations; explicitly retain the original sandbox feature on sandbox matrix rows.
- Add test-only PTY read/discard/task/FD observations without changing original timeouts, output size, backend order or assertions. This is diagnostic evidence, not an Intel root-cause claim.
- Guard Mac Bash empty optional arrays while preserving successful-log retention, original exit status, collector and all original tests.
- Incorporate only the two mechanical PTY postimages produced by the actual original formatter.

### Actual validation and remaining gates

The independent Linux PTY cohort executed **29/29 original cases, zero failures, skips or retries** on source commit `1ddadae2…`, test tree `73f4b304…`. Original scoped `just fix` exited 0 without changes. Original `just fmt --base 20fd174…` exited 0 and produced two reviewed mechanical changes, yielding native tree `ae8ce55d…`. The formatter-review controller stop is preserved. A separate completion job then ran both original remaining `git diff --check` commands successfully, with all source/index/lock guards unchanged. No tests were rerun after fix/fmt.

The Mac original-57 old/fixed comparison is now **complete**: baseline 3 FAIL, fixed **57 PASS / 0 skips / 0 retries**, on actual Bash 3.2.57 and Python 3.14.3. After the full Git fetch failed with HTTP/2 early EOF before checkout or tests, a separately owned exact 13-file projection used the unchanged original tests/collector and real Git. Its actual trees are `69f329ac…` → `93fe0fed…`, with only the wrapper changed. Root verified all 74 native originals, nine source guards, the ordinary index and exact 57 names. This qualifies the original Mac Python/Bash scope, not the full repository, real Bazel product builds, Windows-native behavior or Intel PTY.

New-head CI now has four actual successful jobs. The complete 10:41:39 job observation and terminal-page checks through 10:45:00 contain 19 workflows / 44 jobs: 38 queued, 4 success and 2 skipped. Intel operator executed 33 original cases; Windows operator executed 40. Windows ordinary business libraries executed 118 named cases on actual base-merge `9063c52a…` / tree `b26598d…`; its XML contains three wrapper nodes. Windows retained libraries executed 532 original JUnit cases on head `5b633125…`, with seven additional unnamed nextest skips preserved. Complete original logs, ZIP members, source records and case mappings were verified. These library scopes contain none of the frozen 142 original exit-case names, so those original platform gates remain open. Two supplemental Windows private-directory rejection controls have actual same-head passes.

The superseded blocking run completed/cancelled at 09:42:55; its actor is unknown and this assistant did not cancel or rerun it. Workflow-level queued status does not prove no internal job execution; the earlier run-only inference is explicitly corrected. The original Intel PTY failure, earlier failures and cancellations remain preserved. Current-head strict Windows isolation, Intel PTY, core/integration, TUI, real musl and required-CI gates still need their own original results.

B16's new-host baseline now contains successful original helper, metadata and complete catalog commands, the unchanged 19,506 selectable + 57 ignored identities, and 396 current program/helper identities. The original OpenSSL/libcap/parser failures are preserved; the V7 catalog correction retains exact ignored semantics and all original execution guards. The baseline receipt remains BUILD_ONLY.

A separately reviewed native Foundation job `1a1ab493f2b-fc05-4bfe` has actually started from fixed native source `4a3374e…`. Its first B source `87e44120…` passed the four original SQLite commit-gate controls with zero retries, 216 original filtered cases and 362 unselected binaries separately recorded. Complete raw/JUnit/program-identity records are included. The first launch-tool timeout and exact-key reconciliation response (`reused=false`) remain distinct. Further prescribed positive/negative phases are ongoing; this does not qualify the whole Foundation, B16 normal Root/UI/provider path, or the product head by transfer.

The Windows deletion review confirms a remaining parent `DELETE_CHILD` route under the tested token family. A donor's blanket rejection does not satisfy the original read/write contract; no unverified security patch or weakened assertion is substituted for the original acceptance.

The original ledger remains **8 scoped closed / 14 OPEN / B18 scientific HOLD**. Original exits, budgets, negative controls, security boundaries, ignored cases and retry policy are retained.

### Reviewable records

- [Seven-commit source comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/0e139b599f0fe451f80fb7db4b2913bb9c679dce...5b6331250ff459033bd44d1a95daec70131277cc)
- [Current audit and work-plan entry](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/be6eddc503d909181ea195612c293f115d0447ea/qualification/r3-audit-repair-20261104/continuation-20261105/LATEST.zh-CN.md)
- [New CI, native Foundation and original blocker progress](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/be6eddc503d909181ea195612c293f115d0447ea/qualification/r3-audit-repair-20261104/continuation-20261105/CONTINUATION_PROGRESS_V3.zh-CN.md)
- [Windows deletion boundary review](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/be6eddc503d909181ea195612c293f115d0447ea/qualification/r3-audit-repair-20261104/continuation-20261105/reviews/b11-delete-boundary/REVIEW.zh-CN.md)
- [Mac original-57 complete qualification](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/be6eddc503d909181ea195612c293f115d0447ea/qualification/r3-audit-repair-20261104/continuation-20261105/MAC_WRAPPER_QUALIFICATION.zh-CN.md)
- [Complete project audit](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/CURRENT_AUDIT_PROGRESS.zh-CN.md)
- [Direction and work plan](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/PROJECT_DIRECTION_AND_PLAN.zh-CN.md)
- [Unchanged original 23 exits](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/current-blockers.json)

<details>
<summary>Historical fourth and earlier batches — statements below remain tied to their recorded heads</summary>

## Current fourth-batch candidate — original platform qualification open

The complete audit found that source presence, scoped native passes, scientific evidence and normal product acceptance were being represented at different levels. This fourth batch fixes evidenced runtime and fixture causes, preserves the original failed runs, and makes the remaining gates reviewable in one candidate.

This PR remains **Draft**, targeting `integration/ui-objective-20261103-product` at `63652be658ebed8d3052eb789b951793384fd5e4`. A fresh observation on **2026-11-05 05:37:57–05:37:58 UTC** confirmed main at `732e934ba496d90fbe042b8d41d479ef901643e5`. Original new-head and merge CI must establish their own results.

| Identity | Exact value |
|---|---|
| Published head | `0e139b599f0fe451f80fb7db4b2913bb9c679dce` |
| Publication tree, including audit evidence | `091e659e0da6602299fd14cfa93889191405edd8` |
| Final source-only commit | `20fd174ded4e5ce01bda34e4f6d1d74803301f49` |
| Final native code/CI tree | `4a3374e22e16ce5c764288ad018cd9affadf94ea` |
| Last unfiltered full-test tree | `fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff` |
| Previous published head | `cabcb40d36e116beaa65750e1f674c52035da785` |

### What this batch changes

The source work is split into **22 actual sequential commits**, with **54 source/CI paths** relative to the previous publication. Semantic cohorts remain below 500 changed lines; the final mechanical formatter cohort has an independent complete-diff review.

- Restore the reviewed Root/arg0/trust foundation and retain original inherited-custody, cancellation and checkpoint boundaries.
- Repair Core lifecycle and turn-state fixture observations while preserving exact identity, recovery, refusal and request assertions.
- Evaluate child approvals using the effective denied-read sandbox permissions; prevent Bash snapshot restoration from rereading the user's startup file.
- Isolate the Skills no-project-marker premise, use a real offline official-marketplace fixture, and align V8's default sandbox feature with its linked runtime.
- Preserve original-parent liveness through Linux sandbox restrictions, rearm after those restrictions, and close custody before a user-command fork. Three physical counterfactuals support the change; the original capability test still has an observed prerequisite early return.
- Recognize already-complete Windows deny ACLs on the retained object and add the full DELETE/parent-DELETE_CHILD physical matrix using the unchanged original token and legacy contracts. Native Windows qualification remains pending.
- Correct the actual musl toolchain selection and preserve complete original successful/failed target records without changing test selection, deadlines, retries or ignored cases.

The audit package contains **989 evidence entries** and the current Chinese audit, development plan, qualification record and immutable original 23-item exit conditions. Raw failures, invalid early counterfactuals, controller review stops, source identities and complete original output remain available.

### Actual validation and its limits

| Scope | Actual result |
|---|---|
| Original literal-deny approval controls | 25/25 passed on their recorded source |
| Earlier owning seven packages | 5,408 JUnit PASS / 8 FAIL; original 19 ignored and early-return limits retained |
| Earlier unfiltered full run | **19,485 JUnit PASS / 17 FAIL / 1 TIMEOUT**, 19,503 selected |
| Skills, Migration and V8 repairs | Original 9 / 166 / 76 tests passed in their respective fixed-source runs, zero retries |
| App liveness V2 | Three valid physical negative controls; eight JUnit positives include seven executed behaviors and one capability early return |
| Original Python discovery after the Windows/source cohorts | 57/57 passed, zero skipped |
| Latest original unfiltered full on fb9 | **19,506 selected = 19,490 JUnit PASS + 16 FAIL**; 57 original ignored; zero retries |
| Latest full's observed omissions | **25 early returns inside JUnit PASS**: 24 remote preconditions and one capability precondition |
| Original scoped `just fix` | exit 0, 220.947 seconds; only two same-type Linux64 casts removed |
| Original `just fmt` | exit 0, 42.684 seconds; all 17 postimages independently reviewed |
| Original and complete-candidate `git diff --check` | exit 0, 0.287 and 0.294 seconds; no drift |

The earlier full result is exactly **19,485 PASS / 17 FAIL / 1 TIMEOUT**; no retries or discarded failures are used to improve the comparison.

Four old nonpassing cases now pass in the new full run: App disconnect, Skills, Migration and V8. Fourteen old failures remain by exact name; two new failures are cold-root resume and proxy-response handling. The current raw log does not identify their complete cause. Proxy's original response-read budget is **2 seconds**; 10.514 seconds is the whole test's elapsed time.

The complete latest full archive contains **42 originals / 60,915,164 bytes**. Root independently reconstructed them and reconciled raw outcomes, JUnit, the exact full catalog, all source/index/lock guards, 321 test programs and 33 helpers. The earlier ordinary-index byte stop remains recorded; independent binary/NUL-output review proved all 9,575 ordinary entries equal to the original index semantics. Its unavailable old binary prevents attributing the changed bytes to a particular field or operation.

Both automatic hygiene changes deliberately stopped their controllers at exit 3 for review. The final controller succeeded at exit 0, with all six final source guards intact. Root independently reconstructed the whole final code tree and the publication tree. **No A tests were repeated after fix/fmt**, as required by repository instructions. Hygiene success does not replace the original full failure or supply final-platform qualification.

### Remaining gates and project direction

The original ledger remains **8 scoped closed / 14 OPEN / B18 scientific HOLD**. No original exit, status class, test oracle, security boundary, budget or ignored/retry policy was weakened.

1. Bind fresh original Linux/GNU/musl, macOS Intel/ARM, Windows and UI CI to this head, its base and actual merge checkout. Keep original per-case evidence, skipped jobs, cache markers and attempts distinct.
2. Resolve the remaining original platform failures, including strict Windows token/legacy DELETE and Intel PTY drain/exit behavior, from their actual native outputs.
3. Continue the normal trusted Root/Session/Agentd/Desktop producer/consumer path, SQLx custody and checkpoint controls, then demonstrate real task/cancel/lost-ACK/restart effects with original authority and independent acceptance. B16's prepared foundation is still unexecuted; its latest capacity observation requires a new resource guard.
4. Retain independent Bao/Chain/HIA compatibility and product acceptance. The new scientific J−C evidence has limited planning benefits but does not satisfy the original D−B adoption gate; B18 stays HOLD.

### Current reviewable deliverables

- [完整中文审计与项目进度](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/CURRENT_AUDIT_PROGRESS.zh-CN.md)
- [项目发展方向与后续计划](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/PROJECT_DIRECTION_AND_PLAN.zh-CN.md)
- [Original 23 blockers and unchanged exits](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/current-blockers.json)
- [Fourth-batch exact-source qualification](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/FOURTH_BATCH_QUALIFICATION.md)
- [Complete evidence index](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/fourth-evidence-index.json)
- [Complete latest full-test root review](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/fourth-full-fb9-complete-root-review.json)
- [Final hygiene and complete source reconstruction](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/fourth-final-A-complete-hygiene-root-review.json)
- [22 source commit/tree cohorts](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e139b599f0fe451f80fb7db4b2913bb9c679dce/qualification/r3-audit-repair-20261104/source-commit-chain.json)

<details>
<summary>Historical first, second and third batches — frozen statements refer to their original heads</summary>

## Current third-batch candidate — original qualification still open

This PR remains **Draft**, targeting `integration/ui-objective-20261103-product` at `63652be658ebed8d3052eb789b951793384fd5e4`. It is not a main-qualified release. The most recent main observation is `732e934ba496d90fbe042b8d41d479ef901643e5` (2026-11-04 19:52:19 UTC).

- New head: `cabcb40d36e116beaa65750e1f674c52035da785`
- Complete publication tree: `b2d7f038d6d88156bc6a4cb29c8703f69b808f29`
- Parent: `ff72d462d74f9eb856aa9edbc368caad9c466708`
- Code/CI composition before current audit documents: `aa1b76d8591358be2f591c8e411b9e0364a818fd`
- Original native formatting tree: `7aa959b44ed8d2bdad2ab83fb103c40a3333cf0b`

### Why this follow-up is needed

The parent completed with **13 successful / 2 failed / 1 cancelled / 2 skipped workflow runs**. Its blocking workflow had **24 successful / 9 failed / 4 skipped jobs**. Original Core output was capped before the job-log transport, so the complete failure union cannot be inferred from the available tail. The original 48-case ledger keeps all 121 platform associations, exact failures, partial successes, target-only evidence and unknown cases.

### What changes

The third batch changes 20 source/CI paths and preserves eight repaired historical qualification indexes/README paths. It adds 56 new qualification files with original evidence and current audit/plan records.

- Repair the actual Core namespaced replay and turn-settings fixture observations; preserve the original exact environment identity and rollout history for suspension/resume.
- Observe Queue completion at the real database acknowledgement, with an owned binding negative control. Canonicalize the existing Skills workspace consistently with the automatic environment.
- Preserve a single PTY execution probe with at most one prompt-triggered replacement; add bounded owned-file drain diagnostics. Refresh Fleet through an ordinary tick without changing any process identity.
- Attribute forward/Supervisord/worker failures to their original phases. Preserve every original deadline, error, RPC, authority and physical-send assertion. Supervisord log bodies remain separately UTF-8 bounded after escaping.
- Collect all existing failed-target shard/attempt logs and XML into the existing CI artifact path; missing records/errors remain explicit and Bazel's exit status is preserved.
- Build the two original Windows setup/command-runner helpers in the same isolated target before the unchanged authorized-read scopes.
- Fetch only the immutable source/base UI histories and keep the original two-parent merge. Split timing for the original 13 build commands without changing their bytes/order or the 60-minute budget.
- Add a separate explicit x64 musl Hepta build/process workflow. It verifies configured platform, actual executable, static ELF and same-file `--version`/`--help` receipts. Syntax checks passed; its real hosted execution is a new pending gate.

No dependency, original lock, original test budget, retry/skip policy, strict Windows permission oracle or canonical architecture registry is relaxed.

### Actual validation, with provenance limits

**20 selected Rust cases passed with zero retries across three recorded trees**, not one full-workspace run: Core 3 on eb5a; Queue/Skills 9 on 8699; PTY/Fleet/forward/Supervisord/worker 8 on a69b. Original negative controls retain their intended failures.

For the final eight-case run, original nextest summaries retain **62 filtered-out skipped cases**. Its controller really exited **1** and `success=false`: package-scoped catalog compilation changed Agentd's hash from the initial combined build. Exact source/harness stability, compilation and JUnit are preserved, along with the absent intermediate external-fixture hash sampling point. The record is not rewritten into a global PASS.

The complete UI Python discovery passed **13/13** in 47.297 seconds. Its six unchanged Gateway tests still query local HEAD907d4f5; actual new GitHub source/merge graph and UI execution remain separate gates. The collector's original nine plus four added controls passed **13/13**.

Seven-crate original `just fix --locked --offline -p …` exited 0 in 442.883 seconds with zero automatic source changes. First `just fmt` exited 1 because UV was absent from PATH; the failed attempt is preserved. Reusing the real existing UV 0.11.3 and frozen Ruff 0.15.13, original `just fmt` exited 0 in 5.895 seconds. Root independently reconstructed all six Rust and four Python formatting postimages; Python ASTs and the recovered Rust subtree are unchanged semantically. No Rust/unit tests were rerun after hygiene.

Final assembly was executed on exact tree `b2d7f038d6d88156bc6a4cb29c8703f69b808f29`. Native job `1a1a81d6667-fc05-2dba` is authoritatively **succeeded / exit 0**, with no retry/cancellation/timeout and complete stdout/stderr.

| Original final check | Exit | Seconds | Source drift |
|---|---:|---:|---|
| `just fmt` | 0 | 6.098119 | none |
| `python3 scripts/hepta-docs.py verify --profile development` | 0 | 5.323244 | none |
| `git diff --check` against original 907d4f5 | 0 | 0.877279 | none |

The actual docs result is `PASS_HEPTA_DEVELOPMENT_DOCS_V8`, with `historicalEvidenceRevalidated=false`. Root independently checked all 58 assembly pre/postimages and reconstructed the **complete 145-path native source map** from original tree 36692b4e to the exact published b2d7 tree. Ordinary native index and HEAD remain unchanged; no Cargo, lint or tests were rerun in assembly.

Complete post-assembly evidence is retained as immutable Git blob `547e55637226e12ba89f28979a82acfc757e3d06`, 176,730 bytes, SHA256 `07847c5e73ef962e202324db85158e3c683a4a3b569ff8ceeac0dd03ff6b58b6`, containing all 16 native files, original SDK status/output, guards, full map and runner. A synchronous read timeout is retained separately from the successful native job; the same evidence was recovered through a read-only operation.

### Gates that remain open

- All original new-head/source/merge platform checks, full UI execution and actual full failed-shard artifacts.
- Three original strict Windows token/legacy DELETE failures, unresolved capped CodeMode integration output, Intel drain/daemon/worker and Wine scope.
- Actual latest-main merge qualification; this PR still targets its explicit integration base.
- Normal Root/Agentd/Desktop joint producer and consumer integration, and same-source real authority/operator acceptance.
- Bao/Chain/HIA external acceptance and scientific adoption HOLD. These are not closed by component source or local PASS.

B12's original Windows two-positive/two-negative private-state scope and B14's original source/merge thirteen-resume scope are independently closed at ff72. Their scope does not cover the strict Windows failures.

The B16 source audit identifies real code gaps: current Desktop c42's normal producer is still Notes-only and its UI lacks the older c2 joint consumer. Migration must preserve the current generic original sender/checkpoint contract and ordinary current-user peer gate. The delivered 102-decision/474-net-difference plan separates source preparation from compiled integration; R4 compiled integration explicitly depends on R3's seal contract.

Prior assistant/audit records report an automatic approval rejection for Windows token/loader/DLL production changes. The raw decision receipt and stated reason were not recovered. This history is retained without fabricating a reason, changing those production boundaries or extending it to a general Root code prohibition.

### Reviewable deliverables

- [完整中文审计、项目方向与当前进度](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/qualification/r3-audit-repair-20261104/CURRENT_AUDIT_PROGRESS.zh-CN.md)
- [Exact-source qualification](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/qualification/r3-audit-repair-20261104/THIRD_BATCH_QUALIFICATION.md)
- [Complete evidence index](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/qualification/r3-audit-repair-20261104/third-evidence-index.json)
- [23 original exits and current scoped status](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/qualification/r3-audit-repair-20261104/current-blockers.json)
- [40-module / 91-work-package plan](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/qualification/r3-audit-repair-20261104/PROJECT_DIRECTION_AND_PLAN.zh-CN.md)
- [B16 source and migration plan](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cabcb40d36e116beaa65750e1f674c52035da785/qualification/r3-audit-repair-20261104/B16_R0_SOURCE_AND_MIGRATION.zh-CN.md)

<details>
<summary>Historical first and second batches — frozen statements below refer to their original heads</summary>

## Problem

The frozen r3 candidate fails original Core, App Server, TUI, PTY and Windows contracts. The first repair restored cwd display behavior, actual Agentd binary resolution, current cognitive revision oracles and canonical positive path fixtures. Its complete original CI remains retained: 18 workflows finished with 13 success, 3 failure and 2 skipped. Blocking CI had 24 successful, 9 failed and 4 skipped jobs.

This follow-up addresses the evidenced metadata, terminalization, realtime and fixture causes. Strict Windows permission failures remain open and receive bounded test-only observations.

## Changes

- Bind configured Hook calls to current thread metadata and the filtered tool inventory. Preserve unconfigured/denied/stale-server and active-policy controls. Keep private attempted-call observations inside the existing bounded internal recorder, outside nonofficial wire payloads and durable rollout.
- Wait for existing terminalization completion before mailbox/injection admission while retaining instance, lineage and underlying fences. Separate reusable prewarm connections from request-scoped metadata, full wire identity and recovery identity.
- Route realtime handoffs through one bounded ordered worker so audio/event forwarding continues while the current owner terminalizes. Preserve explicit overflow, close, cancellation and replacement behavior. The synchronous observer remains excluded after its actual audio-blocking negative control.
- Retain Unix App Server signal subscriptions across receive-future cancellation. TERM/INT remain forceable and HUP remains graceful-only. When non-stdio signal handling is requested, initial registration failure intentionally returns a startup error before acceptors open.
- Repair fixture premises: fresh Git state without changing sandbox configuration, stable compact output matching, models HTTP versus WebSocket dispatch, canonical positive paths, actual Python/TUI execution readiness, lease/queue phase separation and isolated resume setup.
- Stage the existing Windows helpers in the declared test-resource layout with strict byte equality and no-clobber publication. Rebind private-directory negative controls to the frozen current implementation. Add bounded test-only ACL/SID/OS-error and Code Mode timing observations while preserving original security assertions and budgets.

## Fixed source and dependency evidence

- Candidate commit: `ff72d462d74f9eb856aa9edbc368caad9c466708`; publication tree: `f780fe13946102a33b329898af48810be9c7bf0c`.
- Parent: `e729e6c2becb528e3a6b49c9e5bbea57bd26637a`.
- PR base remains `integration/ui-objective-20261103-product` at `63652be658ebed8d3052eb789b951793384fd5e4`.
- The 48 changed source files reconstruct `edcc50b93a0b95342567bdfe98e5c0d96c85e52f`, exactly equal to the final native source tree. Qualification documentation is then appended to produce the publication tree.
- [Composed source manifest](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/qualification/r3-audit-repair-20261104/COMPOSED_SOURCE_MANIFEST.json), [final scoped checks](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/qualification/r3-audit-repair-20261104/FINAL_NATIVE_CHECKS.json), and [complete phase summary](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/qualification/r3-audit-repair-20261104/SECOND_BATCH_QUALIFICATION.md) distinguish every tested tree from the final published tree.
- Combined helper inputs were independently generated on `3dd8aa36c60802312584743e6dcfa73e1e5a29a5` in [original workflow 41865994466](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41865994466). Original `just bazel-lock-update` and `just bazel-lock-check` both succeeded, with 806 source inputs unchanged. The real generated `MODULE.bazel.lock` is byte-identical to the existing lock, blob `1904db189003cb0b559f71958518e33a45fb6bb7`. The earlier 805-input scope remains separate.

## Validation

The qualification package records 25 actual native phases, complete JUnit identities, exact source hashes, failures and corrections. Selected native runs use zero retries and have no selected skips. The recorded lane is Linux x86_64; these observations do not grant Windows or macOS qualification.

| Scope | Actual result and limits |
|---|---|
| Hook/MCP/Executor/TokenBudget | 22/22 passed, including original rejection controls. |
| Startup/compact follow-up | 2/2 passed; prior d12 failures remain archived. |
| Realtime and WS | Original/final-oracle 20/20; WS identity 2/2. Real pending-owner and 500 ms synchronous-audio negatives observed. Three V1 controls and final V2 passed in separate recorded runs. |
| App Server | Actual original handshake failure plus passing companion control; repaired remote group 19/19 and recovery/Skills/injection group 14/14. |
| PTY | Actual input-echo negative, then Linux 28/28. Two additional original cases are macOS-only; the earlier incorrect Linux count check is preserved. Intel drain cause remains open. |
| TUI | Actual missing-cwd/old-readiness negative, then 12/12 with original interrupt/shutdown assertions and budgets. |
| Unix signals | TERM/INT/HUP old receivers time out after independently proven signal delivery; fixed three parents plus two original drain cases pass 5/5. Owned-child helpers are not counted as extra parent passes. |
| Lease/queue/canonical TUI | Original follow-ups passed 1 + 4 + 1 on their recorded repair tree. |
| Final scoped checks | Original `just fix` across 11 affected crates: exit 0, 783.9706 seconds. Final `just fmt`: exit 0, 4.7342 seconds. `git diff --check`: exit 0. Warnings remain; no warning-free claim. |

Clippy removed only a redundant clone from one new Core identity test. Root reviewed its complete function, and the reconstructed final blob exactly matches native. Production files, assertion semantics and time budgets are unchanged by that automatic edit. Tests were not repeated after final fix/fmt, per repository instructions; the exact published source now requires original CI.

First-batch AuthBus, kernel-evidence and terminal-cell targets passed on all applicable original platforms on an e729-identical merge tree. AuthBus/kernel source files are Unix-only, and terminal-cell retains one existing ignored local-history test. See [target-level evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/qualification/r3-audit-repair-20261104/B06_ORIGINAL_PLATFORM_TARGETS.json); no unsupported per-case execution or zero-retry count is claimed.

## Gates still open

This PR remains Draft. The original 48-name failure ledger and additional workflow failures are distinct; earlier native passes do not close the new complete original platform matrix. Windows helper/private-directory/recovery tests, strict token/legacy-delete contracts, Code Mode timing and Intel PTY behavior still require their actual original-platform outcomes.

Trusted normal product entry, paired Desktop producer migration, original signed objectives, provider/physical-effect acceptance, complete external-service compatibility and independent scientific adoption remain separate project gates. [The audit addendum](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/qualification/r3-audit-repair-20261104/AUDIT_PROGRESS_ADDENDUM.md) also records the two new concurrent PRs without importing unqualified alternative postimages.

No production-readiness, main qualification or all-blockers-closed claim is made.


</details>


</details>

</details>
