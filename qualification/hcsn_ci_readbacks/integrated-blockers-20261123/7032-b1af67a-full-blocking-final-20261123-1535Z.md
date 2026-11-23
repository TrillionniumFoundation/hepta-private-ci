# #7032 b1af67a 正式全仓 CI 原生终局读回（2026-11-23 15:35 UTC）

## 固定对象与判定边界

- 原源码：`b1af67a38f8cf9cee700cc067da1e6001ce220a8`，Git 根树 `8774f089c6c5fc6e362d29f9b3eb78fb3b4db360`。
- 直接读取 GitHub 原 `blocking-ci` run **45184439037**，attempt 1：2026-11-23 15:35:38 UTC 已结束，`status=completed`、`conclusion=failure`。46 个原 job 完整分页读回后，**28 success、6 skipped、5 cancelled、7 failure**。此前在途期间第一页只有 45 个，不代表终局；末尾增生 `CI required` job 137804276199 失败。
- 原研究专项 run [45184438921](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184438921) 独立 `success`；不能转写为此仓库级通过。
- 原始 Job 清单：[45184439037](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037)；对象固定于此 source SHA，所有历史红例与标准不改。

## 七个真实失败 job

1. `learning.operator exact source`，job [137727965016](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727965016)：原编译/测试步骤失败，严格诊断保留，不能将局部修复分支计数冒充本源通过。
2. `learning.operator deterministic merge`，job [137727965131](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727965131)：原编译/测试失败。
3. `Windows shard 4/4`，job [137727965057](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727965057)：正式四个隔离正例仍红：
   - `restricted_tokens_select_stable_routes_and_cleanup`
   - `windows_elevated_does_not_create_missing_workspace_metadata`
   - `windows_elevated_enforces_deny_read_and_protects_setup_marker`
   - `windows_elevated_unified_exec_enforces_managed_deny_reads`
   原 `test.log` 明示 `ambient parent FILE_DELETE_CHILD` 可以突破删除隔离，替代后端尚未资格化。原 Windows 测试 ZIP artifact ID **14824927487**，原 shard 执行日志 ZIP **14824957480**。不能用底层六项控制或中间的 FLAKY 与后续通过冲抵上述正式失败。
4. `Linux musl Bazel //...`，job [137727965073](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727965073)：原生具名日志有三个仍需分别追踪的失败：
   - `transport::remote_control::tests::remote_control_waits_for_account_id_before_enrolling`：`tests.rs:1965` 的 `auth change should wake remote control before the retry delay: Elapsed(())`；该单测原 149/150。
   - `suite::subagent_notifications::subagent_notification_is_included_without_wait`：core shard 14 的首尝试红。
   - `suite::v2::turn_start_zsh_fork::turn_start_shell_zsh_fork_subcommand_decline_marks_parent_declined_v2`：app-server shard 2 的首尝试红。
   core 与 app-server 原输出同时有 `FLAKY` 标志及后续尝试；应保留首失败与最终运行结论，不能改测试时限或强称修复。原执行日志 ZIP artifact ID **14825510682**。
5. `learning.operator qualification required`，job [137741887322](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137741887322)：严格必需汇总红。
6. `Windows Bazel test required`，job [137748886763](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137748886763)：shard4 红的原汇总。
7. `CI required`，job [137804276199](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137804276199)：综合上游资格未全部成功，原必需门红。

## 五个取消与有证据的通过范围

- 取消项是 macOS ARM 的 repo native、Bazel Clippy、release、Bazel tests，以及 macOS Intel Bazel tests。原生 job 的 `conclusion=cancelled`，即使部分步骤执行过也**不得**判通过；没有再启动同源替代任务。
- `cargo-deny` job [137727963955](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727963955) 确切本源 `success`，因此只签收 #7032 **b1af67a** 依赖安全局部门；main 的另一锁图 59 条 RustSec 原失败仍独立 HOLD。
- Linux GNU、Windows shard1/2/3、Windows Bazel Clippy 和 release build、repo build-test、NDU smoke 的本源相应 job 确有 `success`，并不替代取消/失败的本平台同门。

## 后续处置

- 全仓联合资格 `HOLD`；#7032 保持 Draft，不合并，亦不更改公开 V1、原安全边界、价格、科学来源/动作、固定超时及真实失败历史。
- 有明确可逆修复须先固定原源码和故障，再使用新候选执行**原生同源**测试及全部受影响工作流；同一已完成作业不重复派，Windows 生产隔离后端缺位时不盲试。对 musl 的 FLAKY 首尝试必须按原名录核实正式最终退出，不能以另一个来源的成功替代。
- 本文是对 GitHub 原工作流最终终态、Job 元数据与原生失败日志的一次额外只读读回，**未重跑 CI、未改产品源码**。
