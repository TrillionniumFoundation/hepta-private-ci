# Blocker and claim register

| Item | Evidence status | Meaning |
| --- | --- | --- |
| Exact-head mechanism CI | closed | 73 distinct tests; push and PR both passed |
| Three registered trial processes | complete | All three exit codes and final results retained |
| Independent cohort audit | passed | Original aggregate and all three result hashes match |
| Checkpoint archive | receipt-bound | Separate original ZIP receipt bound to this audit and source |
| Isolated relocated replay | passed and receipt-bound | One additional process/query; source/ZIP/audit/three results/raw output and route pins match |
| bounded_heterogeneous_retention | not established | Scientific outcome; never relabeled as an engineering test failure or erased |
| bounded_heterogeneous_transfer | not established | Scientific outcome; never relabeled as an engineering test failure or erased |
| bounded_learned_router_vs_random | not established | Scientific outcome; never relabeled as an engineering test failure or erased |
| general_memory | not established | Scientific outcome; never relabeled as an engineering test failure or erased |
| int8_checkpoint_storage_and_quality | supported on registered finite suite | Scientific outcome; never relabeled as an engineering test failure or erased |
| learned_router_advantage_over_metadata | not established | Scientific outcome; never relabeled as an engineering test failure or erased |
| matched_budget_fission_advantage | not established | Scientific outcome; never relabeled as an engineering test failure or erased |
| net_memory_compression_advantage | not established | Scientific outcome; never relabeled as an engineering test failure or erased |

Earlier workflow observations retained with the 09:36:31 UTC mechanism-CI closure are historical snapshots. The appended timestamped CI narrative records the final observation used for this publication.

```json
[
  {
    "conclusion": null,
    "id": 39932441732,
    "name": "Hepta architecture convergence",
    "status": "queued"
  },
  {
    "conclusion": null,
    "id": 39932441833,
    "name": "blocking-ci",
    "status": "queued"
  },
  {
    "conclusion": null,
    "id": 39932441722,
    "name": "v8-canary",
    "status": "queued"
  }
]
```

Queued workflows are neither successes nor failures. Their later status is not inferred here. Full system cost comparison, external authority, distributed consistency, and general memory retain the boundaries recorded in the original study.


---

# 发布使用的 CI 最终观察（UTC）

36 PR 完整刷新窗口：**2026-10-23T10:45:31.601Z 至 2026-10-23T10:49:20.046Z**。随后仅对修复 catalog 再读一次：**2026-10-23T10:51:50.661Z**。这是带时间的外部服务状态快照，后续队列进展不被预先假定。

## 固定版本与当前状态

36/36 PR 的实际 head 与发布前固定的 expected head 相同，36 个均 open、draft，GitHub 当时均报告 mergeable。27 个有已发布 expected base 的 PR，其 base SHA/ref 全部匹配。旧 9 个 PR 缺可确认的历史 expected base，完整记录 actual base，但不宣称 base 未漂移。mergeable 仅是当时 API 字段，不是审核或合并许可。

当前固定 head 共 118 个工作流：**12 success、1 failure、2 skipped、103 queued**。全部 run 列表完整，未遗漏分页。92 次只读请求包括 36 份 PR、36 份 run 列表，以及所有 15 个非 queued 工作流和 5 个关键 queued 工作流的 jobs/steps；这 20 份 job 列表完整，共 41 个 job：12 success、1 failure、20 skipped、8 queued。其余排队工作流未逐一查询 job。

| 事项 | 固定源 / run | 当前已观察证据 | 结论 |
|---|---|---|---|
| 本轮机制测试 | `07df4a9` / 39932435741、39932441726 | push 与 PR 两次均 success；完整日志执行相同 73 个 distinct tests（9+9+55）；测试前后核对 exact HEAD | 该机制 CI 门槛已闭合，两次执行仍是 73 个独立测试，不计作 146 |
| 前阶段参数记忆确认 | `1e12dbb` / 39912356783 | confirmation success；原始完整日志与 artifact 已留存 | 历史执行确认已闭合；其 63 项测试不替代本轮 73 项 |
| 原 catalog 依赖缺口 | `cbd139ad` / 39916012060 | failure；`safetensors.torch` 导入 `packaging.version` 时缺少 packaging，真实 catalog tests 尚未执行 | 历史失败保留，由 PR3489 单独追踪修复 |
| catalog 修复的 hosted CI | `9d0473ff` / 39939320934 / job120366576516 | 最新仍 queued、runner_id=0、steps=[]；本地隔离环境另有 6/6 catalog tests 通过 | **hosted clean-install 验证仍待执行，未闭合** |
| 前阶段 growth/admission | `2b42a265` / 39920456698 / job120304154416 | queued、runner_id=0、steps=[] | 外部执行待完成 |
| 本轮 architecture | `07df4a9` / 39932441732 | 两个 job 均 queued | 外部执行待完成 |
| 本轮 blocking-ci | `07df4a9` / 39932441833 | scope、codespell、blob-size 三个已创建 job 均 queued | 外部执行待完成 |
| 本轮 v8 canary | `07df4a9` / 39932441722 | metadata job queued | 外部执行待完成 |

9 个前阶段 v8-canary 工作流的 success 仅代表 metadata job 成功；其中 18 个条件 build jobs 为 skipped。另有 2 个整个条件工作流 skipped。跳过项没有被计为测试通过。当前唯一 failure 是已经提取并定位的旧 catalog 缺依赖；本轮刷新没有新增 failure。

## 修复与边界

PR3489 只修改 catalog workflow：固定安装 packaging==26.3，并把 pull_request 的 job 条件增加本次修复分支的精确匹配。原 workflow_dispatch、旧分支条件、runner、timeout、permissions、SOURCE_SHA、测试命令均保留。该依赖版本来自已成功的本轮 CI runtime 和本地 runtime。隔离 sparse worktree 的依赖 smoke、6 项 catalog tests、测试后 just fmt、git diff --check 均通过；原冻结实验仓库未改。修复 PR 的 CI 真正运行前，不以这些本地结果替代 hosted gate。

queued 是当前调度状态，不能推为 success 或 failure。runner_id=0 与空 steps 仅证明所查 job 尚未获得 runner、未执行步骤；缺少能支持队列原因的证据，不推测组织 billing、配额或权限。此前普通 ubuntu-24.04 runner 已实际完成 confirmation/catalog/metadata jobs，不能声称所有普通 runner 均不可用。本轮未取消、重跑、修改队列或重新探测被拒绝的 runner/billing inventory。

模型产物、三组注册实验、独立审计、固定异路径模型读与 route 重放的完成结论见本目录 summary.md 和原始 receipts；它们与 CI 排队项分别保留。分裂收益、学习路由收益、净压缩优势与通用 memory 仍以预注册研究门槛的真实结果为准，不因 CI 通过而改写。

## 原始证据定位

- 完整 36 PR/118 runs/20 jobs 快照：`raw/memory-population-ci-preflight-20261023/final-36-pr-20261023T104214Z/`。
- 派生摘要：`snapshot-summary.json`，SHA-256 `57fa5d2c6243871ee269e0350efde34cb6c8f149d25301dbed2aa561fb2a3cfd`。
- 逐文件索引：`snapshot-manifest.json`，SHA-256 `8f696957c32badc1ff8d9110f7021a7618221fd5143ec29d76e4730418869cdf`。
- 修复最后观察：`raw/memory-population-ci-repair-20261023/ci-9d0473ff/poll-010.json`。
- 原 catalog 失败日志：`raw/memory-population-ci-preflight-20261023/refresh-20261023T101617Z/job-120289644892-original.log`；原 artifact 的 4 个文件也逐字节保留。
- 本轮两个成功 job 的原始日志与小型原 ZIP：`raw/memory-population-ci-preflight-20261023/`。首次 unified-test 失败、修正后的成功，以及首次 CI test-count parser 收据和更正都保留。

[修复 CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39939320934) · [本轮机制 CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39932441726) · [历史依赖失败](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39916012060)
