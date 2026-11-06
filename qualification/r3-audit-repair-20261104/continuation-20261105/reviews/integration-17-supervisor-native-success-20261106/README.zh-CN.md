# Source 17 Supervisor P0 原生通过增量

本包只保存既有自动 `pull_request` run `42201989809` 的新终态收件。11:11:02 UTC 的完整 jobs API 有且仅有两个任务，均 success；11:11:30 UTC 的完整 artifacts API 有且仅有四份 JUnit。没有重跑、手动调度、取消、私有容量查询或新增本地原生执行。前序完整 head 列表只用于绑定这个 run 的自动事件，旧列表状态与本切点不合并统计。

## 源码与实际执行

两个完整原 job 日志各自打印 checkout `17c6b903a5d5d470b72035f95bb6e087291d7e04`、tree `25020dc30888fa3ffa6f6e8d1073d91edded1756`、唯一 parent `840e8b5dbffca017753cdf87482ce325938f313c`。它们都执行 PR HEAD。实际 PR merge `26cfdcaa70cbd2daecd165137e3b84d2ad1a7284` 与 HEAD 同树，父顺序为 target base `63652be658ebed8d3052eb789b951793384fd5e4`、HEAD；本包保存实际 commit/ref/PR/merge 回执并完整复算 10,804 叶树。既有工作流完整 GET 和源码 blob `fdeb340099f9f720a353aa8b69372e75a335387e` 与此树叶相等。

| 平台 | Job | 完成时间 UTC | Supervisor 原选中 integration cases | 完整协议包 cases | Formatter | Strict Clippy |
|---|---|---|---|---|---|---|
| Ubuntu 24.04 | 127839244015 | 10:47:06 | 3 passed / 0 failed / 0 skipped | 14 passed / 0 failed / 0 skipped | 全 workspace 成功 | 成功 |
| Windows latest | 127839244401 | 10:48:21 | 3 passed / 0 failed / 0 skipped | 14 passed / 0 failed / 0 skipped | Supervisor 包成功 | 成功 |

原测试命令、`--retries 0`、原 45 分钟 job 预算、`CARGO_BUILD_JOBS=2`、严格 `clippy --all-targets -- -D warnings` 及 checkout clean gate 均保持。Linux 实际格式命令为 `cargo +1.95.0 fmt --all -- --check`，Windows 为 `cargo +1.95.0 fmt -p codex-hepta-supervisor -- --check`。原 API 步骤 success 与完整日志的实际命令、Clippy Finished 和零 formatter Diff 块共同支持这些结论。

## 完整性与资格边界

两份日志及整个 MCP 返回全字节保存，Windows 日志的 10,417 个 CR 不被归一化。四个原 ZIP 的官方 API SHA256、size、所有成员 CRC、唯一 junit.xml 和展开字节逐一匹配。完整 XML 逐 case 集合与原 raw PASS、两条 Summary 以及 native source receipt 相等；原日志因 status-level/final-status-level 各打印一次 PASS，按 classname/name 去重，每个平台仍是分开的 3 与 14，不能误计为双倍用例。

六个新增 Unix unit tests 与原 `paired_process_product` 未被这三个指定 Supervisor integration target 选择；`--all-targets` Clippy 不等于执行它们。隔离 Cargo target 目录也不自动证明整个构建没有使用任何缓存。本包不宣布所有 required CI 通过、不新增 blocker 闭合、不把旧 840 失败改写为通过。17 机械后继此次获得自身 formatter 原生资格；此前各个冻结观察的当时状态永久保留。

`ORIGINALS-FREEZE.json` 逐项绑定 23 份完整原件及固定来源；`verify_packet.py --root <解包目录>` 只用 Python 标准库读取原件、重算树/哈希/CRC/XML/日志，不运行 Rust、Cargo、Bazel 或网络。第一次实际离线执行 exit 0、stderr 0，完整 stdout 在 `verification-01.stdout.json`。最终 `FREEZE.json` 绑定原件与本说明/汇总/工具及实际核验回执。传输包另含分片 archive、逐成员 manifest、恢复复验器和恢复原件后的实际执行收据。
