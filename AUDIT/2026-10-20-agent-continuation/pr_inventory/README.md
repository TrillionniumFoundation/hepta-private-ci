# R0 GitHub 全量盘点与可复用修复候选

完成盘点时间：2026-10-20 02:13:41 UTC。仓库：TrillionniumFoundation/hepta-private-ci。操作范围：远端只读 API；没有改动任何分支、CI、PR、权限或用户主机状态。

## 可核验结论

- open PR 全量分页 18 页：前 16 页各 100 条、第 17 页 23 条、第 18 页 0 条，共 **1,623 个唯一 open PR**，其中 **1,593 Draft**。独立搜索 total_count=1623；分页后再次读取首页，首 PR 仍 #2921。
- UTC 2026-10-19 起更新 60 条，2026-10-18 起更新 208 条。此前接力稿的 1621/1591 和 58/206 已被本次快照更新。
- main 为 `f8c9419df6ddeb36ff8b522a50219981fb8d9345`，tree `15c9d6ea07bf3832de82825a6cc1e8c958dd3d45`。
- branches/main 返回 protected=true；required status contexts 是 **CI required** 和 **Architecture required**，app_id=15368，enforcement_level=non_admins。完整 branch-protection endpoint 返回 403 Resource not accessible by integration；rulesets=[]。这不构成已经读到全部合并保护属性。
- 32 个关键 PR 加 14 个定向修复候选，共 **46 个精确 source head、2156 个最新 check-run 记录**。#1176、#1063、#996 的 checks 超过 100，均补取第二页。另保存 main 的全部 110 个 check-run。
- 另对 27 个非空 synthetic merge commit 实际读取 Git 对象及父提交，区分 PR recorded base、live base ref 和 synthetic merge parents，避免旧记录冒充新合成证据。
- Actions 活跃状态端点完整分页：**8 in_progress、282 queued、1 pending**，合计291个唯一 workflow run。queued 端点取4页至空。最老 queued 创建于2026-09-18。它们是远端 Actions 状态，不是用户本机任务数、PID 或 owner lease。

## 当前重要工程状态

| PR | CI required | Architecture required | 必须保留的判断 |
| --- | --- | --- | --- |
| #2917 | 仍运行，已有Windows shard 1/3失败 | success | cargo-deny绿色不能代替全局终态 |
| #2919 | failure | success | scoped native原始故障为ENOSPC；并非Windows fixture资格已证明 |
| #2918 | failure | success | Q24/B4专项通过不等于全局通过 |
| #2734 | failure | success | shared Encoder/Cell owner仍待平台收敛 |
| #2757 | failure | success | signed FinalUse与microbatch仍有全局和B4缺口 |
| #2695 | failure | success | shadow NDU不构成学习升级权限 |
| #2885 | failure | success | UI Chromium失败仍待定位 |
| #2915 | failure | success | Agentd peer auth不能继承其他分支的资格 |
| #2858 | failure | failure | Metrics WAL alias候选未验收 |
| #2758 / #2798 | failure | failure | P4 matrix schema不能替代目标机运行 |
| #2759 | 无head checks | 无head checks | synthetic merge=null；UNVERIFIED |
| #1311 | failure | success | 历史TaskFlow source检查不是当前main merge检查 |
| #996 / #1272 / #1383 | failure | failure | Operations/AuthBus/UI历史分支尚未验收 |

完整 check IDs、source SHA、details URLs、状态和时间保存在 important_prs.json 与 check_runs.jsonl。上述状态各自绑定盘点时的精确源，之后新 push 不继承。

## PR base 元数据与真实 merge 的区别

#1311 的 PR recorded base.sha 是 c6f90d48…，#1494 是78fdb0cf…；live main 已是f8c9419…。其 synthetic merge Git对象当前父提交确实已包括f8c9419和各自source，但是旧 source 上的 checks 不自动证明新的merge已执行。

#2758 更明确地存在 stale merge：recorded base.sha=7759861e…，synthetic merge `015619db703867207b8949ad99a28afc43023026` 的base父是 `3d4cc109ee04cfcdae1f74dde395d3fb7b8622fe`，live shared-encoder base为dc271d4…。因此不得使用该旧合成身份声明当前Cell owner资格。

#1272 的真实base是AuthBus staging分支 `auth-authbus-boundary-convergence-20260928`，SHA `5f6a7177fd6169da47dd8b96d9001f0965ae38ef`，对应#1176。#1383也基于专用UI分支而非main。

## 新 B4 候选去重

接力稿之后新增 #2920 和 #2921，都以 #2757 当前source b920d259…为PR base，但并不具有相同Git tree。

- #2920 source `20bf22ba773148a28a1e6b0d16b8401b731d37db`，tree `1c9ae3352d8f7c779ba6683af3b96d9d6f1a088a`；实际Git parent是cc17ba59…。
- #2921 source `22293e588c95f4fcb5b45907eb4fed3b73fdb755`，tree `57df67bc287f94fcfa4f6e843c5993ac246833f1`；实际Git parent是b920d259…。
- 两者都改 signed-admission workflow、CALLERS.toml和KERNEL_AUTHORITY_BOUNDARIES.json。最后一份allowlist的blob相同，CALLERS.toml和workflow不同。
- #2913更早候选有第四个测试文件变动；不能仅按PR编号覆盖它。b4_duplicate_candidates.json保存各Git对象、文件blob和diff。
- 新候选仍有运行中的checks及已经失败的跨平台/安全checks，无放行结论。

## ENOSPC 已有代码与执行缺口

共找到24个 disk/reverse-consumer/headroom标题或branch候选，全部记录在disk_candidates.json。

优先可复用的最小补丁：
- #1570 `32842b6277b42513a80332c8055312ccacd7168c`，branch `ci/hepta-scoped-low-disk-profile-20261012`，仅blocking-ci.yml job env：CARGO_INCREMENTAL=0、CARGO_PROFILE_DEV_DEBUG=0、CARGO_PROFILE_TEST_DEBUG=0、CARGO_BUILD_JOBS=2。
- #2780 `f9f8502b96aebc56ad537176058493641c05b324`，branch `maintenance/scoped-cargo-disk-budget-20261018`，基于当前main，仅job env前三项，无BUILD_JOBS。保留原选包和test覆盖。
- #2751 `5fd8ee8b6a333b6385733b9ff8ebe1d076177766` 把前三项放在测试步骤inline env，另含Fleet/Windows源码。
- #2776 `59c370e240808157d0c9774191c34744127708c1` 基于#2751旧head，增加hosted SDK清理。
- 上述各候选CI required都未通过，不能继承green。

### #2780 并未真正执行目标 scoped lane

精确source f9f8502b…，blocking run **39106716394**：
- scope job **117614032937** 原始日志明确paths仅 `.github/workflows/blocking-ci.yml`，scope.native=true、scope.full_repo=true。
- scoped native job **117617900226** 为 **skipped**，steps=[]，runner_id=null，started_at等于completed_at。
- scoped job日志下载返回404 BlobNotFound。没有执行三项env的原生测试回执，也没有非零scoped tests。
- root复用该补丁时仍须在新的真实source上执行目标scoped lane，同时保持full-repo required覆盖；不能用这个skipped历史job关闭ENOSPC。

原始scope日志已压缩保留，raw UTF-8 SHA-256为 `5e4be07a4686b7d72559e56cb71705e5887a2b54365d77b86aa8c155541acd1f`。完整身份见pr2780_scope_log_identity.json。

## Windows / UI 定向候选

Windows与Scope/Supervisor链的候选元数据保存在windows_candidates.json，近期UI候选保存在ui_candidates.json。它们是标题与branch去重入口，没有宣称全量diff审计完成。

关键链：#2890 → #2897 → #2900 → #2904 → #2909；平行#2905基于#2890；#2903 → #2914。独立Supervisor #2745、#2895。Windows Memory #2743，SQLite oracle #2805，跨平台Fleet/migration #2751。

近期UI标题/branch只匹配#2885、#2884、#2601、#2600。未发现单独503-terminal修复标题不等于已经证明所有diff均无此修复。

## 文件说明与使用边界

open_prs.jsonl保留全部1623条规范化PR元数据；dependency_edges.jsonl保留全部PR基于ref的依赖边。它是元数据依赖图，尚不是对所有源文件与测试的审查结论。作者、assignee、requested reviewer都是GitHub字段，不能代替真实host owner或lease。

RUNNING_TASKS.jsonl记录远端运行ID、branch、SHA、PR、status、attempt及日志链接；本机PID、worktree与host owner保持UNKNOWN。主机调查归root所有，本子任务没有访问用户专用主机。

本盘点没有任何远端写操作，没有终止或抢占既有任务，没有清理runner缓存，没有取消旧PR，也没有批准生产效果。权限姿态保持DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO。

