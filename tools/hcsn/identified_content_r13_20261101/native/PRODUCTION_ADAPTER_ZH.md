# 生产接入点与可执行研究合同

## 当前结论

R13 目前是研究后端及可执行状态合同，没有进入生产默认路径。只读审查确认，当前生产 `NeuronRuntime` 仍围绕 Q24 输入、稀疏 tick、`SparseJournal` 和 witness 提交组织执行；把一个 CTMC posterior 写成相同长度的 Q24 向量，不会使两者拥有相同状态、时间语义或恢复合同。

审查固定到 main 提交 `732e934ba496d90fbe042b8d41d479ef901643e5`。五个原始源快照和 provider Git blob 身份记录在 [production_sources/SOURCES.json](production_sources/SOURCES.json)，每份快照均独立复算 Git blob SHA 后验证。此提交是读取时的 main 身份，不是对未来 main 的假定。

## 实际生产调用边界

| 已读源码 | 相关责任 | 对 R13 接入的影响 |
|---|---|---|
| [hepta-neuron/runtime.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/codex-rs/hepta-neuron/src/runtime.rs) | 构造模型请求、执行 model port、检查模型 tuple 和输出、创建 sparse tick、提交 journal 与 witness；处理 pending witness | 新后验/事件状态必须成为有版本、可验证、可提交的状态，不能只替换一个输出数组 |
| [runtime_types.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/codex-rs/hepta-neuron/src/runtime_types.rs) | tick 输入、模型请求/输出和执行回执 | tick 具有时钟和检查点字段，但当前 model request 不把 `dt` 与候选 CTMC 状态交给 model port |
| [hepta-agentd/neuron_runtime.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/codex-rs/hepta-agentd/src/neuron_runtime.rs) | `AgentdNeuronOwner` 持有长期 runtime 与 inference control port | 可以作为 future owner 的位置；当前构造器本身不意味着 daemon 默认激活 |
| [inference_control.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/codex-rs/hepta-neuron/src/inference_control.rs) | 绑定 feature receipt、模型 tuple、输出和计量回执 | 不能绕过已有 inference control 绑定而任意注入 drive |
| [sparse.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/codex-rs/hepta-neuron/src/sparse.rs) | Q24 activation、threshold、temporal/activity/eligibility 状态及 sparse checkpoint | 该状态不是 posterior，也不是 Gillespie 的当前离散状态、残余暴露与 RNG |

当前 `NeuronModelPort::execute` 返回 drive/prediction Q24 以及模型执行回执；`SparseJournal` 再按自己的机制提交。R13 的 `p exp(Q dt)` 和 Bayes 状态更新具有另一组守恒、观测和时间要求。一个保留现有核心的 shadow feature adapter 可以先导出有界数值供审查，但这种接入只能称为特征来源；若要替换 cell 核，则需要明确的 operator-state tag、模型请求与检查点版本变更。

## 已实现的最小状态合同

[runtime_adapter.py](runtime_adapter.py) 已经执行，而不是仅写接口草案。`TickRequest` 明确要求下一 sequence、`dt`、模型 identity/version、预期 checkpoint、input digest、READ 标志及 observation identity。运行状态单独保存 float64 posterior、clock、前驱摘要、last input 和 layout identity。

每次 tick 先验证绑定和 READ 语义，成功完成预测与必要观测后才提交后验和时钟。`read=False` 携带 likelihood 或 `read=True` 缺少 likelihood 均拒绝。概率为零的观测也拒绝，不创建虚构的可归一化证据。cache-full 同样不改变 actor state；owner 可以显式清理 prepared cache 后原样重试。

模型迁移要求更新时间不早于当前 clock、版本严格增加、同一 layout identity 和相同维数。先用旧 `Q` 推进至迁移时间，再在同一状态基上保留 posterior，并绑定新 `Q` 和观测模型。`Q` 的 identity 包含版本及精确矩阵位；不同参数不能共享过期的 transition。新的观测模型 identity 必须显式提供。

分布 checkpoint 使用独立 schema `hcsn-r13-research-distribution-checkpoint-v1`，保存 float64 位及模型/源/动态库身份。恢复会验证期望的模型、版本、网格和观测模型，并重新建立缓存。Q24 SparseJournal 不属于此 schema，已经有拒绝测试。

Gillespie event checkpoint 则保存实际当前离散状态、clock、暴露 anchor/threshold、RNG、事件计数和谱系。它与 distribution checkpoint 是不同类型。固定状态基的模型更新先推进旧过程至声明时刻，再保留残余 unit-exponential exposure 或明确重新抽样；旧目标状态和旧绝对下一事件时间不能沿用。事件 CLI 当前验证结构布局与维数，生产外层仍必须加入相同物理网格 identity 的绑定。

## 已执行的恢复与拒绝见证

[test_runtime_adapter.py](test_runtime_adapter.py) 通过 13 项检查，其中连续执行和三段执行分别启动真实的新 Python 进程，跨进程恢复后得到相同 posterior 和最终 checkpoint 字节。检查还覆盖版本/网格不匹配、旧 Q24 schema、过期 checkpoint、非法时间、缺失/未经请求的观测、零 evidence、隐式重划网格及覆盖写入。有效证据见 [runtime_adapter_frozen/RESULTS.json](evidence/runtime_adapter_frozen/RESULTS.json)。

事件的 20 项新进程检查另见 [migration_frozen/RESULTS.json](evidence/migration_frozen/RESULTS.json)。不规则 `dt` 填满缓存后的 actor 拒绝与同请求恢复见 [CACHE_LIMIT_WITNESS.json](evidence/CACHE_LIMIT_WITNESS.json)。这些测试证明所列研究合同的执行，不证明未知错误情形已全部排除。

## 真正接入仍须补齐的责任

生产请求需要从可信 tick clock 明确导出 `dt`，并绑定模型、网格和观测版本；不能在每次 model-port 调用时默认为固定 tick。提交机制需要把候选 operator state 与模型输出、输入 acquisition receipt、预期 predecessor、资源回执和 witness 放在同一可恢复提交边界。当前研究摘要只验证身份和损坏，没有认证来源，也未实现生产 witness CAS。

状态转换需要采用显式 tagged checkpoint：distribution 与 sampled event 必须区分；从既有 Q24 journal 迁移需要定义初始化或可审查映射。不同网格的重映射需要单独数学合同和测试，不能因为矩阵维数碰巧相同就默认成立。

生产资源测试还需覆盖完整 request 生命周期、缓存反复失效、并发 owner、进程总内存、最坏延迟、checkpoint 写放大和失败恢复。当前 per-model cache 限制、CPU 微基准和本地文件摘要不足以满足这些责任。Rust dense 后端对 cached NumPy 仍无速度优势；真实任务也未证明相对 generic HMM 的质量优势，不能据此激活默认核心。

这些缺口已经被缩成可实现和可审查的接口责任；本轮不修改生产源码、不修改既有 Q24 checkpoint，也不声称已取得生产准入。
