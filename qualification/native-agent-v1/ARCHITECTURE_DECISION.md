# 执行模块独立发展的架构判断

## 决策与证据范围

建议独立发展 Hepta 的执行契约与 native agent 库，将 Codex 保留为可替换后端。
目前不建议为取得模块边界而另建长期脱离上游的完整 Codex 分支。
接口、库、进程、仓库是四项不同决定，应分别评估，不能把“全部解耦”作为一个开关。
本文记录源码审查与工程判断，不包含三路性能实验结论，也不宣告生产替换完成。

官方版本固定为 [Codex 0.165.0][release]，发布于 2026-10-27 20:09:38 UTC；
源码固定为 `360319d8dee62d87e2d59fc0c21805d79519cfed`，不混用后续默认分支。
[官方 toolchain][toolchain] 声明 Rust 1.99.1；本实验的 1.95.0 应标为构建覆盖值，
不能把该构建描述为未经修改的官方发布二进制。Hepta owner 审查基线另见下文。

## 官方已经存在的进程内嵌入层

| 接口 | 固定源码确认的职责 |
| --- | --- |
| `codex_app_server::in_process::start` | 在 Tokio tasks 上运行现有 `MessageProcessor` 和 outbound routing，以内存通道代替 stdio／socket |
| `InProcessClientHandle` | 接受 typed request、notification，提供事件消费和 shutdown |
| `InProcessAppServerClient` | 包装底层 handle，集中启动、初始化、typed response、服务端请求回复及退出处理 |

[底层实现][inprocess] 构造同一个 `MessageProcessor`；[共享 facade][facade] 调用该底层入口。
官方 [exec][exec] 与 [TUI][tui] 的代码也实际调用 `InProcessAppServerClient::start`。
因此 facade 是现有执行语义的嵌入方式，无需为了进程内调用重新实现一个 Codex 引擎。

该路径仍保留协议工作：结果使用 JSON-RPC result envelope，`request_typed<T>` 从 JSON value
解码；facade 通过 worker task、`mpsc` 和 oneshot 传递请求。它不能被称为零序列化或零队列。
命令及底层 runtime 通道有界，facade 的本地事件消费队列则为 unbounded，避免未消费通知
阻塞请求响应；底层还可能报告 `Lagged`。宿主仍需及时消费、观察积压并处理事件缺失。[源码][facade]

## 四种独立决定

以下是工程建议，表中的成本机制并非本次实验已经测得的性能差值。

| 决定 | 建议 | 需要保留的约束与代价 |
| --- | --- | --- |
| 接口独立 | 现在收敛中立 execution port、Cell contract 与 execution-core 的重叠 | 单一身份和状态语义；明确准入、接受、终态、取消及原操作恢复，避免重复协议 |
| 库独立 | native loop 与 Codex adapter 各自形成可测试边界 | 注入 model、runtime 和既有 owner；库调用可以留在同一进程，不自动产生 RPC |
| 进程独立 | 按故障隔离、配额和部署需要选择 | 独立进程增加 IPC、监督、断连恢复及 drain；嵌入库共享宿主的故障域和资源 |
| 仓库／项目独立 | 等接口和独立发布需求稳定后决定 | 独立仓库增加版本协调和上游维护；不能靠复制 owner、DTO 或授权日志制造表面独立 |

当前 native 库仍在本 workspace 中复用中立类型及共享 HTTP 基础设施。
有明确库边界，不等于已经成为无需 workspace 依赖的独立发布包。
若未来多个产品需要独立升级，可在固定契约、依赖和兼容测试后拆仓；不应反向创造第二份协议。

## 为什么每个 Cell 不应默认拥有一个进程

Cell 是语义路由、能力或组合的逻辑单元，执行资源可以由有容量限制的共享服务提供。
增加 Cell 不应隐含复制完整模型上下文、provider 连接、工具目录、缓存和会话 owner。
先让 Cell 保存自身必要状态，将可执行意图交给共享 execution port，再按并发和隔离需求调度。
需要不同权限、硬资源配额或故障域时，可以把一组 Cell 放入独立 worker；数量由隔离需求决定。
跨边界仍须保留父子 operation 关联、原请求及取消语义，不能在故障后重建身份来“恢复”。

这是对系统组成的建议，不是关于共享执行器一定更快的测量结论。
结构价值应由同模型、同执行器、同总预算的单 Cell／固定多 Cell／自适应实验独立判断。
会话 fork、创建节点或增加任务吞吐，本身不能证明学到了更好的分工或保留了旧能力。

## 全量解耦需要分别核算的成本

| 成本 | 具体机制 | 判断方式 |
| --- | --- | --- |
| 边界 | 编解码、复制、唤醒、队列、pipe／socket、连接维护 | 固定模型响应重放，比较相同工具和相同任务 |
| 状态 | 多份历史、pending call、schema、catalog、缓存 | 检查实际 owner 和数据副本，测完整进程树及 detached jobs |
| 一致性 | 准入与终态跨边界、代次变更、撤销、丢回应 | 对原操作注入故障，验证仅观察和正确恢复 |
| 生命周期 | readiness、监督、drain、退出及重连 | 分别验证独立进程与嵌入宿主的真实行为 |
| 维护 | workspace 类型、toolchain、feature、lockfile、协议版本 | 固定版本构建和兼容测试，记录必要补丁 |

持久准入、原操作身份和物理入口授权属于正确性要求，即使取消进程边界也不能删除。
二进制大小不等于运行内存，主进程 RSS 也不能代表工具子进程和外部服务的总资源。
本 qualification 的 facade 还有外层 JSONL 测量桥，不能把其结果解释为零 IPC 嵌入的估计。

## exec-server、hepta-runtime 与完整 harness

官方已有 [codex-exec-server][execserver] library、CLI 和 Rust client；其职责是进程／文件系统
handlers、传输与专用协议。它提供的 thread／tool-call metadata 用于关联，不授予执行权限。
这说明“工具执行后端”和“完整 agent harness”应分别验证。

| 替换范围 | 需要承担的职责 |
| --- | --- |
| 工具执行后端 | 真实作业启动、输出、取消、终态与原请求恢复；本实验复用 hepta-runtime jobs owner |
| Agent harness | 用户输入、上下文预算、模型流、工具调用和回填、最终回答、取消及模型断流恢复 |
| 生产 agent 组合 | 将 harness 接到既有会话、队列、代次、租约、授权、持久化和服务生命周期 |

hepta-runtime 可以作为 Codex 和 native 共用的执行基础；仅有 runtime library 并不完成后两行。
native 的有限工具闭环可以独立验证，但不能外推为完整编码 agent 能力或生产迁移已完成。

## 本 prototype 的生产 owner 缺口

本项判断固定在 Hepta 基线 `88a43bece9428b091479712b4c29084720d87123`；
逐项源码与放行门见 [OWNERSHIP_BOUNDARIES.md](OWNERSHIP_BOUNDARIES.md)。
已有 Agentd／Fleet、run coordinator、ThreadStore／LiveThread／QueueStore、history recovery、
FinalUse writer／targets 和 AuthBus；缺口是这些 owner 与 native loop 的组合，不是另建权威服务。

当前 `TurnOwner` 接缝由宿主提供身份与准入，资格 runner 的 `SessionOwner` 仍使用固定 generation 1。
其私有文件、锁、不可变准入和 checkpoint hash chain 证明实验内一致性，不能替代生产 principal、
活跃租约、代次撤销、队列 dispatch 或绑定物理目标的 FinalUse grant。
真实 jobs owner 已复用；`ModelPort` 与同一 `ThreadStore`／`LiveThread` owner 下的 typed checkpoint
API 已实现。后者通过 sidecar SQLite 的 durable commit、原 binding、CAS／hash chain 和原 writer
epoch 保留 pending state；owner task 在等待方取消后仍持有 writer／lifecycle／host permit 至提交结束。
这解决了可复用的存储切片，不代表 qualification runner 或 Agentd 已经使用它；runner 仍使用
`SessionOwner`，native 的状态 codec、生产会话／历史恢复映射及 Fleet／queue permit provider 尚未接入。
sidecar 不与单独的 rollout 文件形成原子事务，currentness permit 也不替代物理入口的 FinalUse。
模型与工具入口尚未完成生产 writer／target 组合，Agentd 的启动、ready、drain 和 AuthBus 路径
也尚未切换。[存储 API](../../codex-rs/thread-store/src/native_checkpoint.rs)
[真实 store 实现](../../codex-rs/thread-store/src/local/native_checkpoint.rs)
canonical converter 只转换关联数据，终态 receipt 不产生新执行权限。[契约说明](CONTRACT_CONVERGENCE.md)

## ModelPort 切片与真实 FinalUse 的组合路径

本次增加的 `ModelPort` 只开放 `open(original_request)` 与 `reconcile(original_request, response_id)`，
engine 已接受该泛型端口，`ResponsesModel` 实现它并保持原行为；返回值仍是受限的
`ResponsesStream`／`ObservedModelCompletion`。qualification runner 使用的是默认实现。
外部宿主可以拒绝首次入口并委托原响应查询，不能通过新公共构造器伪造模型终态。
外部 wrapper 测试使用真实 HTTP peer 检查零 POST 与原 Response ID 的 GET；测试拒绝器不是生产授权。
该切片不创建 grant、authority journal 或新的 operation owner，也没有接通生产 writer。

生产组合必须遵循既有 owner 的真实调用链，以下是尚需完成的接入顺序：

1. 宿主将原 operation、generation、目标和精确载荷交给已有 `ProductionDurableWriter::prepare_operation`，
   使用原 `OperationIntentV1` 与 `ProductionQueuedReceipt`；模型 body 和工具 `ProcessStartParams` 均须保持不变。
   endpoint／destination、策略和 deadline 也须进入相应不可变绑定；native 准入结果本身不授予执行权限。
2. 将 native 状态 codec 接入已实现的 ThreadStore checkpoint API，持久化原 pending 状态及其关联，
   由真实宿主 currentness provider 保留 guard 至提交结束，完成写前记录后才尝试入口；
   不把 grant token 序列化进 checkpoint，也不另建并行 outbox。
3. 从同一 writer 的 `final_use_binding(receipt, destination_id)` 派生准确绑定，交给外部
   `AgentdFinalUseGrantProvider::signed_grant`；不能用仅含 semantic digest 的另一个 binding helper 替换它。
   签发者仍是独立 grant provider，native 库不持有签名密钥。[生产宿主][production-host]
4. 复用同一 writer 的一次性 dispatch claim、原 outbox 状态与同一个 `FinalUseAuthority`；
   真正的 `claim(signed_grant, expected)` 得到不可克隆的 token。完成所有可等待的准备与写前记录后，
   重查 owner／lease／generation、取消和期限，再用该 token 的 `enter(expected)` 消费最终使用权。
5. 将得到的 `EnteredUseToken` 传入具体授权提交函数，紧接模型原 POST 或 runtime 原请求的首次 effect entry；
   不能在 admit 时检查一次、稍后任意发送。现有 infer worker 已有“写前记录→重查→enter→授权提交”实例。
   此保证是宿主本地异步入口；若要求远端物理 spawn 时也核验同一 FinalUse，目标端还须参与该协议。
6. 收到 provider Response ID 或 runtime job binding 后记录原关联；断流／回应不明只能查询该原响应或
   `observe_request(original_params)`。不得再次 POST、换 operation 或再领一个 grant 来判定前次是否发生。
   最后由真实终态证据回写原 writer／turn；accepted、checkpoint 成功和关联 receipt 均不等于任务完成。

第 4—5 步目前存在明确接口缺口：[生产 target trait][production-writer] 返回异步 `ProductionTargetOutcome`，
不交付实时 SSE stream，也不把 `VerifiedUseToken` 作为 target 参数。现有 dispatcher 在
`with_verified_use` 后立即等待 target future；这不能保证 target 内部后续等待后的 HTTP send 再核验一次。
当前核查的生产 target 是 cognitive source 目标，不能把泛型 target 当作现成的 checked HTTP／process adapter。
接入需要从原 writer 中复用一次性 claim 与 token 交接，提供兼容流式模型入口的受检路径；
公开 `mark_indeterminate` 允许原状态重放，不能单独替代私有的一次性 dispatch claim。[writer 源码][production-writer]

[现有 infer worker][native-authorized-entry] 的 `VerifiedUseToken::enter` 和接收 `EnteredUseToken` 的提交函数
提供了可复用的边界形式；[FinalUse 类型][final-use-types] 要求使用同一 authority 的真实状态及撤销前沿。
[hepta-runtime native facade][runtime-native] 复用 jobs owner，但要求宿主验证 principal／turn／generation／FinalUse；
其 [jobs owner fence][runtime-jobs] 不会自动变成 Agentd／Fleet 的同一代次和授权检查。
因此最小 ModelPort 解决宿主注入位置，外部 grant provider、一次性 writer 入口、原 token 消费、
生产恢复与生命周期组合仍是后续放行门，不能用测试 gate 或另建布尔授权替代。

## 保留 Codex 后端与重新评估条件

[facade 的依赖][facade-cargo] 直接连接 app-server、core、exec-server、config 和 protocol；
[App Server][server-cargo] 还组合工具、扩展、历史与持久化等组件。抽出完整 Codex 会接管这些维护关系。
0.165.0 发布记录包含 MCP 取消、阻止中断后的队列唤醒、model-not-found 终态等修复；
长期 fork 需要自行跟踪、合并和验证这些语义，而不只是维护启动包装层。[发布记录][release]

先保持薄 Codex adapter 与可独立验证的 native 模块；生产 owner 组合、目标任务正确性、原操作恢复
和资源证据达到既定门槛后，再决定默认后端和独立发布范围。任何性能结论应引用对应正式实验记录。

[release]: https://github.com/openai/codex/releases/tag/rust-v0.165.0
[toolchain]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/rust-toolchain.toml
[inprocess]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/src/in_process.rs
[facade]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server-client/src/lib.rs
[exec]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/exec/src/lib.rs
[tui]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/tui/src/lib.rs
[facade-cargo]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server-client/Cargo.toml
[server-cargo]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/app-server/Cargo.toml
[execserver]: https://github.com/openai/codex/blob/360319d8dee62d87e2d59fc0c21805d79519cfed/codex-rs/exec-server/README.md

[production-host]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-agentd/src/production_writer_host.rs
[production-writer]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-memory/src/production_writer.rs
[native-authorized-entry]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-infer-worker-host/src/native_app_server.rs
[final-use-types]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/88a43bece9428b091479712b4c29084720d87123/codex-rs/hepta-contracts/src/final_use.rs
[runtime-native]: https://github.com/TrillionniumFoundation/hepta-runtime/blob/d7d039458c8745bea1bafd24f03635e75a66a2f4/src/native.rs
[runtime-jobs]: https://github.com/TrillionniumFoundation/hepta-runtime/blob/d7d039458c8745bea1bafd24f03635e75a66a2f4/src/mcp/runtime/jobs.rs
