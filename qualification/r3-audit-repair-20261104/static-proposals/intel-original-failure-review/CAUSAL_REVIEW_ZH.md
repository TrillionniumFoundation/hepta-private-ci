# macOS Intel 原失败因果复核

## 结论

**本次没有发现可凭现有证据直接修复的 PTY 或 forward 生产缺陷。** `turn_state` 的测试夹具与真实 WebSocket 权限隔离规则存在已核实冲突，A 中的夹具修正针对这一冲突；其余三个旧失败的根因仍开放。此次只读审计不增加任何 Intel 平台闭合项。

| 原精确用例 | 原 Intel 事实 | 当前 A 的实际作用 | 结论 |
|---|---|---|---|
| `websocket_turn_state_persists_within_turn_and_resets_after` | 只读预热成功后提交 Disabled；仅一次成功握手、一个预热请求，最终 1 对 4 | 同权限原例固定启动权限；独立真实权限变化例要求 2 次握手和 `[1,3]` 请求 | 夹具冲突有源码及完整原日志支持；新 Intel 资格待原 CI |
| `forwarder_runs_commands_and_transfers_files` | 13 MiB **写入阶段** 30.603316921 秒超时 | 仅补 relay 接收进度与目的文件大小诊断 | 不是 close 阶段失败；生产根因未知 |
| `pty_dropped_output_receiver_keeps_draining_child` | portable 启动 13.942 ms；2.028 s 时仍未观察到退出，只有 `python_started` | 此用例及 PTY 生产源码完全未变 | drain 根因未知；preserved-FD 分支当次尚未执行 |
| `pty_close_stdin_preserves_large_input_and_delivers_eof` | 实际 `(-1, "__complete__")`，预期 `(0, "__complete__")` | 停止轮询已关闭的输出分支；区分三种退出结果并记录会话状态 | 合理的夹具修正，但不能证明旧 Intel 的 -1 来自该分支 |

## 固定来源与原文

原候选 `cabcb40d36e116beaa65750e1f674c52035da785`，实际测试 merge `28af7f705fa1024b9a6d2ef751fec116002260eb`，tree `b2d7f038d6d88156bc6a4cb29c8703f69b808f29`。本次 A 源码固定于 `bd7631e98f295fefad7654865cea497ceacf7d06` / tree `7d703610ae4f778ad305ebc139860d276f416e8c`。

已读取完整 PTY 原日志 3,403 B（SHA256 `7cd3de65…`）及原 XML 3,870 B；从原 desktop 已保存 ZIP 精确读取并核验 forward 全文 632 B（`228e852e…`）、Core shard10 final 全文 2,914,739 B（`1cfd18fd…`）。读取绑定同一文件 version，逐 chunk SHA256、解压 CRC 与原成员 SHA256 全部一致；未重新下载或运行 native job。完整哈希和 27 份固定源文件身份见机器报告及 `source-manifest.json`。

PTY 原日志实际有 **30 个用例，28 PASS / 2 FAIL**。`pty_preserving_inherited_fds_keeps_python_repl_running` 和 `pty_python_repl_readiness_waits_for_execution_after_input_echo` 都有明确 `ok` 行，应保留这两项成功事实。Bazel XML 的一个 error 是目标包装结果，不是一条单元用例。

## 能解释的部分

原 `turn_state` 测试要求“只读预热 → 完全访问 turn”仍只有一条物理连接。但生产 `WebsocketConnectionIdentity` 明确保留 sandbox 与 sandbox_mode，权限变化就要重新握手；它在新握手完成前保留旧连接。旧服务器按一条连接的完整脚本串行处理，正在等旧连接的第二个请求，因而不能并行完成新握手。完整失败原文恰好只有预热的 request 0 和 `warm-1` completion，随后最终断言 1 对 4。

A 没有删除权限隔离。原同权限用例仍要求一次握手、四次请求以及原 turn-state 清理关系；新增并发服务器用例保留原权限变化序列，要求两次真实握手、`[1,3]` 物理请求、真实工具结果和相同的状态清理关系。该源码修正能解释原夹具冲突，不能代替新 Intel 结果。

## 仍不能解释的部分

forward 原错误发生在 `fs_write_file`，后续 read-back、加密断言、`connection.close()` 和 forwarder shutdown 尚未到达。当前新增计数在 relay **转发前**累计双向 opaque bytes，不能据此证明目的端收到、写盘完成或 ACK 已回。完整生产转发/分帧源码与 cabc 字节一致，因此当前 A 不构成这项超时的生产修复。

PTY drain 用例直接等待 `exit_rx` 的原 2 秒窗口，不使用修改后的输出收集器。源码中的 Unix reader 在输出接收者关闭后仍继续读取，不能把“drop receiver 就停止 drain”当已证根因。原日志只证明写入后的 side-channel marker 未出现，尚无真实 reader 字节/错误结果。

PTY close 的旧收集器把 deadline、exit channel 关闭及真正收到的 -1 都折成 -1。`__complete__` 证明 Python 已收到 EOF 并通过输入字节检查，不能证明 wait/reap 已成功。A 的三路诊断和关闭分支停用能消除歧义；新增关闭输出后再发送真实退出码的控制只验证夹具合同，不是旧 Intel 故障的物理反事实。实际 waiter 仍可能把 `child.wait()` 错误映射为 -1，具体错误目前未打印。

## 下一次原 Intel CI 的最小判定项

1. 保留精确 source/tree、完整目标日志与实际 case roster；缓存目标、重试及 helper/network/Python 提前返回要单独记，不能外推为精确用例通过。
2. `turn_state` 观察原例的一握手四请求，以及已有权限变化控制的两握手 `[1,3]`；保原状态、turn ID 和实际工具结果断言。
3. forward 若再超时，读取现有 A 的 before/after 接收量、relay task finished 与目的文件 metadata；仍须原 13 MiB 写入及完整读回通过才能通过该用例。
4. PTY drain 分别保 portable / preserved-FD 的阶段、2 秒结果与实际会话状态。第一分支失败不能算第二分支已运行。
5. PTY close 区分 `exit_code_received`、`exit_channel_closed`、`deadline_elapsed`，结合 `has_exited` 与 `session_exit_code`，继续要求原 `(0, "__complete__")`，不改 2/5 秒预算。

当前无需另开广泛测试或增加预算。若同样的 drain / write 超时再次出现，现有观测仍不足的部分继续开放，再针对真实读写或 wait 错误补最小诊断。其它主机的一次成功不能替代 Intel 资格，也不能反推旧超时的根因。
