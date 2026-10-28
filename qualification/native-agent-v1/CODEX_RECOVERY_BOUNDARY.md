# Codex 0.165.0 的整进程恢复边界

## 结论与审查范围

本审查固定于官方 `rust-v0.165.0`，commit `360319d8dee62d87e2d59fc0c21805d79519cfed`。
当前 App Server／in-process facade 协议没有提供本次要求的完整接续路径：整个进程被 SIGKILL 后，
恢复原 pending dynamic tool call，保留原 thread／turn／JSON-RPC request／call 身份，
观察原 runtime job，并从真实工具结果继续，而不新建 turn 或重放产生工具调用的原模型决策。

这是固定源码确认的接口组合缺口，不是运行 whole-Codex 故障试验后测得的失败。
不能将 `thread/resume` 成功、相同 thread ID 或历史中仍可见旧 call 单独计为 exact pending 恢复。
本文件不改变 frozen benchmark、协议或受测实现，也不包含性能优劣结论。

## 两层 pending 状态依赖存活的执行进程

| 所在层 | 原等待状态 | 整进程退出后的影响 |
| --- | --- | --- |
| App Server | `RequestId → PendingCallbackEntry`，包含 server request 和 oneshot sender | 新 sender 的回调表为空，旧 JSON-RPC 回应无法找到原 callback |
| Core active turn | `call_id → oneshot::Sender<DynamicToolResponse>` | 原 task、receiver 和 active-turn pending 表不再存活 |

`OutgoingMessageSender::new` 初始化空回调表；`notify_client_response` 只查现有表，缺失时记录警告，
不从历史重建请求。[初始化与存储][outgoing-state] [回应处理][outgoing-response]
Core 工具处理器登记 pending sender 后等待 receiver；回应必须命中原 active turn 的 pending entry。
[工具等待][dynamic-wait] [Core 回应处理][core-response]

`DynamicToolCallParams` 带 thread／turn／call ID，但 `DynamicToolCallResponse` 只有输出与 success；
回应路由依赖外层原 JSON-RPC request，而不是一个可跨重启独立寻址的完成入口。[协议类型][dynamic-types]
保留外部 runtime job 和结果不会自动恢复这两层等待状态。

## thread/resume：重挂存活线程与冷恢复不同

warm resume 会调用 `replay_requests_to_connection_for_thread`，重新发送尚在内存回调表中的请求。
该机制可用于存活服务的连接重挂；它不从磁盘重建 pending callbacks。[重放实现][pending-replay]

cold resume 创建新的 thread/session，明确以 `has_live_in_progress_turn = false` 处理恢复状态；
没有 live active turn 时，历史 `InProgress` 被投影为 `Interrupted`。
[冷恢复分支][cold-resume] [状态处理][stale-turns]
因此，读取原历史与恢复原工具执行 continuation 是不同证据。

## 已存在的相关 API，以及它们没有证明的部分

| API | 固定源码确认的能力 | 本次边界 |
| --- | --- | --- |
| `thread/inject_items` | 将原始 Responses items 写入历史，不启动 user turn | 不重建原 dynamic-tool waiter 或 server-request callback |
| `CodexThread::recover_turn_if_idle` | Core Rust API，保留指定 turn ID，并重新启动采样 | 当前 [App Server ClientRequest][app-protocol] 未暴露对应恢复命令；本方法不恢复原 request／call 等待状态 |
| daemon continuation | 在恢复的会话上继续未完成工作 | 先记录旧 turn 的 `TurnAborted`，再建立新的 continuation turn |

**Core 的 `recover_turn_if_idle` 确实存在。** 不能笼统声称 Codex 无法保留 turn ID。
`RecoverTurnRequest` 明确规定 sampling restart；其参数没有原 dynamic request/call 的恢复记录，
官方测试也核对了恢复时发生的模型请求。[Core API][core-recover] [请求定义][recover-request] [官方测试][recover-test]
这不等于已证明该方法会重放某个具体工具决策，也不证明它会接续原 pending tool call。
未来将真实工具结果注入、原作业观察与 Core 恢复组合起来，需要独立实现、固定版本和故障验证。

历史注入和 daemon continuation 的行为分别见[注入实现][inject-items]与[daemon 实现][daemon-continuation]。
facade 使用相同 `MessageProcessor` 和回应机制；进程内嵌入不自动增加持久 pending 恢复。
[共享实现][in-process]

## 本次 fault qualification 的记分边界

`qualification/native-agent-v1/fault_recovery.py` 的故障目标为：

| 路径 | 被杀进程 | Codex 核心是否继续存活 | 能据此报告的范围 |
| --- | --- | --- | --- |
| Hepta native | 整个 qualification agent runner | 不适用 | 该 runner 的重启与原操作／job 恢复，以实际记录为准 |
| Codex App Server | runtime helper | 是 | helper 重启后的原 runtime job 恢复 |
| Codex facade | runtime helper | 是 | helper 重启后的原 runtime job 恢复 |

三路 fault 目标不等价，不能据此计算 whole-agent 恢复胜负、恢复速度优势或可靠性优势。
Codex whole-process exact pending 恢复应单独标为“未完成／当前协议接入缺口”，不能把未测项计为失败。
普通 replay／live 的任务结果继续按对应独立记录报告；故障目标差异不改变那些记录本身。

后续若新增 Core 恢复 adapter，应独立验证原身份、真实工具结果归属、模型请求序列与唯一物理 job，
并明确其与当前 App Server／facade 受测版本的差异。仅注入历史、复用 turn ID 或得到最终回答均不足够。

[outgoing-state]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/outgoing_message.rs#L248-L261
[outgoing-response]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/outgoing_message.rs#L484-L511
[dynamic-wait]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/tools/handlers/dynamic.rs#L190-L243
[core-response]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/session/mod.rs#L3528-L3545
[dynamic-types]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server-protocol/src/protocol/v2/item.rs#L1668-L1683
[pending-replay]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/outgoing_message.rs#L463-L481
[cold-resume]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/request_processors/thread_processor.rs#L4325-L4461
[stale-turns]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/request_processors/thread_lifecycle.rs#L1074-L1087
[core-recover]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/codex_thread.rs#L470-L518
[recover-request]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/protocol/src/turn_input.rs#L101-L112
[recover-test]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/tests/suite/turn_input_submission.rs#L612-L675
[inject-items]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/request_processors/turn_processor.rs#L995-L1023
[daemon-continuation]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/request_processors/daemon_continuation.rs#L88-L120
[in-process]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/in_process.rs#L1-L38
[app-protocol]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server-protocol/src/protocol/common.rs
