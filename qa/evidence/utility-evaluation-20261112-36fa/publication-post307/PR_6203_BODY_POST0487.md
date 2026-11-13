## 当前检查点：实际修复与格式化证据已闭合，资格仍未通过

本 PR 要解决的是完整证据不足时仍可能被当作可比较结果、以及原 owner 到实际消费者的接线与恢复证据缺口。本轮完成了四处编译错误修复的精确应用和原格式化流程的完整证据闭合；当前版本的编译、检查和真实任务闭环仍需实际完成。

**真实合格链仍为 0，`qualification=false`。** PR 保持 draft；源码分支 HEAD 仍为 `cc57c7198db6293ccca562253c42fffbe2a04633`。已发布的 [证据检查点 `04874bbc`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04874bbc298638cf20007dff5fe8e250df063196/qa/evidence/utility-evaluation-20261112-36fa/README.md) 含 6,176 个文件，完整递归读回和类型化树哈希已核验，先前 5,681 个非 README 文件全部保留。

### 已实际完成并独立核对

| 事项 | 真实观察 | 结论范围 |
| --- | --- | --- |
| 原单次维护 `1a1d3eccd3a-392-231` | `just fix` 返回 101，原 formatter 未执行；原失败和实际 witness 修改完整保留 | 原 fix 仍是已消费的失败，未重分类为 lint 成功 |
| 四处修复与独立 fmt `1a1d41eb3ef-392-2b2` | 四个已审源文件精确应用；原 `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f` 在原 900 秒预算内返回 0；权威 supervisor exit 0 | 本轮只有 fmt，没有 fix 重试或 Rust 测试；producer 为 `APPLIED_AND_FORMATTED_REVIEW_REQUIRED` |
| 实际源码完整性 | 四修后树 `1eacf738...`；62 个实际 formatter 变更；最终物理树 `f905b18e6b05de1582024548179725a05d932536`，15,237 个文件 | 完整 raw/gzip/分片及所有源前后像已核对；HEAD/index 仍为原 `0c59`，该现场并非新的 clean final candidate |
| 原始执行收据 | 独立解码 51 份原读取 SDK、41 个完整二进制路径，完整 stdout 1,450 bytes、stderr 0；39 输入不变，41 只读命令全 0，原 Git 元数据不变 | 原始终态与有限观察已核对；没有推定额外执行、全系统排他性或真实采用 |

关键完整材料：

- [Root 原始运行闭合审查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04874bbc298638cf20007dff5fe8e250df063196/qa/evidence/utility-evaluation-20261112-36fa/post307-root-review-v1/ROOT_ACTUAL_FMT_RUNTIME_CLOSURE_REVIEW.json) 与 [原始运行完整 placement](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04874bbc298638cf20007dff5fe8e250df063196/qa/evidence/utility-evaluation-20261112-36fa/provider-0c59-fix101-apply-fmt-runtime-v1/PLACEMENT.json)。
- [Root 全源码及完整库存审查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04874bbc298638cf20007dff5fe8e250df063196/qa/evidence/utility-evaluation-20261112-36fa/post307-root-review-v1/ROOT_ACTUAL_FMT_SOURCE_REVIEW.json) 与 [独立 fmt62 语义审查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04874bbc298638cf20007dff5fe8e250df063196/qa/evidence/utility-evaluation-20261112-36fa/provider-0c59-fmt62-semantic-peer-v1/REVIEW.json)。
- [实际源码内容可获取性](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04874bbc298638cf20007dff5fe8e250df063196/qa/evidence/utility-evaluation-20261112-36fa/provider-0c59-actual-fmt-source-v1/SOURCE_AVAILABILITY_REVIEW.json)：62 个实际 after 源 blob 均逐个创建并完整 GET 相等，再实际构造出同一 `f905` Git tree。该证据只覆盖源码材料，不证明模型材料、持续可用、合法授权或消费者采用。

### 新 Root 协调器候选的准确边界

Initial custody、原 Ready 到普通 task factory、同 Arc drain、以及原 Current/journal 冷入口已分层冻结并完成静态审查；actual-f905 rebase 是 9 个路径（3 修改、6 新增）。[独立 rebase 审查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04874bbc298638cf20007dff5fe8e250df063196/qa/evidence/utility-evaluation-20261112-36fa/coordinator-f905-independent-peer-v1/REVIEW.json) 没有把静态结论当作编译或运行结果。

目前这 12 个新公开方法只有导出和机制调用，**没有实际非测试 Root-host 启动或恢复调用者**。9 个 ignored Root 机制用例也未执行。cold 机制只重开原 Current/journal，并在同一进程保留其它 fixture owners；没有证明真正的 Root 进程、daemon、Source/Cell 冷恢复。fixture 超时后的 Drop cancellation 也不等于 worker 已 join。

新 metadata getter 命名层只修改新 API 及其机制调用，原生产函数保持原字节。最终 CALLERS、保护摘要、QA 和 Root workflow 登记仍需冻结、独立核对并实际通过原检查。现有 39 个 Root parents 与拟新增 9 个用例须通过原运行器和 exact JUnit 名单验证；ignored skip 不计通过。

### 继续执行的条件与真实目标

[后继 B 路线 HOLD](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/04874bbc298638cf20007dff5fe8e250df063196/qa/evidence/utility-evaluation-20261112-36fa/post-f905-new-candidate-hold-v1/PLAN.HOLD.md) 保留原 clean `cc57` donor 和 sole-parent 谓词，将对最终完整候选另建隔离目录。旧 `0c59/f905` 现场及失败记录保留。最终 source map、commit、完整库存、固定运输容量和 typed request 先冻结，再建立独立单次维护合同并走原预算、source gates 和 native workflow。没有复用旧失败 fix 的执行额度，也没有从以往 PASS 继承当前资格。

普通真实链仍需完成：

**真实授权 A → 原 Training owner → 独立 B → Adopt 或完整 NoUpdate → 实际新消费者 C → daemon 与 Root 进程冷恢复。**

缺结果、成本、来源、独立性、材料或原 owner 权限仍保持 InsufficientEvidence/Unknown。工程 Root review/approval JSON 不构成 Hepta 运行时授权；确定失败也不自动成为完整 NoUpdate 或 Objective Fraud。

---

## 先前检查点原文（保留历史状态）

## Current execution checkpoint — materialized; original fix failed; qualification remains false

The complete isolated source candidate `0c59aaca0b4932507f068c723f73da2f96729b3d` was physically materialized and its original materialization job completed with exit 0. Root verified the complete 15,237-entry raw index and the frozen source inventory against the candidate. The [fixed evidence checkpoint `30717b6b66f1a825c6e3113f26ec9732f5aae8c7`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/30717b6b66f1a825c6e3113f26ec9732f5aae8c7) contains **5,682 files and 815 subdirectories**, preserving all 5,127 previous non-README files exactly. It records completed materialization, exact maintenance control staging, and the first running main observation; its README explicitly bounds that historical window.

**The actual later maintenance job failed.** Root independently fetched and checked all four terminal primary blobs below. This supersedes the historical execution-HOLD/running descriptions retained farther down this PR body; none of those earlier records was rewritten.

| Actual result | Exact evidence |
| --- | --- |
| Sole main job `1a1d3eccd3a-392-231`: supervisor exit 1, no timeout/cancellation/automatic retry, complete durable stdout 129,815 bytes and stderr 0 | [Original supervisor terminal](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/5980149603c1ab8f2a4a7aa7f21e9822c28c4c51) |
| Original scoped `just fix`: return 101, failed, original 7,200-second budget; raw command log 128,490 bytes | [Original execute_logged return](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/ff6f6805f6f336ce68825793220204ebb333b1b5) · [Original fix terminal](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/63b4ec2d123e8eddaeaef3bccc1490285eab8df2) |
| Only `fix` attempted; `fmt` not run; test commands dispatched 0; qualification false | [Original maintenance RESULT](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/c9ddc9349881689c2825852c746e8235f83cb921) |
| Driver's complete physical-source audit retained one actual modified file, `codex-rs/hepta-learning-ledger/src/witness.rs`; all 15,237 leaves accounted for; original Git metadata and all 24 frozen inputs audited unchanged | Same original RESULT; Root's complete postimage readback/review is still in progress |

The observed compiler diagnostics identify six errors: one private helper re-export, two comparisons between different original input types, and three attempts to clone the deliberately non-Clone `AgentdRootAuthorityPeer`. A separate correction overlay is being prepared against the actual retained postimages. It must preserve the original owner, UID, permission and operation-identity contracts. No second fix, fmt, test, source-ref movement or activation has been dispatched as part of that correction.

**The PR/source branch still points to `cc57c7198db6293ccca562253c42fffbe2a04633`. Real authorized A → original Training → independent B → Adopt or evidence-complete NoUpdate → new C → daemon and Root cold recovery chains remain 0.** This is a draft engineering checkpoint; no exact-source qualification, production learning loop, merge or deployment is asserted. The Root-local Initial custody implementation is a separate uncompiled, unqualified overlay and is not part of the running/failed 0c59 source.

Next work is to preserve the full failed-run evidence and actual postimages, independently review the concrete correction, and construct an explicit bounded successor for the remaining original gates. Failed work and its costs remain in the ledger.

---

## Historical PR record preserved verbatim

## Current source preparation — 0c59aaca (unqualified; execution HOLD)

A complete [prepared source candidate `0c59aaca0b4932507f068c723f73da2f96729b3d`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/0c59aaca0b4932507f068c723f73da2f96729b3d) now exists, with sole parent `cc57c719...` and tree `4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09`. **The PR/source branch remains at `cc57c719...`; no candidate execution result or qualification is asserted.**

This candidate composes the frozen 90 Rust and 20 non-Rust covered files into 109 actual updates: 49 new, 60 modified and one covered original file unchanged. There are **zero canonical deletions**. Independent mode-aware Merkle reconstruction and Git's own index/write-tree computation agree on the complete tree. Its 15,237-file inventory is an **expectation for later physical verification**, with 6,666 Rust files under `codex-rs` and 6,788 across the repository; all 90 executable files and the original symlink retain their modes.

Root independently read back all 10 changed Git trees and their 1,435 immediate entries, and verified the original raw commit bytes against the typed commit OID. [Candidate readback proof](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/816716719793e212b4f7b7208dfb233054c3cf12) and [complete actual API payloads](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/d5da0f3314dc2d4f9d6adc70d757dc98b38af0ff) preserve these checks.

The original formatter base `c0f78493...` has also been recovered as an exact snapshot closure. Its [independent review](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/8af43d58ba310e90e39fcedb42c998cb81a920de) confirms the fixed 83-object supplement; this does not certify current runtime availability or authorize a loader. The new isolated materializer and exact staged-input/process requests are being reviewed against the original guards, destination-only writes, full donor/target checks, 1 MiB transport bounds and 600 + 180 / 900-second materialization budgets.

**New materialization, fix/fmt, source/native tests and real authorized A/B/C execution have not run. Qualified real chains remain 0.** Production CURRENT/Version/FinalUse/new-consumer custody remains a separate open implementation obligation.

The published evidence cutoff below remains `143bcea9`; this source candidate and format-base recovery are later work and are not retroactively included in that checkpoint.

---

## Latest evidence checkpoint — 2026-11-13 / 143bcea9 (HOLD)

**Real qualified authorized A → original Training owner → independent B → Adopt or evidence-complete NoUpdate → actual new C → daemon/Root cold-recovery chains: 0.** The PR is still a draft at source `cc57c7198db6293ccca562253c42fffbe2a04633`. This update publishes verified evidence and prepared source material; it does not certify a new source revision or the real learning chain.

### Published and independently read back

[Evidence commit 143bcea947e97914775aef8bcae475e4e24c38b8](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/143bcea947e97914775aef8bcae475e4e24c38b8) has sole parent `0e5a50fc4f7f26b4120c0837902cb5d046d3f58e`. Its [checkpoint README](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/143bcea947e97914775aef8bcae475e4e24c38b8/qa/evidence/utility-evaluation-20261112-36fa/README.md) identifies the complete bounded content manifest.

- Leaf `d35f68d511da0bf2e834f9343096ecf51723aa37`: **5,128 files and 773 directory trees**, including the leaf root. The full recursive API response was not truncated. Root compared every path, mode, blob and directory Merkle identity.
- All **4,722 previous non-README files** are unchanged. The previous README and its original PR body remain archived. There are 405 new files and one README replacement; the largest new leaf blob is 331,739 bytes, below the original 512,000-byte limit.
- The three ancestor trees change only the intended child link. Root verified the actual commit and used a non-forced compare-and-swap from `0e5a50fc...`; fresh source/evidence ref reads confirm the evidence advancement and source head `cc57c719...` unchanged.
- Publication proof: [`6a4c60f5e2a17af8efadf07e41de89d9c1c18919`](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/6a4c60f5e2a17af8efadf07e41de89d9c1c18919), actual create and full GET verified.

### What this checkpoint establishes

It preserves the frozen 89-Rust/20-non-Rust composed source preparation, separate material-before-Trainer split and peer review, original Decision/Outcome retention, first Pending admission, expiry and cleanup correction, registration evidence, and production CURRENT interface proposal with its independent review. These are exact prepared bytes and static review evidence; new fmt/fix, source gates and native execution have not been completed.

The guarded single-archive restoration completed normally in job `1a1d38b82e9-392-160` at 06:14:59–06:15:27 UTC. The fixed V8 archive was restored with the specified size, SHA-256 and mode. The script's complete physical-source inventories and raw index/config/ref checks before and after match; all 15,188 source files are unchanged. This is a dependency-restoration result only. Earlier busy refusals, missing-material observations and Unknown SourceBefore records are retained without retrospective replacement.

A canonical deletion-scope error is explicitly corrected: the obsolete test helper name was absent from original `cc57`; it was removed only from an intermediate prepared layer. No canonical deletion is authorized. Earlier conditional whole-source counts based on subtracting that absent file are withdrawn; exact per-file bytes and reviews remain valid.

### Remaining work and qualification limits

The complete final source graph must be derived, materialized in a new isolated checkout, maintained by the original single scoped fix and original fmt base, then pass the original source and native gates against its exact revision. The original format base `c0f78493...` requires its real commit and complete snapshot objects; recovery work is a later evidence window and does not change the base or budget.

Production CURRENT still needs concrete original-owner handoffs for PublishedTask/Cell drain, Artifact/FinalUse, Version and the actual new consumer. A fixture CurrentStore, engineering approval, content root or committee key separation does not prove those obligations. Missing outcomes, independent-source evidence, permissions or cost evidence remain **InsufficientEvidence / Unknown**. They are not promoted to NoUpdate, Fraud or successful adoption.

No merge, deployment, activation or runtime Root grant is asserted.

<details>
<summary>Previous checkpoint narrative, preserved verbatim</summary>

## Latest evidence checkpoint — 2026-11-13 / 0e5a50fc (HOLD)

**Real qualified authorized A → T → B → decision → new C → daemon/Root cold-recovery chains: 0.** The PR remains a draft at source `cc57c7198db6293ccca562253c42fffbe2a04633`. The separate [evidence commit](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/0e5a50fc4f7f26b4120c0837902cb5d046d3f58e) preserves the new work without claiming that its source preparation passed the original gates.

The new checkpoint contains 4,723 files and 681 directory trees. All 4,367 previous non-README files remain unchanged, and the previous README is archived. Root checked all 5,403 recursive API entries without truncation, every path/mode/blob and all directory Merkle identities; the three ancestor trees changed only the intended evidence link. Publication used the expected-parent, non-forced ref update and actual final ref reads. The [content manifest](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e5a50fc4f7f26b4120c0837902cb5d046d3f58e/qa/evidence/utility-evaluation-20261112-36fa/post-ef773-checkpoint-v2/CONTENT_MANIFEST.json) can reconstruct the complete map, including its own Git content identity.

### Current source preparation

The [exact composed overlay](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e5a50fc4f7f26b4120c0837902cb5d046d3f58e/qa/evidence/utility-evaluation-20261112-36fa/provider-composed-local-capability-overlay-v1/EXACT_COMPOSED_OVERLAY_76.json) has 76 changed/new Rust paths plus two prepared workflow/QA files. All 47 layer applications matched their exact predecessors; the two independent Linux exports were merged with a whole-byte inverse. All 78 blobs were actually read from Git and hash-checked. They remain **unformatted, uncompiled and unexecuted**.

The sealed local Version/S/C paths preserve the original channel's same-UID refusal, owner-derived capabilities and fixed limits. Independent review identified and then checked two concrete corrections: final deadline checks after full authentication, and actual shared T/E client identity across V, S and C. Completion readiness shares the same C capability/permit/counter. The earlier per-handler full-current check for B withdrawal after admission remains included. These are reviewed source properties, not measured behavior or complete caller-gate results.

The seven-case Version local test packet is archived separately and is not part of the 76-file overlay. The historical two-UID harness is explicitly superseded by a three-non-Root-UID plan; no successful public three-UID run is claimed. The previous unpersisted registration proposal remains unavailable at its exact bytes; rebuilding a new view does not turn its historical proposed counts into a gate pass.

### Actual execution and remaining acceptance

The successful original source-gate job and isolated materialization still apply only to exact `cc57`. The isolated native attempt stopped before any behavioral command because the fixed V8 archive was absent. Two subsequent single-archive restoration attempts both stopped at the original global concurrency guard, with no download or publication. A quiet 04:08 observation was not a lease; the 04:11 attempt was refused, and a read-only 04:40 observation again saw active build/clippy processes. No third restoration or native retry followed. Missing before evidence remains **Unknown**, not binding drift or a negative utility conclusion.

The [first-admission review](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e5a50fc4f7f26b4120c0837902cb5d046d3f58e/qa/evidence/utility-evaluation-20261112-36fa/root-freeze-first-admission-review-v1/REVIEW.md) keeps the remaining authority boundary explicit: complete original A ledger evidence, the exact freeze payload/signature, and Root-preselected objectives/profile/components/budget/protocol/full trust must agree. Existing Material control replay only reconstructs already held inputs. A pure codec cannot grant that authority. Full first admission, actual original-owner fresh work, complete registration, original formatting/lint/test gates and daemon/Root cold recovery remain outstanding. Real provenance, independent evaluation, hard gates and lifecycle cost evidence are still required for any Adopt or evidence-complete NoUpdate.

See the [checkpoint README](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/0e5a50fc4f7f26b4120c0837902cb5d046d3f58e/qa/evidence/utility-evaluation-20261112-36fa/README.md) for exact windows, limitations, source identities and preserved history. No merge, deployment or activation is claimed.

---

## Previous checkpoint record (preserved)

## Current review checkpoint — 2026-11-13T03:58:52.839604+00:00

**Draft / HOLD. Real qualified authorized task chains: 0.** Source HEAD remains `cc57c7198db6293ccca562253c42fffbe2a04633`; the later provider work is preserved as source preparation and has not been promoted to this branch.

The evidence branch now points to [`ef773760ed7265ed881710f07be9915429a23a56`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/ef773760ed7265ed881710f07be9915429a23a56). Its [checkpoint README](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ef773760ed7265ed881710f07be9915429a23a56/qa/evidence/utility-evaluation-20261112-36fa/README.md) contains **4,368 files**, verified against the complete non-truncated Git readback and all **605 directory Merkle hashes**. All 3,637 previous non-README paths are unchanged; the previous README is archived. Only the evidence leaf and its three ancestor entries changed.

### What the actual records establish

- The original source-gate job `1a1d23c92f3-2564-1cb4` succeeded for exact cc57: 492 explicit closure ok cases, the self-test, and the complete caller gate. These results exclude every new provider increment.
- Isolated materialization job `1a1d2d20686-392-36` succeeded with all 15,188 physical source entries and the exact detached source/index state. The complete 54-entry capture and independent Root review are preserved.
- Native job `1a1d2e908ac-392-5a` ended **failed/exit 1**, without timeout, cancellation or automatic retry, at `ValueError: RUSTY_V8_ARCHIVE actual existing file required`. It dispatched **zero behavioral test commands**. The original `UnknownMissingBefore` remains unchanged; the separately observed admission inventory is not substituted for it. The complete 47-entry failure capture is preserved.
- Read-only job `1a1d2f968fe-392-69` succeeded. The fixed archive returned `ENOENT` before and after; the binding's complete 39,884 bytes and original SHA256 matched. Its eight original records are preserved. The loss's writer, timing and cause remain Unknown. The diagnostic did not repair materials or rerun native qualification.

### Source preparation and remaining gates

Frozen packets now cover the shared original Training/Evaluation readback, Linux cfg correction, ten mechanism tests, a narrow test-helper rename, explicit typed calls, fresh material and staged T→B/E preparation, opaque local Selector readback, Version-owned same-C NextUse/readiness, and its append-only six-case test mount. The local combined candidate contains 53 Rust paths at the checkpoint. It remains **unformatted, uncompiled and unexecuted**.

The original 33 Root CI parents are preserved with six further parents prepared. The partial changed-path caller inspection resolved eight ambiguous receivers by explicit typed calls; it is not the complete 6,619-file gate. Full registration/protection, original formatter/lint/test gates, actual dual-UID owner processes, the complete Fresh→Version→same-C path, and daemon/Root cold recovery remain outstanding.

This is an explicitly reconstructed evidence checkpoint. The earlier large tree request returned 422 without a SHA; the expected 4,287-file leaf was absent when probed. One 3,717-file immutable partial tree existed, but no commit/ref had moved. After transient tool state was lost, the exact 3,896-file map, actual placements, Git objects and local artifacts were recovered. The old 4,287-file README/manifest are archived as unpublished intent, not represented as successful publication. Some Root-local SDK serializations held only in transient state are unavailable; the complete original H job captures above remain available. No H job was repeated due to that state loss.

The required real acceptance is unchanged: authorized A → original Training owner → independent B → Adopt or evidence-complete NoUpdate → new actual C → daemon and Root cold recovery. Missing authority, material, outcomes, cost or independence evidence remains Unknown / InsufficientEvidence. A content root does not by itself prove availability, authorization or actual consumer adoption.

---

## Previous checkpoint description (historical, preserved verbatim)

## Why this change is needed

A known failed metric could take precedence over missing applicable evidence, turning an incomplete evaluation into an `Ineligible` comparison and permitting a completed `NoUpdate`. This change gives missing applicable evidence precedence while retaining the known failed metrics. Complete eligible and complete negative comparisons retain their separate meanings. The learning-stage regression keeps the original Training cut at Evaluation when a future window is missing and prevents a NoUpdate receipt.

## Current revision and acceptance state

**Draft / HOLD.** Source remains **`cc57c7198db6293ccca562253c42fffbe2a04633`**, tree **`b7b357c07b5539769a068c6b9b009629f5612d1e`**, sole parent `246d8cb614770252ee42029a5c014f2a4904176a`. The PR is unmerged. The complete original source proof has been reviewed. The first subsequent native request failed its live-source precondition before running any behavioral test.

| Gate or outcome | Actual observed state |
| --- | --- |
| Original formatter and canonical alignment | Normal exit 0; exact five-file repair, no additional formatter changes; all original source/Git/input audits passed. |
| Source closure on cc57, original 600-second limit | **PASS:** complete raw log has 492 explicit successful methods and zero failures. |
| Caller self-test, original 300-second limit | **PASS:** original complete receipt and raw output reviewed. |
| Full caller verification, original 4,800-second limit | **PASS:** 569 boundaries, 569 privileged inventory names, 422 protected-file inventory entries covering 351 distinct paths, 6,619 Rust files, `authorityGranted=false`. |
| Whole source job `1a1d23c92f3-2564-1cb4` | **PASS:** authoritative normal exit 0 at 2026-11-13 00:25:02.355 UTC, complete durable output, no timeout/cancellation/retry. |
| First native job `1a1d26326ac-2564-1cd4` | **Precondition FAILED / exit 1:** `behavioral_tests_started=false`, `stages=[]`, `source_before=null`, `source_comparison="unknown_missing_before"`. |
| Evaluator / focused / ordinary / Root behavior on cc57 | **No behavioral result yet.** The failed native admission dispatched none of these stages. |
| Hosted CI | Latest archived exact-source query around 00:37:01 UTC: zero checks, suites, status contexts and workflow runs; combined pending. This is a dated observation, not CI PASS. |
| Real authorized A → Training → independent B → Adopt/complete NoUpdate → new C → daemon/Root cold recovery | **0 qualified task chains.** |

[Complete source review](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0/qa/evidence/utility-evaluation-20261112-36fa/cc57-final-source-root-review-v1/ROOT_COMPLETE_SOURCE_REVIEW.json), [original complete run result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0/qa/evidence/utility-evaluation-20261112-36fa/source-qualification-cc57-v2/completed-originals/ORIGINAL_RUN_RESULT.json), [original failed native result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0/qa/evidence/utility-evaluation-20261112-36fa/native-cc57-v1-failed-precondition/RESULT.json).

The source review includes the complete 111,500-byte closure log, 48-byte self-test log and 270,271-byte caller report; all nine retained original inventory reads; exact raw Git before/after; all 25 input identities; and all 13 original read-only command terminals. Origin source stayed complete and unchanged during **that** execution, with 15,188 rows and zero extras. Read-only recovery of those completed artifacts does not prove the worktree stayed unchanged later.

## Why the native admission refused

The native wrapper's source-success bootstrap matched the actual completed source result. Its original raw Git guard then rejected the later workspace. Actual raw HEAD still identifies cc57, but the repository had acquired `refs/retired-artifacts/20261112-r71/3b03227b9431ee012e6b`, also pointing to cc57. Its raw index also differed from the source-qualification baseline. The guard's required no-refs condition was therefore not met.

The failed native post-snapshot has the expected commit/tree and an empty porcelain status, but its complete compact inventory differs. Read-only diagnostic `1a1d27152aa-2564-1ce4` compared the complete retained execution snapshots using the exact original native serializer: **15,181 equal rows, seven missing tracked historical qualification archives, zero added or removed rows**. The seven archives total **18,176,884 bytes**. Their original paths, modes, sizes, SHA256 and Git blob identities remain available. The complete failed raw snapshot and original gzip were independently recovered and matched the actual full read identities.

**Writer and cause remain Unknown.** Nearby ref/index timestamps do not identify a writer, retirement mechanism or fraud. Missing evidence is not a complete utility comparison. The original `unknown_missing_before` and zero-stage failure are preserved. No old ref deletion, index reset or expected-inventory relaxation is used to make the refusal disappear. Recovery requires a separately reviewed independent directory, exact original cc57 content and a new actual raw Git baseline.

[Complete difference and Root review](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0/qa/evidence/utility-evaluation-20261112-36fa/native-cc57-preflight-root-v1/ROOT_ACTUAL_SNAPSHOT_DIFFERENCE_REVIEW.json), [original seven-row difference](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0/qa/evidence/utility-evaluation-20261112-36fa/native-cc57-precondition-readonly-diagnostic-v1/SNAPSHOT_DIFF.original.json).

## Changes retained in the source candidate

- Preserve incomplete-evidence precedence and the four evaluator regressions while integrating the original-owner paths. A negative retention member cannot substitute for an eligible primary comparison. Complete primary-negative NoUpdate, missing-evidence refusal, fraud and payment remain distinct.
- Preserve original authorization, task/source bijection, inclusive expiry and actual readback arguments. Missing original Model, Selector, Version or FinalUse owners continues to refuse. The legacy NextUse Trainer reference remains explicit to the conservative caller collector.
- Retain evaluated NoUpdate purpose-separated 4/5/6-cut handling, original Training/Evaluation ownership, one Version preparation, and publication/selector/new-consumer readback mechanisms. Legacy 3/4/5 remains separate.
- Retain all 569 caller boundaries and all original authorization flags. The 422 protected inventory rows comprise 39 synchronized existing rows, 10 additional rows and 373 unchanged old rows; these rows cover 351 distinct paths.
- Preserve the complete original QA inventory and the V1 scope-gap failure. The later coverage correction reached all 34 intended scopes across 20 paths; scoped diagnostics are not substituted for the complete original gates.

The parent source gate exposed four failed methods. The final five-file non-Rust repair appends the actual `recover_original_custody` identifier to three Training readback forbidden lists; appends the exact new CALLERS allowlist hash; includes the existing observer `require_profile` method; applies the original Selection branch attacks to its actual `if`/`else` form with a same-length domain mutation; and includes the already-selected 33rd Root workflow parent. Existing forbidden markers, closed boundaries, authorization flags, original mutations and method inventory remain. Original formatting returned 0 without further source changes.

## Separate Root provider proposal and remaining behavior

The evidence includes a concrete **unapplied** Root resident provider v1 source proposal: eight postimages, four new files, 659 insertions and zero deleted lines. It adds a separate 21-right handoff for one original Root pidfd and ten original stream/pidfd pairs, with receiver identity, capability ownership and absolute lifetime checks, plus a service that composes the original typed registration, owners, runtime and stream service. Fresh versus read-only recovery comes from trusted registration.

The four modified old files restore byte-for-byte after removing the exact inserted blocks. Independent static review found no concrete authorization-escalation or FD-cleanup defect within its stated coverage. The proposal **has not been applied, formatted, compiled, gated or activated**. Its four tests cover wire/metadata mechanisms only. Complete ten-owner NoUpdate/recovered paths, A disconnect, cancellation/join and delayed handoff require actual integration tests. Later test-fixture work is separate from this frozen v1 evidence.

Default main still has no demonstrated legitimate typed provider source. A proposed handoff, caller-list entry, fixture or separate process does not establish the requested real authorized chain. [Provider proposal](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0/qa/evidence/utility-evaluation-20261112-36fa/root-resident-provider-proposal-v1/README.md) and [bounded independent review](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0/qa/evidence/utility-evaluation-20261112-36fa/root-provider-independent-peer-v1/REVIEW.json).

After exact independent materialization, native qualification keeps the original **45,000-second outer limit**, all 14 phase limits, whole evaluator library and four required regressions, unchanged seven focused filters, complete five-package ordinary phase and all 33 current Root workflow cases. Original order, 8 MiB stack, nextest defaults/overrides and zero retries remain. No completed parent result is transferred to this source or to the unapplied provider proposal.

## Evidence preservation and utility boundaries

The published evidence checkpoint is **`07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0`**, sole parent `15673f01e5248efdecd00fcb06a58ae3dd45d2c0`, root tree **`016b1d22e42141612b4453516688d206fac0c673`**. It contains **3,638 files**, adds **310 paths**, preserves all 3,327 old non-README blobs and archives the old README. The complete non-truncated recursive readback, all 434 Merkle trees and three ancestor trees were verified; commit and expected-old-SHA ref publication were read back with `force=false`.

This checkpoint contains the complete source proof, first native refusal, seven-row diagnosis and bounded provider v1 review. The earlier 3,454-path preparation window and its cutoff remain unchanged. Later object-availability/materialization observations are not backdated into this window. [Published checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0/qa/evidence/utility-evaluation-20261112-36fa/README.md).

Historical failures remain: parent `246d…` source closure failed (488 successful methods, four failed methods producing six failure entries), while its other two source gates passed. Historical `c0f…` evaluator passed 163/163 and focused native had 81 pass/28 fail; ordinary and Root did not start. Transport errors, the earlier cc57 ancestry-admission Unknown, prior incomplete coverage and review corrections remain archived without changing their original outcomes.

Real utility still requires the complete deployable composition and strongest deployable comparator, full frozen costs including failed/cancelled/search/evaluation/download/service/maintenance work, old/rare/critical task constraints, actual independent B outcomes, accessible and legitimately authorized model material, actual new C adoption and daemon/Root cold recovery. Privacy, authorization and must-pass tasks cannot be offset by average quality. Distinct keys/processes do not prove independent task sources, training lineage, judges or operational control. Action-dependent forecasts without the necessary state/policy/propensity and identification conditions remain Unknown.

NDU objectives, predictions, policy, critic, independent observations and public reward contract remain separate. Adopt, complete NoUpdate/Ineligible, InsufficientEvidence/Unknown and reproducible Objective Fraud retain different meanings. **Real qualified task chains remain 0; no merge, deployment, bonus maturity or payment is established.**


</details>
