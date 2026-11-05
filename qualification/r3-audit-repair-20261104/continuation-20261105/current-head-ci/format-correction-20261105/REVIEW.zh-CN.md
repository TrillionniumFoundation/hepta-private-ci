# 主候选原始格式失败与最小修复复核

原始提交为 `eed4d6bb61b789b19f60facc79f9e031765fa4c9`，树为 `ca1c4671ef6b2773280d01b5d76c6166252f5856`。原生任务 [run 42063947910 / job 127372805931](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42063947910/job/127372805931) 的唯一失败步骤是 `cargo +1.95.0 fmt --all -- --check`，退出码为 1。

## 复核结论

接受按原始格式化输出机械重建的两文件、四处差异。`environment_selection.rs` 的全部非空白字节完全相同，原断言和五秒预算保持不变；`control_tests.rs` 除空白外，仅增加 `requires_openai_auth` 二元组中的一个可选尾逗号。两个完整修复后文件均已实际创建 Git 对象并经完整 GET 比对。

| 源文件 | 原始 blob | 修复后 blob | 允许的变化 |
| --- | --- | --- | --- |
| `codex-rs/core/src/agent/control_tests.rs` | `05054632b7cd82e5e7587dbcb7aee293788e00a2` | `6c93451a16f833c0241bdbe55806a6af60fa6195` | 空白、一个二元组可选尾逗号 |
| `codex-rs/core/src/environment_selection.rs` | `3c08e1620e800c30c47d98cc775cb20d4650ac88` | `18aaa1120cc8449246f363105f16acb459a00dfa` | 仅空白 |

## 原始结果与范围

同一原始任务中，Supervisor 三项原测试、Agentd protocol 十四项原测试、Supervisor 严格 Clippy 和工作区未改动检查均通过。两份原始 JUnit ZIP 的官方摘要、CRC、完整成员与原始日志中的命名结果一致。日志每项 PASS 显示两次来自执行行和最终状态汇总，不能计作两次执行。

这些通过结果属于旧的 `eed` 提交，不能转移为新候选或 `codex-core` 的原生通过。此次操作没有执行本地 `just test`、`just fix` 或 `just fmt`；按格式器原输出应用补丁也不等于运行格式器。后续本地流程仍须按仓库要求完成测试、scoped fix、fmt 的既定顺序，原资源门槛继续保留。

## 完整证据与复核入口

[`transport-manifest.json`](transport-manifest.json) 绑定完整日志、原始 API、两份 ZIP、四个原始差异片段、全部前后源码、指令文件、机械重建脚本和检查结果。分片以 `base64(gzip(JSON))` 方式保留完整字节；成员列表见 [`members-manifest.json`](members-manifest.json)。

解包后运行 `python verify_format_evidence.py <解包目录>` 可重新核对全部原始差异、完整前后源码、原始 API、ZIP 和命名结果。脚本仅验证已有证据，不执行 Rust、格式器、测试或 Git 操作。机器可读结论见 [`review.json`](review.json)，实际检查输出见 [`verification.result.json`](verification.result.json)。
