# Cell 架构：六项要求、实际代码路径与采用边界

本说明以 `a6f3aa12ba187448c35449c7da0a9798ae4ca987` 为既有基线，区分该基线已经实现的机制与本候选的增量。审计在 2026-11-07 UTC 更新；目录日期沿用本轮任务标识。本文件是源码与验证范围索引，不是生产启用、真实模型质量或资源收益的批准。

**本候选补齐表示接口、输入背压、有限恢复余量与完整状态绑定的具体缺口；生产中的统一 Cell 调度、全部表示后端和跨 owner 原生迁移仍需接线与独立验收。** 既有 `DENY_ALL`、外部效果 owner、独立认证、最终使用处的 fence、旧 TaskFlow 无环检查继续成立。新增测试的源码存在不等于测试已执行；实际结果须使用绑定本候选源码的独立运行回执，不能继承历史测试总数。[原注册边界][registry]、[原 Circuit admission][circuit-admission]、[原 topology admission][topology-execution]

## 1. 六项映射

| 用户要求 | a6f3aa12 已有的机制 | 本候选增量 | 尚未获得的资格 |
| --- | --- | --- | --- |
| 5.2 外层契约与内部表示 | 不可变 backend 注册、scope／来源／bundle 身份、原生决定回执；Q24 输入宽度 1–512 | 五类精确表示 profile、完整来源 envelope、显式协商与投影；双方完整契约的 current-use 核对、密封 backend 绑定、原 admission／commit 的冷重建 | 真实 EG2 特征来源和质量资格；token／时空／生成／训练状态的完整执行后端；owner 对材料和评价证据的独立认证 |
| 5.3 控制与高频计算分离 | 独立 inference port、共享 worker 抽象、Cell 分区状态、按兼容性组成 microbatch；Organ 回调保持轻量可信代码边界 | Circuit 表示入口复用原 Cell owner／worker，并在 durable admission 后再次核对当前契约；Cell 队列／批次字节上限、队列局部取消与 plasticity 即时背压 | 默认 daemon 的统一 Cell scheduler、GPU 批处理与运行中取消／watchdog、受控大张量引用的生产实现 |
| 5.4 有界反馈执行 | 独立的 Circuit V2 profile、延迟边、轮次、子回路、join／退出、预算、SQLite 历史、一次计算 admission 和只读恢复 | 停止后拒绝追加调度轮询；普通 lease、最后恢复接管与结算余量分开 | V1 candidate 到 V2 的完整升级／编译入口、普通 daemon 调度接线、无限恢复或无界日志压缩 |
| 5.5 可恢复拓扑变化 | 七阶段 lifecycle journal、独立 observer 与 anchor、原 intent 恢复；公开拓扑执行入口保持关闭 | V2 静止完整状态 roster、实际字节验证、前后 state root／migration pin 绑定、EffectLedger 保持、逐阶段 bundle 核验 | 全部真实 owner 的物理停发、迁移、writer 转移与路由发布；在途工作跨代迁移；Control lifecycle 启用 |
| 5.6 三种更新速度 | 快速 checkpoint；受预算的参数候选；独立评价／提案／选择／下一任务观察；结构 proposal 与 lifecycle 分离 | 利用既有分离，增加结构快照完整性与慢学习入口的即时背压 | 通用训练 job owner、真实异步训练恢复和采用适配器；跨 Cell 联合 BP、长期信用分配的科学结果 |
| 5.7 宿主与长期增长 | Agentd 已拆分 model／Cell、学习、authority、外部效果等 host；已有 journal／队列硬上限 | 保留原 owner 组合，修补具体容量漏洞；提供可校验、可还原的短路径证据归档与双平台验证 workflow | 全部宿主重构完成、无限期运行／压缩／GC、同候选质量与 p99／吞吐／RAM／VRAM／完整成本联合结果 |

## 2. 5.2：精确内部表示如何进入现有外层契约

### 既有基线

[`CellBackendRegistrationV1::digest`][registry] 同时绑定 backend、功能 capability、expert、Cell definition、参数 bundle 和 state schema。它的原生数值 profile 仍要求全局特征 schema 与 `CellDecisionReceiptV1` 输出。原 [`CellGlobalFeatureProjectionV1`][feature-projection] 导入全局 Q24 conversion；提高宽度上限不会补出 token、时间、空间、缺失模态或训练状态语义。

原请求与决定的 scope、源 frontier、预算、checkpoint 和因果身份由 [`cell_types.rs`][cell-types]、[`cell_binding.rs`][cell-binding] 与原 owner 保存。本候选复用这些执行契约，没有把自然语言生成输出改名成决定回执。

### 本候选实际接通

[`cell_representation_profile.rs`][representation-profile] 定义 `GlobalVector`、`TokenSequence`、`MultimodalSpatiotemporal`、`GenerationOutput`、`TrainableState`。每个 profile 明确 generation、语义 schema、dtype、精确 shape、axis、role、模态、是否允许缺失及字节预算；codec／tokenizer／坐标系／timebase／训练协议也是身份的一部分。形状运算与总字节累加执行溢出检查，总编码载荷硬上限为 64 MiB。可选模态必须显式缺失，同一模态的各视图不能部分伪造为零张量。[profile 实现][representation-profile]

[`CellRepresentationV1`][representation] 按值冻结 profile、context 与完整 tensor bytes，固定 producer 身份、generation、binding、scope、来源 bundle／record／frontier 和因果回执。公开借用不能修改已经封存的内容。本候选还规范化移入的向量容量与有界标识符，避免长度很小、预留分配很大的输入被永久持有；这仍不能当作进程 RSS 或 GPU 内存计量。

[`CellRepresentationNegotiationV1`][representation-negotiation] 要求 producer 明确提供输入 profile，consumer 明确接受输出 profile。直接消费要求精确 profile 一致；转换必须固定 component generation、实现、参数、输入／输出 profile 和质量证据，并匹配 consumer 预先解析的 `qualified_projections`。这里验证的是**精确 pin 一致性**；artifact／evaluation owner 仍负责 pin 的真实性、当前性和实际质量判断。

`CellRepresentationUseV1` 现在分别携带 producer 与 consumer 的 `CellRepresentationEndpointUseV1`：endpoint identity、generation、binding digest 和完整 `contract_digest`，另有本次 scope 与 source frontier。完整契约 digest 覆盖 offered／accepted profiles、投影资格清单及字节预算；这些策略变化即使没有更换 endpoint 名称或实现 binding，也会使原协商失效。`validate_use` 在 `consume_direct` 和 `project` 处核对双方观测与原协商、来源是否一致。观测必须从实际 owner 读取并认证，不能复制旧协商的 pins 冒充当前状态；相等比较本身不提供认证、访问权或并发 lease。[协商与最终使用观测][representation-negotiation]

[`CellNativeRepresentationInputV1::project`][representation-native] 是本候选已经实现的执行适配器：从 global F32 或 signed Q24 表示按显式、唯一、有序坐标选择生成至多 512 个 Q24 值，检查全部输入值有限且位于 `[-8, 8]`，使用 ties-to-even，不静默补值或裁剪。完整 source manifest、全部原 tensor 字节、backend／negotiation／component／encoder pins 和输出进入原 observation 身份；未选中的维度变化也会使同一 operation 冲突。

密封投影保存原双方契约与 backend 身份。`validate_backend` 比较冻结的完整 backend digest，在历史读回时也不能用同 definition、不同 expert／capability 的 backend 重标旧输入；`validate_current_use` 另核对新取得的双方契约、scope 和 frontier。`enter_representation` 在原 [`enter_cell_step`][cell] 前执行这些检查；排队或 durable admission 之后仍需在真正模型接触前重新取得观测并复验。[密封绑定与新入口][representation-native]

`restore_admitted` 解决进程重启后只剩原始材料、旧 endpoint 已不再被选择时的重建：先向原 Cell owner 查询精确 operation／semantic request 的 pending 或 committed 记录，再以冻结 negotiation、source 与 selection 重建完整 observation。pending 路径还使用原 snapshot 重建完整 model request 并要求逐项相等；缺失原 admission、替代 operation、修改完整来源或模型请求均不能借此创建新工作。此入口不调用模型、不写状态，也不把历史 pins 冒充 current。[冷重建实现][representation-native]

`recover_representation` 继续调用原 [`recover_cell_inference`][cell-inference]，只读回原 admission；回执缺失或 UNKNOWN 时保留原 pending、operation 与 reservation。恢复允许原历史 endpoint 不再 current，但不会授予新执行权：重建对象进入新的 admission／dispatch 仍须通过 live current-use 核对。投影与决定回执继续保持 `DENY_ALL`，不会自授学习、发布或外部效果权限。[历史读回边界][representation-native]

### 范围与验证

表示层可以无损承载一个 768 维 F32 vector；这不表示当前原生模型直接执行 768 维输入，也不表示实际 EG2 已完成接入。Token、时空、多模态、生成输出和训练状态目前具备精确承载与直接协商，不能据此声称这些类别都已有执行 worker。

[`cell_representation_tests.rs`][representation-tests] 的回归源码覆盖 768 维承载、形状／预算／缺失／mask、投影 pins、双方 current endpoint 与完整策略变化、完整来源身份、UNKNOWN／replay、过期弃权和 spare capacity。新增 [`cell_representation_recovery_tests.rs`][representation-recovery-tests] 实际关闭并重开 journal／witness 文件、丢弃旧投影后重建原 pending，再检查 committed 读回；它还断言 endpoint 更新阻断新使用、旧 UNKNOWN 保持原身份。上述为测试路径与断言的说明，执行结果须另见绑定源码的运行回执。受控模型夹具不构成真实 Encoder、生成或训练状态后端的质量结果。投影构造成本不包含在原 model latency 字段内，完整成本报告须单独计入。[适配器计量说明][representation-native]

## 3. 5.3：计算路径与控制路径

### 已有边界保持

[`TrustedReadOnlyOrganV1`][organ-runtime] 是编译内置、同步、快速返回的可信回调；其合同禁止 I/O、spawn、模型调用与外部效果，也明确不是 sandbox。本候选没有用它承载 GPU 或生成模型。

数值执行走原 `prepare → durable inference admission → inference control → decide → owner commit`。[Cell pipeline][cell]、[admission／readback][cell-inference]。[`InferenceWorker`][model-worker] 保持已加载 manifest／handle 与 request／grant 检查，实际驱动由 `ModelDriver`／`NeuronFeatureDriver` 提供。这是共享 worker 的可组合机制，不能从抽象 API 推导实际显存节约或生产 GPU 调度已完成。

[`AgentdCircuitCellOwnerV1`][circuit-cell] 已能将持久 Circuit admission 接入原 Cell pipeline，并在 Cell owner 提交后返回 Circuit completion。其实现不调用工具或发布外部效果，源码也明确说构造该对象不会启用普通 daemon startup 中的服务。

### 本候选的表示调用接线

[`AgentdCircuitCellOwnerV1::execute_representation`][circuit-cell-representation] 是实际非测试 caller：接收原 Circuit owner 签发的 admission、完整输入与密封投影，始终检查冻结 backend、Circuit／Cell definition 及 observation 字节；之后复用原 state owner、inference control 和执行主体。`CircuitCellRepresentationResolverV1` 负责从现有 owner 解析并认证当前观测，不能从投影对象复制旧 pins。

新工作在准备前取得双方 current-use 观测；完成 durable inference admission 后，[`GuardedCellDispatchV1`][circuit-cell-dispatch] 再次调用 resolver、验证双方契约，再读取时钟核对 Cell／Circuit 截止时间与 lease，随后才接触共享 model port。admission 前拒绝不会新增 Cell pending；admission 后拒绝保留原 pending 与 Circuit reservation，不调用模型，也不以拒绝自动获得重试资格。

已有 pending 的恢复和 committed receipt 的 replay 不调用 live resolver，只核对原冻结身份并走原 readback／lookup。这使 producer 切代或投影资格变化阻断新计算，同时保留已发生事实的对账路径。旧通用 `execute` 使用 `is_representation_observation` 拒绝该保留前缀，要求这种输入经 typed 表示入口；前缀识别只是协议路由约束，不认证输入，也不替代实际 authority／owner 的权限边界。[入口与复用执行主体][circuit-cell]、[表示接线回归源码][circuit-cell-representation-tests]

### 本候选的有界排队

[`CellBatchQueueV1`][cell-batch] 保留按 runtime、bundle 和 state schema 的精确兼容性组批，并新增队列／批次各自的输入 buffer 字节上限。计费覆盖 observation、候选 mask 分配、规范化输入标识符和两份 feature buffer，包括向量 spare capacity；definition、checkpoint、模型驻留内存遵守各自约束，不能与此计数混同。

队列满、单请求超批次字节上限或总字节上限时，在 owner admission 前拒绝。`cancel_queued` 以完整 scope 与 operation ID 定位，仅移除当前队列项并释放该项计费；`RemovedBeforeQueueDispatch` 不代表另一个调用者没有 admit 同一 operation，`NotQueued` 也不代表效果不存在。真正 pending／UNKNOWN 仍必须询问原 owner。

批次在 durable admission 前和之后读取原单调时钟；admission 后过期或时间回退保留 pending，不伪造无接触证明。队列取消不打断已经执行的模型，运行中取消、worker watchdog 与硬件释放仍属于具体 worker owner。[队列源码][cell-batch]、[容量／取消回归][cell-batch-tests]

慢学习也存在同类资源问题：基线 [`PlasticityRuntimeHandleV1`][plasticity-runtime] 使用 `send().await`，有限 channel 之外仍可能积累持有请求的等待 futures。本候选把 parameter／topology 两条发送路径改为 `try_send`，队列满立即返回 `QueueFull`，关闭仍返回原 `Closed`。这次未入队的拒绝不改变任何较早尝试的对账责任。[实际 Agentd 满队列回归][plasticity-budget-tests]

### 尚需生产接线

本轮源码审计在非测试代码中未找到 `CellBatchQueueV1` 或 `AgentdCircuitCellOwnerV1` 的普通 daemon 构造调用。默认 daemon 的统一 Cell 调度、实际 GPU batch driver、受控张量引用／回收、运行中取消和公平性策略仍需显式 owner bootstrap。不能因为 library 路径不经过完整 agent turn，就宣称全体线上内部传播已切换到该路径。

## 4. 5.4：V1 DAG 与 V2 有界反馈并存

### 已有 V2 执行语义

原 [`NeuralCircuitCandidateV1::compile_taskflow`][neural-circuit] 继续生成 TaskFlow V1，复用无环、可达性和 terminal 检查。独立 [`BoundedCircuitDefinitionV2`][circuit-profile] 已提供版本化反馈 profile：延迟边、轮次、activation／frontier／causal depth、child depth、quantum、事件数、时间和 work budget，以及 compute／decide／subcircuit／join／exit 节点。

[`circuit_runtime.rs`][circuit-runtime] 与 [`circuit_progress.rs`][circuit-progress] 执行调度、延迟反馈、退出和实际工作结算。[`AutomationStore` 的 Circuit V2 方法][circuit-store] 在现有 SQLite owner 中持久化冻结 definition、route、输入、调度与回执；事务提交后才返回 dispatch。重复命令不返回新 dispatch，恢复从完整因果事件重算并核对 projection。

[`CircuitComputationAdmissionV2`][circuit-admission] 由真实 owner 在第一次持久 claim 后构造，不能 Clone 或 Deserialize。ack 丢失后的恢复只允许原 computation readback，即使下游 Cell 尚未收到请求，也不能把“没有回执”当作未执行证明。Agentd 的桥同时核对原语义请求、scope、双时钟、Circuit lease 和 Cell deadline。[桥与调用前检查][circuit-cell]

### 本候选修复的历史容量漏洞

原历史上限是 `max_events + 3 × max_activations + 64`，但停止后重复 `Advance`／`Cancel` 和续租可继续占用它，使 UNKNOWN 无处结算。本候选在 [`circuit_journal.rs`][circuit-journal] 的**新写 admission**上限制这类消耗，保留每个 activation 的 claim／indeterminate／settlement 空间，并从 64 个余量槽中分出：

- 62 次普通 lease 转换；
- 1 次 lease 到期后、符合原更高 generation／fence 规则的最终恢复接管；
- 1 个最终 stop。

最终恢复 lease 允许原工作结算与停止，不能开始新计算或重启反馈。其再次到期后仍是 exhausted HOLD；这不是无限恢复机制。旧 canonical replay／hash／state 格式未修改，已经耗尽的旧历史也不会被重写或凭空扩容。真实 UNKNOWN 仍保持原 invocation 与 reservation，不退款、不换 operation ID。[新恢复回归][circuit-budget-tests]

模块依赖 DAG 与运行时反馈回路是不同对象。本候选没有删除旧 cycle 检查，也没有给 V1 candidate 加一个名义上的 V2 wrapper。通用 V1→V2 编译／升级、普通 daemon 调度服务和面向外部效果的最终消费者接线仍未完成；Circuit completion 本身不能代替原 operations／authority owner 的最终效果 admission。

## 5. 5.5：完整状态绑定接入原生命周期 owner

### 基线的七阶段协议

原 [`RuntimeCellLifecyclePlanV1`][lifecycle] 和 [`RuntimeCellLifecycleJournalV1`][lifecycle-journal] 已有 StopAdmission、Drain、FenceWriters、TransferState、Publish、ReadBack、Resume。每次准备记录精确 intent，独立 observer 认证原生观察，独立 anchor 防止已经确认的历史回滚；恢复继续返回原 pending intent。未认证或 UNKNOWN 观察不能变成 `NotApplied`。原 journal 已为 prepared intent 的未来观察预留容量。[恢复实现][lifecycle-recovery]

基线 state root 是不透明 digest，不能仅凭它判断是否包含 optimizer／RNG／sampler 或外部效果状态。原 [`CellCompatibilityBundleV1`／cutover plan][cell-bundle] 已记录 bundle 组成、训练 lineage、状态 preserve／reset／migrate 等语义，但仍依赖各 owner 提供真实材料和执行。

### 本候选的 V2 完整材料 profile

[`cell_lifecycle_state.rs`][lifecycle-state] 要求十类有序组成：Parameters、Optimizer、RandomGenerator、Sampler、PrivateState、SourceReferences、MemoryReferences、Routing、RequestLedger、EffectLedger。不适用的组成也需要显式 schema-bound absence 记录，不能把遗漏解释成空状态。

`RuntimeCellVerifiedStateV2` 验证供给字节的长度与内容 digest，在调用方预算和 64 GiB 硬上限内处理；不可变借用固定材料。`RuntimeCellLifecyclePlanV2` 把实际前后材料绑定到 agent／principal、Cell 集合、generation、writer／fence、topology、bundle、source frontier 和原 state roots，并把两根及 transform／qualification pin 纳入原 handoff migration digest。

这个 profile 明确要求静止快照：in-flight requests 和 UNKNOWN effects 必须为零。EffectLedger 的 owner、checkpoint、schema、content digest 和字节长度必须前后一致；模型或拓扑恢复不能改写外部世界。真正的补偿必须作为独立效果处理。

[`cell_lifecycle_state_journal.rs`][lifecycle-state-journal] 的 create／prepare／record 调用原 journal，未增加第二个 DB、writer 或 native callback。记录观察时，V2 再按 Applied／NotApplied 的有效阶段核对 predecessor／successor bundle；TransferState 的 NotApplied 仍应观察到 predecessor bundle。[真实 SQLite 回归][lifecycle-state-tests]

### 仍然关闭的边界

这是 **opt-in V2 wrapper**。调用方必须在每阶段持续使用 V2 入口；底层 V1 格式与 API 继续兼容，不会自行持久标记 V2 profile 或重新加载完整材料。因此不能声明所有历史 V1 入口已经强制执行完整状态验证。

字节完整性也不是“每个 schema 的语义已经完整”、材料 custody、迁移质量或原生 writer 转移的证明。独立 observer、Control、Supervisor、Agentd、Fleet、authority、operations、artifacts、plasticity 和目标状态 owner 的实际原生接线仍需要组合。

[`require_control_lifecycle_admission_v1`][topology-execution] 保持返回 `CellLifecycleAdmissionUnavailable`；公开 apply／recover 不因一个正确的 manifest、签名或 test fixture 获得执行权限。本候选没有启用物理 split／merge／migration，没有把模型回退当成外部效果回滚。

## 6. 5.6：三种速度已有真实隔离，缺口在具体 owner 实现

| 更新速度 | 实际入口与状态 owner | 已有可执行约束 | 本候选的作用与剩余接线 |
| --- | --- | --- | --- |
| 快速状态 | [`decide_cell`／`commit_cell_step`][cell]、[`CellPartitionOwnerV1`][cell-owner]、[`CellOwnerJournalV1`][cell-journal] | 按 principal／agent／cell／run 隔离 checkpoint；snapshot／writer epoch／来源／operation CAS；有 pending 时拒绝新 admission 与 source reset；原日志恢复不重跑模型 | 新表示和队列继续使用这些 owner。没有赋予快速状态写入者修改已选择参数或 topology 的 API |
| 较慢参数 | [`propose_cell_update`][cell-update]、[`LearningIterationCoordinatorV1`][learning-iteration-core]、Agentd [`learning_iteration.rs`][learning-iteration-host] 和 [`plasticity_runtime.rs`][plasticity-runtime] | 独立 dataset／steps／elapsed／working-byte 预算；下一 generation；明确 trainable mask；候选变化必须属于允许参数；前后 owner 的 scope／definition／frontier／epoch 不变；候选不得授予 authority | 本候选给既有 proposal channel 增加即时 QueueFull。没有在 foreground `commit` 中安装候选，也没有新增一个空的“更新速度”枚举 |
| 更慢结构 | [`topology_plasticity_host.rs`][topology-host]、原 lifecycle journal、公开 runtime lifecycle gate | proposal writer 独立验证 generator／observer／evaluator、当前 artifact／ledger 与外部 anchor；proposal 不直接 apply；原生采用仍走独立 Control 门 | V2 进一步约束完整 state 闭包与效果账本。真实结构采用继续 HOLD |

参数提案的前后检查刻意不要求 checkpoint revision 静止：短期状态可在同一 definition、source frontier 和 writer epoch 下推进。它检查的是学习期间不能偷换 serving 身份、来源或 writer。真正采用下一 bundle 必须有独立 cutover 和选择；`CellUpdateCandidateV1` 不会变成可执行采用凭证。[参数候选逻辑][cell-update]、[bundle cutover][cell-bundle]

Agentd 的 learning iteration 已有真实可选 runtime 接线：[`AgentdConfig`][agentd-config] 接收 bootstrap，运行期要求 governed plasticity owner 同时存在，再由 [`RuntimeTasks`][runtime-tasks] 监督该服务。[`LearningIterationCoordinatorV1`][learning-iteration-core] 逐步处理 Experience、Dataset、Training、Evaluation、Proposal、Selection、NextUse，校验独立 actor、固定 lineage、预算、expiry 与 checkpoint hash；NoUpdate 是合法终止结果。Selection 与 NextUse 是已有 owner 的只读观察，不由训练者自行选择或签发采用。

[`LearningIterationOwnerPortsV1`][learning-iteration-ports] 要求真实任务来源、删除／撤销 frontier、独立评价、job 对账、watchdog、checkpoint CAS／独立 rollback domain 和下一任务实际使用回执。当前仓内此 trait 的具体实现，以及 `CellUpdatePortV1` 的具体实现，审计所见仍在测试夹具中。一般化的训练 job owner 不能靠填写 digest 或接口注释代替。已有 [`AgentdSharedReplayHostV1`][shared-terminal] 确实提供窄 terminal-cell baseline 的实际 train／load／predict 组合，但不是通用 head／adapter／world-model 训练服务。

[`accumulate_plasticity`][plasticity-statistics] 是 eligibility 与低维调制信号投影后的充分统计量，明确不读取或修改选中参数。它、NDU 价值、离散路由反馈和参数候选接口都不能称为已实现跨 Cell 端到端 BP。本候选没有新增可微图、梯度传播或长延迟信用分配算法；这些科学问题需独立 protocol、评价与真实模型结果。

## 7. 5.7：宿主组合、持久化与长期增长

### Agentd 已有的组件边界

[`runtime.rs`][agentd-runtime] 保持一个 generation 的 identity、Fleet registry、state、cancellation 和 task supervision；App Server 继续是其 required service。模型／Cell、记忆／学习、authority 和外部效果已经有独立文件与 owner 适配器，本候选复用这些边界，没有声称完成新一轮全部宿主拆分。

| 组件 | 已有组合路径 | 保留的 owner 责任 |
| --- | --- | --- |
| 模型与 Cell | [`circuit_cell.rs`][circuit-cell]、[`circuit_cell_representation.rs`][circuit-cell-representation]、[`circuit_cell_dispatch.rs`][circuit-cell-dispatch]、原 inference worker | Cell checkpoint 与共享 inference facility 分开；表示 dispatch 复验双方当前契约与时钟／lease；历史读回保持冻结绑定；仍需普通 daemon 接入 |
| 记忆与学习 | [`shared_terminal_cell.rs`][shared-terminal]、[`learning_iteration.rs`][learning-iteration-host]、[`plasticity_runtime.rs`][plasticity-runtime] | Memory 来源许可、ledger、artifact、评价与 proposal writer 留在原 owner；慢学习额度独立 |
| 原始认知 writer 与恢复 | [`production_protected_host.rs`][protected-host] | 先认证独立 Current／原 writer binding，再打开原 SQLite owner；不从任意 DTO 创建新 writer |
| 桌面／外部效果与权限 | [`operations_host.rs`][operations-host]、[`automation_effect_host.rs`][automation-effect-host]、[`text_session_host.rs`][text-host] | 原 operations journal、独立 FinalUse grant、真实 destination observation、原 Root／Host session 和当前 fence 继续负责 |

### 持久化口径

Cell journal 保存 durable inference admission、足以重建 checkpoint 的 tick 和已提交决定回执；原始输入仍须由来源 owner 在恢复时提供并匹配原请求。表示层的 `restore_admitted` 依赖这些原记录及完整冻结材料，不是仅凭 tensor hash 恢复新任务，也不负责替来源 owner 保存原件。Circuit journal 保存决定下一路线的因果状态、原 computation claim 与结算。Lifecycle、authority、artifact 采用和外部 effects 的持久责任不因内部 tensor 可重算而被削弱。[Cell journal][cell-journal]、[表示重建][representation-native]、[Circuit store][circuit-store]、[生命周期 journal][lifecycle-journal]

新表示 bytes 和排队 buffer 没有被自动转成新的 agent turn 或新的外部效果事务。大张量／optimizer 的真实保存、引用授权和释放仍由目标 owner 负责；V2 complete-state wrapper 不会替其开文件或持久化材料。

已有硬上限是有限服务窗口的保护：Cell journal 最多 64 MiB，并受 max_records、partition／receipt 数与 pending 结算预留约束；Circuit 与 lifecycle 也有有限历史额度。达到上限时拒绝新的 admission 不能等同于已实现长期压缩、归档、checkpoint rollover 或 GC。替换 owner journal 仍需要原身份、anchor、fence 和 UNKNOWN 账本的明确迁移协议，不能通过删历史继续服务。[Cell 容量与恢复][cell-journal]、[Circuit 本轮保护][circuit-journal]

### 证据路径治理

本候选提供 [`scripts/hepta_evidence_archive.py`][archive-script]：从精确 Git revision／目录清单生成有界短路径 archive parts 和 manifest shards，校验原 Git blob、SHA-256、长度、mode 和完整清单；verify 不需要将长历史路径展开到文件系统，restore 只写新目录。解码后的 manifest 另受累计 32 MiB 上限约束。14 项本地回归已通过，覆盖损坏、遗漏、路径越界、截断、已存在目标和独立的路径／blob 预算；[最终回执][archive-test-receipt] 固定受测脚本与测试源码的 SHA-256。[归档回归][archive-tests]

历史证据迁移已经实际完成：原 `a6f3aa12ba187448c35449c7da0a9798ae4ca987` 的 **4,087 个文件、116,240,752 字节**通过完整归档校验，并在新目录实际恢复，逐文件与原字节、Git blob 和 Git mode 一致。原先 47 个大于 512,000 字节的文件和 37 个超过 190 UTF-16 单位的路径，改为 143 个不超过 480,000 字节的 payload parts、3 个压缩成员清单及稳定索引；最终证据树的最长相对路径为 84 UTF-16 单位。完整 payload 为 68,586,635 字节，SHA-256 为 `684f8fef0dad5b6fa75b0ab295c47872178edbe713966a157454b043f61b9752`。原字节与失败状态保持原义，归档不产生新的真实性认证或模型资格。[迁移回执][evidence-migration]、[完整成员与分块索引][evidence-archive-index]、[恢复说明][evidence-index]

原 [Windows job 128184561094](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42302804112/job/128184561094) 的完整解码日志已保存在 [原失败日志][windows-checkout-log]，其 checkout 失败与后续产品测试跳过保存在 [原步骤回执][windows-checkout-record]，没有改记为产品测试失败或通过。[`hepta-evidence-archive.yml`][archive-workflow] 固定原 source／listing 并配置 Ubuntu、Windows 的完整性与 checkout-path 预算检查，始终上传验证输出；**本轮尚未观察到新的 Windows CI 执行结果**。归档的本地完整恢复结果不替代这项平台门，也不证明同候选的质量、服务性能或长期状态增长资格。

## 8. 验收与剩余工作

本候选的机制回归集中在 [表示／协商][representation-tests]、[表示冷重建][representation-recovery-tests]、[Agentd 表示调用][circuit-cell-representation-tests]、[Cell 队列][cell-batch-tests]、[Circuit 恢复额度][circuit-budget-tests]、[完整生命周期材料][lifecycle-state-tests]、[Agentd proposal 即时背压][plasticity-budget-tests] 和 [证据归档][archive-tests]。它们分别验证自己的代码路径；必须在实际受测源码上记录命令、工具链、范围、退出状态、原失败与 skip，不能把构建准备、源码审计或历史通过当作本轮结果。

生产采用还需要以下具体闭环：

1. 给普通 daemon 显式装配 Cell scheduler、共享 worker、真实 encoder／representation owner 与当前 pin 解析器；完成请求取消、截止时间、队列／batch 公平性及原身份恢复。
2. 给 token、时空、多模态、生成输出和训练状态提供有明确语义与预算的实际 consumer／worker；验证完整来源、失效／撤销与最终使用处身份。
3. 给 learning iteration 提供真实 dataset／training job／evaluation／selection／next-use／anchored checkpoint owner，超时后对账原 job，禁止换 ID 重训；保留 foreground、training 与结构变化各自的预算。
4. 将静止完整快照绑定接到 Control 主导的原生生命周期，包括 Supervisor／Fleet 的停止和 drain、目标 owner 真实迁移、writer 交接、当前路由发布与最终使用 fence；单独设计在途和 UNKNOWN 迁移。
5. 在同一候选、同一负载／数据切分与独立评价下联合报告质量／保留／校准、p50／p99、吞吐、RAM／VRAM、状态增长、排队／投影／序列化／训练／迁移／恢复的完整成本。共享模型抽象、fixture 的一次加载计数和单独 resident 数字都不构成这种结果。

当前没有由本候选代码自动成立的“资源更省”“模型更强”“端到端 BP 完成”“跨 owner 原生迁移已上线”结论。完整性、权限约束和有限恢复的工程验证，与科学效果及生产采用分别记账。

[registry]: ../../codex-rs/hepta-neuron/src/cell_registry.rs
[feature-projection]: ../../codex-rs/hepta-neuron/src/cell_feature_projection.rs
[cell-types]: ../../codex-rs/hepta-neuron/src/cell_types.rs
[cell-binding]: ../../codex-rs/hepta-neuron/src/cell_binding.rs
[representation-profile]: ../../codex-rs/hepta-neuron/src/cell_representation_profile.rs
[representation]: ../../codex-rs/hepta-neuron/src/cell_representation.rs
[representation-negotiation]: ../../codex-rs/hepta-neuron/src/cell_representation_negotiation.rs
[representation-native]: ../../codex-rs/hepta-neuron/src/cell_representation_native.rs
[representation-tests]: ../../codex-rs/hepta-neuron/src/cell_representation_tests.rs
[representation-recovery-tests]: ../../codex-rs/hepta-neuron/src/cell_representation_recovery_tests.rs
[cell]: ../../codex-rs/hepta-neuron/src/cell.rs
[cell-inference]: ../../codex-rs/hepta-neuron/src/cell_inference.rs
[cell-owner]: ../../codex-rs/hepta-neuron/src/cell_owner.rs
[cell-journal]: ../../codex-rs/hepta-neuron/src/cell_journal.rs
[cell-batch]: ../../codex-rs/hepta-neuron/src/cell_batch.rs
[cell-batch-tests]: ../../codex-rs/hepta-neuron/src/cell_batch_budget_tests.rs
[cell-update]: ../../codex-rs/hepta-neuron/src/cell_update.rs
[organ-runtime]: ../../codex-rs/hepta-control-plane/src/organ_runtime.rs
[model-worker]: ../../codex-rs/hepta-infer-worker-host/src/model_worker.rs
[neural-circuit]: ../../codex-rs/hepta-automation/src/neural_circuit.rs
[circuit-profile]: ../../codex-rs/hepta-automation/src/circuit_profile.rs
[circuit-runtime]: ../../codex-rs/hepta-automation/src/circuit_runtime.rs
[circuit-progress]: ../../codex-rs/hepta-automation/src/circuit_progress.rs
[circuit-store]: ../../codex-rs/hepta-automation/src/circuit_store.rs
[circuit-journal]: ../../codex-rs/hepta-automation/src/circuit_journal.rs
[circuit-admission]: ../../codex-rs/hepta-automation/src/circuit_admission.rs
[circuit-budget-tests]: ../../codex-rs/hepta-automation/src/circuit_recovery_budget_tests.rs
[circuit-cell]: ../../codex-rs/hepta-agentd/src/circuit_cell.rs
[circuit-cell-dispatch]: ../../codex-rs/hepta-agentd/src/circuit_cell_dispatch.rs
[circuit-cell-representation]: ../../codex-rs/hepta-agentd/src/circuit_cell_representation.rs
[circuit-cell-representation-tests]: ../../codex-rs/hepta-agentd/src/circuit_cell_representation_tests.rs
[lifecycle]: ../../codex-rs/hepta-runtime/src/cell_lifecycle.rs
[lifecycle-journal]: ../../codex-rs/hepta-runtime/src/cell_lifecycle_journal.rs
[lifecycle-recovery]: ../../codex-rs/hepta-runtime/src/cell_lifecycle_recovery.rs
[lifecycle-state]: ../../codex-rs/hepta-runtime/src/cell_lifecycle_state.rs
[lifecycle-state-journal]: ../../codex-rs/hepta-runtime/src/cell_lifecycle_state_journal.rs
[lifecycle-state-tests]: ../../codex-rs/hepta-runtime/src/cell_lifecycle_state_tests.rs
[topology-execution]: ../../codex-rs/hepta-runtime/src/topology_execution.rs
[cell-bundle]: ../../codex-rs/hepta-learning-artifacts/src/cell_bundle.rs
[learning-iteration-core]: ../../codex-rs/hepta-learning-artifacts/src/learning_iteration.rs
[learning-iteration-host]: ../../codex-rs/hepta-agentd/src/learning_iteration.rs
[learning-iteration-ports]: ../../codex-rs/hepta-agentd/src/learning_iteration_ports.rs
[plasticity-runtime]: ../../codex-rs/hepta-agentd/src/plasticity_runtime.rs
[plasticity-budget-tests]: ../../codex-rs/hepta-agentd/src/plasticity_runtime_budget_tests.rs
[plasticity-statistics]: ../../codex-rs/hepta-neuron/src/plasticity.rs
[topology-host]: ../../codex-rs/hepta-agentd/src/topology_plasticity_host.rs
[agentd-config]: ../../codex-rs/hepta-agentd/src/config.rs
[agentd-runtime]: ../../codex-rs/hepta-agentd/src/runtime.rs
[runtime-tasks]: ../../codex-rs/hepta-agentd/src/runtime_tasks.rs
[shared-terminal]: ../../codex-rs/hepta-agentd/src/shared_terminal_cell.rs
[protected-host]: ../../codex-rs/hepta-agentd/src/production_protected_host.rs
[operations-host]: ../../codex-rs/hepta-agentd/src/operations_host.rs
[automation-effect-host]: ../../codex-rs/hepta-agentd/src/automation_effect_host.rs
[text-host]: ../../codex-rs/hepta-agentd/src/text_session_host.rs
[archive-script]: ../../scripts/hepta_evidence_archive.py
[archive-tests]: ../../scripts/tests/test_hepta_evidence_archive.py
[archive-workflow]: ../../.github/workflows/hepta-evidence-archive.yml
[evidence-index]: ../cell-unification-20261106/README.md
[evidence-migration]: ../cell-unification-20261106/MIGRATION.json
[evidence-archive-index]: ../cell-unification-20261106/archive/index.json
[archive-test-receipt]: ../cell-unification-20261106/failures/test-result.json
[windows-checkout-log]: ../cell-unification-20261106/failures/windows-checkout.log.gz
[windows-checkout-record]: ../cell-unification-20261106/failures/windows-checkout.json
