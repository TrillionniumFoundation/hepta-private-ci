# 775 Windows 名称引用修复候选的执行检查点

**`775bf555` 已完成自身的 Linux 原生七包、Codespell、原格式/Clippy 和指定库/进程回归。** 这份记录只属于 commit `775bf555b0a7faf6eed17627acb0d0433294b737`、tree `e6f4644152d11a06457fdd92d8e5066675b26565`。后续合入并发分支的候选须独立执行；本检查点不声明 Windows 编译、Windows ACL/私有状态、Darwin 或部署资格通过。[固定源码](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/775bf555b0a7faf6eed17627acb0d0433294b737)；[报告结果核对](WINDOWS775-EXECUTION-HISTORY-VALIDATION.json)

## 固定源码、运行服务与原始结果

源码是 `797116d61cf422c26274ffef31297dce84a53a80` 的直接单父后继，仅有两个 Windows 测试文件的名称引用修改。原生 source-preparation commit `587a37f7cb3196426962024a094dab8947596fef` 与 canonical 775 的 tree 相同，但两者身份不同；下面执行回执明确绑定 canonical 775。[源比较与报告构建记录](checkpoints/775/BUILD-SOURCE-REPORT.md)

原生运行 job `1a1ac9e9596-fc05-55ec` 的权威终态为 `succeeded / exit 0`；stdout/stderr 已同步、完整、未截断，无外层超时、取消或自动重试。17 份命令回执的执行前后均为相同的 775 commit/tree，工作区状态为空，日志字节数和 SHA256 全部匹配。[运行服务终态](runtime/windows-canonical-775-runtime-status.json)；[总回执](native/windows-canonical-run1-summary.json)；[逐项核对](WINDOWS775-EXECUTION-HISTORY-VALIDATION.json)

| 执行或核对范围 | 本候选的实际结果 | 原始入口 |
| --- | --- | --- |
| 原七个完整包、无测试名过滤 | **1,219 passed（1 slow）、78 skipped；0 failed、0 timed out**；nextest 阶段 36.538 秒 | [原日志](native/seven-package-run4-original-test.log)、[JUnit](native/seven-package-run4.junit.xml)、[命令回执](native/seven-package-run4-original-test.json) |
| 69 项必需案例与完整 JUnit 检查 | **69/69 clean、整体 CLEAN、exit 0**；独立回查全部 69 项在 JUnit 中唯一匹配 | [必需案例审计](native/seven-package-run4-required-tests.69.native-audit.json)、[源码绑定清单](native/seven-package-run4-required-tests.69.source-bound.json) |
| 七项严格仓库检查 | **7/7 exit 0** | [七包汇总](native/seven-package-run4-summary.json) |
| Codespell 2.4.3 原命令 | **exit 0**，日志为空 | [回执](native/windows-canonical-run1-original-codespell.json)、[原日志](native/windows-canonical-run1-original-codespell.log) |
| 原全工作区格式检查 | **exit 0**；稳定版 rustfmt 的 nightly-only 选项忽略告警保留 | [回执](native/windows-canonical-run1-original-workspace-format.json)、[原日志](native/windows-canonical-run1-original-workspace-format.log) |
| 原四包格式检查 | **exit 0**；执行宿主为 Linux | [回执](native/windows-canonical-run1-original-four-package-format.json) |
| 原三策略 Clippy | **exit 0** | [回执](native/windows-canonical-run1-original-ci-policy-clippy.json) |
| ExecServer 与 AppServerClient 两个完整 library target | **319 passed（1 slow）、0 skipped**；nextest 阶段 45.015 秒 | [原日志](native/windows-canonical-run1-two-library-regression.log)、[回执](native/windows-canonical-run1-two-library-regression.json) |
| AppServer `process_exec` 选择范围 | **5 passed、1,016 skipped**；nextest 阶段 0.455 秒 | [原日志](native/windows-canonical-run1-app-server-process-regression.log)、[回执](native/windows-canonical-run1-app-server-process-regression.json) |

七包为 Agent Protocol、Agentd、Infer Worker Host、Runtime、Contracts、Learning Ledger、Supervisor；实际完整包名保存在原汇总中。七项仓库检查为 Map qualification、module status facts、strict module registry、module documents qualification、Chef custody、Rust CI feedback 和 module docs metadata。69 项是对完整运行的审计子集，不是执行过滤器；局部清单通过不会覆盖套件其余失败。[原七包汇总](native/seven-package-run4-summary.json)

原 Clippy 保留 `clippy::correctness`、`clippy::await_holding_lock`、`clippy::await_holding_invalid_type` 三项 deny policy。原全工作区格式命令含 `--config imports_granularity=Item`，但稳定版明确忽略该 nightly-only 选项；本记录只称命令退出成功。原 nextest 选择、profile、超时、重试和断言不降低；78 个 suite skipped 和 AppServer 的 1,016 个 skipped 均保持未执行记账。不同命令与历史候选的数量不累加为整个仓库的总通过数。[原命令与日志核对](WINDOWS775-EXECUTION-HISTORY-VALIDATION.json)

## 源码和导航边界

两处修改分别为 PTY 测试中的 3 个 HANDLE 方法显式 trait 选择，以及沙箱子模块对 `pretty_assertions::assert_eq` 的显式导入。独立审阅的 postimage 与原生 formatter 后字节完全相同；原 HANDLE 权限、unsafe 范围、错误处理、8 个删除权限断言和等待预算保持。它们针对实际 Windows E0034/E0659 编译诊断，但本轮 Linux 执行不编译该 Windows-only 路径。[源码审阅](review/windows-name-resolution/REVIEW.md)；[原生 source export](native/windows-name-source-run1-export.json)

固定 775 的原始导航 helper preview 返回 **0 changed Maps、written=false、ledger=null**。40 张 Map 和三份既有 history 的字节摘要与 797 全部一致；未新增导航 ledger。40 个 productionImplementation 仍为 false，371 项操作与 108/140 条原 gate 均保留。[原生 preview](native/windows-canonical-run1-navigation-preview.json)；[775 源码事实](checkpoints/775/MODULES40-SOURCE-FACTS.json)

## 归档及历史保留

归档 [native-775-checkpoint.tar.gz](native/native-775-checkpoint.tar.gz) 为 **217,229 字节**，SHA256 `1c59a87b3802c3a6d451907fcd2815ee49129234acfba8aae4868a7a8bb20a59`。归档共 70 个文件，MANIFEST 登记其余 69 个文件，逐条解包摘要已核对。它保存本候选的原始日志、JUnit、命令/源码回执、source export 与复现材料，并明确链接 bb55 基础证据归档，不声称重装了每个旧候选的所有文件。[归档与输入核对](WINDOWS775-EXECUTION-HISTORY-VALIDATION.json)

本次 JUnit 为 **280,618 字节、34 个 suite、1,219 个 testcase**，SHA256 `17954158f84b9e560182b4b22f86cadab6d37a3d472bf8e08351dbae48040e28`。独立解析未发现 failure、error、flaky/rerun 结点；选择跳过的 78 项由原 nextest 日志保留，不能因为它们没有写入 JUnit 而抹去。[原 JUnit](native/seven-package-run4.junit.xml)；[逐项核对](WINDOWS775-EXECUTION-HISTORY-VALIDATION.json)

此前 f581 的完整 suite 失败、bb55 的 Linux 通过和平台 Codespell/Windows/Bazel 失败、797 的独立原生结果继续按各自身份保存。775 后续合并候选、证据发布提交及其他相同 tree 对象均不得继承这里的运行身份。
