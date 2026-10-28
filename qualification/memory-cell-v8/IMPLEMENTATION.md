# Memory Cell V8：六项集成交付与验收边界

本轮实现把类型化请求、三类 memory cell、参数训练、访问分区学习、预算约束和多 owner 读取接到现有 Hepta 路径。**当前交付是可审计的工程候选，六项验收尚未全部满足。** V8 自然语言寻址的训练、独立校准和一次冻结 held 测量已经归档；生产准入仍为 `serving_admitted=false`。[CI01：40609738136](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40609738136) 的整体结果为 **失败**，同时保留了 18 项 Python、509 项普通 Rust、3 项既有 actual 测试以及冻结 V7 native 对照的局部实测。两项新增 actual 测试没有完整通过。[CI02：40612088249](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40612088249) 与 [CI03：40612818087](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40612818087) 仍为 **pending**；局部成功不能替代最终精确源码的完整工程验证，也不表示研究验收通过。

本文以 `qualification/memory-cell-v8/` 为相对路径起点。自然语言寻址的模型阶段已经结束；以下结果不再用于修改本轮寻址权重、候选或阈值。后续只补入实际 CI、修复与格式化收据，并保持原始失败证据。CI01 的结果绑定原始 source `92097d22a47d85e9e118c9685b7c915fa3dc49ae`；CI02 绑定 `1f52f23f`。CI03 绑定 `75256635aae979f34b4ec830764b7dbfa24c389d`，包含 `6fbe1018` 新增的完整 evaluation 输入锁。它在 CI02 结果产生前启动，没有使用 CI02 结果选择或改动模型、数据、阈值或学习协议；两轮全部结果均保留。

第 3、4、6 项的完整解释口径见 [ACCEPTANCE.md](ACCEPTANCE.md)：明确训练因果收益的可识别范围、固定比较分母、逐项 retention 转移，以及三类参照和完整成本门。该说明解释现有冻结协议，不改变模型或验收门。

## 1. 六项交付对应到哪里

用户表中的 `learning.operator`、`learning.eval` 等名称在这里表示能力边界；实际实现复用已有 crate 和 Agentd 入口，不代表另行创建了同名运行时。

| 顺序与用户交付 | 当前实际模块与入口 | 可复核证据 | 尚未满足的验收 |
| --- | --- | --- | --- |
| **1．类型化 MemoryRequest/Readout、可靠语义寻址** | [cognitive.types 请求/读出](../../codex-rs/hepta-cognitive-types/src/memory_cell.rs)、[memory.retrieval 来源重验](../../codex-rs/hepta-memory-retrieval/src/memory_cell.rs)、[context.compiler 证据注入](../../codex-rs/hepta-context-compiler/src/memory_cell.rs)；[V8 addressing worker](addressing/worker.py) 经 Agentd 的 pinned resolver 接入 | 已有 [TRAINING](evidence/addressing/frozen-01/TRAINING.json)、[ADMISSION](evidence/addressing/frozen-01/ADMISSION.json)、[HELD](evidence/addressing/frozen-01/HELD.json)。CI01 冻结 V7 native 对照留下 240/240 条读出记录，known 正确 40/120；V8 native 完整结果 pending | 校准正确覆盖 72.5%，低于 80%；held 正确覆盖 60.83%，近域 OOD 接受率 10.53%，超过 5%。生产准入失败；CI01 的 4 条双 cutoff 错误保留，修复后的整套 native 路径尚待验证 |
| **2．事件、语义、过程三类可用 cell** | [SQLite owner](../../codex-rs/hepta-memory/src/memory_cell_owner.rs)、[原生关联模型](../../codex-rs/hepta-neuron/src/associative_memory.rs)、[Agentd runtime](../../codex-rs/hepta-agentd/src/memory_cell_runtime.rs)、[组合执行](../../codex-rs/hepta-agentd/src/memory_cell_execution.rs)；通过 `AgentdClient.memory_cell_read` 进入 control 路径 | CI01 的既有 actual 测试已完成新写入值的参数训练、真实 control 读回和跨类型 `apply` 组合；[V8 paired fixture](../../codex-rs/hepta-agentd/src/memory_cell_language_v8_tests.rs) 的冻结 V7 arm 也完成新 owner 写入、2 次参数 fit 和 240 条读出记录 | 这些是 CI01 源码上的局部实测；V8 新候选整套 native 验证仍 pending。240 条记录含拒答与错误，不是 240 条正确接受。语义/过程仍保留显式 catalog，尚未证明比传统存储更省总空间 |
| **3．参数训练、回放、校准、干净重建** | [Agentd trainer](../../codex-rs/hepta-agentd/src/memory_cell_training.rs) 的 `Clean` / `Replay`、[learning ledger 接入](../../codex-rs/hepta-agentd/src/memory_cell_learning.rs)、[artifact 发布/选择](../../codex-rs/hepta-agentd/src/memory_cell_release.rs)；[V8 population trainer](learning/population_training.py) | 寻址阶段完成 12 次真实 head fit。CI01 的 `legacy-training.json` 已记录实际训练/回放/纠正/撤回后的读回、干净重建参数一致，以及纠正/撤回后拒绝旧 replay；[prospective harness](../../codex-rs/hepta-agentd/src/memory_cell_prospective_tests.rs) 与[评分器](learning/score.py) 的完整结果 pending | 已写地址读回与干净重建不能代替未来任务改善；11 arm 的未来任务与重训前后 retention 比较尚未完整获得，也未证明持续写入下的长期遗忘控制 |
| **4．分裂、合并、休眠、预算竞争** | [population](../../codex-rs/hepta-neuron/src/memory_population.rs)、[驻留缓存与 sleep/wake](../../codex-rs/hepta-neuron/src/memory_population_cache.rs)、[结构预算](../../codex-rs/hepta-plasticity/src/memory_budget.rs)；[已完成访问的分区学习](learning/allocation.py) 与 [V3 原生校验](../../codex-rs/hepta-neuron/src/memory_population_learned.rs) | CI01 的 `legacy-population.json` 已实测显式 1→2→1 shard 训练/签名发布、sleep 后唤醒读回和过期 source-cut 拒绝。固定 1…8、轻量选择器、learned-coaccess、direct-owner 共 11 arm 的完整比较仍 pending；见 [learning/README](learning/README.md) | 既有生命周期成功不等于自主选择结构。存储 byte-time、同时进程 RSS byte-time、尾部成本仍缺测；完整成本准入保持 `NoChange`，没有“超过强固定结构的全成本净收益”结论，也未执行自主结构提案/发布 |
| **5．多节点读取、迁移、一致版本发布** | [MemoryCellNetworkV1](../../codex-rs/hepta-agentd/src/memory_cell_network.rs)、[版本向量与绑定](../../codex-rs/hepta-agentd/src/memory_cell_network_bindings.rs)、[OrganHost 路由生命周期](../../codex-rs/hepta-agentd/src/memory_cell_network_organ.rs)、[持久化 anchor](../../codex-rs/hepta-agentd/src/memory_cell_network_anchor.rs) | CI01 的[真实进程测试](../../codex-rs/hepta-agentd/src/memory_cell_network_process_tests.rs) 已通过，`network-process.json` 记录 6 次成功读回、新 PID/spawn、同一持久 owner/cut/bundle/CURRENT、generation 1→2 和失败/恢复/迁移计费；anchor commit 两侧真实进程退出测试也通过 | 范围为同机独立 OS 进程和 Unix control sockets，且使用 control-only readiness fixture；不提供跨机器数据库复制。迁移的是只读路由和已准入版本，未调用 TaskFlow effect；通信计数不是完整网络 wire 成本 |
| **6．新领域、新组合、新专业化迁移** | [causal coaccess allocation](learning/allocation.py)、[任务批次构造/执行](../../codex-rs/hepta-agentd/src/memory_cell_prospective_batches.rs)、[独立原始证据复算](learning/evidence.py) | 协议在 prefix 后冻结逻辑 shard 分区，随后执行逆序、跨组、交错组三类 future 组合和相同 retention 任务；CI01 的局部试跑材料已保留，但 11 arm 的完整执行与比较仍 pending | 任务使用已经写入且属于 support 的信息、固定六种读取操作和五种 procedure opcode。逻辑分区没有自动改变 OS 节点拓扑；尚未证明开放领域新类型发现、跨领域专业化迁移或通用 memory system 自发形成 |

## 2. 真实实现的模型与数据边界

### 三类 cell 与执行链

事件 cell 从 canonical SQLite owner 读取带时间戳的事实；`history` 和 `change` 使用实际 Unix 秒 cutoff。语义 cell 返回已记忆的 `{factor, label}`，过程 cell 返回 `{opcode, bias, limit}`。`apply` 组合当前事件、语义属性和过程，执行注册的 `identity`、`add_bias`、`multiply`、`affine`、`clamp` 语义。字段与解释器边界由 [typed values](../../codex-rs/hepta-cognitive-types/src/memory_cell_values.rs) 定义。

语义/过程模型执行真实的小型 tanh MLP/Adam 参数训练，再导出供 Rust 执行的数值参数。原生模型使用地址特征预测 catalog 中的类型化值，并保留支持来源与训练 lineage。**完整 catalog 值仍显式存放，事件与来源事实也仍在 owner 中。** 因此当前可以论证“确实训练并执行了参数模型”，不能据此论证“事实已被纯参数压缩”或“总存储成本低于数据库”。支持集合之外会拒答；模型输出保持 prediction 身份，来源 ID 也不会自动使模型值变成事实。实现见 [原生模型与 catalog](../../codex-rs/hepta-neuron/src/associative_memory.rs) 和 [既有参数训练器](../memory-cell-v7/training.py)。

自然语言寻址是另一组模型：固定多语言 MiniLM 表征，加训练得到的正样本六类 operation head 和独立二类 supportedness head。其实际学习器是 logistic regression；没有微调基础 encoder。hybrid 候选还使用公开训练材料建立的词/字符 TF-IDF 特征。它输出受约束的执行假设，不输出 memory value；实体仍需 owner 提供 canonical ID/aliases。新增实体能够通过新 owner registry 绑定，并不意味着开放世界实体发现已经实现。见 [addressing/model.py](addressing/v8_addressing/model.py) 与 [addressing 协议](addressing/README.md)。

从请求到上下文的链路是：类型校验 → owner/alias/time 绑定 → pinned addressing worker → 选中 bundle 的原生执行 → owner source-cut 与来源依赖重验 → 类型化 readout → 有界 context evidence。artifact 发布、独立选择和最终使用的权限继续由既有 owner 管理。学习、分区、迁移或一个 digest 都不能自行授予发布或 final-use 权限。对应入口见 [worker config](../../codex-rs/hepta-agentd/src/memory_cell_address_worker_config.rs)、[release](../../codex-rs/hepta-agentd/src/memory_cell_release.rs) 和 [context evidence](../../codex-rs/hepta-context-compiler/src/memory_cell.rs)。

### 校准失败仍能测量候选

正常 [worker.py](addressing/worker.py) 要求独立校准 gate 通过。本轮 calibration 未通过，因此不获生产准入。单独的 [qualification_shadow_worker.py](addressing/qualification_shadow_worker.py) 允许隔离 fixture 测量同一个冻结模型、同一组阈值，但只接受保留的 ControlFixture owner/scope，并在 score kind 中标记 `qualification-shadow`；它不生成 final-use grant。

[paired native runner](../../codex-rs/hepta-agentd/src/memory_cell_language_v8_tests.rs) 为冻结 V7 和 V8 分别创建真实 owner，写入同一批记录，各自训练参数 cell，再执行同一 fixture 的全部 240 个请求。每行先调用真实 resolver，再调用完整 control read；两次路由分别计数与计费。直接 resolver 的 OOD 错误路由必须留在收据中，不能因下游读回失败而消失。**CI01 已取得冻结 V7 arm 的局部实际结果：新 owner 写入后完成 2 次参数 fit、240/240 条读出记录，known 正确 40/120。** 其中 4 条 unsupported 双 cutoff 请求仍记录为错误，不能改算正确拒答；完整 V8/V7 配对运行尚未通过。这些 native 结果与下节冻结的 Python 分类结果分开保存。

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

calibration 和 held 各有 240 个 native 请求：120 known、80 unsupported、40 identity/time 边界。每份输入有 12 个实体、60 条类型化记录。unsupported 中有 4 条被 owner parser 以多 cutoff 边界拒绝，其余 76 条在实体别名归一化并去重后形成 38 个 classifier wording。unknown entity 的 16 条、ambiguous alias 的 12 条和 time-conflict 的 12 条也不进入 classifier 分母。全部 240 行原样保留；CI01 的冻结 V7 native arm 已执行这 240 行，完整配对验证仍待完成。Python parser 排除的 4 条与 CI01 native 仍报错的 4 条双 cutoff 请求均保留各自实际结果，不将 native 错误重标为正确拒答。[ADMISSION 输入摘要](evidence/addressing/frozen-01/ADMISSION.json)；[HELD 输入摘要](evidence/addressing/frozen-01/HELD.json)

这样不会用重复实体或容易被 parser 拒绝的请求稀释 classifier OOD 接受率。已公布的 4/38 不能改写成 4/80 或 4/240。Python held 收据明确记录 `native_rows_executed_by_this_python_stage=0`。

calibration/held 由与实现不同的作者预先准备并锁定，且检查与公开训练/selection 的文本和 family 重叠。它们仍属于作者构造的任务集，不是外部第三方盲测或独立同分布总体样本；没有总体风险、概率校准或统计显著性的保证。[addressing 协议](addressing/README.md)；[SOURCES.json](evidence/addressing/frozen-01/SOURCES.json)

## 4. 分区如何学习，以及完整成本为何保持 NoChange

[allocation.py](learning/allocation.py) 只读取已经完成请求的地址集合、顺序、请求/读出 digest 和来源 cut，统计地址频率与共同访问次数，再在相同 shard 容量约束下作确定性贪心分配。这里的“因果”表示访问前缀先发生、候选随后冻结、未来结果不进入训练字段；共同访问计数不等于发现了世界中的因果关系。trace hash 证明内容一致，真实过去与执行顺序还需要 pinned host 和原始阶段证据复核。

分区确定后，[population_training.py](learning/population_training.py) 在各 shard 内执行真实 MLP 训练；[原生 V3 loader](../../codex-rs/hepta-neuron/src/memory_population_learned.rs) 独立复算 trace 摘要和分区，owner/bundle 继续绑定 source cut。原 V2 固定地址排序分区保留，不能靠将任意路由塞进旧 schema 绕过校验。这使同一 owner 内语义/过程逻辑 cell 的 shard 分工可以根据已完成访问重新分配，不需要为每批访问手写整张分区图；它没有自动改变 OS 节点分工或网络拓扑。注册操作、模型类型和权限边界仍是显式实现。

[prospective 协议](learning/README.md) 预声明 11 个 arm：固定 1…8 shard、同信息的 lightweight-prefix-selector、learned-coaccess、direct-owner。固定库存的事后最强者是有意偏强的 hindsight oracle；轻量选择器与 learned 使用同样的前缀和 selection 信息，并承担相同的完整八候选搜索账；direct-owner 通过实际 owner/control API 获取相同事实，承担它实际发生的存储、通信和运行成本。

每个参数 arm 计划按真实写入 → bootstrap fit/发布 → 重训前 retention → 已完成 prefix → 候选 fit/发布/锁定 → selection/future/retention 顺序执行。保留原始 worker request/response、参数、catalog、support、lineage、阶段日志和 control 计数。未来组合只作用于 **已经写入并进入 support** 的数据；参数存储重训后的保留率也不是数月持续引入新事实后的遗忘曲线。自然语言寻址由单独试验测量，本 prospective 使用显式受信 integration resolver。[harness](../../codex-rs/hepta-agentd/src/memory_cell_prospective_tests.rs)；[原始证据校验](learning/evidence.py)；[参数字节校验](learning/fit_evidence.py)

成本审计保留完整 child lifecycle wall、源 SQLite/发布 artifact/实验材料逻辑字节、RPC 与 pipe 字节、原生唤醒和淘汰计数，以及各进程在取样点之前的峰值 RSS 观测。host 在最终报告构造/序列化前取样，训练 worker 在最终响应序列化前取样；之后至退出的尾部 HWM 未测。各进程观测 HWM 求和是显式代理，不是同时峰值或 RSS×时间积分。catalog 与参数不能从计费中删去，累计快照不能相加重复计费，失败 arm 也不能从比较中筛除。当前任意正权重的代理得分不是货币成本或完整生命周期成本。[costs.py](learning/costs.py)

存储 byte-time、同时进程 RSS byte-time、父协调器完整簿记/最终报告尾部尚未完整测量；exclusive communication time 保持未知。**因此完整成本准入保留 `NoChange`，即使未来某个代理得分看起来有利，也不能声称已超过最强固定结构的全成本净收益。** 本轮实际 `prospective-score.json` 仍 pending；现有评分代码不会执行 Rust budget proposal bridge，也不会据此自行调整或发布结构。[score.py](learning/score.py)；[结构预算门](../../codex-rs/hepta-plasticity/src/memory_budget.rs)

## 5. 多节点一致性与“迁移”的范围

网络层绑定 consumer、各 owner 的身份/spawn generation、source cut、选中 artifact/bundle 和 deployment generation。读取前后检查完整版本向量；失败或取消关闭当前 admission，恢复需要重新探测所有 owner。持久化 anchor 保存已确认版本，重启后仍先处于不可用状态，再执行完整恢复；successor 必须是明确的后继 generation。防回滚依赖调用者管理独立的 rollback domain：如果 journal 与调用者的 expected vector 一起恢复到旧状态，校验和不能检测这一整域回滚。[network](../../codex-rs/hepta-agentd/src/memory_cell_network.rs)；[anchor](../../codex-rs/hepta-agentd/src/memory_cell_network_anchor.rs)

CI01 中，真实进程测试由父进程终止并回收 owner 子进程，再让新的进程打开同一 SQLite/artifact roots；已经检查新 PID、新 spawn generation、原 owner/cut/bundle/CURRENT 保持、successor generation 1→2，并完成 6 次成功节点读回。另一项真实进程退出测试验证 anchor commit 前后两侧的持久状态，范围是 journal 提交边界，不代表已穷举整条迁移路径的每个崩溃点。网络 fixture 使用显式 control-only App Server readiness seam 和单类原生参数；它验证真实控制协议、授权绑定与恢复，不构成完整生产 App Server 生命周期或训练效果的证明。通信计数包括失败、恢复与迁移尝试，但不包含所有内核封装、诊断/退出开销，不能解释为独占网络时间。[process tests](../../codex-rs/hepta-agentd/src/memory_cell_network_process_tests.rs)

这是 **同机多进程恢复与只读路由迁移**。路由状态经现有 `OrganHostV1` 生命周期替换，真实 I/O 与权限检查保持在外部 host。没有数据库复制、跨机器 replica protocol、自动发现未知节点，也没有以 memory prediction 驱动 TaskFlow effect。多机器容错、一致复制和持久数据移动仍不在当前已实现验收范围内。[organ 路由实现](../../codex-rs/hepta-agentd/src/memory_cell_network_organ.rs)

## 6. 原始证据保存与复核入口

[frozen-01/ARCHIVE.json](evidence/addressing/frozen-01/ARCHIVE.json) 列出 **140 个原始文件**及其字节数/SHA-256，包括各阶段结果、候选和执行源快照；归档已按分片与成员哈希复核。压缩包共 3,571,952 B，分为 9 片；拼接后的 SHA-256 为 `06c1c8698c36d0ee2ab0dd8b0d623682eaaa1a79cc19ff5c0d05ab920c3eb71c`。未压缩 tar 为 6,318,080 B，索引同时绑定其摘要。

复核时按 `ARCHIVE.json.parts` 的索引顺序拼接 `raw-evidence.tar.xz.part-000.bin` … `part-008.bin`，检查每片与完整压缩包，再解压并检查 140 个成员；不以重新序列化的 JSON 替换原始字节。本文只引用汇总，不重放训练或读取原始私有措辞。便于审阅的独立入口是：

- [TRAINING.json](evidence/addressing/frozen-01/TRAINING.json)：候选、实际 fit、选择指标、训练/编码成本。
- [ADMISSION.json](evidence/addressing/frozen-01/ADMISSION.json)：独立校准、最终部署 identity、生产准入失败。
- [HELD.json](evidence/addressing/frozen-01/HELD.json)：同 held 的 V8/V7 分类结果、native 零执行声明。
- [SOURCES.json](evidence/addressing/frozen-01/SOURCES.json)：输入锁、最终 manifest、native fixture 摘要及失败尝试边界。
- [ARCHIVE.json](evidence/addressing/frozen-01/ARCHIVE.json)：完整原始证据与归档传输索引。

## 7. 实际 CI、局部结果与最终收尾

[V8 CI](../../.github/workflows/memory-cell-v8.yml) 负责环境/模型准备、Python 单测、相关 Rust 测试与实际 ignored native 测量；[ci_verify.py](ci_verify.py) 保存命令退出、测试发现数量、原始运行文件和工程结果。当前没有本轮完整 CI 的通过收据。以下局部结果来自 [CI01 原始 artifact](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40609738136) `memory-v8-verification-92097d22a47d85e9e118c9685b7c915fa3dc49ae` 中的 `memory-v8-ci-output/receipt.json`、`execution.log` 和对应原始 JSON；不改写该 run 的整体失败结论。

CI01 的 source commit 为 `92097d22a47d85e9e118c9685b7c915fa3dc49ae`，source tree 为 `faf3a5117e9413dc54d20a879e7a97e3c6740a99`。18 项 Python 与 509 项普通 Rust 全部通过；5 项 actual 测试中 3 项通过、2 项失败。两个新增 actual 首次均被 60 秒限制终止，随后自动重试也未通过；失败输出保留。`receipt.json` 的 `passed=false`，缺少 `candidate-native-held.json`、`prospective-learning.json` 和 `prospective-score.json`。既有实际测试的成功和失败 run 中留下的部分材料，都不能填补这些缺失的完整收据。

三项已通过的既有 actual 测试分别证明本次运行中：自然语言 worker 经原生参数和 control socket 执行六种操作；真实新值训练、Replay、纠正/撤回、Clean 重建与读回；显式 1→2→1 shard 训练/签名发布、sleep/wake 读回和 stale source-cut 拒绝。对应 `legacy-language.json`、`legacy-training.json`、`legacy-population.json` 明确不声称独立未来任务收益。两项新增网络进程测试属于已通过的 509 项普通 Rust 测试，另有 `network-process.json` 保存实际版本与费用。

| 验证项 | 当前状态 | 已有证据与待补录边界 |
| --- | --- | --- |
| 精确被测 commit/tree、CI run URL/ID、工程退出 | **CI01 整体失败；CI02/03 pending** | CI01 原始 `receipt.json` 与 `execution.log` 已确认局部通过；CI02 `40612088249` / source `1f52f23f`、CI03 `40612818087` / source `75256635` 的完整验证尚待，不能沿用 CI01 通过项声明整体验证成功 |
| V8 与冻结 V7 的同 fixture native 请求 | **V7 局部实测；完整配对 pending** | CI01 `baseline-native-held.json`：240/240 条读出记录、known 正确 40/120、4 条双 cutoff 错误原样保留；没有完整 candidate 收据。直接路由和 control 调用分别计费，结果不能冒充冻结 Python 分类分母 |
| 参数学习、未来任务与遗忘边界 | **既有训练/重建通过；11 arm 比较 pending** | CI01 `legacy-training.json` 与部分 prospective `.artifacts` 保留；完整 `prospective-learning.json`、`prospective-score.json` 尚缺，未来任务/retention/全成本结论不能由局部 arm 推得 |
| 同机进程崩溃/重启、anchor、一致版本 | **CI01 局部实测通过** | `network-process.json` 与两项 process 测试日志确认真实进程恢复、6 次节点读回、提交边界和费用；不代表跨机器数据迁移，也不代替最终源码验证 |
| 最终 `just fix` / `just fmt` | **pending** | 精确成功 CI receipt 绑定的 request、每条命令原始退出/日志、阶段 patch、source/tested/after tree 与压缩 artifact 索引 |

最终收尾见 [FINALIZATION.md](FINALIZATION.md)。成功的工程 CI 与科学质量 gate 分开记录；`NoChange` 或寻址 gate 失败可以被成功、完整地测量，不能改写成科学验收通过。只有成功 CI 的原始 receipt 绑定 exact tested source 后才能执行本轮 final fix/format；其后不重跑测试、不微调模型，不以格式化后的 tree 冒充原始被测 tree。

本轮可以确认的模型结论是：V8 在已冻结、同一份 authored held 上提高了 known 覆盖，同时增加了近域 OOD 接受；生产准入没有通过。CI01 已为三类 cell 的真实读回、参数回放/干净重建、显式结构生命周期和同机多 owner 恢复提供局部工程证据；V8 完整 native 配对、11 arm 未来任务比较及最终精确源码验证仍待完成。开放领域通用记忆、纯参数压缩、自主结构净收益和自发专业化仍是尚未获得证据的研究目标。
