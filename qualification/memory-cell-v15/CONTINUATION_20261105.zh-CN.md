# Memory Cell／Meta Network：持久评估、迁移活性与归因增量

日期：2026-11-05（UTC）。来源基线为 [#4885](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4885) 的 `f88b826d3c22b5f89fd350dab4813be2855a2f93`；其中已经包含 [#4847](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4847) 的原生迁移转换核。本文衔接 [完整研究报告](META_NETWORK_RESEARCH.zh-CN.md)，区分本轮实现、历史模型结果与尚待验证的设计。执行结果以本目录后继证据清单为准。

## 1. 本轮推进的四个具体缺口

**迁移活性。** 原参考协议允许合法 owner 提交 `transfer=null`，SQLite 的非整数 `TEXT PRIMARY KEY` 接受空值，Cell 却已切换为 `prepared`。之后按 `WHERE id=?` 进行的 ready、commit、abort 找不到该行，recover_prepare 又要求 active。修复必须在任何持久状态变更之前拒绝异常标识，并证明拒绝后正常提交、撤销与重启仍可达。已有坏记录不得通过自动清空恢复为健康状态；其修复需要单独保留来源与管理员恢复证据。

**答案类型与准入假阳性。** 原 worker 使用 Python 的 `==` 比较答案，使布尔 `True` 被当作整数 `1`。相同 256 题、相同 durable evaluator 和真实子进程探针，在修复前把候选计为 256/256 并批准；修复后为 0/256 并拒绝，两次都正常完成并保留持久终态。新的 `typed_json.py` 由 worker 和诊断器共用：bool、int、float 类型分离；对象 key 顺序无关，数组顺序有关；非 JSON、自定义比较对象与非有限浮点拒绝。有限浮点的正负零按值相等。该回归证据使用合成任务及人为成本控制，不是产品质量实验。[同探针前后证据](evidence/typed-output-20261105/)

**持久实验与查看次数。** 旧评估器冻结了 cohort 和 planned_looks，但未跨进程保留实际执行占用。本轮增加单个 SQLite WAL/FULL 账本和实际评估包装入口，在预测器执行之前原子占用实验、比较、look、稳定 operation ID。已占用、运行中、未知及取消不会因为重启而自动获得第二次执行许可；完整终态可读回。该保证仅适用于通过 `DurableMatchedEvaluator`、连接同一持久账本的调用；直接使用旧评估器或另建数据库不具备该保证，生产调用链尚未全面接入。整个账本被回滚、复制或删除仍超出其保证，不能称为分布式权威或独立回退防护。

**错误归因。** 新的诊断接口要求冻结实际 query／payload 与其摘要、候选池、局部输出、路由选择与最终执行结果，分别定位证据不存在、候选漏召回、专家内排序、跨专家路由和读者错误。每个 arm 的模型、scorer、router 身份也绑定进轨迹。这是固定轨迹上的描述性分解；全 Cell shadow scoring 的成本须计入，数据来源仍需认证，不能据此断言修复某一级会因果改善最终收益。历史 V14 semantic receipts 只保留 skill／output 和有限 composition trace，缺少这类逐 Cell 信息，因此不能从最终正确率反推出各段原因。本轮对其 42 个方法／seed 组的结论为 `unavailable`，不是零路由错误，也不是新增模型实验。

## 2. Memory Cell 的实现单位

Memory Cell 应是有身份、类型、依赖、版本和更新边界的持久服务。小模型承担表示、压缩、访问或控制的一部分；权威来源、纠错、撤销、权限与所有权继续由明确的持久协议负责。每个 Cell 不必拥有一个独立 Transformer。

| 记忆类型 | 权威内容与更新语义 | 优先竞争的后端 |
|---|---|---|
| 精确事实 | 实体、关系、值、有效时间、来源与冲突；纠错不能悄悄覆盖历史 | 类型化 KV／关系索引，加可选语义检索 |
| 事件与经历 | 时间、观察、行动、结果；追加、时间查询、合法过期 | 事件日志、分层索引、可引用摘要 |
| 语义与概念 | 多来源概念、相似性、定义边界、概括的不确定性 | 共享 encoder、retrieval、centroid／ridge／head |
| 程序与技能 | 输入输出类型、前后置条件、工具版本、失败与恢复经验 | 版本化程序、技能检索、专属 head；LoRA 作为候选 |
| 连续状态与工作记忆 | 当前 belief、时间、状态估计、过期与重置条件 | 普通门控／SSM 与 Hepta 连续动态 Cell 对照 |
| 参数化规律 | 可重复利用的领域映射、压缩表示或读出规则 | Transformer／LoRA／在线神经记忆，保留证据与回退 |

类型化记忆与模型后端是两个维度。一个事实 Cell 可以同时维护显式记录、索引及参数缓存。数据库式 KV、kNN datastore 和 attention KV cache 也须区分：attention KV cache 绑定模型、前缀和位置，不能直接当作跨模型通用事实库。

共享 encoder 可以降低重复训练与驻留成本，但必须把 encoder／tokenizer 身份纳入索引、head、ridge 统计与校准版本。升级 encoder 后不能继续沿用旧向量并假定可比。多租户共享 encoder 不授予相互读取记忆的权限。

| 内容后端 | 适合检验的收益 | 不能省略的成本与限制 |
|---|---|---|
| 类型化 KV／检索 | 精确引用、纠错、删除、增量追加；语义检索支持改写 | 原始记录、索引、encoder、候选生成与 reader 均计费；精确 key 查找不等于语义覆盖 |
| 共享 encoder＋专属 head | 表示复用、轻量局部更新、同表示下可比较 | head 可能只学标签选择；共享表示遗忘、版本升级和共享骨干费用必须计入 |
| Centroid | 少量统计、简单更新与相似性分类 | 多模态类别和复杂边界可能失真；合并需要计数，时间衰减和删除需要可重算依据 |
| Ridge／线性读出 | 固定表示下凸优化、可解释充分统计、便宜的读取 | `d×d` 统计、求解与正则成本；高正确率也可能主要来自预训练 encoder |
| Transformer／LoRA | 表示调整、可迁移规律、无逐条检索的读出候选 | 学习并不保证事实精确、可追溯或可删除；底座、训练、optimizer、replay、版本与失效重训不能只算 adapter 字节 |
| 类型化多后端 Cell | 同一更新／权限／来源契约下，选择最合适的实现 | 类型是语义边界，不是自动提高智力的额外网络层；各后端必须竞争同一任务和预算 |

## 3. 与 MoE 的相同与不同

Switch Transformer 说明稀疏选择不同参数可以控制激活计算，同时仍有通信、训练和负载问题。[1] LEMoE 将 MoE adapter 用于持续编辑，说明 MoE 与记忆系统存在真实交集。[2]

| 维度 | 普通计算 MoE | 本文 Memory Cell／Meta Network |
|---|---|---|
| 专用性 | 专家学习不同输入区域的计算变换；不保证自动形成可解释类型 | 类型、来源及更新边界先明确，是否学习出有效专用性再验证 |
| 路由 | token／hidden state 选择稀疏专家 | 在当前有权限、来源有效、资源可用的 Cell 内检索与组合 |
| 共享状态 | 可共享主干与整体训练目标 | 可共享 encoder，但可变记忆、版本和 owner 必须明确 |
| 生命周期 | 一般随整体模型 checkpoint 发布 | 独立更新、撤销、冷恢复、迁移、split／merge 与当前指针切换 |
| 权限 | 神经路由本身不提供访问控制 | 授权先决定可访问集合，模型仅在该集合内评分，最终效果再次核权 |
| 扩容证据 | 参数总量、激活量与质量之间需实验验证 | 除质量外，还需覆盖、负迁移、完整成本、故障与迁移验证 |

因此，Cell 内部可以使用 MoE，Meta Network 也可以借用 MoE 路由方法；它们不能省去持久权威层。普通 MoE 的一个专家不天然等于一个可单独撤销、迁移、纠错的 Memory Cell。

## 4. 最新研究改变了什么判断

**Engram（2026）。** 以静态 N-gram lookup 和上下文门控，将 conditional memory 与 MoE 的 conditional computation 分开，在论文自己的设置下作同参数／同 FLOPs 对照。它支持研究“把可查找知识与每次重算分开”，但没有实现本项目的权限、事实纠错与 owner 迁移。其 100B 表 host-offload 测试使用 H800、512 sequences、主机 DRAM 与 PCIe，且 dense backbone 实验排除了 MoE expert-parallel 通信；最多约 2.8% 吞吐损失不能移植成手机／局域网 batch=1 的结果。[3]

**Doc-to-LoRA（ICML 2026）。** 训练超网络，将上下文一次前向映射为 adapter，可减少每篇文档重新优化和反复消费上下文的开销。超网络训练、加载、输入编码、生成 adapter 的存储与后续正确率都要计入。本项目尚未复现该方法，不能把它写为已取得压缩收益。[4]

**Understanding LoRA as Knowledge Memory（2026）。** 区分完美路由与实际路由，发现实际路由可能抵消模块化优势；增加合并模块也可能造成干扰。该研究支持拆开容量、路由与组合检查，不给任意参数平均提供“记忆求并”的语义。[5]

**Titans／MIRAS。** 前者以梯度、动量与衰减维护神经记忆；后者将结构、关联目标、保留约束和学习规则分开。这些是可测试的后端选择，不是免训练、免成本或已有磁盘持久性。内循环状态也是 checkpoint 的组成部分。[6–7]

**LongMemEval-V2（2026，Work in Progress）。** 将静态状态、动态状态、工作流、环境陷阱和前提识别列为长期记忆能力，并明确准确率与时延的权衡。可以借鉴任务结构，仍需冻结实际版本和来源，不能把工作中的预印本当作本项目长期产品验收。[8]

## 5. 如何分化、split、merge 与迁移

分化先由类型、数据更新频率、权限域、失效模式及成本驱动。语义聚类只是候选工具。只有整组网络在独立未来任务上有净收益，才提交新的拓扑；不能用每个子 Cell 的局部得分代替组合结果。

对相同 encoder、目标与权重规则的 ridge，保存去重数据的充分统计 `G=Σxxᵀ`、`H=Σxyᵀ` 后，可合并统计再解 `(G+λI)W=H`。这不是直接平均权重；若每份统计已包含 `λI`，合并时不可重复加正则。Centroid 合并需要有效样本数与相同时间窗口。删除或纠错要求正确撤回统计贡献，或从当前合法来源重建。Ridge 本身也是参数模型，不能把 ridge 胜过 LoRA 解释成所有参数记忆无用。

Split 必须保留来源 lineage、覆盖与权限不扩大约束，绑定整个父子计划。Merge 必须先解决重复记录、冲突、撤销及数值兼容；不同底座／tokenizer 的 LoRA 不能凭尺寸一致直接合并。被拒候选及其训练、验证和存储成本继续保留。

完整对象闭包应包括模型、记忆、索引、schema、encoder、tokenizer、路由、校准、运行配置及源记录身份。若声称可续训，还必须包含 optimizer、scheduler、RNG、sampler／data cursor、精度与 kernel 条件。可推理冷恢复、精确续训、owner 移交、权威灾难恢复是四项不同资格。

迁移前源 owner 被新代次冻结，目标核验并持久化完整闭包后报告 ready，最后由现有权威事务提交 owner 切换。丢 ACK 使用原 operation ID 查询，不能换 ID 重做。旧源恢复后，最终写入端必须依据当前 owner／epoch 拒绝旧请求。Chubby 的 sequencer 机制明确体现了接收端检查 generation 的必要性。[9]

模型回滚必须选择旧内容作为新的当前候选，并重新校验当前来源、撤销与权限。不能把安全前沿一同回滚，否则旧模型可能重新带回已撤销知识。单目录哈希链及签名无法证明自己不是完整旧副本；需要独立且不会同时回退的前沿或已验证复制权威。本轮 [整库回退隔离复现](evidence/authority-rollback-20261105/observation.json) 进一步证实：正常移交、撤销后被拒绝的同一签名 read／prepare，在完整旧快照及原 key 恢复后重新获准。该观察的 `guard_qualified=false`，不计入安全通过数。

## 6. Hepta Neuron 的受控研究位置

优先让连续动态、First-Passage／Reset、Belief、Continuation Q 与 NDU 决定何时读、等待、再次查证、更新或提出结构候选，内容路径保留可检验的明确记录。

First-Passage 是触发事件的概率模型，不是事实真实性或授权的证明。Reset 只重置定义明确的状态，不能无日志删除持久记忆。Call／Put 通道的互补关系须保留原事件定义；终点事件与路径首达事件不能混用。Belief／Q 的校准必须覆盖缺测、漂移与未知结果，NDU 要计入当前动作及后续维护成本。

在相同内容后端与执行器下，保留普通控制器／相同价值控制、解析控制器／解析加价值控制的 2×2；单独报告解析增量和价值控制增量。再固定控制器比较 KV、ridge、head 与 LoRA。这样才能区分收益来自内容表示、候选范围、路由、执行器或停止策略。

## 7. 相同输入、预算与完整成本

同预算应是实际约束向量：训练与推理 CPU/GPU 秒、峰值 RAM/VRAM、持久字节、网络字节、能耗、期限和候选搜索次数。使用同一个名称或训练 epoch 不建立可比性。先给出各方案在相同预算内的 Pareto 结果，再按冻结的效用与资源价格计算净收益。

`C(Q,U,T)=F+Qq+Uu+Ts+m+r`：固定成本 `F` 包含准备、训练、调参、失败候选和验证；`q` 包含编码、候选生成、路由、网络、执行与核权；`u` 是更新与旧能力回归；`s` 是原始来源、基座、索引、优化器、replay、版本、副本与日志；`m,r` 分别是迁移与恢复。父子阶段的包含关系需防止重复计费。

如果新方案读取成本并未降低，不能假设更多读取会摊薄出优势。若降低，仍需在真实有效生命周期内覆盖新增固定／维护成本。权限变化、数据更新和漂移可能使缓存或 adapter 提前失效。无法给出的能耗和网络测量应保持未知，不能填零；FLOPs 不等于物理焦耳。

冻结训练、校准、选择与最终任务；按独立来源簇计算区间，保留超时、OOM、拒答、不可用、失败恢复及取消的分母。不同 seed 重复同一批问题不增加独立样本数。新增持久账本约束实际执行次数，但不能证明来源时间、样本独立性或仪表真实性；这些仍须独立来源与测量支持。

## 8. 小设备获得大规模能力的必要条件

本机需要容纳 router、基础 encoder、活跃 Cell、缓存、运行时及恢复余量。访问必须足够稀疏，常见工作集需要足够本地命中；跨 Cell 推理、热点队列和网络尾时延不能吞掉收益。基础执行器必须有能力理解与组合检索证据，新增储存不自动修复推理缺陷。

任意独立新事实无法被小模型无损压缩到任意小的空间；有效压缩依赖数据规律、共享先验与允许的失真。把冷知识放到远端，是扩大系统可访问容量，远端存储、计算、网络和不可用成本仍存在。本机离线能力与依赖网络的系统能力应分别报告。

长期评价要覆盖新增、纠错、删除、否定、罕见类型、时效、跨 Cell 多跳、断网、重启、迁移及源不可用，报告最差时间窗和旧能力保持。关键切片负迁移或恢复资格失败，即使总体平均提高也拒绝晋级。

## 9. 真实模型结果及不能跨越的证据范围

本轮重新核验了 V14 的 10 个固定 Git blob；没有重训模型、重选 seed 或新增独立问题。下表来自原 96 个 semantic 请求；三列是 seed 17／29／43 在同一组问题上的结果，不能当作 288 个独立样本。持久字节是原实验记账口径，尚不是所有历史探索、副本与生产服务的总占用。[原审计结果](evidence/v14_audit.json)

| 方法 | 正确数／96（17、29、43） | 原记账持久字节 |
|---|---|---:|
| Lexical ridge | 81、81、81 | 722,940 |
| MiniLM ridge | 84、84、84 | 90,994,583 |
| BERT ridge | 62、62、62 | 18,067,913 |
| BERT linear head | 68、60、59 | 18,113,686 |
| BERT MLP head | 64、60、67 | 18,226,526 |
| BERT fast weights | 55、40、59 | 18,067,855 |
| BERT LoRA | 35、39、58 | 18,287,461 |

这些结果足以拒绝“参数更复杂必然更好”的说法，并保留原协议下三个预定神经候选在 15 个 seed×读取周期场景都未超过最佳已测基线的负面证据。它们不足以证明 LoRA 在所有记忆任务都无效，也不能用 MiniLM 对 BERT 的差异隔离参数化记忆的因果效果。BERT centroid／ridge／head 可以固定实际 encoder 表示进行局部比较；Q/V LoRA 则改变 encoder 的有效映射，只能称为相同预训练基座、不同表示适配方案，不能称为共享同一冻结 encoder。两类实验仍需新的独立任务与真正相同的总资源约束。

已知原记录 CPU 为 299.247398 秒、wall 为 199.960275605 秒，但历史探索、物理能耗、生产网络、云账单与完整长期维护没有测全。缺项保持未知。因此，目前没有“同预算、完整成本下 Meta Network 已获得正净收益”的合格结论。

为确认新类型比较没有改变这里引用的历史正确数，又对固定原始输出进行只读复算：4,032 个单步输出、504 个组合输出，Python 原判等与严格 JSON 类型判等的差异为 **0**。此项没有调用模型或执行器，不增加独立样本。[类型语义复核](evidence/integrated-20261105/historical-typed-audit.json)

## 10. 交付门槛及状态

冻结源码的联合运行在 2026-11-05 16:25–16:27 UTC 完成：普通模式 **150/150**、`-O` 模式 **150/150**、历史身份负例 **9/9**；重新核验原跨设备记录中的 **16 个签名对象**。当前 Python 源码运行前后未变；历史 `checks.*` 恢复为原字节，没有用新测试冒认旧设备源码。完整命令、原始日志、版本和有限验证进程成本见 [联合执行回执](evidence/integrated-20261105/run.json)。150 项是有限协议与控制的验证数量，不是模型基准分数。

另一次实际 x230 原生执行在修复后的标识边界上通过 **3 项 Rust 回归**，并与签名 Python／SQLite 参考的 **64 组、1,536 次转换和 64 次重置，共 1,600 行**一致；这是迁移转换子集，无新语言模型跨设备迁移。[原生回执](evidence/identifier-liveness-20261105/QUALIFICATION.json)

| 门槛 | 当前证据状态 | 要闭合的具体判据 |
|---|---|---|
| 非法标识导致 prepared 永久卡住 | 参考实现及原生转换子集已修复 | 相同 red／green、拒绝前无状态变更、合法提交与中止可达；生产适配层另行接线 |
| 类型混淆导致候选误批准 | 已修复，并保留原错误批准证据 | 真实 worker、完整 evaluator 和原正例同时通过 |
| 进程重启／改 ID 重复消费最终集 | 同一持久 owner 的包装入口已实现 | 同账本的竞争、崩溃、终态保留与完整候选冻结通过；新库／整库回退不在该保证内 |
| 候选覆盖、局部评分与路由可分辨 | 诊断器已实现；历史实测轨迹不足 | 新实测必须保留认证输入、候选、全部局部选择与实际路由，计入 shadow 成本 |
| 整个权威旧副本恢复后不复活旧权限 | **未闭合，已复现违反** | 独立不可同时回退的前沿／复制权威；相同旧签名在完整恢复后仍被最终效果端拒绝 |
| V15 owner／epoch 与现有生产 owner 边界端到端组合 | **未闭合** | 复用已有原生 runtime、最终使用复核和 Control 事务，接入 V15 身份、持久请求绑定、receipt、epoch fence；不是另开一份 Python 权威 |
| 真实语言模型完整跨设备迁移／续训 | **未闭合** | 真实模型与记忆闭包、optimizer／scheduler／RNG／sampler；冷进程恢复、旧 owner 拒绝、后续训练轨迹按预先声明容差匹配 |
| 长期保持、完整成本和正净收益 | **未闭合** | 冻结独立未来来源、共同预算和执行器；包括失败、未知、更新、恢复与全部资源成本的对照 |
| 当前提交远端必需 CI | 以具体 SHA 的执行结果为准 | 排队不是通过；旧源码的通过不能授予新源码资格 |

### 既有原生能力与准确接线位置

仓库已有 canonical Memory Cell owner、Agentd read-time revalidation、signed artifact selection、局部多 owner 路由和 TaskFlow image migration。本轮 V15 转换核尚未与这些路径组成跨物理节点、实际写端受当前 owner epoch 约束的完整生产协议。这里的“未闭合”不否定已有组件。

固定基线 `f88b826…` 的 [runtime](../../codex-rs/hepta-agentd/src/memory_cell_runtime.rs) 在读取后复核 publication 与 source owner；[config](../../codex-rs/hepta-agentd/src/config.rs) 有 `with_memory_cells` 显式依赖注入，但默认 `memory_cells: None`，同一 ref 的 [main](../../codex-rs/hepta-agentd/src/main.rs) 没有调用该组合入口。后续应在真实 startup 与 canonical typed-write 事务内接入经验证的依赖，不是仅在测试构造器中配置成功。

[V9 provider](../../codex-rs/hepta-agentd/src/memory_cell_migration_v9_transport.rs) 的构造与重连都只允许 loopback；跨物理主机需要另行验证的机密传输。已有 Unix control peer 的多 owner 组合也不代表独立物理故障域。不能删除 loopback 限制来获得“跨节点完成”。应复用现有 durable intent、目标去重、原 operation ID 查询和 TaskFlow 最终授权。

[AuthorityFrontierStore](../../codex-rs/hepta-contracts/src/authority_trust.rs) 与 [FinalUseAuthority](../../codex-rs/hepta-contracts/src/final_use.rs) 已提供独立 CAS 前沿接口；受保护的 open 路径在外部／本地状态不一致时拒绝。部署仍须证明具体前沿不会同本地权威一起回退，并覆盖实际 source／revocation／registry／owner 状态。只保护 final-use nonce 而让 CognitiveStore 来源库回退，不能达到完整记忆新鲜性要求。外部 CAS 前进但本地 fsync 失败时必须保持 fenced，经审计恢复，不可自动降级。

现有 V14 LoRA 记录只有参数与 AdamW，缺少独立 RNG／sampler 游标，无法事后补造精确续训资格。后续工程验收应先从可验证真实 checkpoint 开始，取得完整闭包的冷恢复资格；续训再保存 optimizer、scheduler、RNG、sampler／cursor 和数值 profile，并同不中断对照比较。只有冷恢复、owner 移交、续训分别通过之后，才进入独立未来任务的收益验收。

这些门槛不能通过增加测试数量、节点数量或改写状态字段全部置绿。整库回退已得到明确反例；其余系统与收益资格仍需对应的运行环境和实测证据。

## 参考文献

1. [Switch Transformers, JMLR 2022](https://www.jmlr.org/papers/v23/21-0998.html)。
2. [LEMoE, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.149/)。
3. [Conditional Memory via Scalable Lookup: Engram, 2026](https://arxiv.org/html/2601.07372v1)，尤其第 6.4 节。
4. [Doc-to-LoRA, ICML 2026](https://proceedings.mlr.press/v306/charakorn26a.html)。
5. [Understanding LoRA as Knowledge Memory, 2026-07-29 version](https://arxiv.org/html/2603.01097v5)。
6. [Titans: Learning to Memorize at Test Time](https://arxiv.org/html/2501.00663v1)。
7. [MIRAS](https://arxiv.org/html/2504.13173v1)。
8. [LongMemEval-V2, 2026, Work in Progress](https://arxiv.org/abs/2605.12493)。
9. [The Chubby lock service for loosely-coupled distributed systems, OSDI 2006](https://www.usenix.org/legacy/event/osdi06/tech/full_papers/burrows/burrows_html/index.html)。

## 本次原始首 prompt

> 全量冲请研究 Hepta Neuron 如何分化成不同类型的 Memory Cell，使小模型在单节点专门压缩、存储、检索并更新某类记忆，再通过 split/merge、跨节点路由和持久迁移组成 Meta Network；明确该方案与 MoE 的专家专用性、路由、共享状态和权限的相同与不同，以及小设备获得大规模能力的真正条件。比较共享 Encoder + 专属 Head、KV/retrieval、ridge/centroid、Transformer/LoRA 参数记忆、类型化记忆和候选覆盖/专家内评分/跨专家路由。
>
> 实现可回滚的模型及记忆版本、唯一 owner、跨节点身份与证据、故障恢复和负迁移拒绝；对相同输入记忆、同预算、同执行器与完整存储/推理/训练成本评估准确率、长期稳定性和净收益。不得因参数化记忆更复杂或 Meta Network 节点数增加就推断整体智能或产品收益已提升。全量冲剩余blocker，直到所有blocker全部闭合
