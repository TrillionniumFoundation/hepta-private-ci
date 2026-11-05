# Hepta Neuron、类型化 Memory Cell 与 Meta Network

日期：2026-11-05（America/New_York）。本文给出研究设计、工程契约与验收条件，衔接 V15 的有限协议实现；不新增模型实验，不改变历史实验结论。文中的“应当”“建议”和公式属于待验证设计，“已验证”仅用于下列固定来源实际覆盖的范围。

## 1. 结论与当前证据

Hepta Neuron 可以成为 Memory Cell 内部的状态更新器、读出器或价值控制器。Memory Cell 本身应定义为有类型、有来源、有独立更新边界的持久记忆服务：小模型学习某类信息的表示、压缩与访问规律，明确的记录和权威协议负责事实版本、权限、提交与恢复。Meta Network 则组合这些 Cell、目录、路由、执行器和迁移机制。

当前最有依据的路线是：先建立类型化 KV／retrieval 的可信读写链，使用冻结 Encoder 加 centroid、ridge 或专属 Head 作为强基线，再让 Transformer／LoRA／fast memory 在独立评价中竞争。对规律性强、重复读取多、更新较少的记忆，参数压缩可能值得；对频繁纠错的精确事实、长尾事件和访问边界，显式记录通常更容易核验。具体优劣仍须实测。

| 固定来源 | 已验证或已记录的范围 | 尚不能据此认定 |
|---|---|---|
| 历史 [V13 / #4532](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4532)，执行源码 `8ae2d91947203a868f880312df823004b7289f25` | 小型特征 Adapter 的真实训练；固定数值 profile 下三台 CI VM 的参数、Adam、RNG、sampler 完整状态续训，原 13 项严格检查通过 | 当前 V15 原生 owner 接线、不同数值 profile 下逐位一致、异构个人设备部署或全网经济收益 |
| [#4817](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4817)，证据归档 `379c21c2e625c3a3dfbb514e11b9e8fe2213cda8` | Python／SQLite 参考协议、53 项限定测试；Mac→pocket4 的持久保存、不同进程冷计算、签名 owner 交接 | 原生生产接入、权威整盘回退防护、真实语言模型跨设备迁移或收益 |
| [#4847](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4847)，候选 `4675d776489f1c1f2c832451e44fcd4bad3f583f` | 已保存的 57 项协议验证；Rust 五种迁移转换；Mac 与 x230 分别匹配 64 条状态序列中的 1,536 次操作及完整历史 | 全 V15 原生等价、密码学／持久事务适配、模型训练迁移或全仓 CI 通过 |
| [#4864](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4864)，`c8a8bdc5ef9ac060f2c6abf3dc7e561953f8b684` | 预先注册 cohort、训练／校准／选择／最终来源隔离、输入权限对齐与有限多次检验修正 | 持久实验注册服务、真实独立未来数据或完整成本测量 |
| 本轮合并与修复，见 [ADMISSION_HARDENING.md](ADMISSION_HARDENING.md) | 本地普通和 `-O` 各 93/93 项通过；8 项旧误批准反例全部拒绝，合格人工正例保留；独立 worker、成本身份和历史来源校验 | 新语言模型收益、实际完整成本或生产服务完整验收 |
| V14 固定证据及 V15 复算 | 原有 96 条语义请求：lexical ridge 为 81/96，MiniLM ridge 为 84/96，BERT LoRA 三个 seed 为 35/39/58；21 个结构候选被拒绝 | 严格总预算相等的胜负、长期稳定收益或新独立样本 |

原 [CI 41981272551](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41981272551) 的历史来源身份校验失败已保存。本轮修复把当时执行的源码归档与当前代码分别验证，不改写旧签名与成本，明确输出旧回执不构成当前设备代码资格。独立复核还验证：同时改归档与全部可改 metadata，仍不能通过固定 verifier 的 manifest 身份检查。新候选的远端 CI 状态单独记在本轮验收材料中；本地通过不等于远端通过。1,536 次相关状态转换也不是 1,536 个独立科学样本。[R1–R6]

本轮已推送 [草稿 PR #4885](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4885)。限定 [CI 42051127746](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42051127746) 绑定 `e455cfb761c8e41d8add94a7790e9d0e51fdff2d`；截至保存的 2026-11-05 15:19 UTC 状态仍在排队，没有已执行 job 或 artifact。因此本轮只报告实际取得的本地资格，远端新 CI／原生编译验收保持未完成，原运行未被取消。

V14 的三个 seed 重用了相同请求；不同 Encoder 的预训练知识与资源使用也不同。另一个事实绑定任务中 KV 的 192/192 与这里的语义任务不是同一个分母。既不能用其中一个结果贬低全部 KV，也不能把更强 Encoder 带来的收益全部归给 Memory Cell。现有结果尚未证明参数记忆、学习分裂或节点扩张带来稳定净收益。

这也不等于“参数没有学到记忆”。V14 事实任务的 LoRA 为 164/161/174 of 192，关闭 LoRA 而保留训练后的 Head 后降至 32/24/37；这一干预支持参数分支确实参与承载新绑定。与此同时，同任务 KV／BM25 为 192/192，所记录开销更低。组件具有真实学习作用、网络协议可以恢复，以及整体方案优于强对照，是三项分别取得证据的结论。[R7–R8]

## 2. Cell 如何分化：六类语义与共同契约

分化首先应发生在读写语义、有效时间和评价目标上，再决定模型结构。以下六类是工程上的初始分区，不是关于记忆的完备分类；每类可以按主体、项目、来源及权限进一步分片，不要求每类占用一台物理机器。

| 类型 | 必须保留的语义 | 初始权威表示 | 可学习部分与主要拒绝条件 |
|---|---|---|---|
| 实体与事实记忆 | 主体、属性、精确值、单位、有效时间、冲突和纠错来源 | 版本化 KV、关系记录、原始证据引用 | 实体解析和语义检索；错实体、错数值、旧版本必须拒绝 |
| 经历与事件记忆 | 事件顺序、当时状态、参与者、结果与因果证据 | 追加事件日志、时间索引及可追溯摘要 | 事件编码、摘要和重要性预测；摘要不能覆盖原事件或捏造因果 |
| 程序与技能记忆 | 输入输出类型、前后置条件、工具版本、成功与失败轨迹 | 版本化程序／技能库及执行回执 | Head、ridge、LoRA 学习选择与参数映射；未经授权的动作不能因评分高而执行 |
| 偏好与情境记忆 | 主体、适用情境、明确表达或推断、有效期和撤回 | 带来源的偏好记录与显式约束 | 学习软偏好和优先级；推断不能升级为用户硬约束，也不能改写权限 |
| 多模态与空间记忆 | 原始片段、时间对齐、身份锚点、空间关系与不确定性 | 文件／片段引用、类型化绑定及索引 | 模态专属 Encoder 与匹配；缺失原证据时不能把相似性当成身份一致 |
| 动态状态与工作记忆 | 当前任务、belief、缺测、预算、时间尺度、终止与恢复点 | 有界任务状态、滤波／SSM 状态和检查点 | Hepta 解析 Cell、遗忘和读取时机；活动 reset 不删除持久事实或撤销记录 |

共同记录至少包含 `namespace、cell_id、memory_type、entity/address、schema_version、source_revision、valid_time、recorded_time、provenance、policy_reference`。有效时间描述事实何时成立，记录时间描述系统何时获知，两者不能互相替代。例如“昨晚设备已离线”可以今天才写入，不能因此变成“今天才离线”。

同一 Cell 可同时保留原始记录、检索索引、学习到的摘要和参数读出。参数输出应携带可核验的证据引用；确实无法定位依据时，标记为模型预测，采用相应的拒答或再检索规则。类型化记忆是一层共同契约，和 KV、LoRA 等物理表示正交。

“单节点专用”不要求持续把所有记忆训练进模型。较稳妥的循环是：验证新事件→写入来源版本→更新低成本索引→提出 Head／参数更新候选→配对评价→发布新 bundle。未通过的候选保留诊断，服务仍使用最后一个合格版本。不得先覆盖现用参数，再把测试失败解释为暂时波动。

## 3. 表示后端的选择与真实成本

| 后端 | 适合解决的问题 | 必须纳入比较的代价与限制 |
|---|---|---|
| 共享 Encoder＋专属 Head | 统一表示上的类型内分类、评分、选择和字段预测 | Encoder 本身的存储与推理；共享表示不足；升级后的 Head、索引、校准器失配 |
| 精确 KV | 随机 ID、数值、配置、事实版本、纠错和删除 | 全部记录、历史、副本和索引；模糊查询需额外定位机制 |
| Retrieval／kNN／RAG | 文档、事件和长尾事实的可追溯访问 | embedding、索引、原文、rerank、上下文 token；漏召回与读取错误 |
| Centroid | 低成本粗路由、簇原型和拒识 | 多峰及少数模式被平均；计数和分簇状态；无法无损恢复任意事实 |
| Ridge／线性 Head | 固定表示下的稳定映射与评分 | 特征及充分统计量、正则选择；删样本和纠错的更新机制 |
| Transformer／LoRA | 稳定规则、语义模式、可复用技能及部分事实关联 | 完整基座、tokenizer、训练、优化器、replay、适配器冷加载、遗忘及干扰 |
| TTT／Titans 型 fast memory | 将序列经验压入可更新线性模型或 MLP 等状态 | 测试时更新算力、状态与 I/O；会话隔离、遗忘、持久恢复仍需额外实现 |

先冻结共享 Encoder，是为了使不同 Head 的比较清楚，也使回滚与索引复用可判断。若共享 Encoder 在多个私有域上训练，仅分离 Head 不能证明知识隔离。更新 Encoder 应产生新身份，同时验证旧任务保持、embedding 重建、Head 兼容与校准，不能只替换一份权重文件。

Ridge 可通过求解线性系统 `(XᵀX + λI)W = XᵀY` 获得，不需显式求逆。若保留增量统计量，状态量包含 `d² + do`，不只有最终权重的 `do`。Centroid 也需记录样本计数及必要的分布信息。纠错、删除和窗口过期时，要么能正确撤销对应统计贡献，要么从合法数据重建。Ridge 已经是参数模型，因此“ridge 胜 LoRA”不能推出“所有参数记忆无效”。

同一 Encoder、目标定义和正则条件下，两个 ridge Cell 可合并去重后的 `XᵀX、XᵀY` 再求解；若各自保存的矩阵已经含 `λI`，合并时不能把正则项重复相加。直接平均两组 ridge 权重通常不等于联合拟合。Centroid 合并同样需要按有效样本计数加权，并保留冲突和时间窗口规则。LoRA 参数平均没有普遍的“记忆集合求并”语义；split 复制父参数也不是把父知识无损切分。

数据库 KV 与 attention KV cache 必须分开：前者表示业务记录，后者是特定模型、层、位置和上下文计算的中间状态。Cache 复用需要绑定完整依赖与权限，不自带事实纠错、跨模型兼容和事务语义。

kNN-LM、RAG、RETRO 说明外部检索是有竞争力的记忆路径；RETRO 的较小参数量依赖外部数据库，不能漏算数据库后再称总系统很小。[L3–L5] LoRA 减少的是可训练增量，并不免除基座或保证任意事实准确记忆。[L6] TTT 把隐状态设为可学习模型，Titans／MIRAS 提供测试时更新与保留规则；这些工作没有给 Hepta 的持久 owner、权限和事务提供现成保证。[L7–L9]

2026 年的 Doc-to-LoRA 用超网络生成文档适配器，是减少每篇文档独立优化的候选方向。应将超网络训练、驻留、输入编码、适配器存储和实际回问质量一起记账，不能把“一次前向”理解为零训练成本。本报告未在 Hepta 上复现它。[L10]

## 4. 与 MoE：可借鉴的分工及不可混同的状态

| 维度 | 典型 token-level 稀疏 MoE | Memory Cell Meta Network 的要求 |
|---|---|---|
| 专家专用性 | 联合训练与 gate 形成的参数分工 | 显式类型、数据来源、更新规则及独立评价形成的服务范围 |
| 路由对象 | 每层、每个 token 的隐状态 | 查询、事实、时间范围、子任务或多步证据访问 |
| 共享状态 | 常共享 attention、embedding、残差流；普通推理权重通常固定 | 可共享只读基座；可变记忆、写入进度、权限和恢复前沿有明确 owner |
| 输出合并 | 在共同表示空间组合激活 | 合并有来源、版本和授权范围的结果，由固定执行器完成推理 |
| 更新与故障 | 训练／推理集群管理参数与通信 | 需处理持续写入、迁移、丢 ACK、崩溃和旧 writer 恢复 |
| 权限 | gate 的分数不表示读取或训练授权 | 召回、读取、训练、导出、迁移及最终使用都受当前授权约束 |
| 扩容收益 | 总参数增长与稀疏激活计算分开 | 网络容量、单次可访问容量、任务能力和总成本分开 |

Switch 与 Mixtral 支持条件计算，但普通 MoE 专家不是具有独立事实库与事务的服务。Mixtral 原文没有观察到明显的按主题专家分配，更多表现为语法和位置局部性；不能直接把某个专家解释成天然的“代码记忆”或“个人偏好记忆”。[L1–L2]

两种架构可以嵌套：Cell 内部可以使用 MoE，Meta Network 可以采用稀疏路由思想。判断关键是实际存储什么、谁能更新、输出怎样组合。把服务叫作“专家”不会赋予它长期记忆，把数据放到另一个节点也不会自动建立访问隔离。

## 5. 必须拆开的三种错误：覆盖、评分、路由

**候选覆盖**首先检查正确、当前且授权的证据能否进入预算内候选池。记录 Recall@k、所有必需证据同时覆盖率、过期候选率、授权域遗漏及错误域混入。跨事件问题可能需要四条证据，命中其中一条不能算完整覆盖。增加 k 带来的读取成本也应进入账本。

**专家内评分**在固定专家和候选池下测量：排序是否正确、能否识别旧版本与否定、输出是否校准、未知时能否拒答。使用同一候选集比较 centroid、ridge、Head、LoRA，才能判断差异来自评分还是召回。候选缺失时，不能仅靠更强的评分器宣称解决了问题。

**跨专家路由**在相同访问次数、token 和截止时间内选择正确 Cell 及组合。不同专家的 cosine、ridge score、局部 softmax 不是可直接比较的概率，应校准到共同目标，例如“本次调用在预算内返回足够且有效证据的概率”。类型、负载、来源变化以后，原校准不保证仍然成立。

如果一个成功路径必须先覆盖证据，再正确选择，最后正确读取组合，其成功概率可按条件概率分解；这里不需要假设误差独立。回退、直接参数回答等其他成功路径单独记账，不能把这个分解误当作完整系统的强制上界。Oracle 路由用于定位瓶颈，不能计入产品成绩。

《Understanding LoRA as Knowledge Memory》在自己的任务中区分完美路由与实际 embedding 路由，实际路由可能抵消多模块收益；参数合并也依赖具体策略。它支持把容量、路由与组合拆开测量，不能代替本项目的实测结论。[L11]

训练型 Router 只能在合法候选域中选择。读取请求还要在最终使用处重新验证来源、授权 epoch 和当前 bundle。校准良好的高分不能跳过权限；缓存的旧成功回执也不能当作新的授权。

## 6. 可回滚版本、唯一 owner 与证据身份

模型版本与记忆版本可以不同，但一次可执行发布必须固定它们的合法组合。建议 bundle 清单绑定模型／Head、记忆快照、Encoder、tokenizer、schema、索引、路由器、校准、运行时、来源依赖；继续训练还绑定 optimizer、RNG、sampler、步数及数值条件。逐个下载几个 `latest` 文件会产生未经验证的组合。

本轮检查到的 V14 LoRA 归档保存了参数与 AdamW 状态，却没有独立 RNG 状态和 sampler 游标。它可作为冷加载推理验证的候选材料，但不能证明精确续训恢复。后来补存这些状态，应从新检查点开展延续实验；不能把补存内容倒填为历史实验已经具备的条件。

这一缺口专指所检查的 V14 LoRA 归档。V13 的小型特征 Adapter 已有三 VM 完整状态续训证据，不能将其抹去；也不能把该旧模型、固定数值 profile 的结果转授给当前 V15 的原生服务或另一个 Transformer checkpoint。V13 首次逐位续训失败与第二次限定成功都应继续保留。[R7]

唯一 owner 表示：在权威目录的一个已提交版本中，每个 Cell 至多有一个被允许写入的主体。它允许多个只读副本，不意味着某个物理节点永远持有所有权。应区分用户／服务主体、节点凭证、进程 incarnation、Cell ID、owner generation 和 bundle digest；字符串主机名或 IP 不是独立身份凭证。

每个变更请求绑定稳定 operation ID、完整参数摘要、目标 authority、预期 owner generation 与前版本 CAS。相同请求重试返回同一历史结果，同 ID 不同字节拒绝。状态、去重记录和回执在同一持久事务中提交；“发出请求”与“实际提交”分别记录。外部效果还需要目的端去重或可对账机制，不能由本地日志推导任意外部动作恰好执行一次。

**模型回滚是使用旧合格参数发起一次新发布，owner generation、来源撤销和权限收窄继续单调前进。** 记忆纠错回滚应写新事件说明补偿关系，不覆盖已经确认的后续安全事实。整个数据库恢复到旧备份是另一个问题：若恢复把权威前沿也退回，旧 owner 可能再次被接受，必须依靠独立单调见证或合格的复制权威阻止。

单调计数器不能静默回绕。#4847 的修复针对 SQLite 饱和 INTEGER 转为 REAL 的实际夹具缺陷，并为 prepare 保留完成 commit／abort 所需的后继空间；它不是普通流量可在现实时间耗尽 `2^63` 次更新的主张，也不等于整盘回退已解决。[R3–R4]

证据需要分别说明来源源码、构建环境、二进制、输入、实际执行进程、终态、输出和回执摘要。历史实验继续绑定当时源码，新版本可以验证旧证据但不能把旧执行重命名为新执行。哈希证明字节身份，签名证明某主体认可相应内容，两者都不直接证明事实为真、模型更好或节点永久保存数据。参考实现的 Ed25519 身份也不等于 PQ 或硬件认证。

## 7. 迁移、split／merge 与故障恢复

第一版迁移应优先采用可核验的短暂停写，而非一开始追求无停顿切换。完整事务顺序如下；这些是生产接入要求，不能从当前无 I/O 的 Rust 转换内核推导已经满足。

| 阶段 | 必须完成的动作 | 失败后的处理 |
|---|---|---|
| Prepare | 当前 owner 认证、CAS，冻结写入，记录目标、bundle、迁移 ID 并推进代次 | 拒绝不完整前置条件；不能先复制后猜测当前版本 |
| Copy／Verify | 目标取得完整闭包、验证摘要和兼容性，持久保存并从新进程读回 | 保留未提交状态；损坏或缺少组件不能进入 ready |
| Ready | 目标签名绑定同一迁移及实际验证的 bundle，权威再次检查来源 | Ready 只表示本协议确认，不证明目标无限期诚实保管 |
| Commit | 同一权威事务切换 owner 与目录，持久化结果 | 丢 ACK 时查询原操作／迁移；不换 ID 重派 |
| Final use | 实际写入和效果接收端检查当前 owner、代次、权限与来源 | 旧进程即使复活也拒绝；历史成功不能授权新写入 |
| Abort／Recover | 未提交迁移以新代次解除冻结；丢失 owner 时由已授权恢复者接管 | 已提交后只允许新迁移；不重新启用旧代次 |

Chubby 的接收端代次检查提供了旧持有者 fencing 的重要设计依据。多个权威副本则需要已验证的共识、领导权及线性读语义；采用 Raft 的名称或库不代表这些接线自动正确。[L12–L13] 网络分区时不能让两侧独立授予 writer 而仍声称全局唯一；无法确认当前前沿时应拒绝需要当前授权的提交，并明确服务可用性损失。

Split 的最初输入是候选分区计划，不是自动创建更多节点。验证项包括地址覆盖、无意重叠、版本与删除标记保留、来源闭包、权限、复制成本及新路由。训练和评价新 Cell 时，原 Cell 继续作为稳定服务；最后通过一次权威目录事务退役父 Cell 并激活子 Cell。

Merge 先检查 schema、冲突规则、权限和共同执行接口，再决定是否重训或保留内部子分区。不同权限域的参数平均通常不能提供逐条访问过滤；不能因为 KV 合并可保留每行 ACL，就假设权重合并也能精确隔离。跨不兼容域的参数合并应拒绝，或保留独立模型和访问边界。

当前参考协议的同 scope／owner、精确地址分区、来源依赖保留和 ACL 交集是保守边界。交集不扩大权限，但可能降低合法服务覆盖，也要算入端到端损失。复制父参数给多个子 Cell 不证明来源已经分离；去掉 manifest 中的一条来源更不等于机器遗忘。需要来源独立化时，使用合法数据重建或另行取得可验证的遗忘证据。

整组 split／merge 必须由全计划评价器准入。每个子 Cell 单独合格，不能证明跨专家覆盖、组合推理和总成本合格。若计划净收益不足，保留原拓扑；被拒绝计划的训练、搜索和评估成本仍计入。

## 8. Hepta 解析 Cell 的合理职责

可把单元计算拆为 `h=Encoder(x)`、动态状态更新 `s'=F(s,h,Δt)`、记忆更新候选 `m'=U(m,h,a)`。First-Passage／Reset、Call／Put 双通道等解析结构应主要作为 `F` 或动作触发策略的候选，用来预测何时读取、刷新、压缩、整理、请求恢复或停止。Belief 和 continuation Q 估计当前不确定性及继续操作的价值，NDU 选择计入全成本的行动。

其中“高惊讶”“到达阈值”“预期价值高”都不是事实正确或有权执行的证据。遗忘门可以降低某些活动状态的权重，不能直接删除审计日志、撤销记录和用户仍要求保留的事实。模型建议与权威提交应保持明确边界。

研究应在相同记忆后端、输入、执行器和总预算下做 2×2：A 普通核心，B 普通核心＋价值控制，C 解析核心，D 解析核心＋价值控制。主要看 `D−B`，同时报告 `B−A、D−C、C−A` 与交互项。读取了更多原始信息、使用了更强 Encoder 或增加了搜索预算，都应单列为不同因素。

梯度与解析算子正确，是模型候选可研究的前提；完整任务收益需要另外证明。若普通控制器同样能选择正确记忆且更便宜，解析版本不应因结构复杂而晋级。TTT、Titans 和 MIRAS 为内部更新与保留策略提供可比较候选，也须遵循这套同信息、同预算评价。[L7–L9]

## 9. 小设备得到大规模能力的条件

应分别报告本地离线能力、网络可访问知识、网络可调用计算，以及实际复杂任务完成率。手机连接更多 Cell 可以扩大可达信息，但若 Router 找不到必要节点、执行器不会组合返回结果，或调用链超过时延预算，任务能力不会同步增长。

必要条件是：工作集足够稀疏；授权范围内的正确 Cell 可以廉价定位；活动基座、Head、上下文、缓存和恢复余量装得下；冷加载、通信和排队可控；远端结果可信且版本兼容；失联时有明确退化路径。跨节点逐层传激活与按任务调用 Cell 的通信形态不同，必须分别测量。Petals 展示了组合多方资源执行大模型的可行性，但依赖网络与其他设备的真实算力；官方说明也明确指出中间层 peer 可能恢复输入或改变输出，embedding 不是隐私保证。[L14–L15]

并行 fan-out 的墙钟受关键路径、慢节点及重试影响，CPU／GPU／能耗则汇总全部参与分支。共享对象在同一物理存储中只计一次，在每台设备各存一份时按副本计。不能用手机侧资源降低来掩盖全网总成本上升，也不能把联网能力称作本地离线能力。

压缩的前提是数据有可利用的结构、只保留任务充分信息，或允许受控失真。任意独立随机事实不能靠增加网络层数消除其信息量。保留原始证据用于纠错和恢复时，应将其计入全系统存储；较小 adapter 只能先说明活动表示较小。

## 10. 同信息、同预算、同执行器的评价

### 10.1 可比性与 Pareto 边界

相同输入记忆意味着相同来源字节、更新顺序、有效版本、允许工具、教师信息和查询时间，不能让某一臂额外看到答案所在 Cell、未来记录或隐藏标签。机制比较固定 Encoder／基座；产品比较可以允许不同模型，但必须明确不同预训练信息与资源，并分别报告。

相同预算指相同训练与搜索机会、CPU／GPU 时间、活动内存、持久存储、调用数、token 和截止时间上限。低成本基线无须故意耗尽预算。固定多个预算档，在各自可行域内展示准确率、p95 延迟、总资源和失败率的 Pareto 边界；某方法更准但更贵时，结论应保留这个权衡。

各臂使用同一版本和初态的执行器、同样权限与输出判定；有可变状态时采用隔离实例，防止先运行的实验泄漏记忆。超时、OOM、拒答、不可用和恢复失败保留在请求分母内；拒答是否正确依据任务标签判断，不能把安全拒绝统统算作业务成功。

本轮评估器用新解释器与私有工作目录执行每一臂，并在可信回调定义模块范围内按值保存宿主状态。两个不同 wrapper 共享 backing state 的 A/A 假增益已从 `1.0` 消除为 `0.0`。独立复核四个原反例通过，覆盖子进程累计 CPU 超限拒绝、启动后取消清理、模块配置快照和创建进程失败保留分母。CPU／地址空间实时限制仍为每进程；已回收子进程 CPU 在结束后累计检查。外部数据库、绝对路径、远端服务和其他导入依赖仍需独立控制，这不是敌手代码沙箱。

### 10.2 完整成本与 break-even

对方案 `j`，在冻结的查询量 `Q`、更新量 `U` 和保存周期 `T` 下记账：

\[
C_j(Q,U,T)=F_j+Qq_j+Uu_j+Ts_j+m_j+r_j.
\]

`F` 包含数据处理、模型准备、训练、调参、失败候选和验证；`q` 包含编码、检索、路由、网络、读取、执行和最终检查；`u` 包含索引／参数更新及旧任务回归；`s` 包含原始记录、基座、优化器、replay、索引、版本、副本与日志保存；`m、r` 分别覆盖迁移和故障恢复。能耗、账单、物理空间及冷加载不能漏掉。未测项记录未知，不补零；父进程总量与包含的子阶段不能重复加总。

在质量满足门槛且 `q_b>q_p` 时，参数方案 `p` 相对基线 `b` 的摊销阈值可由下式求得：

\[
Q_{be}=\frac{F_p-F_b+U(u_p-u_b)+T(s_p-s_b)+(m_p-m_b)+(r_p-r_b)}{q_b-q_p}.
\]

分子为正时它才表示需覆盖的额外固定／维护成本；分母非正时，不能用“读取越多越省”解释优势。需要在真实有效生命周期内达到阈值：若参数经常因数据更新或权限变更而失效，不能假设无限查询来摊薄训练。以上各项必须使用同一种成本单位；没有可信的效用换算时，保持多目标 Pareto 结果，不任意将准确率减去毫秒。

本轮修复要求实际预算上限和 worker 限额参与摘要；两臂写同一个名字不再算同预算。成本回执绑定数据、cohort、workload、完整协议信息和各臂的合法输入身份，空价格表及缺少资源计价说明不能取得经济批准。每个资源必须有测量，即使价格明确为零也不能缺测。worker 的 CPU／RSS 实测仅为全账本下界；回归夹具所用 `10 CPU 秒、128 MiB` 是明示人工值，不能被当成完整成本实测。

### 10.3 长期稳定与负迁移拒绝

更新序列应包含新增、纠错、矛盾来源、删除、过期、漂移、重复请求、冷重启、断连及迁移。报告新任务收益、旧事实保留、非目标能力、长尾与各类型表现、最差时间窗、校准、未服务请求和恢复时间。LongMemEval 的信息提取、跨会话／时间推理、知识更新和拒答维度可借鉴，但外部 benchmark 不能替代这些系统检查；采用时固定具体数据版本和摘要。[L16]

候选发布至少需满足：目标任务有预定增益或成本节省；关键旧任务非劣；权限、删除与恢复不变量通过；在冻结调用量及成本假设下净收益成立。对顺序更新持续检查旧编辑和普通能力，不能只验最新写入。已有研究在 ROME／MEMIT 的特定顺序编辑设置中观察到渐进和突发遗忘，支持这一检查需求；它不是所有参数记忆必然失败的定理。[L17]

统计单位按独立用户、实体或时间簇预先确定，同题多 seed 不增加独立题数。候选选择、超参调整和 split 搜索放在训练／验证阶段，最终评价使用未参与选择的隐藏或未来任务。反复查看同一留出集并挑最好拓扑需要额外控制选择偏差。置信界应覆盖配对差和多重比较；未来成本有不确定性时使用保守上界或单独区间，不把一次计时当作经济保证。

当前 cohort 逻辑检查来源隔离和预定 look 范围；本轮同时冻结实际执行的协议，阻止注册后把 `10,000 looks` 替换成 `1 look` 来放松置信界。它仍缺少跨进程持久实验账本。生产宿主须在分派前原子保留 `(experiment、registration、comparison、look)`，记录 `reserved／running／unknown／terminal`，丢 ACK 查询原操作，并阻止用新 registration 重复挑选已看过的 holdout。进程内冻结和摘要不能替代这些持久约束。

拒绝原因应区分覆盖不足、评分退化、路由失败、旧任务损伤、成本超限和证据不完整。安全机制通过不能替代质量通过，平均质量提高不能覆盖权限失败。恢复到上一版本后，还要核验当前来源与撤销前沿；失败候选的模型、索引或优化器状态不能残留为现用状态。

## 11. 下一实施阶段与明确关闭条件

| 阶段 | 可交付的具体结果 | 才能关闭的条件 |
|---|---|---|
| 当前候选身份与准入修复 | 合并两分支，分开绑定旧／新源码；绑定完整成本、隔离执行和冻结协议；普通／`-O` 本地各 93 项通过 | 后继候选的精确源码远端 CI 与下载证据核对；旧证据没有被改写为新运行 |
| 持久实验账本 | 唯一 authority 管理 experiment／look 的原子预留、unknown 与终态 | 重启、重派和新 registration 不能使同一最终数据被自适应挑选而冒充新样本 |
| 原生唯一 owner | Rust 转换接入实际认证、持久事务、去重及最终执行栅栏 | 同一候选完成正例、旧 owner／旧代次拒绝、丢 ACK 与崩溃恢复 |
| 权威灾难恢复 | 独立前沿或合格复制目录、备份恢复与分区协议 | 整盘回退、旧进程复活和网络分区不能产生第二个有效 writer |
| 真实模型多设备 | 完整模型／记忆／索引闭包，必要的 optimizer／RNG 续训状态 | 源不可用时冷取、装载、实际任务、更新、读回与故障恢复成立 |
| 公平基线与长期验证 | 固定 Encoder 的 retrieval／ridge／Head／LoRA，以及预注册长期负载 | 同预算 Pareto、关键切片非劣与完整成本结果可复核 |
| 学习型结构 | 固定、随机／负载分区及学习 split／merge 的受控比较 | 整组网络在独立未来任务有增量且可恢复；否则维持已有结构 |

原生协议、灾难恢复、模型效果、经济收益分别取得证据。直到后两项通过前，Memory Cell 和 Meta Network 应被描述为已部分实现、继续受测的架构，不以参数复杂度、节点数量、测试用例总数或文档完整度替代产品能力。

## 参考来源

### 仓库与固定证据

- **R1**：[V15 固定归档 README，379c21c2](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/379c21c2e625c3a3dfbb514e11b9e8fe2213cda8/qualification/memory-cell-v15/README.md)，对应 [#4817](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4817)。
- **R2**：[Mac→pocket4 有限生命周期验证](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/379c21c2e625c3a3dfbb514e11b9e8fe2213cda8/qualification/memory-cell-v15/device_qualification/README.md)。
- **R3**：[原生迁移转换增量，4675d776](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4675d776489f1c1f2c832451e44fcd4bad3f583f/qualification/memory-cell-v15/native-transfer/README.md)，对应 [#4847](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4847)。
- **R4**：[原生限定资格记录](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/4675d776489f1c1f2c832451e44fcd4bad3f583f/qualification/memory-cell-v15/evidence/native-transfer-20261105/QUALIFICATION.json)；[V14 固定证据复算](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/379c21c2e625c3a3dfbb514e11b9e8fe2213cda8/qualification/memory-cell-v15/evidence/v14_audit.json)。
- **R5**：[冻结 cohort 原始增量，c8a8bdc5](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c8a8bdc5ef9ac060f2c6abf3dc7e561953f8b684/qualification/memory-cell-v15/COHORT_REPRODUCE.md)。
- **R6**：[本轮实现、反例与复现说明](ADMISSION_HARDENING.md)；[同一 probe 的前后对照](evidence/cost-admission-20261105/README.md)；[准确源码验证材料](evidence/admission-hardening-20261105/)。
- **R7**：[V13 实际训练与三 VM 续训资格，#4532](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4532)；[保留的两次迁移结果](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/fb145d471406d9c68f7c5f501ef71f0379e76f9e/qualification/memory-cell-v13/MIGRATION_RESULTS.md)。本轮读取原记录，未重新执行其训练。
- **R8**：[V14 真实参数记忆、路由与结构结果，ae63a79e](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ae63a79ee3aafb1c9e1e042cac2c04921a7a897d/qualification/memory-cell-v14/README.md)。

### 原始论文与作者文档

- **L1**：Fedus et al., [Switch Transformers](https://jmlr.org/papers/v23/21-0998.html), JMLR 2022。
- **L2**：Jiang et al., [Mixtral of Experts](https://arxiv.org/html/2401.04088v1), 2024；架构与第 5 节路由分析。
- **L3**：Khandelwal et al., [Generalization through Memorization: Nearest Neighbor Language Models](https://arxiv.org/abs/1911.00172)。
- **L4**：Lewis et al., [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)。
- **L5**：Borgeaud et al., [Improving language models by retrieving from trillions of tokens](https://arxiv.org/abs/2112.04426)。
- **L6**：Hu et al., [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)。
- **L7**：Sun et al., [Learning to (Learn at Test Time): RNNs with Expressive Hidden States](https://proceedings.mlr.press/v267/sun25h.html), ICML 2025；[官方 PyTorch 实现及性能边界说明](https://github.com/test-time-training/ttt-lm-pytorch)。
- **L8**：Behrouz et al., [Titans: Learning to Memorize at Test Time](https://arxiv.org/abs/2501.00663)。
- **L9**：Behrouz et al., [It's All Connected: A Journey Through Test-Time Memorization, Attentional Bias, Retention, and Online Optimization](https://arxiv.org/abs/2504.13173)。
- **L10**：Charakorn et al., [Doc-to-LoRA: Learning to Instantly Internalize Contexts](https://proceedings.mlr.press/v306/charakorn26a.html), ICML 2026。
- **L11**：[Understanding LoRA as Knowledge Memory: An Empirical Analysis](https://arxiv.org/html/2603.01097v5), 2026-07-29 版本；多适配器、路由及合并的限定实验。
- **L12**：Burrows, [The Chubby lock service for loosely-coupled distributed systems](https://www.usenix.org/legacy/event/osdi06/tech/full_papers/burrows/burrows_html/), OSDI 2006。
- **L13**：Ongaro and Ousterhout, [In Search of an Understandable Consensus Algorithm, extended version](https://raft.github.io/raft.pdf)。
- **L14**：Borzunov et al., [Petals: Collaborative Inference and Fine-tuning of Large Models](https://arxiv.org/abs/2209.01188)。
- **L15**：[Petals 官方 Security, privacy, and AI safety 文档](https://github.com/bigscience-workshop/petals/wiki/Security,-privacy,-and-AI-safety)。
- **L16**：Wu et al., [LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory](https://arxiv.org/abs/2410.10813)；[作者维护的数据与评价代码](https://github.com/xiaowu0162/longmemeval)。
- **L17**：[Model Editing at Scale leads to Gradual and Catastrophic Forgetting](https://aclanthology.org/2024.findings-acl.902/), Findings ACL 2024。
