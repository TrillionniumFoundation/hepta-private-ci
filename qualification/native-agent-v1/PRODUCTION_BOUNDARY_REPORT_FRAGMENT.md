## 模块决策、生产接入与恢复边界

本轮完成的是有限 native agent 闭环、可注入的模型接口及同一 ThreadStore owner 内的持久 checkpoint 切片。
正式 benchmark 仍使用独立的 qualification `SessionOwner` 和默认 `ResponsesModel`；Agentd 尚未切换。
因此，资源与任务结果描述的是这个受测实现，不能描述为已经接入全部生产 owner 的 native 服务成本。
详细实现与固定基线见 [架构决策](ARCHITECTURE_DECISION.md)及[owner 边界](OWNERSHIP_BOUNDARIES.md)。

### 已实现的切片及其证据范围

| 能力 | 已实现、可验证的内容 | 尚不能据此声称 |
| --- | --- | --- |
| Native loop | 用户输入、上下文预算、模型流、工具执行与回填、最终回答；工具复用真实 runtime jobs owner，pending 保留原操作 | 完整 Codex 编码能力、生产工具策略或全部旧会话兼容已覆盖 |
| `ModelPort` | engine 接受泛型端口；外部 wrapper 测试证实拒绝入口后实际 HTTP peer 零 POST，精确 pending body 不变，原 Response ID 查询继续委托原解析器 | 生产 FinalUse 已被消费；测试 gate 不是 grant，受限 completion 类型也不是执行授权 |
| ThreadStore checkpoint | 原 live writer／epoch／删除围栏；原 binding、CAS、完整 hash chain；SQLite durable commit；等待方取消后 owner task 继续持有 guard 至提交结束 | benchmark 或 Agentd 已使用 sidecar；与单独 rollout 文件原子提交；宿主真实 Fleet／lease verifier 已安装 |
| 工程与 fault 检验 | 本轮记录的 259 项测试、严格 Clippy 及已声明范围的 fault qualification 通过 | 所有生产接入门已通过，或三路 whole-agent 故障恢复已公平比较 |

`NativeCheckpointPermit` 只保留宿主交来的 guard，本身不校验 Fleet、lease 或 FinalUse。
恢复保留原 operation／generation／lease 的关联；当前宿主必须独立提供观察或落账该原操作的有效权限。
不能把恢复写成新操作，也不能把固定 generation 1 的实验 owner 当成生产代次验证。

### 生产替换仍需完成的组合

1. **会话与队列。** 以真实 Agentd／Fleet、run coordinator、LiveThread 和 QueueStore 组成一个
   `TurnOwner`，保留原 thread／turn／operation、租约、代次与队列提交身份。
2. **持久状态。** 将自包含 native state codec 接入已实现的 checkpoint API；核对旧线程恢复、
   队列重投、损坏拒绝及 history recovery binding。checkpoint 与 rollout 的跨文件一致性仍须明确处理。
3. **模型与工具的实际入口。** 从同一 production writer 的原 receipt 派生准确 binding，
   由外部 grant provider 签发，复用一次性 dispatch claim 和同一 `FinalUseAuthority`。
   可等待的准备和写前记录结束后，再核对取消、deadline、lease、generation／撤销，
   用原 token 的 `enter(expected)` 消费最终使用权并交给实际提交函数。现有 target trait 的
   流式 SSE 交接仍有接口缺口；不能把 `admit` 时的一次检查算作稍后 HTTP／process 入口已授权。
4. **不明结果恢复。** 未知模型结果只查询原 Response ID；未知工具结果只观察原请求／job。
   没有可查询的原 Response ID 时继续 pending，不靠新 POST 判断前次是否发生。
   当前 live qualification gateway 未验证生产 provider 的 retained-response GET 恢复。
5. **服务生命周期。** 接入 Agentd startup、readiness、fencing、drain、取消、AuthBus queue reconciliation
   与 supervisor shutdown，并在这些真实 owner 下重做撤销、丢回应和崩溃边界的检验。

这些工作应复用已有 authority、writer 和 jobs owner；新增布尔授权、复制 grant journal 或第二个作业登记表
不能补齐组合。接受、checkpoint 成功和关联 receipt 都不等于真实终态完成。

### 执行层如何独立

| 决定 | 当前建议 |
| --- | --- |
| 独立接口 | 收敛 execution port、Cell contract 与 execution-core；同一身份和状态语义供两个后端使用 |
| 独立库 | 发展 Hepta native agent 与薄 Codex adapter；宿主注入模型、工具和既有 owner |
| 独立进程 | 按权限、配额和故障隔离需求决定；Cell 是逻辑能力单元，不默认一 Cell 一进程 |
| 独立仓库 | 等契约和发布需求稳定后再拆；当前 workspace 库边界不等于独立发布包 |

官方 Codex 0.165.0 已有进程内 facade，且与 App Server 复用 `MessageProcessor`。
因此获得可替换执行边界不需要先长期 fork 整个 Codex；完整 fork 会接管协议、工具、历史、取消与升级维护。
facade 仍有队列和协议处理，本次受测 facade 还带外层 JSONL 桥，不能解释为零 IPC。
接口／库独立不强制 RPC；跨进程才额外引入通信、监督、断连、状态同步和版本协调成本。
这些是架构机制，具体差值以对应正式测量为准。[官方嵌入实现][native-boundary-inprocess]
[官方 facade][native-boundary-facade]

### Codex 整进程恢复的准确边界

固定官方源码中，App Server 的 pending JSON-RPC callback 与 Core 的 dynamic-tool waiter 依赖存活内存。
warm `thread/resume` 可重放仍存活的 callback；冷启动读取旧历史不会自动重建原 request／call continuation。
Core **确实存在** `recover_turn_if_idle`：可保留指定 turn ID，但会重新启动模型采样，
不是当前 App Server／facade 提供的原 pending dynamic-tool 恢复入口。
[Core API][native-boundary-recover] [sampling restart 定义][native-boundary-recover-request]

| 本次 fault 路径 | 故障目标 | 可报告的结论范围 |
| --- | --- | --- |
| Native | 整个 qualification agent runner | 该 runner 在实际夹具中的原操作／job 恢复 |
| App Server／facade | runtime helper，Codex 核心继续存活 | helper 重启后的原 job 恢复 |

故障目标不同，因此不能计算 whole-agent 恢复胜负。Codex whole-process exact pending 恢复尚未完成验证；
源码表明当前协议组合存在缺口，**未测不能计为失败或 native 的可靠性优势**。
复用 thread／turn ID、注入历史或得到最终回答，也不单独证明原 pending call 已接续。
[pending callback 实现][native-boundary-callback] [冷恢复状态处理][native-boundary-cold]

执行模块及有限任务验证的进展也不证明 Cell 的语义寻址、自适应分裂／重组或通用智能已经成立。
结构价值仍须在固定模型、执行器与总预算后，独立比较单 Cell、固定多 Cell 与自适应系统。

[native-boundary-inprocess]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/in_process.rs
[native-boundary-facade]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server-client/src/lib.rs
[native-boundary-recover]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/core/src/codex_thread.rs#L470-L518
[native-boundary-recover-request]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/protocol/src/turn_input.rs#L101-L112
[native-boundary-callback]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/outgoing_message.rs#L248-L261
[native-boundary-cold]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/request_processors/thread_lifecycle.rs#L1074-L1087
