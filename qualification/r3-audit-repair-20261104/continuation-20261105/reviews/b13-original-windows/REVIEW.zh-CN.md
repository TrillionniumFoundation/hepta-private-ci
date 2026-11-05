# B13：原 Windows Lease / Queue 合同闭合建议

建议由根审确认后标为 **CLOSED_SCOPED**。范围是固定源 `5b6331250ff459033bd44d1a95daec70131277cc`、等树合成 merge `9063c52a063b6f26c48e9418f6d8dbd14e9e06ff` 上的原 Windows 九例 Lease / Queue 合同。原退出条件逐字保留：

> 原过期、quarantine、guardian、release=0、单发送及重启不重放断言全保留并在原平台通过。

## 原平台与当前证据

原 48 个失败的冻结记录中，B13 对应 `completion_panic_retains_exact_authority_in_settlement_guardian`，原失败平台只有 `windows-shard3`。另外八例是已有合同回归控制，不能把它们写成原 48 个失败。历史 Q05/Q06 收集计划还列出了五个平台的库存查询；本次没有把那个查询清单改写成五个平台全部通过。

Queue 八例在本次 Windows source-head job `127149583164` 和 base-merge job `127149583430` 的完整原始 `test.log` 中逐名各一次 `ok`，两个目标各 36 个原用例通过。源与 merge 的实际 Git tree 都是 `b26598d0d97d8d51e723bb5582137315f2174d35`。其 XML 是 Bazel 外层 wrapper，具名 Rust 结果来自完整原日志。

此前缺正文的 Agentd 第九例，现已在同一原 main Windows shard2 job `127339255880`、artifact `13431285250` 中取得完整结果。原目标 `//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test` 非缓存通过，console 为 31.0 秒；原日志为 3 passed、0 failed、0 ignored、172 filtered，30.56 秒。其中精确第九名是 `runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence`，不是同目标另一条 `qualification_host_binds_one_local_turn_and_replays_exactly_once`。

这是真实存在并执行的 Bazel qualification wrapper。它启用已有的两个 cognitive-write features，选择三个 `runtime::tests::qualification_` 原例。默认 Cargo 不含 qualification feature 的事实不能否定这次执行；172 个被原 wrapper 筛掉的用例也没有被计入通过。

## 九例与原合同

| 原用例 | 保留并在当前通过例中执行的合同 |
|---|---|
| `qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence` | 真实 30 秒 setup lease；先完成有效 lease 下的 H7 写入，再等待其实际过期；原 `ExpiredActive`、返回错误、完整 head 不变的 quarantine 断言。 |
| `caller_abort_after_core_started_keeps_exact_authority_until_persistence` | 实际 caller 取消后，超过短 lease 的竞争仍被拒绝；放行前零请求、放行后一个请求与一条持久化消息。 |
| `completion_panic_retains_exact_authority_in_settlement_guardian` | 注入完成阶段 panic，原 guardian 继续持有 authority；竞争拒绝、`release_count == 0`、完成后单请求与单消息。 |
| `core_error_after_started_never_releases_ambiguous_dispatch` | 真实 hook 返回 block；精确 Core 错误、零 release、保留原队列行、零请求；过期后的竞争仍拒绝。 |
| `rollout_flush_before_dispatch_db_completion_recovers_without_resubmit` | durable rollout 后注入 DB 完成错误；重开实际 SQLite runtime 后恢复，原单发送和单消息断言。 |
| `queued_input_and_unique_event_ids_round_trip` | 完整输入与列表往返、UUIDv7、两个事件各自的 thread 与唯一 ID。 |
| `reserved_to_persisted_legacy_row_deletion_emits_queue_changed` | 已持久化 turn 的旧队列行被精确认领为 Persisted；空队列、一个 change 事件、一个 provider 请求。 |
| `queue_empty_observer_waits_for_owned_database_ack_after_turn_complete` | TurnComplete 和 queue-change 不能提前冒充 DB ACK；原 dispatch 与 observer 必须继续等待，实际释放后完成。 |
| `externally_changed_queues_dispatch_independently_and_retry_failed_wakes` | 外部、独立和恢复 turn 的实际派发；原三条有序 prompt 精确相等，无额外重放。 |

两个测试源文件的 Git blob 与旧缺证计划中的冻结引用完全相同。Queue 原 10 秒等待、400/300ms 延迟、已有 25 秒 ACK 窗口和 1/11/11 秒实际观察延迟没有为这次验收改变。

## 负控与限制

当前通过的原例自身包含实际拒绝与故障控制：hook 真实阻止提交、completion panic/error、短 lease 过期后竞争拒绝、gated DB ACK，以及真实过期后的 H7 quarantine。它们均在原精确断言之前发生，未用任意错误或 summary 替代。

历史第二批原件还保留了另一固定 native 源上的 Lease 1 例和 Queue 4 例通过。该原收据的 `targeted_negative_observations` 为空；本审查不补造历史“撤回实现后红、恢复后绿”的实验，也不把历史 native 结果借给当前源。

完整 54 成员 ZIP 的 CRC、各成员 hash、collector 中的两个目标文件 hash 已重新核验。Agentd 目标只有 final `test.log`/`test.xml`，没有该目标的 attempt 文件；这是现存原件事实，不是 `--retries 0` 声明。collector 的 mtime 本身不能独立证明 invocation，故同时保留 clean 源绑定、实际 action 与非缓存 console 行。

本建议不关闭整体 B15，不代表 GNU / musl / macOS 全矩阵，也不代表 Agentd、AppServer、Root 或 Current 的独立生产接受。新发布头 `eed4d6` 仍需它自己的原 CI，不能承接这里的通过状态。

机器可复核详情见 [closure-review.json](closure-review.json)，完整固定源身份见 [source-map.json](source-map.json)。
