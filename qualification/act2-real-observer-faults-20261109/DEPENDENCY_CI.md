# ACT-2 依赖栈 CI 只读审计

本次仅读取 GitHub 状态、已有日志和 annotations；未重新运行、取消或修改 workflow。
当前各 PR 的名为 `CI required` 的检查均失败；名为 `Architecture required` 的检查均成功。
这里记录实际检查名称，不推断所有 base 分支的保护规则配置。

| PR | source head | blocking run | CI required | Architecture required |
|---|---|---:|---|---|
| #5470 | 17a1d2c500099f338ab3fb1381c2ab6e03cb39a1 | 42615514539 | failure | success |
| #5511 | 181e8ef9b2708692db673b237b50e230c2b0ee9c | 42615511352 | failure | success |
| #5512 | f9cee303dd68642d6601acc3fb02451bf80ae94a | 42615517410 | failure | success |
| #5514 | 0817910eb1889c1d341a1bd5122a69777d539cd8 | 42615785716 | failure | success |
| #5535 | db3324c75cd4ef1e46ee4603a5fd8df240fe8722 | 42617881003 | failure | success |

## 旧故障的已观察信号与边界

旧 source head `da4e882dd6740ccb64ca9623fe5aa413bd9df675`、run `42611167929`、
job `129139839821` 的完整 annotation 已读到：
GitHub runner 报 `System.IO.IOException: No space left on device`，无法写自己的
`Worker_20261109-114304-utc.log`，并多次在 flush/dispose 中失败。

这确认了 runner 磁盘耗尽这一失败信号。它不能证明早期所有编译／测试无源码失败，
不能证明第 8 步完成，也不能把旧 job 改记通过。
旧 job 的完整日志再次读取仍为 `BlobNotFound`；该 run 的 artifact 列表为空。
精确 checkout 的日志当前不可用，不能只凭 check 的 source head 补称它已执行完毕。

当前 scoped native 的三项 annotation：

- #5470 job `129161711358`：hosted runner lost communication；原因未唯一定位。
- #5511 job `129158434095`：runner 写诊断日志时 `No space left on device`。
- #5512 job `129157947185`：runner 写诊断日志时 `No space left on device`。

## 另有真实失败记录，不能统一归因于 runner 磁盘

两份可读的 macOS Intel Bazel 完整日志已保留：

- #5514 job `129161653245`：checkout 是 PR merge `b61a0652bc39f889e6ce095d6703dbb233ceffb6`。
- #5535 job `129170398295`：checkout 是 PR merge `bb282975bb5cc7139a2d2e6f5b0694d4c4c4f851`。

`annotation-commands.jsonl` 中的 `source_sha` 字段标注 PR source head，
不是对每个 job 的实际 checkout 的替代；上述两个 merge 身份由日志直接记录。

两份日志均记录 ACT action-skill 集成目标通过，
包括 `action_skill_tests::act2_runtime_view_rejects_unavailable_or_mismatched_observer_evidence ... ok`。
日志中没有 `notes_actual_ui` 或 `notes_act2` 运行记录；不能据此宣称 Notes 已在这些 Bazel job 中运行。
它们早于本轮 #5567 的新增 GUI 测试。

同时，两份日志均记录 circuit automation suite 为 66 passed / 12 failed：

- `circuit_drain::tests::drain_observation_includes_runs_beyond_the_first_page`
  在 `hepta-automation/src/circuit_drain_tests.rs:95:6`，`open: Invalid`。
- `circuit_drain::tests::stopped_circuit_blocks_drain_after_reopen_until_original_work_settles`
  在同文件 `16:10`，`open: Invalid`。
- `circuit_journal::tests::expired::expired_recovery_rejects_live_stale_and_changed_original_requests`、
  `expired_recovery_settles_after_the_lease_allowance_is_exhausted`，
  以及 lease-churn、stopped-polling、legacy-stopped-history 测试：
  `circuit_recovery_budget_tests.rs:46:6`，`durable owner: Invalid`。
- `recovery_owner_settles_multiple_receipts_without_a_new_lease`：
  `circuit_expired_recovery_tests.rs:235:6`，`store: Invalid`。
- 三项 `circuit_learning_outbox` 测试：
  `circuit_learning_outbox_tests.rs:20:6`，unwrap `Invalid`。
- `circuit_task_readback::tests::task_readback_never_initializes_missing_or_repairs_lost_history`：
  `circuit_task_readback_tests.rs:34:6`，`original owner: Invalid`。

#5535 日志另记录七个 Agentd circuit fixture 失败，位于
`hepta-agentd/src/circuit_cell_test_support.rs:17:23`，`fixture failed: Invalid`。
两份日志都有 code-mode endpoint timeout，以及
`runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence`
的 StaleFence / local lease expired 失败，分别定位到 runtime_tests.rs:767:33 和 :703:33。

上述七个 fixture/support/runtime 测试源码文件在 M6
`885dae0f3285267e9e9c49d8b43b0d009779f9e8`、
#5514 head、#5535 head 的完整 Git blob SHA 相同，见
`failing-fixture-source-hashes.json`。
这只证明这些测试文件在 M6 已存在且未被 ACT 栈改动；
不证明 M6 在这些环境曾通过，也不排除其他实现／组合因素。
失败根因与修复仍待专项定位，不能改称全部为环境问题。

两项 cargo-deny job 的 annotations 只有 Ubuntu label 迁移 warning，
日志读取返回 Transport closed；没有证据将 warning 认定为失败原因。

## 原件索引

- `annotation-commands.jsonl`：8 条完整 gh argv、exit、stdout/stderr、UTC 采集时刻、job/run/source head。
- `job-*-annotations.json`：各次 gh 返回的完整 JSON，未裁剪 message。
- `runtime-read-annotation-result.json`：批量采集进程 stdout 的完整 runtime 回执。
- `current-head-checks.json`：五个 head 的已有 workflow 和 bounded check-run 快照；
  #5514/#5535 的 API 默认页只返回 30 项，文件明确记录 total 与 returned，不当作完整清单。
- `old-source-check-runs.json`、`old-job-step-result.json`、
  `old-job-log-error.json`、`old-run-artifacts.json`：旧 source/job 的状态和读取限制。
- `job-129161653245.log`、`job-129170398295.log`：完整解码日志文本。
- `broad-failure-locations.json`：以上日志的 checkout、ACT 记录及全部匹配 panic 的行号摘录。
- `job-129161652221-log-error.json`、`job-129170398013-log-error.json`：日志获取错误。
- `SHA256SUMS.json`：本目录其他文件的字节数及 SHA-256。

## first fixture 的进一步定位

`circuit_drain_tests.rs:16/95` 都在 `AutomationStore::open_root` 的 `.expect("open")` 失败；
尚未调用 drain、Circuit 事件或任何业务时钟。
`store.rs` 的 open_root 路径中，直接产生 `AutomationError::Invalid` 的候选是
`create_private_directory` 的 canonicalize(path) 与输入 path 不同（:1276），
或 `AbsolutePathBuf::try_from(root)` 拒绝（:54）。
其他该阶段 SQLite、迁移、IO 失败通常映射为 Unavailable，校验失败映射 Corrupt/AccessDenied。
对应完整源码保留为 `source-store.rs` 和 `source-circuit_drain_tests.rs`，绑定见 source-snapshot-bindings.json。

这两个 fixture 直接把 `tempfile::tempdir().path().join("automation")` 传入，未先 canonicalize。
macOS /var 与 /private/var 别名是与该拒绝条件一致的具体候选；同 runner 日志中其他测试确实有这两种路径。
但日志没有这两个失败 fixture 自己的 path/canonicalize 输出，故没有唯一确认别名就是实际根因。
当前没有证据将这 12 项 open Invalid 定为 Bazel 缺资源或固定时钟过期。
runtime_tests 的真实 lease 过期是另一个已观察失败信号，不能移作这些 Circuit open 错误的原因。

依赖栈不能据本次读取合并；required CI、广泛失败定位与完整 ACT-2 晋级继续 HOLD。
