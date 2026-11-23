# Windows 原生四项验收

在 #7005、#7009、#7013 和 `c6a3ed9c` 的 x86_64-pc-windows-msvc shard 4/4 原始归档中，以下四项每次都出现在最终 `test.log` 的 FAILED 名单。对每份 ZIP 的全部成员逐项检查，成员数、选定原始日志的 SHA-256 和字节数按运行保存在 `final-archives.json`。每项测试在一次运行中计一次。

| 原生用例 | 尚缺的合格正例 |
|---|---|
| `restricted_tokens_select_stable_routes_and_cleanup` | 以当前限定身份和必需的私有桌面实际执行 HTTP/SOCKS 稳定路由、环境隔离和清理断言。该夹具在进入这些断言前遇到桌面前置条件。 |
| `windows_elevated_does_not_create_missing_workspace_metadata` | 通过正式准入的提权后端，完成原工作区元数据断言。 |
| `windows_elevated_enforces_deny_read_and_protects_setup_marker` | 通过同一正式准入，实际满足原禁止读取、保留允许访问及设置标记保护断言。 |
| `windows_elevated_unified_exec_enforces_managed_deny_reads` | 在原 unified-exec 入口执行并满足托管读取策略。 |

后三项在 c6a 命中正式的 Windows 文件系统隔离拒绝。该提交的 `legacy_boundary.rs` 和 `elevated_admission.rs` 对相应后端返回未取得资格；`prepared_process_context.rs` 也明确其准备资源的能力与加载器和生命周期的生产准入分开。四次运行的这三份源码、私有桌面实现、两份原正例文件以及附列的 exec-server 测试/辅助代码和 Rust 工具链配置均有相同 Git blob。按运行 head 核对的固定标识见 `source-and-attempts.json`。

公开 OpenAI Codex 的 #34613 提交引入同源网络用例。其后 #46554 提交 `a633ebc1245f0db4e36154d0747d6bcebeccbdbd` 统一了旧沙箱的私有桌面选择，并包含上述四个同名函数。在 gnullvm 的 shard 4 中，普通的网络与 core 目标均标记为 SKIPPED。在 shard 1 的 Windows-cross 标签下，网络目标使用缓存的通过结果，core 集成目标报告通过。公开提交对应的原测试文件分别为 `66038ce4ef6650cf0cd69434bea63e3c77d9971d` 和 `65871028260351989130b3c95cba47bf1f9c606e`，与本仓不同。该公开提交也缺少上段所列的三份被保护的准入/持有资源文件。这些公共结果提供历史上下文；当前 MSVC 身份与完整后端仍需原生具名成功证据。[公开来源](https://github.com/openai/codex/pull/46554) · [公开 shard 4](https://github.com/openai/codex/actions/runs/35412411902/job/105814479580) · [公开 shard 1](https://github.com/openai/codex/actions/runs/35412411902/job/105814479687)

本仓 #4043 的 Windows 原生安全拒绝对照通过，另一些功能正例仍红。#6798 的 Windows setup 与私有目录夹具分别有原生通过，其变更说明也记录了 network-proxy 和 core 集成目标失败。缺少一份将当前保护身份、环境、被准入的正式后端和上述四个原断言同时锁定的通过记录。下一次资格验证应先绑定生产后端、令牌与私有桌面的实际身份，再运行相同 Windows MSVC 目标；保留现有拒绝控制及失败证据。[#4043 原记录](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4043) · [#6798 原记录](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6798)

## 其它测试的最终状态

同一份 c6a 原始 ZIP 还有一个最终失败。`exec_server_resumes_detached_session_without_killing_processes` 等待 WebSocket 事件超时，其测试目标最终 5 过、1 败。此前三份原始 ZIP 均记录该用例为 ok。c6a 作业日志另有远程环境服务收尾和 CLI 会话文件两次失败尝试，两项在归档内最终 shard 1 的日志中均为 ok。本次一共有五个最终失败。四次扫描没有把重播、重试、缓存或同一个用例在日志中的重现计作独立验证。[c6a 原作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45125165932/job/137528575116)

## 复核

将 GitHub 发出的五份原始 ZIP 放在同一目录，命名为 `7005.zip`、`7009.zip`、`7013.zip`、`c6a.zip`、`e327.zip`。也可在归档仍可用时用下列命令按固定 artifact ID 下载，再复算每个 ZIP 的 SHA-256、每个选定日志的摘要、预期的具名状态和完整最终失败列表。Bazel 的各次尝试独立收录在任务日志，ZIP 中的主 `test.log` 用于最终状态。

```sh
python verify_native.py /tmp/hepta-windows-archives --download --output /tmp/windows-final.json
cmp /tmp/windows-final.json final-archives.json
```


## #7016 的第五次原运行

e3277e96 的 shard 4 正式终结。从其原始 ZIP 的 139 个成员中提取全部最终 test.log，最终失败恰为上表四个原隔离正例。分离会话用例成功，原 exec-server-process-test 目标 1.7 秒通过，作业汇总没有缓存标记。四个隔离正例的连续五次原失败保留；c6a 的分离会话红也仍在原记录内。复核程序现同时校验五个原始 ZIP。e327.zip 是第 5 份原 ZIP，另一个专项目录保留了分离会话的独立原生重跑。[原 Windows 作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787598/job/137546561430) · [六个完整会话目标](../windows-detached-session/DETACHED.md)

## c12 的第六份原运行

扫描 c12 原 shard 全部 139 个成员，恰有五个具名的最终失败。四个 Windows 隔离正例第六次均失败。分离会话用例再次在等待 WebSocket 事件时超时；该项在这六次整 shard 中四过两败。两次失败的原夹具都将五处等待汇合到同一错误，既有专项六次整目标的 36/36 不能定位哪个请求超时。下载六份原 ZIP 后上述程序可独立复核。[原作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138928408/job/137573328593) · [本次原 ZIP](c12.zip)

另在 c12 的相同 Rust 源树上独立运行原 windows-sandbox-rs 单测目标，禁止命中测试缓存，要求单次执行。六个指定的桌面/令牌准入与拒绝控制全部通过。对原始文本与 Bazel XML 的复算给出 289 过、0 败、5 原忽略。测试程序的两行输出与并行诊断交错，托管收集器的行首计数漏记这两条；四份 Rust 汇总与按具名结果恢复的 294 项一一对应。这些用例验证底层按角色拒绝或要求合格后端的行为。整 shard 的四个端到端隔离正例仍为红。[具名原目标](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45140086113/job/137575625240) · [原 ZIP](desktop-role.zip) · [复算实现](verify_desktop.py)
