# Cell 六项收敛：实现与验证边界

本分支以 #4929 的 `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75` 为基线，
将真实 owner 人口统计、V13 已选内容使用、Joint 常驻执行、journal checkpoint、
有界跨参数版本迁移和完整周期成本比较收敛到原有边界。它没有创建全局状态管理中心。

## 来源与资格不能互换

| 来源 | 本次实际引入 | 未转移的资格 |
| --- | --- | --- |
| #4890 / `caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b` | `cell_roles.rs`、`cell_population.rs` 及各自测试的原文件 | 分化研究结果、行为质量、生产采用 |
| #4929 / `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75` | 当前 stateful generation、原 control/worker、journal 和 Agentd 组合基线 | 原生全工作区测试通过；该基线已有失败记录 |
| #4930 / `dd1adf3defc5f1b1bcf3358419e23490e24b9a6a` | `neuron-learning-closure-v13` 原内容验证器及固定参考来源 | JointGenerator 可续训、未来任务质量、native 模型采用 |

`population_v2` 继续是原稀疏激活机制，不能替代新增七角色人口统计。V1 decision 和
V2 generation 使用共同 scope/状态槽观察，但保持各自实际执行协议；未将 V1 缺少的
学习绑定伪造成 V2 resumable 状态。

## 六项落点

| 方向 | 当前可执行实现 | 尚未成立的结论 |
| --- | --- | --- |
| 身份和准入 | 从实际 V1/V2 owner 生成封闭观察；Agentd 校验真实 artifact bundle 后绑定角色、任务准入与活跃/容量检查 | 产品 host 自动接线与跨 owner 调度登记、角色标签证明行为质量 |
| 学习闭包 | V13 完整内容验证、原 SourceOwner 当前选择/来源事务、固定模型、新进程下一任务预测 | 独立效果评价已通过、Joint 与 V13 资格合并、生产采用 |
| 共享计算 | 显式 resident Joint profile；共享 immutable model/public/初始编码；每 Cell 独立 state/prefix/commit | Joint microbatch、连续 tensor 新内核、吞吐或能耗改善倍数 |
| 长期容量 | 同 owner 的新 checkpoint 段、原段保留、容量/恢复/队列年龄观察、结果读回 reconciliation | 无界长期运行、独立 witness/receipt/cost 上限解除、无证明终结 Unknown |
| 迁移回退 | drained 后参数版本转换；同 witness 切换；升级后的确认写入在向前回退中保留 | 所有 schema/runtime/source 升级、真实生产 artifact verifier 已接入 |
| 完整成本 | 补模型取得/迁移 stage；14 阶段完整性及所有 Unknown 检查；同条件跨来源比较并保留来源 | 训练/评价/模型取得等 owner 的成本汇集、真实全周期 CPU/能量计量、效率收益证明 |

### 真实 owner 人口统计与 Agentd 准入

[`cell_owner_population.rs`](../../codex-rs/hepta-neuron/src/cell_owner_population.rs)
读取真实 Cell scope、generation、writer epoch、revision、manifest/definition、参数、
source frontier、checkpoint、可用的 learning/evolution binding、pending/outbox 活跃状态
及状态容量。观察字段封闭；V1/V2 对同一个完整 scope 派生同一状态槽，重复登记被拒绝。
agent/run 的人口统计 namespace 使用长度前缀，避免字符串连接造成别名。

[`AgentdNeuronGenerationOwnerV2::bind_population`](../../codex-rs/hepta-agentd/src/neuron_generation_population.rs)
将现有 artifact owner 解析的 `CellCompatibilityBundleV1` 与实际 runtime manifest、generation、
state/output schemas 及 encoder/head 核对。绑定后的既有 `step`/`step_checked` 在任何模型联系前
执行角色和人口统计检查；`step_with_population` 将其他当前 owner 的观察送入同一准入路径。
host 原有 scheduler 必须串行化这些观察和准入；目标 owner 的过期观察会被重新比对并拒绝。
这些绑定/聚合入口当前由测试显式调用；产品 host 自动取得 artifact 声明、登记角色和提交
跨 owner 完整观察集合的接线尚未实现。未绑定的兼容调用路径不会自动获得七角色准入。

现有异步 bootstrap 可通过 `with_population` 在服务挂接前完成同一 owner 的绑定；
handle 的 `population_observation` 读取当前封闭观察，`step_with_population` 将有界 peer
集合送入原 `Admission / Dispatch / Settlement` 检查。host 必须把调度互斥覆盖到观察收集和
异步准入完成；队列不能替其他 owner 证明观察仍然新鲜。这沿用 #4929 的显式 host bootstrap，
没有新增默认 artifact、角色或另一套服务。

未知工作、取消但尚未 reconciliation 的工作、未确认输出继续占活跃容量。已提交精确 replay
和已派发 pending 的读回保持原优先级，不会因新增人口统计产生重复模型调用。

### 后端独立的内容与实际使用

参见 [V13 使用路径](../neuron-learning-closure-v13/README.md)。`selected_use.py` 不训练、不
评价或发布版本；它要求原 SourceOwner 已有精确 scope/cell/epoch/artifact 选择。完整验证后
保留从同一份 bounded bytes 加载的模型，随后在原 owner 的 transaction 内重查选择和 live cut，
再执行原 Adapter 的下一任务预测。事务覆盖所有预测批次。

V13 的分批只限制本后端的数值工作区，不是 Joint microbatch。输出明确保留 `DENY_ALL`、
synthetic/reference 区分和 `adoption_performed: false`。测试的 validator 检查形状/有限值，
并不冒充未来任务效果评价。既有研究分支的训练结果不能自动授权本分支 native 采用。

### 常驻执行、checkpoint 和迁移

- [常驻 Joint 的实际模式和执行边界](resident.md)
- [Checkpoint、迁移、回退、恢复与仍然存在的容量限制](lifecycle.md)

后端始终返回纯 proposal；Cell owner 提交 state、不可撤销 prefix、outbox 和成本；原
inference owner 保留派发和结果记录。共享常驻进程没有发布、工具调用或采用权限。

### 完整成本的可比较性

`CellTaskCostV2` 的 14 个阶段是 Encoder、Routing、Inference、Training、Planning、Critic、
Codec、Queue、Persistence、Recovery、Communication、Evaluation、ModelAcquisition、Migration。
存储读写和 byte-time 是各阶段的计量字段。各 stage 没有发生时，调用方须提供有依据的
零值；未测得的 CPU/energy 等保持 `None`，不能补零以换取比较通过。

[`compare_cell_task_costs_v2`](../../codex-rs/hepta-neuron/src/cell_cost_comparison.rs)
要求相同 task、inputs、资源预算、执行环境、计量合同和评价条件。双方可有不同的实现来源，
返回值保留各自完整 ledger identity。失败、拒绝和取消尝试仍被计费；任意 exclusive 或
inclusive envelope 尚为 Unknown 时拒绝宣称完整周期。

资源只累加 exclusive 项，inclusive envelope 不再重复相加。并行工作总时长和外部实测
elapsed 分开比较。差值为 candidate−baseline；负值只表示该量较少，不证明质量相同或授权采用。
比较合同本身仍由原计量/评价 owner 负责，非零 digest 不替代真实计量证据。
本次实现完整性比较和拒绝规则；真实训练、评价及模型取得 owner 的成本汇集尚未接入。
实际推理账本的未知指标仍会使完整周期比较被拒绝。测试构造的完整账本不能替代这项集成。

异步 handle 的 `record_cost` 现在把一条 `CellCostEntryV2` 交给同一个 journal 持久化。
原 owner 核对任务/来源身份、精确重放、冲突和已有 exclusive 项的 envelope 引用；句柄在
入队前限制 envelope 成员数量。此端口允许真实 host 录入已经测得的部分成本，保留失败尝试
和 `None`。训练 receipt 到具体 Cell 任务账本的映射、评价/取得模型的计量及共享资源分摊
仍需原 owner 提供；训练预算或 artifact 声明大小不会自动转换成实际费用。

## 验证与审阅

`run_native.py --source-sha <exact-sha> --output-dir <outside-source-dir>` 记录干净源码、
工具链、分阶段命令/日志摘要、helper 实际 Cargo 产物、完整 nextest 输出与 JUnit。
源码或 helper 来源变化时停止，不以猜测二进制路径、缺省 fixture 或跳过失败来继续。

原生范围为 `codex-hepta-neuron`、`codex-hepta-agentd`、`codex-hepta-infer-worker-host`，
以及与未知结果/派发持久性直接相关的 `codex-hepta-infer-core`。本次没有改 core/common/protocol
生产代码；这个范围不能写成整个继承工作区测试通过。最终实测结果见随附验证记录。

审查已补回归：checkpoint header transplant、读回跨 deadline、resident 校验后过期、
学习验证后换版/撤回、checkpoint 二次无界读取、预测类别张量放大、Unknown 包络被忽略。
这些边界测试证明具体拒绝/保留语义，不是长期可用性或性能收益认证。
