# #7032 b1af67a 源 CI 原生日志阶段性核验（2026-11-23 14:30 UTC）

## 身份与不变量

- PR [#7032](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/7032) 仍为 Draft，source HEAD `b1af67a38f8cf9cee700cc067da1e6001ce220a8`，base `67b04d5833f5660a22c5658a90793f7f76249aa0`，未合并。此次源变化是已单独核验的 `cookie 0.18.2 → 0.18.3` 双锁修补。与默认 main 的安全依赖图分别计算，不能混合资格。
- [源 HCSN 连续输运 CI 45184438921](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184438921) 原 `continuous-transport` 作业 `137726265853` 终结 **success**。官方原工件 `14822933158`，名称 `hcsn-continuous-transport-b1af67a38f8cf9cee700cc067da1e6001ce220a8`，60,169 bytes，运行日志中上传 SHA-256 `734f9aaa5390514d3b1de266d40813e1b3cc2ade18cb8fe232f6d202bb534740`。这证实修复后源码的该科学工作流通过，不表示其全部仓库门通过。

## 原正式 blocking-ci 45184439037：原生终态与未完部分

[官方原运行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037) 对应确切 source HEAD `b1af67a3`。于本次读回时，整个 workflow 仍标记 **in_progress**。所调用 GitHub 作业列表接口仅返回最新 attempt 的**第一页 30 条**；此页中 21 success、2 conditional skipped、3 failure、4 cancelled。不能把第一页数量当完整工作流终局，也不能把 cancelled 当 pass。

- 原安全作业 [cargo-deny / cargo-deny 137727963955](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727963955)：真实 `Run cargo-deny` 和跟踪文件干净检查均 **success**。原源码双锁修补因此在 source CI 的这一安全门已经闭合。默认 main 的 59 条独立告警仍开放。
- [learning.operator exact source 137727965016](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727965016) ：先完成默认/任意精度 JSON 夹具恢复并上传源绑定回执，随后 exact-source 阶段退出 **101**。原 Rust Clippy 输出包括 `codex-hepta-bellman-operator` example `qualification_performance` 18 条 `expect()/unwrap()/collapsible_if` 等错误、`codex-hepta-control-plane` 两条（`cns_route_digest_v1` dead-code、8/7 参数）；后续 coverage/mutants/scale 因上游失败跳过。此项不能标记科学产品门通过。
- [Windows shard 4/4 137727965057](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727965057)：原 `bazel test shard` **failure**。具名失败中有三个 elevated 隔离正例 `windows_elevated_does_not_create_missing_workspace_metadata`、`windows_elevated_enforces_deny_read_and_protects_setup_marker`、`windows_elevated_unified_exec_enforces_managed_deny_reads`，均报 `ambient parent FILE_DELETE_CHILD can bypass deletion boundaries; a replacement ... has not been qualified`；`restricted_tokens_select_stable_routes_and_cleanup` 报 `capability-only workspace tokens require a private desktop`。原 job 同时上传 `bazel-testlogs-windows-shard-4-attempt-1` **14824927487** (143,246 bytes) 和 Bazel execution archive **14824957480**。四个产品正例继续 HOLD；不以其它低层部件通过代替它们。
- [Linux musl 137727965073](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45184439037/job/137727965073)：原 `bazel test` **failure**。原终局至少三组具名红：`transport::remote_control::tests::remote_control_waits_for_account_id_before_enrolling`（`auth change should wake ... before retry delay: Elapsed(())`）；`suite::subagent_notifications::subagent_notification_is_included_without_wait`（`timed out waiting for parent rollout to include subagent notification`）；`suite::v2::turn_start_zsh_fork::turn_start_shell_zsh_fork_subcommand_decline_marks_parent_declined_v2`（结果 `Failed`，期望 `Declined`）。原 musl execution artifact **14825510682**（13,370,749 bytes）。这些是此次 source 的真实失败，不能由 #7021 另一树的成功代替，也不能无因果地归于 cookie 安全升级。
- macOS ARM 多项在第一页出现 `cancelled`，未提供完整通过证据；未将其视为安全或产品闭合。

## 阻塞边界与后续

保留冻结 HCSN 来源/采购价格/最差来源门槛、原 500ms 时限、权限保护、公开 V1、原 ignore 名单以及所有原始失败。严格 Agentd 剩余诊断、Windows 产品隔离、Q24 长尾、源联合 CI 及 main 不同依赖图上的安全告警仍为 **HOLD**。没有在这份核验里重派任何现有工作流、修改源码、压制诊断、合并 Draft，或者据一次新的通过改写旧失败。

本页仅是已读取原工作流步骤、原生日志和工件元数据的精确源码阶段性观察；待同源完整终局和 ZIP/JUnit 逐项独立复核后才能升级资格结论。