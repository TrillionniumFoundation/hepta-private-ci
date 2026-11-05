# ff72 原 48 项失败的终态核对

固定产品头：`ff72d462d74f9eb856aa9edbc368caad9c466708`；GitHub merge：`8e20cb5ec8261053ea472f06f79a0def072f3dce`；二者产品 tree 均为 `f780fe13946102a33b329898af48810be9c7bf0c`。原 48 个源码 postimage 已逐项核对 native 最终清单；资格文档追加没有改变这些源码。

## 结论

**ff72 完整 CI 仍未通过，原 48 名的全矩阵资格闭合数仍为 0。** 18 个 workflow 为 13 success、2 failure、1 cancelled、2 skipped；91 个 checks 为 72 success、11 failure、7 skipped、1 cancelled。Architecture 与 owner-package 门禁通过，不能据此关闭正常入口 B16；Rust UI base-merge 仍 cancelled。

以下四类互斥，按每个原名在所有已读 scope 中最强的可见信息归类；**不表示其原失败平台全部通过**：

| 原 48 名的 ff72 证据层级 | 名数 | 含义 |
|---|---:|---|
| 可见 exact case FAIL | 8 | 保留真实失败；Wine 与直接平台分开 |
| 至少一个 scope 可见 exact case PASS | 13 | 部分是其他平台或 Wine；不外推其余平台 |
| 仅原平台非缓存 target PASS | 11 | 没有该 case 的成功正文/JUnit，保留 target 层级 |
| 没有可见 case 正文 | 16 | 同目标通过的其他 case 与未打印均不构成证据 |

此前 35 个原名的 latest native PASS 全部保留，包括因果仍开放的 PTY drain；这些历史执行不覆盖 ff72 的新平台失败。JSON 逐项记录全部 48 名、121 个原平台关联、原有 patch refs、已发布源码 blob、历史 JUnit、当前日志原行、缺失窗口和后续 native 回执。

## ff72 仍明确失败的原名

| 范围 | 原用例 | 当前事实与下一门槛 |
|---|---|---|
| GNU/musl 工作流的 Wine-exec | `suite::abort_tasks::root_turn_suspension_preserves_unfinished_turn_history` | Wine 原例持续失败；两工作流共享 Linux RBE，不能计两种运行时资格。后续 Linux unchanged baseline 与修后都 PASS；Wine 原例仍需真实通过。 |
| macOS ARM + Intel | `suite::v2::executor_skills::restricted_executor_skill_can_read_permitted_reference`；`suite::v2::executor_skills::restricted_executor_skill_is_listed_only_when_permitted` | 两平台各保留原失败 attempts。修后 Linux 原组 5/5 已有完整 JUnit，须在实际 macOS CI 复验。 |
| macOS Intel | `tests::pty_dropped_output_receiver_keeps_draining_child` | 原 2 秒 drain 断言仍失败；根因仍开放。Linux PASS 不能证明 Intel FD/drain 正常。 |
| macOS Intel | `tests::pty_preserving_inherited_fds_keeps_python_repl_running` | 原例仍失败，新 readiness gate 本身 PASS。新标记修复没有闭合原 FD/REPL 失败；保留原 5 秒 readiness / 2 秒 PID 预算。 |
| Windows | `token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes` | ACE 规范化后的识别缺陷已有直接证据；原幂等性断言仍失败。生产权限边界尚未修改。 |
| Windows | `token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces`；`unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots` | 真实 outside delete 违规仍存在；WRITE_RESTRICTED / parent DELETE_CHILD 是待验证原因，不是已证根因。三个 strict assertions 保留，诊断不能冒充修复。 |

## 已改善但仍须保留证据边界的项目

- Windows `file_system_windows` 非缓存 target PASS（30.1 秒），CLI `sandbox_cloud_config` 非缓存 target PASS（16.3 秒）。这为原 8 个 exec helper 名及 1 个 CLI helper 名提供真实目标级证据；main log 没有逐例成功正文，未提升为 9 个 exact PASS。
- Windows Queue 服务 target 非缓存 PASS（69.6 秒），TUI unit target 非缓存 PASS（56.0 秒）。原 Queue guardian 与 TUI interrupt 在对应原 Windows 平台仍按 target 层级记录。
- macOS TUI unit 两平台非缓存 PASS；positive sqlite canonical fixture 在 Linux 有原 exact JUnit。原 macOS 逐例成功正文未随 target 日志输出，未制造 exact 记录。
- Windows CodeMode approval 原例及 `patch_approval_diag` 未在可见正文出现。Core shard 11 / 10 分别有 3,886,941 / 8,759,877 字节 stdout 被 1,048,576 字节上限省略，仍为 **unknown**。
- 四个非 Windows job 也存在同类 Core 省略。已读 full job log 只证明传输完整，不证明每个 case 的证据完整。旧 wrapper 的 tail 重放不计为另一次 attempt。

## 原 48 之外新观察到的失败

这是可见名字的**下界 18 名**，不是完整新 failure union。

最终失败 target / final-log tail / 完整 JUnit 中可见的 8 名：

1. ARM Queue：`externally_changed_queues_dispatch_independently_and_retry_failed_wakes`。
2. Intel exec forward：`forwarder_runs_commands_and_transfers_files`。
3. Intel supervisord：`five_real_agents_survive_daemon_restart_and_isolate_one_agent_release_changes`。
4. Intel fleet：`six_agent_fleet_lifecycle_keeps_peers_fair_and_isolated`。
5. Intel worker：`native_app_server::tests::real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone`。
6. Core：`suite::tools::namespaced_custom_tool_call_preserves_namespace_through_dispatch_and_replay`。
7. Core：`suite::turn_state::websocket_turn_state_is_stable_within_turn`。
8. Windows source + merge：`authorized_read_rpc_is_capability_gated_and_denies_outside_root`；实际在 capability oracle 之前缺少 setup helper。

另有 10 名只记录为 **retry-stage visible failures**，不升级为持续终态失败，也不凭后来未打印就造 exact PASS：

- Linux：`suite::network_approval::guardian_receives_exact_trigger_for_single_network_request`；`suite::v2::connection_handling_websocket_unix::websocket_transport_second_sigterm_forces_exit_while_turn_running`；`suite::v2::plugin_list::app_server_startup_refreshes_cached_remote_catalog_without_blocking_plugin_list`。
- Windows Core：`suite::rmcp_client::streamable_http_tool_call_round_trip::test_case_2_headers_helper`；`suite::apply_patch_cli::apply_patch_cli_preserves_existing_hard_link_outside_workspace`；`suite::auto_review::remote_model_override_uses_catalog_model_for_strict_auto_review`；`suite::cli_stream::integration_creates_and_checks_session_file`；`suite::subagent_notifications::subagent_stop_replaces_stop_and_skips_internal_subagents`。
- Windows AppServer：`suite::v2::plugin_list::plugin_list_honors_global_remote_catalog_cache_ttl`；`suite::v2::attestation::attestation_generate_round_trip_adds_header_to_responses_websocket_handshake`。该 target 终态 FLAKY，2 个失败 shard attempts / 18 个 attempts，不是零重试。

## 后续 native 证据另记，不覆盖 ff72

已逐文件验 hash 并读完整 JUnit：

| 固定树 / 阶段 | 实际结果 | 保留限制 |
|---|---|---|
| `edcc50b9` Rust residual baseline | namespaced FAIL 0.732 秒；turn_state TIMEOUT 60.012 秒；suspension Linux PASS 1.027 秒 | 原失败与 timeout 均保留 |
| `eb5a1084` Rust residual fixed | 3/3 PASS，0 retries | Linux x86_64；Wine/Windows/macOS 未由此通过 |
| `508ce2bf` Queue causal baseline | 新真实 DB-ack control 1 个预期 FAIL | 不混入原 48 |
| `869971be` Queue fixed | 4/4 PASS，含 ARM 原失败名 50.681 秒 | 原 ARM CI 仍须通过 |
| `869971be` App skills fixed | 5/5 PASS，含两个原 macOS 失败名 | 原 macOS CI 仍须通过 |

这几棵树不是“最终所有补丁组合后全套通过”的证明。新的 UI/native 统一 batch 尚须完整 source/status/JUnit 回执后单独追加。

## 独立范围内已满足的出口

**B12：** ff72 Windows private-state 原 2 positives、2 个真实负控各命中预期失败且另一 oracle PASS、源码 clean restore，范围内闭合。它不是 Windows token/legacy delete 权限资格。

**B14：** root 已独立核 source artifact 13347559410 与 merge artifact 13350280119 的 ZIP 和 JUnit；两 lane 原 resume 各 13/13、rollout 各 121/121，0 retries，原 13-case 出口范围内闭合。两 lane server 各 253 PASS / 1 FAIL 的 helper 缺失仍开放，整个 exec recovery workflow 仍失败。

## 证据入口

- [固定原资格清单](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ff72d462d74f9eb856aa9edbc368caad9c466708/qualification/r3-audit-repair-20261104/second-batch-qualification.json)，blob `f03ce31c7e39759148577633dad9b36b4e0b3669`。
- [ff72 blocking CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41875454075)。
- [Rust UI run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41875454150)。
- Windows 终态收据 blob `2a73377bdc7787db8c5e49423269d08b39428e5d`；source/merge artifact 联合核验 blob `9fa13c7ef424e6e1d4c1eb7f556d222082b7b3a4`。
- 本 JSON 索引列出 8 个 blocking job 原始 log blob/bytes/SHA256；GNU/musl/ARM/Intel/Windows 全部重新独立核过 hash。无重新运行测试，无 ref 或共享工作树修改。
