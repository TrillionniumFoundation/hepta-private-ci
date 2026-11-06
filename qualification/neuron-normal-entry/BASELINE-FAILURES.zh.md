# 7391 原生门：失败诊断与待验证修复

本记录对应固定源码 `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75`、tree `1b3a22ee08028175433d20b87263bd1dc1c4eca4` 的 ai395 原生门。原始 `failure-details.json`、`junit-scoped.xml`、runner 输出与 helper manifest 保持原样。本分支的下述修复尚未经过新的固定提交原生门；源码判断、修复落盘和测试通过分别记录，不能相互替代。

## 原始执行范围与证据

| 项目 | 原始观察 |
| --- | --- |
| 源码身份 | 上述 SHA/tree，原门核对源码干净且身份一致。 |
| fix 与严格 lint | scoped fix 完成且没有留下源码变化；严格 `-D warnings` 门通过。 |
| helper 准备 | 8 个 package 的 10 个 binary 正常构建完成，保留 Cargo artifact 路径、profile、字节数和 SHA-256；后续字节复核的限制见第 9 节。 |
| scoped 测试 | JUnit 有 6,631 个 testcases，6,577 个通过、54 个失败、0 个 error。失败中 51 个为普通失败、3 个为 runner timeout；命令退出 100。 |
| skipped 口径 | runner 另报 94 个 skipped；这 94 个不在该 XML 的 skipped 计数中，不能把 XML 的 `skipped=0` 写成整个 runner 没有跳过用例。 |
| 完整 workspace 门 | 控制器终态为 `stopped-before-workspace`，未启动完整默认 workspace 测试。 |

上述统计来自 `failure-details.json`、`scoped-runner-summary.json`、`status.json` 及原 JUnit；原 JUnit SHA-256 为 `bc3da8cece8e4f399de52a61b3d5b3b2fa92ccccbc7f7e9fe5020be7b3dff896`。下文代码链接均固定在原受测 7391，说明诊断所依据的旧源码；“本轮修复”描述随后候选中的改动，不表示旧链接已经包含修复。

54 个失败不能统一归因于环境、负载或 timeout。下面逐组区分实际报错、可由源码确认的合同问题和仍待执行的修复；未得到确定根因的条目继续保留。

## 1. Cold root resume：fixture 在显式冷重开前已触发 eviction

失败用例为 `suite::multi_agent_resume::cold_root_resume_restores_agent_identity_and_role_on_followup`。首次与 runner 原有重试分别返回 `Error: thread <UUID> not found`，没有调用栈，也没有阶段 context。因此，**旧 JUnit 单独不能确定是哪个 `get_thread`、flush 或 reopen 调用返回错误**。

已读源码形成一个具体、可修复的生命周期冲突：

1. [原 fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/multi_agent_resume.rs) 配置 `max_concurrent_threads_per_session = 3`，先后创建 root、worker、grandchild 和 sibling 四个线程；在 sibling 完成后，仍对先前保留的 worker Arc 调用 `flush_rollout()`。
2. [`effective_agent_max_threads(V2)`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/config/mod.rs) 从总容量减去 root 的一个槽，实际只允许两个 resident 子线程。
3. [`spawn.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/agent/control/spawn.rs) 在派发初始任务前提交 resident slot；[`residency.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/agent/control/residency.rs) 为第三个子线程找槽时可以对已完成的 LRU worker 执行 shutdown 并从 resident registry 移除。
4. [`LocalThreadStore::shutdown_thread`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/thread-store/src/local/live_writer.rs) 移除 live recorder。此后旧 Arc 的 [`LiveThread::flush`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/thread-store/src/live_thread.rs) 仍走 live writer 路径，会得到同文案的 `ThreadNotFound`。

这说明 fixture 不能保证其声称的“直到显式 flush/shutdown 才进入 cold cutoff”。它不是关于机器资源不足的推测，也不能单凭旧日志断言这就是原生失败唯一实际路径。

最小修复只把此测试的配置容量设为 4，明确容纳上述四个线程。该 helper 仅由这个测试的 initial/resume builder 使用；后半测试检查 lazy reload、身份、角色、父子 turn、provider 不被重定向、显式 interrupt 释放 worker 和 sibling 存活，不依赖容量 3 自动 eviction。所有这些断言以及原 flush/shutdown 调用保留。worker flush 和真实 root restart 加入阶段 context，让下一次失败可定位。生产 residency、并发限制和独立 eviction 测试均未修改。

本轮状态：修复已落盘，尚未执行；旧失败的精确返回阶段仍未知。

## 2. Zsh parent approval：把具体拒读文件错误声明为 glob

失败用例为 `suite::unified_exec_zsh_fork_approvals::unified_exec_zsh_fork_parent_approval_preserves_denied_reads`。原生两次都在 session 初始化读取 AGENTS 指令时失败，错误为绝对 `.../secret.env` 的 unreadable glob 无法安全展开。

[原 fixture helper](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/unified_exec_zsh_fork_approvals.rs) 将所有 `Deny` 项无条件转换成 `FileSystemPath::GlobPattern`，而唯一调用链实际传入 `tempdir.join("secret.env")`，没有 glob 元字符。[Linux sandbox 的 `split_pattern_for_ripgrep`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/linux-sandbox/src/bwrap.rs) 要求找到首个通配元字符才能生成扫描计划；literal 路径因此返回 None，原有 fail-closed 逻辑准确拒绝启动。

最小修复把这个仅用于具体文件的 fixture deny 项构造成 `FileSystemPath::Path`，由 `AbsolutePathBuf` 验证实际绝对路径。没有意图测试 glob 的 caller 被改变。原有 Deny、root read、project write、network restricted、父级 approval、非零退出码和 secret 不得出现在 stdout 的断言全部保留。

没有更改 bubblewrap、系统权限、sandbox 环境变量、sysctl 或 deny 策略，也没有放宽扫描根或跳过测试。修复后是否通过，以新的固定提交原生运行和原始结果为准。

## 3. 七个 custom-provider fixture：显式撤销继承的 mock metadata permit

实际失败为六个 private-request-metadata 断言，以及 Bedrock responses-lite 的请求内容断言。对应测试如下：

| 固定源码 | 用例 |
| --- | --- |
| [additional_context.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/additional_context.rs) | `additional_context_is_model_visible_but_not_a_user_message_item` |
| [client.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/client.rs) | `sends_audio_urls_to_responses`、`sends_local_audio_to_responses`、`stateless_responses_preserve_durable_item_turn_metadata_across_turns` |
| [code_mode.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/code_mode.rs) | `code_mode_exec_surfaces_handler_errors_as_exceptions` |
| [compact.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/compact.rs) | `multiple_auto_compact_per_task_runs_after_token_limit_hit` |
| [responses_lite.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/responses_lite.rs) | `responses_lite_does_not_expose_standalone_web_search_for_bedrock_provider` |

源码诊断：共享 [TestCodex fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/common/test_codex.rs) 默认明确授权本地 mock 接收 internal chat metadata。这个授权由 [model-provider-info/test_support.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/model-provider-info/src/test_support.rs) 中绑定实际 endpoint 的非序列化 permit 表达。把 provider 显示名称改成 custom 或 Bedrock，并不会撤销已存在的 permit。上述 fixture 想验证 custom provider 不接收内部 metadata，却保留了默认 mock 授权，配置与断言不一致。

本轮修复只在这七个 custom-provider 配置中显式设置 `mock_internal_chat_metadata = None`，并断言实际 mock endpoint 不满足 `accepts_internal_chat_message_metadata_for_request`。共享默认 fixture 仍模拟明确允许该 metadata 的后端。原请求内容、metadata 不得泄漏和 Bedrock web-search 行为断言保留；生产 provider policy、endpoint 校验和 metadata 编码规则未被放宽。

本轮状态：fixture 修复已落盘，尚未执行；不把七个旧失败改计为通过。

## 4. SQLite retained-owner listing：seed 必须是可被列表选中的真实行

实际失败为 `state_db_bridge::tests::initial_alias_binding_keeps_sqlite_listing_on_the_retained_owner`：预期 retained-owner 的 thread ID 列表，实际得到空列表。

[原测试](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/state_db_bridge_tests.rs) seed 设置了 title，但 `preview` 仍为 `None`。[生产 threads 查询](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/state/src/runtime/threads.rs) 明确包含 `threads.preview <> ''`，没有 preview 的行因此不满足正常 listing 条件。这是 seed 不具备列表资格，不能据空列表推出 retained-owner 被替换。

本轮只为 seed 补上 `Some("retained owner preview")`，使原场景确实包含一条 eligible listing row；原 retained-owner、路径、thread 身份和列表断言全部保留。没有删除 SQL 条件，也没有改 alias/owner 的生产绑定规则。

本轮状态：测试数据修复已落盘，尚未执行。

## 5. Unified exec terminate：等待同一操作的实际退出

实际失败为 [`unified_exec_persists_across_requests`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/unified_exec/mod_tests.rs)：第一次 `terminate_background_terminal(process_id).await` 被直接断言为 true，但实际返回 false。

源码合同区分终止请求和实际 exit 观察；请求发出并不保证在同一轮查询中已经完成退出。原测试把一次调用的即时返回等同于退出证明，未保留这个异步边界。

本轮把这一次即时断言改为至多 5 秒、每 10 毫秒查询一次的循环，始终使用原 `process_id`，直到实际 termination observation 返回 true。之后原“再次 terminate 返回 false”和“后台 terminal 列表为空”的断言仍执行。没有制造新操作、接受未退出状态、删除清理检查或延长整个 runner watchdog。

本轮状态：测试等待合同已修复，尚未执行；5 秒有界循环是否足以观察该实际操作，由下一轮结果决定。

## 6. 九个 pushed-process fixture：完成信号不能等待冗余 terminate

实际失败均属于 [`exec_command_consumes_pushed_remote_process_events`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/unified_exec_process_events.rs) 的九个参数场景：完整事件、sandbox denial、legacy exit、truncated replay、三个 managed-network 变体和两个 Windows launch 变体。旧日志在 fake websocket 的 `read_exec_server_json` 返回 `websocket read should not time out: Elapsed(())`。

源码诊断：fake server 已推送 stdout/exit，但仍继续等客户端再发 terminate 才退出；生产路径观察到 exit 后可以直接完成，不承诺补发一个冗余 terminate。因而旧 fixture 的收尾依赖了生产合同没有要求的消息。这与仅凭 timeout 文案猜测网络或资源不足不同。

本轮给 fake server 增加由测试持有的 completion channel。只有测试已收到真实 turn 完成、并在相关 managed-network 分支确认 model response receipt 后，才通知 fake server 结束收尾等待。已有正常 terminate 分支仍可结束 server。completion 返回原 `process/read` 次数与实际 `process/start` 内容，全部 read-count、cwd、sandbox、权限、网络批准注册和模型输出断言保留。

completion 只用于受控 fixture 的生命周期同步，不充当生产进程的 exit receipt，也不提前报告工具完成。本轮状态：九个场景共享的 fixture 修复已落盘，尚未执行；原 timeout 仍作为原生失败保留。

## 7. 三个 Hook/MCP 失败：修复真实 metadata 与 configured-call 路径

这组不是只改测试数据。原生失败分别为：

- [`executor_stop_hook_runs_after_attachment`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/hooks_executor.rs)：预期的 thread metadata 与实际缺失值不一致。
- [`mcp_tool_hook_passes_thread_metadata_to_model_hidden_tools`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/hooks_mcp.rs)：隐藏工具 hook 的预期上下文没有出现。
- [`token_budget_context_injects_plain_thread_hint_text`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/token_budget.rs)：预期 thread-hint 文本没有匹配。

已读真实 caller 有三个缺口：[`CoreHookMcpExecutor`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/hook_mcp_executor.rs) 未保留传入 hook metadata，且通过面向模型可见工具的 `prepare_call` 准备已配置的 host hook；[`session/mod.rs`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/session/mod.rs) 的 thread-hint 调用在 arguments 之外缺少所需的 thread metadata。

本轮改动保留 `HookMcpCall.metadata`，并由真实 session owner 覆盖 `threadId`；thread-hint caller 也补上对应 metadata。[McpBinding](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/codex-mcp/src/binding.rs) 新增 `prepare_configured_hook_call(server, tool, expected_environment)`，从同一个已过 tool policy 的 calls 集合取 prepared handle，并在有预期 environment 时精确匹配。原模型 `prepare_call` 的 visibility 限制不变。

独立源码复核确认：calls 集合在 [tool_catalog](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/codex-mcp/src/connection_manager/tool_catalog.rs) 已应用 enabled/disabled filter；新 accessor 不恢复被禁用工具。唯一新生产 caller 是私有 CoreHookMcpExecutor；真实 session、Hepta governance、active policy，以及原已配置 hook 的 trust/approval 路径保留。prepared call 的 catalog revision read-lock 与执行顺序保留，过期 handle 必须在 preparation closure 之前拒绝。没有把 model-hidden 变成新授权，也没有虚构一次 approval。

新增两组实际 binding 测试覆盖 hidden model 拒绝、合法 host hook、错误 environment、disabled/absent tool、原 approval mode，以及同一 handle 在 revision 变化后不能到达 preparation。三个原端到端测试的断言未改。本轮状态：生产调用修复与新增回归已落盘，尚未执行。

## 8. Supervisor paired-process fixture：按真实控制方法响应

原生 `two_real_pairs_restart_one_without_peer_pid_churn` 明确失败为“Agentd drain request did not return a drain acknowledgement”；`five_real_pairs_adopt_all_ten_children_and_isolate_one_matrix_crash` 则触发 runner watchdog。后者没有足够阶段证据，不能宣称其 timeout 已由本节唯一解释。

[原 `run_agent_child` fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/hepta-supervisor/tests/paired_process_product.rs) 对每个反序列化成功的控制请求都返回 Health，包括 Drain。它不满足 Supervisor 的真实 drain acknowledgement 合同。

本轮修复限于这个控制进程 fixture：校验 schema 和 spawn generation；Health 只响应 Health；Drain 仅在持久 lifecycle 为 Draining 时关闭本地 admission 并返回 DrainSnapshot；错误 lifecycle、其他方法和未知方法返回 Error。该 fixture 没有 turn runner 或 delivery outbox，且拒绝所有工作 admission，因此它的零在途计数只描述这个真实空工作 fixture，不能转移为普通 Agentd drain 资格。Health readiness 同时检查 Running 且 admission 未关闭。

真实多进程的 PID 隔离、采用与 restart 断言保留，生产 Supervisor 的 drain、授权、进程等待和故障判断没有放宽。本轮状态：fixture 协议修复已落盘，尚未执行；尤其不能把 five-pair watchdog 提前改计为解决。

## 9. Helper 元数据与实际字节是两条独立证据

### 9.1 连字符环境键经 `/bin/sh` 丢失

原生缺失 `hepta-joint-propose` runtime metadata 的失败实际有六个：Neuron 五个 Joint 进程用例，以及 Agentd 的 `synthetic_joint_control_service_preserves_real_output_cost_and_owner_on_reopen`。错误发生在取得 helper 构建路径时，不能据此宣称这些用例已经运行并验证了 Joint 数值输出。

[7391 helper 脚本](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/scripts/hepta_cell_test_helpers.py) 本就导出 `CARGO_BIN_EXE_hepta-joint-propose` 与 `CARGO_BIN_EXE_hepta_joint_propose` 两种键。实际独立探针 `1a1afa6b80b-fc05-6a7b` 的 `helper-environment-probe/read.json` 记录：直接启动时两键都有值；经本次 `/bin/sh` 路径后，连字符键为 null，下划线键仍为原值。这是已执行的环境传递观察，不是凭键名猜测，也不等于 helper 没有构建。

本轮 [Agentd 调用处](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/hepta-agentd/src/neuron_generation_joint_tests.rs) 使用已有 `codex_utils_cargo_bin::cargo_bin("hepta-joint-propose")` 解析真实构建元数据；[Neuron 调用处](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/hepta-neuron/src/cell_joint_generation_tests.rs) 在原键缺失时读既有下划线别名。保留 absolute path、实际文件与内容摘要核验，不猜 `target/debug`，不新增模型或假 executable。新 lookup 仍须由下一轮原生测试验证。

### 9.2 scoped 构建重写了一个准备阶段的 binary

`helpers-before-scoped.json` 记录 10/10 的路径内容与准备 manifest 相同；`helpers-after-scoped.json` 只记录 **9/10** 相同。唯一变化是 `codex-linux-sandbox`：

| 观察点 | 字节数 | SHA-256 |
| --- | --- | --- |
| 准备 manifest 与 scoped 前 | 242,942,768 | `d3174dd44ad14260a351c3f0b19a0e04ec0d03ec21a4e3f4111a86e288779a80` |
| scoped 后 | 245,247,752 | `d6edfae01f5c54277d9cb9ff9d384a30e0ac217ccbfd321150567ce63f6aaf40` |

后续 Cargo 构建可以重新链接同一个 target 顶层路径。源码 SHA 一致不代表准备阶段的 executable 字节一直未变；前后 hash 也不是每次 spawn 实际执行内容的独立证明。原门没有为每次调用记录此 helper 的实际字节，因此不能追认“过去十个 helper 全部执行了准备时同一内容”，也不能仅凭这次变化认定任一 sandbox 失败的根因。

本轮 helper 工程把 Cargo `compiler-artifact.executable` 的实际内容复制到每次 attempt 独立目录，保留原 compiler 路径、profile、复制内容的流式 SHA-256/字节数，执行同步与内容复核后，再把两种环境别名指向该副本。新 attempt 不覆盖既有 manifest/env；另有只读复核入口核对源码身份、完整 binary 集合、环境映射和当前副本内容。这项源码改动仍须新的准备和测试执行产生证据，不能补写旧门的证明。

去掉副本写权限与独立目录可以避免正常 Cargo 重链接覆盖已选路径，**不构成不可篡改存储**：拥有目录/文件权限的主体仍可替换文件或改变权限；两次读取相同也不能证明期间从未短暂修改。证据只报告实际观察和宿主保管前置条件。

## 10. 六个 WebSocket 场景：脚本必须允许兼容性变化后的真实重连

实际观察分成两种。三个 [git-enrichment 场景](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/git_enrichment.rs) 与两个 [websocket turn-state 场景](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/turn_state.rs) 的原 stderr 只记录了 startup prewarm batch，此后没有预期的同连接请求；startup/turn-state 在 30 秒预算结束，两个 ephemeral git 场景直接等 TurnComplete 并在 10 秒失败。[`remote_mid_turn_compact_v2_sends_turn_state_over_websocket`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/compact_remote.rs) 则实际只观察到 2 个请求，原断言要求 5 个。

已核对的源码合同有三点：

1. [WebsocketConnectionIdentity 与 `websocket_connection`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/client.rs) 比较实际 compatibility projection；[projection](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/responses_metadata.rs) 绑定 sandbox、workspace 元数据及 compaction 请求种类等字段。变化时需要新连接，不能为测试复用旧连接而删除这些绑定。
2. `TestCodex::submit_turn` 显式设置 Disabled permission profile，可能把 startup 的 read-only 改成 danger-full-access；git 普通 turn 的异步 enrichment 又会从空 workspace 元数据变成真实仓库状态。compaction 请求种类与普通 sampling 也不同。这些是具体 compatibility 变化，不是随机网络延迟。
3. [原 WebSocket fixture server](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/common/responses.rs) 逐连接消费脚本：在旧连接上等下一条 scripted request 时，还不会接受新连接。旧测试却把跨 compatibility 边界的所有 batch 放在同一连接，因而会阻塞合法重连。stable-within-turn 用例还没有独立 warmup batch，启动 prewarm 会先消费其原本留给实际 turn 的第一份响应。

本轮只调整这六个 fixture 的精确脚本边界，使用现有多连接配置，不改变公共 mock server 或生产 transport：

| 场景 | 每条连接上的确切请求数 | 保留的核心断言 |
| --- | --- | --- |
| git startup | `[1, 1, 1]` | prewarm 没有 workspace enrichment；真实 follow-up 包含修改后仓库的 remote、HEAD 和 dirty 状态。 |
| system / ambient git | `[1, 1, 1, 1]` | root/system 的独立 prewarm、system turn 的真实最新 git 元数据和原 root-turn lineage。 |
| 两个 turn-state | `[1, 3]` | 专属 warmup 后，实际 turn 的 tool follow-up 仍复用同一个物理连接；第一 state 保持、下一 logical turn 清空；原 read-only→danger-full-access 与 turn ID 断言保留。 |
| mid-turn compaction | `[2, 1, 2]` | prewarm+sampling、compaction、普通 continuation 三个阶段；后两次 continuation 共享连接；按原顺序核对全部 5 个 payload 和一直保留的 `sampling-state`。 |

git fixture 用已有 `test_sync_tool.wait_for_git_enrichment` 等待真实 enrichment owner 完成，替代固定 sleep。关闭的是上述明确完成的 scripted connection；没有接受任意连接数、删掉 logical payload/state 断言、延长事件预算或关闭安全绑定。

本轮状态：三份测试文件的修复已落盘，尚未执行。旧“turn completion and its finish owner”错误同时包住两个等待阶段，单凭文案不能认定是 finish owner 卡住；不经过该 helper 的两个 ephemeral 失败也说明不能把这六项一概归给新增 finish-owner 等待。

## 11. 两个 HTTP TokenBudget 场景：manual compaction 之后也要观察原 finish owner

实际失败为 `token_budget_context_uses_new_window_after_compaction` 的 token-budget-only 与 retain-client-developer 两个参数场景，原日志都在 `core/tests/common/lib.rs` 的事件等待处约 10 秒超时。[fixture](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/token_budget.rs) 明确关闭 WebSocket，因此不能借用第 10 节的 transport 解释。

源码中存在独立的收尾窗口：第一次普通 `submit_turn` 已等待自己的 finish owner；随后测试提交 `Op::Compact`，私有 `assert_context_compaction_item_lifecycle` 核对两个 ContextCompaction item 事件，但一遇 TurnComplete 就返回，caller 立即提交下一 turn。[真实 task finish 合同](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/tasks/mod.rs) 在 TurnComplete 之后仍保留收尾 fence，下一次 admission 可以尚未 ready。此时 helper 如果继续等没有被接纳的新 TurnStarted，就会超时。

本轮精确修复这个私有 helper：记录实际 compaction TurnComplete 的 `turn_id`，保留原 started/completed 断言，再增加一个 10 秒有界等待，观察已有 `pending_normal_turn_finish_completion(&turn_id)`。原 item 事件循环是直接 `next_event`，没有独立 deadline；不能把新增 finish 等待描述成原循环早已共用的计时起点。后继普通 turn 的事件预算未延长。该接口按 Finish terminalization 和精确 owner turn ID 匹配，并不限于 `TaskKind::Normal`；没有替换成不相关任务的全局等待，也没有拿 TurnAborted 当正常完成。生产 admission、compact 路径和两份 HTTP mock response 均不变。

本轮状态：源码证明了一个真实窗口，修复已落盘，尚未执行；旧日志没有调用栈，不能提前声称已复现并排除所有其他失败阶段。

## 12. Pre-output recovery fixture：必须在首个 provider event 之前中断

实际失败为 [`recover_turn_if_idle_preserves_id_and_resumes_plan_mode`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/turn_input_submission.rs)：首次与重试均在 5 秒后报告 `interrupted idle turn should expose its recovery epoch`。原 fixture 第一段 SSE 不受 gate 控制，先发出 `response.created`；只有后续 `response.completed` 被 gate 挡住。

[真实 outer turn executor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/session/turn.rs) 在对首个 provider event 做 `match` 之前调用 `gate_first_provider_output`，因此 Created 也关闭 pre-output 恢复窗口。[task owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/src/tasks/mod.rs) 在该边界持久化 Unready。原 fixture 已允许 outer executor 消费 provider event，再期望出现合法 recovery epoch，与该合同冲突。

本轮把第一份响应的 Created 与 Completed 一起置于同一个既有 gate 后。[streaming SSE server](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/common/streaming_sse.rs) 仍先记录已收到的物理请求并通知，再等待响应 gate；所以测试继续证明实际 dispatch，不是没有接触 provider 的假请求。原 Ready/input/TurnContext 持久顺序、同一 turn ID、Plan 模式覆盖参数、两次请求、原 input 只出现一次和 5 秒预算均保留。没有放宽 Unready 或物理输出后的恢复授权。

本轮状态：最小 fixture 修复已落盘并经独立源码复核，尚未执行。Plan 是原 recovery request 中的模式参数；本记录不把它夸大成原测试已有的单独模式结果断言。

## 13. Skill zsh fixture：同一个 TurnComplete 只能消费一次

实际失败为 [`shell_zsh_fork_skill_scripts_ignore_declared_permissions`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/skill_approval.rs)，原日志在公共事件等待处超时。

源码给出一个确定的事件消费错误：私有 `wait_for_exec_approval_request` 只有在消费 TurnComplete 时才返回 None。测试成功断言 approval 为 None 以后，又调用 `wait_for_turn_complete`，因而等待同一轮并不存在的第二个完成事件。

本轮只删除这次重复等待并说明消费关系。approval 必须为 None、实际 tool output、turn sandbox 拒绝越界写入、目标文件实际不存在等原断言全部保留；同文件第二个场景的必要 completion 等待不变。没有改变 skill approval、声明权限、sandbox 或执行环境。

本轮状态：源码修复已落盘并经独立复核，尚未执行；原失败仍保留。

## 14. 两个 auto-compaction watchdog：拒绝结果不能被当成已启动 turn

原生 [`auto_compact_emits_context_compaction_items` 与 `auto_compact_allows_multiple_attempts_when_interleaved_with_other_turn_events`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/compact.rs) 首次和重试均在约 60 秒被 runner watchdog 终止，原 JUnit 没有栈或最后事件。因此不能宣称旧执行已精确定位到某次循环，也不能仅据 watchdog 判成资源不足。

两个 fixture 都有同一源码窗口：对三个连续 user turn 调用 `start_or_steer_turn`，只 unwrap Result，没有检查里面是否为 Started；每轮裸 `next_event` 循环一遇普通 TurnComplete 就提交下一轮。Finish owner 此时可能仍保留 admission fence，合法的 NotIdle 可以被当成成功提交后丢弃；之后裸循环将一直等待不存在的新完成事件。

本轮仅修这两个循环：每次 submission 必须为 Started，否则立即显示实际返回；捕获消费到的普通 TurnComplete ID 并与刚接纳的 ID 比较，再以 10 秒有界等待观察该精确 finish owner。原 auto-compaction item ID、legacy event、不得伪造 auto-compaction task lifecycle、六个请求及两次 summary/tool-output 内容等断言保留。模型响应脚本、token 阈值、生产 admission 和原 runner 时限均未改。

本轮状态：修复已落盘，尚未执行；这是闭合源码可见窗口，不是追认两次历史 watchdog 已有唯一根因证明。

## 15. Apps recovery 与 OAuth fixture：保留真实竞争，同时等原 turn 收尾

实际失败分别为 [Apps follow-up](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/mcp_tool_exposure.rs) 的公共事件等待超时，以及 [OAuth round-trip](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/rmcp_client.rs) 的 `a newly discovered OAuth server blocked the user turn during store contention` 5 秒 deadline。两者原先手工消费上一轮 TurnComplete 后立即提交后继 turn，也没有观察对应 finish owner。

Apps fixture 现在同时保留第二轮实际 TurnComplete ID 与 AppsReady，两个条件满足后，在**原来的同一个 5 秒 block 内**等该 ID 的 finish owner，再提交第三轮。原 Calendar namespace 恢复、三个 model 请求和三次 initialize 断言不变。

OAuth fixture 在第一轮 contention 的**原 5 秒 block 内**等其真实完成 ID 的 finish owner，credential-store 文件锁仍真实持有；随后新发现 server 的 turn 显式检查 submission 为 Started，并保留原第二个 5 秒预算。锁的释放位置、真实认证失败/恢复、token 和模型回复断言均未提前或删除。没有取消待测竞争来制造通过。

本轮状态：这两处测试修复经独立源码复核，尚未执行。源码能确认遗漏收尾等待，原日志仍不足以排除其他失败阶段；没有更改生产 MCP、OAuth、目录可见性或审批策略。

## 16. Idle async-hook fixture：只生成待测的那份旧轮结果

实际失败为 [`async_hook_finishing_while_idle_waits_for_the_next_turn`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/core/tests/suite/hooks.rs)，原生首次与重试均在约 5 秒报告 `timed out waiting for the next turn to complete`。

原 fixture 要验证第一轮结束后才完成的旧 hook 结果：闲置时不能自行启动 model turn，下一轮必须在新 prompt 前包含旧 context，并把旧 warning 绑定到第二轮。但同一个 UserPromptSubmit 脚本也会在第二轮运行；共享 release 文件此时已存在，因此它会再生成一份当前轮的 additional context。fixture 实际不再只有那份被测旧轮结果，可能在第二轮引入额外 sampling，与仅两份 model response 的脚本冲突。旧日志没有完整事件轨迹，本记录不把这条源码路径写成已经动态证明的唯一超时原因。

本轮只把 gated fixture 变为一次性结果源：用 `started.open("x")` 原子认领第一份真实 invocation，后续 invocation 碰到 FileExistsError 后正常退出且 stdout 为空。生产 hook 仍按每个匹配 turn 调用；非 gated fixture 保持原行为。[真实 UserPromptSubmit parser](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75/codex-rs/hooks/src/events/user_prompt_submit.rs) 对 exit 0、空 stdout 不生成 entries 或 additional context，因而没有为消除重复而伪造一份空 JSON 结果。

首轮真实 gate/finished 文件、闲置 150 毫秒不得发事件、总共两次 model 请求、旧 context 在新 prompt 之前、warning 属于第二轮 ID 和第二轮 5 秒预算等断言均保留。本轮状态：fixture 修复经独立源码复核，尚未执行。

## 17. 保留尚未闭合的失败与下一轮判定边界

原始失败集中还有 stream-FD `Operation not permitted`、事件等待与异步 deadline、compaction 请求数断言和 watchdog 等条目。本轮不能把它们随上述修复一并计为解决，也不根据共同的 timeout 文案推断共同根因。five-pair watchdog 与 cold resume 的不确定边界已分别保留。

同一 7391 的 [独立 GitHub composition 执行](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42174445576/job/127749547759) 也终态失败：runner 记录 5,894 个执行、5,855 个通过、37 个普通失败、2 个 timeout、92 个 skipped。这是另一运行范围的记录，不能与 ai395 的 6,631 直接合并。两处均出现 websocket compaction 的请求数 2 对 5、三个 git-enrichment 场景、两个 websocket turn-state 场景和两个 token-budget-after-compaction 场景失败；第 10、11 节据实际 transport/finish-owner 合同分别修复，仍待新门验证，不能把失败全部归给单台机器的资源。

下一轮必须绑定新的固定源码、实际 helper manifest、原始日志和 JUnit，再逐项判断修复结果；scoped 门通过后仍须执行此前没有启动的完整默认 workspace 门。此文不修改原 54 个失败的结论，不授予 normal-entry 新测试、真实训练权重、跨 manifest 采用或跨 boot 恢复资格。

## 18. GitHub JUnit 收集：缺失报告必须使验证门失败

已实际下载同一 GitHub run 的两份原生 artifact，并核对 GitHub 提供的 archive SHA-256：composition artifact `13484454604` 为 1,244,838 字节、29 个文件，摘要 `23cbc1242923fa47b072a38186a52a05b62abab43ab5ae638005b0579d0e85d2`；mechanisms artifact `13483506997` 为 715,492 字节、15 个文件，摘要 `aa9391fee84c0f07d9c13fadcce6cbd476cac4f38ed79531cb5ab2c12be367b6`。两份都没有 JUnit XML。因此，第 17 节的 GitHub 数字只来自保留的 runner 日志，不能声称已有独立 XML 复核。ai395 的原始 XML 和 6,631 case 解析不受这一缺口影响，也不能移作 GitHub 证明。

两边实际 nextest 版本不同：GitHub workflow 固定 `0.9.103`；ai395 的版本回执为 `0.9.146`。原配置只在 `profile.default.junit` 声明输出，而 `just test` 选择 `local`。旧 CI 只在预期文件存在时复制，缺文件不会独立使收集门失败。本轮为 `profile.local.junit` 明确声明 `path = "junit.xml"`，与 [nextest 的 profile 输出配置](https://nexte.st/docs/machine-readable/junit/) 对齐；不改变测试选择、重试或 watchdog。

新增 `hepta_ci_junit.py` 在每次 scoped/full 命令后保留真实 XML并核验：对应执行记录的干净 source/tree/argv、命令时间窗内的新文件、实际字节摘要、非空 case、逐 case 的 failure/error，以及与原 runner 终态计数的一致性。命令失败、缺失/陈旧 XML 或计数矛盾均不能通过；失败报告仍保留，输出使用独占创建，不覆盖旧证据。脚本的合成回执测试只验证这项收集逻辑，不计入 Rust 执行或模型资格。

新的 workflow 同时对 attempt helper 副本做 scoped/full 后验字节硬核对。上传内容包括日志、执行回执、XML、manifest 和复核记录，**不包括 `helpers/bin` 中的 executable 副本**；实际副本的路径、模式、字节数和 SHA-256 保留在 manifest 中。不能把该 artifact 描述成包含运行主机所有文件的镜像。
