# Memory Cell V8：六项集成交付与验收边界

本轮实现把类型化请求、三类 memory cell、参数训练、访问分区学习、预算约束和多 owner 读取接到现有 Hepta 路径。**工程候选已完成两轮完整的相关集成验证，六项验收仍未全部满足。** [CI02：40612088249](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40612088249) 与 [CI03：40612818087](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40612818087) 均通过 18 项 Python、511 项普通 Rust 和 5 项 actual 测试，包括真实参数训练、native 配对读回、完整 11-arm 比较和同机多进程恢复。V8 自然语言寻址的生产准入仍为 `serving_admitted=false`；learned 分区没有超过强固定、同信息轻量或 direct-owner 对照的冻结成本代理，完整成本门保持 `NoChange`。[CI01](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40609738136) 的失败与局部结果原样保留。

本文以 `qualification/memory-cell-v8/` 为相对路径起点。自然语言寻址的模型阶段、源开发与测试阶段均已结束；这些结果没有用于重新选择寻址权重、候选、阈值或比较协议。CI02 绑定 source `1f52f23f2dc9cf1ecc863c61e52cce8e53f35330`，CI03 绑定最终受测 source `75256635aae979f34b4ec830764b7dbfa24c389d`，已包含 finalizer 的完整 evaluation 输入冻结。CI03 在 CI02 结果产生前启动，没有使用其结果改动模型、数据或协议。两轮评分器均在各自精确源码树上只读重放，输出与原收据逐字节相同；这不增加训练或独立试验样本。最终 `just fix` / `just fmt` 已成功，原始补丁应用后与 CI 生成树一致，完整收据见第 7 节。

第 3、4、6 项的完整解释口径见 [ACCEPTANCE.md](ACCEPTANCE.md)：明确训练因果收益的可识别范围、固定比较分母、逐项 retention 转移，以及三类参照和完整成本门。该说明解释现有冻结协议，不改变模型或验收门。

## 1. 六项交付对应到哪里

用户表中的 `learning.operator`、`learning.eval` 等名称在这里表示能力边界；实际实现复用已有 crate 和 Agentd 入口，不代表另行创建了同名运行时。

| 顺序与用户交付 | 当前实际模块与入口 | 可复核证据 | 尚未满足的验收 |
| --- | --- | --- | --- |
| **1．类型化 MemoryRequest/Readout、可靠语义寻址** | [cognitive.types 请求/读出](../../codex-rs/hepta-cognitive-types/src/memory_cell.rs)、[memory.retrieval 来源重验](../../codex-rs/hepta-memory-retrieval/src/memory_cell.rs)、[context.compiler 证据注入](../../codex-rs/hepta-context-compiler/src/memory_cell.rs)；[V8 addressing worker](addressing/worker.py) 经 Agentd 的 pinned resolver 接入 | 冻结 Python 结果与两轮完整 native 配对均已归档。CI03 两 arm 各 240/240 条读出记录；V8 known 正确 73/120、unsupported 错误接受 6/80；未知实体、歧义别名、时间冲突共 40 条均正确拒绝。见 [native 审计](evidence/ci/run-03/NATIVE_AUDIT.json) | 生产准入失败：独立 calibration 覆盖 72.5% 低于 80%；冻结 Python held 覆盖 60.83%、OOD 接受 4/38；native 的 6/80 也未通过质量门。修复了双 cutoff 的工程错误，没有借此放宽模型门 |
| **2．事件、语义、过程三类可用 cell** | [SQLite owner](../../codex-rs/hepta-memory/src/memory_cell_owner.rs)、[原生关联模型](../../codex-rs/hepta-neuron/src/associative_memory.rs)、[Agentd runtime](../../codex-rs/hepta-agentd/src/memory_cell_runtime.rs)、[组合执行](../../codex-rs/hepta-agentd/src/memory_cell_execution.rs)；通过 `AgentdClient.memory_cell_read` 进入 control 路径 | 新写入值、实际参数训练、真实 control 读回和跨类型 `apply` 已实测。两轮 prospective 的固定 2…8、lightweight、learned、direct-owner 均完成 future 72/72 正确读与 12/12 正确任务；固定 1 的不可用结果同样保留。见 [学习审计](evidence/ci/run-03/LEARNING_AUDIT.json) | 三类 cell 在声明的类型/操作与预算范围内可运行；语义/过程仍保留显式 catalog，不能据此声称纯参数存储或总空间优于传统存储。语言寻址未获生产准入 |
| **3．参数训练、回放、校准、干净重建** | [Agentd trainer](../../codex-rs/hepta-agentd/src/memory_cell_training.rs) 的 `Clean` / `Replay`、[learning ledger 接入](../../codex-rs/hepta-agentd/src/memory_cell_learning.rs)、[artifact 发布/选择](../../codex-rs/hepta-agentd/src/memory_cell_release.rs)；[V8 population trainer](learning/population_training.py) | 实际训练/回放/纠正/撤回、Clean 参数重建一致、旧 replay 拒绝均通过。CI02/03 prospective 分别完成 176/180 次 shard fit，参数均实际更新；十个可运行 arm 的 retention 逐项保持 24/24 读与 4/4 决策正确，无被净差掩盖的退化 | 这是既有事实上的策略比较，未隔离梯度训练本身的未来收益；没有未训练反事实，direct-owner 同样正确。固定 1 的退化来自容量准入，不能称参数遗忘；未证明持续写入下的长期遗忘控制 |
| **4．分裂、合并、休眠、预算竞争** | [population](../../codex-rs/hepta-neuron/src/memory_population.rs)、[驻留缓存与 sleep/wake](../../codex-rs/hepta-neuron/src/memory_population_cache.rs)、[结构预算](../../codex-rs/hepta-plasticity/src/memory_budget.rs)；[已完成访问的分区学习](learning/allocation.py) 与 [V3 原生校验](../../codex-rs/hepta-neuron/src/memory_population_learned.rs) | 显式 1→2→1 shard 训练/签名发布、sleep/wake 读回和 stale source-cut 拒绝通过；两轮完整 11-arm 比较、完整八候选搜索账与独立复算均完成。见 [CI02 评分](evidence/ci/run-02/prospective-score.json)、[CI03 评分](evidence/ci/run-03/prospective-score.json) | 两轮 learned 相对强固定、同信息轻量和 direct-owner 的冻结代理比较均为负；全生命周期成本仍缺测，完整成本门 `NoChange`。没有全成本净收益结论，未执行自主结构提案/发布 |
| **5．多节点读取、迁移、一致版本发布** | [MemoryCellNetworkV1](../../codex-rs/hepta-agentd/src/memory_cell_network.rs)、[版本向量与绑定](../../codex-rs/hepta-agentd/src/memory_cell_network_bindings.rs)、[OrganHost 路由生命周期](../../codex-rs/hepta-agentd/src/memory_cell_network_organ.rs)、[持久化 anchor](../../codex-rs/hepta-agentd/src/memory_cell_network_anchor.rs) | 三轮[真实进程测试](../../codex-rs/hepta-agentd/src/memory_cell_network_process_tests.rs) 均通过；每轮记录 6 次成功读回、新 PID/spawn、同一持久 owner/cut/bundle/CURRENT、generation 1→2 和失败/恢复/迁移计费；anchor commit 两侧真实进程退出也通过。见 [CI03 收据](evidence/ci/run-03/network-process.json) | 范围为同机独立 OS 进程和 Unix control sockets，使用 control-only readiness fixture；迁移只读路由和已准入版本。没有跨机器数据复制/迁移，也未调用 TaskFlow effect；通信计数不是完整 wire 成本 |
| **6．新领域、新组合、新专业化迁移** | [causal coaccess allocation](learning/allocation.py)、[任务批次构造/执行](../../codex-rs/hepta-agentd/src/memory_cell_prospective_batches.rs)、[独立原始证据复算](learning/evidence.py) | 完成 prefix 后冻结分区及三类 future 组合；learned 的真实地址分区在忽略 shard 编号后仍异于同 k 固定分区。CI02/03 分别改变 68/300、56/300 个地址对的共同归属；未来正确率与强对照持平 | 分工发生在已写入 support 内的逻辑 shard，未来只测 Apply/Semantic/Procedure 组合。没有自动调整 OS 节点拓扑，未证明新领域/新类型发现、跨领域专业化迁移或通用 memory system 自发形成 |

## 2. 真实实现的模型与数据边界

### 三类 cell 与执行链

事件 cell 从 canonical SQLite owner 读取带时间戳的事实；`history` 和 `change` 使用实际 Unix 秒 cutoff。语义 cell 返回已记忆的 `{factor, label}`，过程 cell 返回 `{opcode, bias, limit}`。`apply` 组合当前事件、语义属性和过程，执行注册的 `identity`、`add_bias`、`multiply`、`affine`、`clamp` 语义。字段与解释器边界由 [typed values](../../codex-rs/hepta-cognitive-types/src/memory_cell_values.rs) 定义。

语义/过程模型执行真实的小型 tanh MLP/Adam 参数训练，再导出供 Rust 执行的数值参数。原生模型使用地址特征预测 catalog 中的类型化值，并保留支持来源与训练 lineage。**完整 catalog 值仍显式存放，事件与来源事实也仍在 owner 中。** 因此当前可以论证“确实训练并执行了参数模型”，不能据此论证“事实已被纯参数压缩”或“总存储成本低于数据库”。支持集合之外会拒答；模型输出保持 prediction 身份，来源 ID 也不会自动使模型值变成事实。实现见 [原生模型与 catalog](../../codex-rs/hepta-neuron/src/associative_memory.rs) 和 [既有参数训练器](../memory-cell-v7/training.py)。

自然语言寻址是另一组模型：固定多语言 MiniLM 表征，加训练得到的正样本六类 operation head 和独立二类 supportedness head。其实际学习器是 logistic regression；没有微调基础 encoder。hybrid 候选还使用公开训练材料建立的词/字符 TF-IDF 特征。它输出受约束的执行假设，不输出 memory value；实体仍需 owner 提供 canonical ID/aliases。新增实体能够通过新 owner registry 绑定，并不意味着开放世界实体发现已经实现。见 [addressing/model.py](addressing/v8_addressing/model.py) 与 [addressing 协议](addressing/README.md)。

从请求到上下文的链路是：类型校验 → owner/alias/time 绑定 → pinned addressing worker → 选中 bundle 的原生执行 → owner source-cut 与来源依赖重验 → 类型化 readout → 有界 context evidence。artifact 发布、独立选择和最终使用的权限继续由既有 owner 管理。学习、分区、迁移或一个 digest 都不能自行授予发布或 final-use 权限。对应入口见 [worker config](../../codex-rs/hepta-agentd/src/memory_cell_address_worker_config.rs)、[release](../../codex-rs/hepta-agentd/src/memory_cell_release.rs) 和 [context evidence](../../codex-rs/hepta-context-compiler/src/memory_cell.rs)。

### 校准失败仍能测量候选

正常 [worker.py](addressing/worker.py) 要求独立校准 gate 通过。本轮 calibration 未通过，因此不获生产准入。单独的 [qualification_shadow_worker.py](addressing/qualification_shadow_worker.py) 允许隔离 fixture 测量同一个冻结模型、同一组阈值，但只接受保留的 ControlFixture owner/scope，并在 score kind 中标记 `qualification-shadow`；它不生成 final-use grant。

[paired native runner](../../codex-rs/hepta-agentd/src/memory_cell_language_v8_tests.rs) 为冻结 V7 和 V8 分别创建真实 owner，写入同一批记录，各自训练参数 cell，再执行同一 fixture 的全部 240 个请求。每行先调用真实 resolver，再调用完整 control read；两次路由分别计数与计费。直接 resolver 的 OOD 错误路由必须留在收据中，不能因下游读回失败而消失。**CI02、CI03 均已完成完整配对：每 arm 新写入 owner 记录、执行 2 次参数 fit、返回全部 240 条读出记录。** 240 条含正确回答、拒答和错误接受，不能写成 240 条全部正确。CI01 只有冻结 V7 arm 的完整读出材料，其 4 条双 cutoff 工程错误保留；后续 typed abstain 修复没有回写旧收据。这些 native 结果与下节冻结的 Python 分类结果分开保存。

## 3. 已冻结的寻址实测

### 选择与模型身份

[TRAINING.json](evidence/addressing/frozen-01/TRAINING.json) 记录了六个预声明候选：semantic/hybrid × `C ∈ {2, 8, 32}`，每个训练两个 head，总计 **12 次实际 head fit**。选中候选为 **5：hybrid，C=32**。公开 selection 上的 78/88 known 正确、0/46 OOD 接受用于选择候选，不作为独立未来效果。

独立校准只收紧已选阈值，未更新权重或重新选择候选；held 后没有再次调参。冻结来源 commit 为 `7e194d9f0858e805a0cab502215a1f64ddc0ea00`，最终 manifest SHA-256 为 `0182aebb86e3f2ed7dd089864762970791b70cff2240861602ef15be2461ac86`。模型阶段的一次 source-lock 失败发生在任何 fit 之前，失败材料和之后的原样重试均保留。[来源与阶段边界](evidence/addressing/frozen-01/SOURCES.json)；[归档索引](evidence/addressing/frozen-01/ARCHIVE.json)。

部署计量为 **127,538,960 B 共享 encoder + 450,283 B 候选部署 artifact**。后者包含 manifest、词表/策略/校准材料与权重，不能全部解释为纯数值 head 参数；这也没有覆盖 owner 数据、语义/过程 catalog、支持、lineage、训练搜索和运行驻留等完整成本。不能仅以 450,283 B 宣称整个 memory system 很小。[ADMISSION.json](evidence/addressing/frozen-01/ADMISSION.json)

### 相同口径下的结果

| 阶段/模型 | known 正确 | known 错误接受 | known 拒答 | OOD 接受 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| V8 独立 calibration | 87/120＝**72.50%** | 0/120 | 33/120 | 0/38＝0% | 覆盖低于 80%，`serving_admitted=false` |
| V8 冻结 held | 73/120＝**60.83%** | 0/120 | 47/120 | 4/38＝**10.53%** | 覆盖与 OOD 门均未满足 |
| 同一 held 上的冻结 V7 | 40/120＝**33.33%** | 0/120 | 80/120 | 1/38＝**2.63%** | 对照覆盖较低，OOD 接受也更低 |

来源：[独立校准](evidence/addressing/frozen-01/ADMISSION.json)、[同 held 双模型结果](evidence/addressing/frozen-01/HELD.json)。

V8 在这份同 held 上增加了 33 个正确 known 路由，正确覆盖增加 **27.5 个百分点**；同时多接受了 3 个近域 OOD，OOD 接受率增加约 **7.89 个百分点**。这表明覆盖与拒绝行为发生了变化，不能写成可靠性已经全面提升。V8 同时变更了公开训练材料与 policy，因此该比较也不能单独归因于双 head 架构。

按 operation 分解，held 中每类均有 20 条 known wording：

| Operation | V7 正确/20 | V8 正确/20 |
| --- | ---: | ---: |
| current | 3 | 5 |
| history | 12 | 12 |
| semantic | 8 | 20 |
| procedure | 9 | 12 |
| change | 0 | 6 |
| apply | 8 | 18 |

`current` 与 `change` 仍有较高拒答率；其余类别的改善也不能替代总体 OOD 控制。以上全部为 **Python 分类/策略测量**，没有把 native 读值计入正确分子。[HELD.json](evidence/addressing/frozen-01/HELD.json)

### 为什么分母是 120/38，而不是 240

calibration 和 held 各有 240 个 native 请求：120 known、80 unsupported、40 identity/time 边界。每份输入有 12 个实体、60 条类型化记录。unsupported 中有 4 条被 owner parser 以多 cutoff 边界拒绝，其余 76 条在实体别名归一化并去重后形成 38 个 classifier wording。unknown entity 的 16 条、ambiguous alias 的 12 条和 time-conflict 的 12 条也不进入 classifier 分母。全部 240 行原样保留，并已在 CI02、CI03 的两个 native arm 中执行。Python parser 排除的 4 条与 CI01 native 报错的 4 条双 cutoff 请求保留各自实际结果；后两轮的新运行正确拒答不改写 CI01 的错误。[ADMISSION 输入摘要](evidence/addressing/frozen-01/ADMISSION.json)；[HELD 输入摘要](evidence/addressing/frozen-01/HELD.json)

这样不会用重复实体或容易被 parser 拒绝的请求稀释 classifier OOD 接受率。已公布的 4/38 不能改写成 4/80 或 4/240。Python held 收据明确记录 `native_rows_executed_by_this_python_stage=0`。

calibration/held 由与实现不同的作者预先准备并锁定，且检查与公开训练/selection 的文本和 family 重叠。它们仍属于作者构造的任务集，不是外部第三方盲测或独立同分布总体样本；没有总体风险、概率校准或统计显著性的保证。[addressing 协议](addressing/README.md)；[SOURCES.json](evidence/addressing/frozen-01/SOURCES.json)

### 完整 native 结果另列

以下使用原始 native 请求分母，保留直接路由与最终读值各自的结果。native 的 80 条 unsupported 与 Python 去重后的 38 个 wording 是不同测量口径，不能互换，也不能将 6/80 解释为 4/38 的简单换算。[CI02 native 审计](evidence/ci/run-02/NATIVE_AUDIT.json)；[CI03 native 审计](evidence/ci/run-03/NATIVE_AUDIT.json)

| 运行与 arm | 读出记录 | known 原生正确 / 120 | unsupported 错误接受 / 80 | 工程错误 | 质量门 |
| --- | ---: | ---: | ---: | ---: | --- |
| CI01 冻结 V7，局部完成 | 240/240 | 40 | 2 | 4 | 未通过 |
| CI02 冻结 V7 | 240/240 | 39 | 2 | 0 | 未通过 |
| CI02 V8 shadow | 240/240 | 73 | 6 | 0 | 未通过 |
| CI03 冻结 V7 | 240/240 | 40 | 2 | 0 | 未通过 |
| CI03 V8 shadow | 240/240 | 73 | 6 | 0 | 未通过 |

两轮完整运行均正确拒绝 16 条 unknown entity、12 条 ambiguous alias、12 条 time conflict；这不抵消 unsupported 错误接受。CI02 冻结 V7 的 known 正确数是 **39**，CI01/CI03 与冻结 Python 对照是 **40**，该差异的根因尚未确定，不以较好的一轮覆盖较差结果，也不擅自归因于某个模型或环境因素。重复执行用于工程修复与精确源码验证，不是新的独立盲测样本；两轮没有改变寻址权重、阈值或 held 输入。

## 4. 分区如何学习，以及完整成本为何保持 NoChange

[allocation.py](learning/allocation.py) 只读取已经完成请求的地址集合、顺序、请求/读出 digest 和来源 cut，统计地址频率与共同访问次数，再在相同 shard 容量约束下作确定性贪心分配。这里的“因果”表示访问前缀先发生、候选随后冻结、未来结果不进入训练字段；共同访问计数不等于发现了世界中的因果关系。trace hash 证明内容一致，真实过去与执行顺序还需要 pinned host 和原始阶段证据复核。

分区确定后，[population_training.py](learning/population_training.py) 在各 shard 内执行真实 MLP 训练；[原生 V3 loader](../../codex-rs/hepta-neuron/src/memory_population_learned.rs) 独立复算 trace 摘要和分区，owner/bundle 继续绑定 source cut。原 V2 固定地址排序分区保留，不能靠将任意路由塞进旧 schema 绕过校验。这使同一 owner 内语义/过程逻辑 cell 的 shard 分工可以根据已完成访问重新分配，不需要为每批访问手写整张分区图；它没有自动改变 OS 节点分工或网络拓扑。注册操作、模型类型和权限边界仍是显式实现。

[prospective 协议](learning/README.md) 预声明 11 个 arm：固定 1…8 shard、同信息的 lightweight-prefix-selector、learned-coaccess、direct-owner。固定库存的事后最强者是有意偏强的 hindsight oracle；轻量选择器与 learned 使用同样的前缀和 selection 信息，并承担相同的完整八候选搜索账；direct-owner 通过实际 owner/control API 获取相同事实，承担它实际发生的存储、通信和运行成本。

每个参数 arm 已按真实写入 → bootstrap fit/发布 → 重训前 retention → 已完成 prefix → 候选 fit/发布/锁定 → selection/future/retention 顺序执行。保留原始 worker request/response、参数、catalog、support、lineage、阶段日志和 control 计数。未来组合只作用于 **已经写入并进入 support** 的数据；参数存储重训后的保留率也不是数月持续引入新事实后的遗忘曲线。自然语言寻址由单独试验测量，本 prospective 使用显式受信 integration resolver。[harness](../../codex-rs/hepta-agentd/src/memory_cell_prospective_tests.rs)；[原始证据校验](learning/evidence.py)；[参数字节校验](learning/fit_evidence.py)

成本审计保留完整 child lifecycle wall、源 SQLite/发布 artifact/实验材料逻辑字节、RPC 与 pipe 字节、原生唤醒和淘汰计数，以及各进程在取样点之前的峰值 RSS 观测。host 在最终报告构造/序列化前取样，训练 worker 在最终响应序列化前取样；之后至退出的尾部 HWM 未测。各进程观测 HWM 求和是显式代理，不是同时峰值或 RSS×时间积分。catalog 与参数不能从计费中删去，累计快照不能相加重复计费，失败 arm 也不能从比较中筛除。当前任意正权重的代理得分不是货币成本或完整生命周期成本。[costs.py](learning/costs.py)

存储 byte-time、同时进程 RSS byte-time、父协调器完整簿记/最终报告尾部尚未完整测量；exclusive communication time 保持未知。**完整成本准入保留 `NoChange`，两轮实际冻结成本代理也均不支持 learned 净收益。** 两轮原始 `prospective-score.json` 与精确源码只读重放完全一致；评分器没有执行 Rust budget proposal bridge，也没有据此自行调整或发布结构。[CI02 重放](evidence/ci/run-02/REPLAY.json)；[CI03 重放](evidence/ci/run-03/REPLAY.json)；[结构预算门](../../codex-rs/hepta-plasticity/src/memory_budget.rs)

### 两轮完整比较的结果

两轮各有 11 个独立 child 进程，每轮的 11 个 arm 具有相同事实/source cut，跨 arm 使用相同 prefix、selection、future 与 retention 请求。固定 2…8、lightweight、learned 和 direct-owner 在每轮都取得 **72/72 个 future 正确读、12/12 个正确组合决策**；固定 1 为 0/72、0/12，具体状态是不可用，详见下文。每个 arm 的 future 有 24 次 Apply、24 次 Semantic、24 次 Procedure；可运行参数方案内部触发 48 次语义加 48 次过程读取，不能将这 96 次内部调用当作 96 个独立任务。[CI02 学习审计](evidence/ci/run-02/LEARNING_AUDIT.json)；[CI03 学习审计](evidence/ci/run-03/LEARNING_AUDIT.json)

| 运行 | past selection 选定 k | 实际训练进程 / shard fit | Learned 代理分 | 同信息 lightweight | 事后最优固定参照 | Direct owner |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CI02 | 6 | 20 / 176 | 339,895,212,628 | 339,804,592,479 | 38,489,733,790，fixed-4 | 97,705,578,234 |
| CI03 | 7 | 20 / 180 | 275,765,703,889 | 275,703,793,889 | 31,300,034,139，fixed-7 | 75,393,542,635 |

代理分越低越好，采用协议冻结的任意正权重，不是货币或完整生命周期成本。以“参照分 − learned 分”计，CI02 对 lightweight/固定 oracle/direct-owner 分别为 **−90,620,149 / −301,405,478,838 / −242,189,634,394**；CI03 分别为 **−61,910,000 / −244,465,669,750 / −200,372,161,254**。两个 adaptive 方案各自承担同一完整八候选搜索账：CI02 为 300,809,920,963 代理分，CI03 为 243,837,575,195。此搜索账包含固定候选的完整真实试验及 future/retention 诊断，是保守的实验计费，不能称在线选择必需成本。固定 oracle 只付自身运行和共同证据成本，是有意偏强的参照。没有从两轮中选择较有利结果，也没有单次时长差的统计显著性主张。

分区确实学到了不同地址组合，而非仅重命名 shard：将每个 shard 的地址集合排序，再对集合排序，learned 与同 k 固定分区仍不同。每 type 均有 25 个支持地址；CI02 在 300 个地址对中改变 68 对共同归属，prefix 同 shard coaccess 权重从 28/240 增到 120/240；CI03 改变 56 对，权重从 16/240 增到 104/240。**前缀目标改善没有转化为本次未来总唤醒改善**：CI02 learned 语义/过程唤醒为 15/19，总 34 次，同 k 固定与 lightweight 为 23/5，总 28 次；CI03 learned 为 19/22，总 41 次，同 k 两参照为 23/11，总 34 次。计数来自 future 结束减 selection 结束的累计快照，不将累计值相加。

176/180 次 shard fit 均验证了真实参数更新，但本实验比较的是完整存储/分区策略，**不能隔离梯度训练本身带来的未来收益**。所有参数 arm 都已经拟合相同 owner 事实；没有未训练模型反事实，fixed-4 的候选预测参数/路由/阈值还与其 bootstrap 一致。Direct-owner 无模型训练却同样完成未来任务。可以确认实际训练、读取和组合执行，不能由此推出参数训练比精确 owner 读取更有效。

### Retention 与固定 1 的失败根因

独立审计按相同 query/operation/source 配对重训前后 retention，并逐项重算正确值与组合决策。两轮中十个可运行 arm 的 24 个读与 4 个决策前后均正确，没有被净差为零掩盖的“对→错/错→对”交换。固定 1 的 24 个读与 4 个决策全部从正确变成失败；它在 selection/future/retention 合计 **120 次**返回的原始状态均为 `Unavailable`（JSON `unavailable`），reason 为 `native memory inference failed`，不能改写为公开 `BudgetExceeded` 或“72 次错误接受”。

结合精确受测源码与原始 native shard 字节可定位容量准入原因：固定 1 只有一个 shard，CI02 的语义/过程逻辑驻留需求为 **25,416 / 24,009 B**，CI03 为 **25,414 / 23,705 B**，均超过每 type 的 **16,384 B** 预算。需求由实际参数、catalog、support、lineage 字节相加；对应源码在唤醒或执行模型之前检查该需求并拒绝，外层映射为上述 `Unavailable`。原 readout 没有直接捕获内层错误枚举，这一根因是源码与数据的确定性归因。请求的 `max_cells=max_hops=3` 合法；零驻留/零唤醒，以及 future 内部读取为语义 48、过程 24（Apply 在语义阶段短路），与该路径一致。它证明此结构在给定预算下不可运行，不证明已经训练的参数遗忘了事实。[驻留计量](../../codex-rs/hepta-neuron/src/memory_population_cost.rs)；[准入检查](../../codex-rs/hepta-neuron/src/memory_population_cache.rs)；[外层读出映射](../../codex-rs/hepta-agentd/src/memory_cell_execution.rs)

## 5. 多节点一致性与“迁移”的范围

网络层绑定 consumer、各 owner 的身份/spawn generation、source cut、选中 artifact/bundle 和 deployment generation。读取前后检查完整版本向量；失败或取消关闭当前 admission，恢复需要重新探测所有 owner。持久化 anchor 保存已确认版本，重启后仍先处于不可用状态，再执行完整恢复；successor 必须是明确的后继 generation。防回滚依赖调用者管理独立的 rollback domain：如果 journal 与调用者的 expected vector 一起恢复到旧状态，校验和不能检测这一整域回滚。[network](../../codex-rs/hepta-agentd/src/memory_cell_network.rs)；[anchor](../../codex-rs/hepta-agentd/src/memory_cell_network_anchor.rs)

三轮真实进程测试均由父进程终止并回收 owner 子进程，再让新的进程打开同一 SQLite/artifact roots；检查新 PID、新 spawn generation、原 owner/cut/bundle/CURRENT 保持、successor generation 1→2，每轮完成 6 次成功节点读回。另一项真实进程退出测试验证 anchor commit 前后两侧的持久状态，范围是 journal 提交边界，不代表已穷举整条迁移路径的每个崩溃点。网络 fixture 使用显式 control-only App Server readiness seam 和单类原生参数；它验证真实控制协议、授权绑定与恢复，不构成完整生产 App Server 生命周期或训练效果的证明。通信计数包括失败、恢复与迁移尝试，但不包含所有内核封装、诊断/退出开销，不能解释为独占网络时间。[process tests](../../codex-rs/hepta-agentd/src/memory_cell_network_process_tests.rs)；[CI02 网络收据](evidence/ci/run-02/network-process.json)；[CI03 网络收据](evidence/ci/run-03/network-process.json)

这是 **同机多进程恢复与只读路由迁移**。路由状态经现有 `OrganHostV1` 生命周期替换，真实 I/O 与权限检查保持在外部 host。没有数据库复制、跨机器 replica protocol、自动发现未知节点，也没有以 memory prediction 驱动 TaskFlow effect。多机器容错、一致复制和持久数据移动仍不在当前已实现验收范围内。[organ 路由实现](../../codex-rs/hepta-agentd/src/memory_cell_network_organ.rs)

## 6. 原始证据保存与复核入口

[frozen-01/ARCHIVE.json](evidence/addressing/frozen-01/ARCHIVE.json) 列出 **140 个原始文件**及其字节数/SHA-256，包括各阶段结果、候选和执行源快照；归档已按分片与成员哈希复核。压缩包共 3,571,952 B，分为 9 片；拼接后的 SHA-256 为 `06c1c8698c36d0ee2ab0dd8b0d623682eaaa1a79cc19ff5c0d05ab920c3eb71c`。未压缩 tar 为 6,318,080 B，索引同时绑定其摘要。

复核时按 `ARCHIVE.json.parts` 的索引顺序拼接 `raw-evidence.tar.xz.part-000.bin` … `part-008.bin`，检查每片与完整压缩包，再解压并检查 140 个成员；不以重新序列化的 JSON 替换原始字节。本文只引用汇总，不重放训练或读取原始私有措辞。便于审阅的独立入口是：

- [TRAINING.json](evidence/addressing/frozen-01/TRAINING.json)：候选、实际 fit、选择指标、训练/编码成本。
- [ADMISSION.json](evidence/addressing/frozen-01/ADMISSION.json)：独立校准、最终部署 identity、生产准入失败。
- [HELD.json](evidence/addressing/frozen-01/HELD.json)：同 held 的 V8/V7 分类结果、native 零执行声明。
- [SOURCES.json](evidence/addressing/frozen-01/SOURCES.json)：输入锁、最终 manifest、native fixture 摘要及失败尝试边界。
- [ARCHIVE.json](evidence/addressing/frozen-01/ARCHIVE.json)：完整原始证据与归档传输索引。

## 7. 实际 CI、完整证据与最终收尾

[V8 CI](../../.github/workflows/memory-cell-v8.yml) 负责环境/模型准备、Python 单测、相关 Rust 测试与实际 ignored native 测量；[ci_verify.py](ci_verify.py) 保存命令退出、测试发现数量、原始运行文件和工程结果。CI02、CI03 各自的 18 项 Python、511 项普通 Rust、5 项 actual 及独立评分命令全部成功，必要收据齐全、受测 checkout 无 tracked 源码变更。范围是工作流列明的相关 crate 与实际集成测试，原收据明确 `complete_workspace_test=false`，不能写成所有 workspace 测试均已执行。

| 运行 | 原始 source commit / source tree | 工程结果与证据 |
| --- | --- | --- |
| [CI01：40609738136](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40609738136) | `92097d22a47d85e9e118c9685b7c915fa3dc49ae` / `faf3a5117e9413dc54d20a879e7a97e3c6740a99` | 整体失败，保留局部成功与错误：[receipt](evidence/ci/run-01/receipt.json)、[archive](evidence/ci/run-01/ARCHIVE.json) |
| [CI02：40612088249](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40612088249) | `1f52f23f2dc9cf1ecc863c61e52cce8e53f35330` / `62ef0f8a912d989d47ac29faec56800139a6738d` | 18 Python + 511 普通 Rust + 5 actual 通过：[receipt](evidence/ci/run-02/receipt.json)、[archive](evidence/ci/run-02/ARCHIVE.json)、[精确树重放](evidence/ci/run-02/REPLAY.json) |
| [CI03：40612818087](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40612818087) | `75256635aae979f34b4ec830764b7dbfa24c389d` / `45682053f8e9655b897877b94871afca78855de7` | 18 Python + 511 普通 Rust + 5 actual 通过：[receipt](evidence/ci/run-03/receipt.json)、[archive](evidence/ci/run-03/ARCHIVE.json)、[精确树重放](evidence/ci/run-03/REPLAY.json) |

CI01 的 18 项 Python 与 509 项普通 Rust 全部通过；5 项 actual 中 3 项通过、2 项失败。两个新增 actual 首次均被 60 秒限制终止，随后自动重试也未通过；失败输出保留。该轮 `receipt.json` 的 `passed=false`，缺少 `candidate-native-held.json`、`prospective-learning.json` 和 `prospective-score.json`。后两轮完整验证没有回写或删除 CI01 的结果，CI01 的部分材料也不冒充完整收据。

三项既有 actual 测试在三轮均通过：自然语言 worker 经原生参数和 control socket 执行六种操作；真实新值训练、Replay、纠正/撤回、Clean 重建与读回；显式 1→2→1 shard 训练/签名发布、sleep/wake 读回和 stale source-cut 拒绝。完整 artifact 保留对应 `legacy-language.json`、`legacy-training.json`、`legacy-population.json`，这些收据不声称独立未来任务收益。后两轮另有完整 native 配对与 11-arm prospective 原始材料；`NATIVE_AUDIT.json`、`LEARNING_AUDIT.json` 只读派生解释并绑定原始字节，未修改冻结 scorer、质量门或运行结果。

| 验证项 | 当前状态 | 已有证据与解释边界 |
| --- | --- | --- |
| 精确被测 commit/tree、CI run URL/ID、工程退出 | **CI02/03 完整相关验证通过** | 各自原始 receipt、execution log、完整 artifact 及精确源码树 scorer 重放已归档；CI01 整体失败保留 |
| V8 与冻结 V7 的同 fixture native 请求 | **完整配对实测；质量门未通过** | 两轮各 240 条/arm；V8 known 73/120、unsupported 错误接受 6/80。冻结 V7 的 CI02 39/120 与 CI03 40/120 都保留；双 cutoff 修复只影响新运行 |
| 参数学习、未来任务与遗忘边界 | **11 arm 完整实测；策略收益未成立** | 全部原始 fit/阶段材料、primary score、独立逐项审计与精确树重放已归档；真实参数更新、保持性与未来正确率分别报告。未隔离梯度收益、未证明长期遗忘控制；全成本 `NoChange` |
| 同机进程崩溃/重启、anchor、一致版本 | **精确受测源码上通过** | 三轮 `network-process.json` 与 process 测试日志确认真实进程恢复、每轮 6 次节点读回、提交边界和费用；不代表跨机器数据迁移 |
| 最终 `just fix` / `just fmt` | **成功，原始补丁已应用** | [finalization receipt](evidence/finalization/run-01/receipt.json)、[应用审计](evidence/finalization/run-01/REVIEW.json)、[完整归档](evidence/finalization/run-01/ARCHIVE.json)；本地暂存 tree 与 CI `after_tracked_tree` 完全相同；结束后没有重跑测试或训练 |

最终收尾见 [FINALIZATION.md](FINALIZATION.md)。[最终化 CI 40615518988](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40615518988) 已成功：`FINALIZE_REQUEST` 绑定 CI03 受测 source `75256635aae979f34b4ec830764b7dbfa24c389d` 与成功原始 receipt SHA-256 `aa4d3bd1a35114b941ff8abecbb33097938bc0da3a8fca985f2826799f8f8b16`。最终化执行 source 为 `1568911035e6055fb0491170ce7a571dca32e496`、tree 为 `9d28d41eaa19527030a81c212780f3f720ecb01c`；其受保护源码与被测源码一致。十个 Hepta package 的 `just fix --locked` 用时 218.42 秒，`just fmt --base 0b0b041b6dd8121050c335cb3be73bb1d8cb7904` 用时 3.58 秒，两条命令退出码均为 0。Clippy 唯一修改是测试闭包参数移除未使用的 `mut`；格式阶段只修改 `hepta-agentd` / `hepta-neuron` 的 Rust 文件。

原始补丁 271,201 B、SHA-256 `a37f2b6664c4ef80586d8a61abf6eb8af698e40d74be80bef58f624c504f4099` 已用 `git apply --index` 应用，生成的 tree 精确等于 CI 记录的 `0edfb8eb486d38e562e1b2bb6032d7adcd641f4c`；26 个改动文件的字节/模式和 101 个冻结 Python 文件的字节/模式全部核对一致。原始最终化 receipt SHA-256 为 `67409d8d3104fa444b9bc1137ba7ef4fd7ad7902c2241e87290b37dc19ef4117`；27 个原始 artifact 文件、完整 ZIP 分片、每阶段补丁与命令日志均保留。此后的说明和派生审计提交只增加证据，不改变执行源码。

成功的工程 CI 与科学质量 gate 分开记录；完整测得 `NoChange` 或寻址 gate 失败不能改写成科学验收通过。最终 fix/format 后没有重跑测试、没有微调模型；格式化后的 tree 不冒充原始被测 tree。

本轮已实测三类 cell 的新写入读回、参数回放/干净重建、显式结构生命周期、学习得到的逻辑分区、完整未来组合及同机多 owner 恢复。V8 在冻结 authored held 上提高 known 覆盖，同时增加近域 OOD 接受，生产准入没有通过；learned 分区与强对照未来正确率持平、两轮冻结代理比较均不占优。梯度训练的独立未来收益、长期遗忘控制、跨机器数据迁移、开放领域通用记忆、纯参数压缩和自发专业化仍是尚未获得证据的研究目标。
