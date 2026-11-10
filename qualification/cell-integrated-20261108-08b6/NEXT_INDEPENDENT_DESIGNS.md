# MEM-1、VERIFY-1、NDU/CTRL-1、HCSN：下一次独立实验设计审阅稿

**状态：DRAFT_FOR_REVIEW。本文件不是预注册文件，不表示任何下一轮实验已经运行，也不授予集成或生产采用资格。**

这四项设计保留当前负面结果。已看过的材料只能用于诊断、工程准备和开发；不能把原确认集重命名成新的确认集。本轮 PRED-1 的独立冻结协议、执行补充和原归档源码另有身份，不属于这里的四项设计，也不因独立模拟研究完成而替代共同集成候选的验收。

优先保持 Cell 图、基础模型、任务执行器和终局检查器固定，每项只改变一个主要学习变量。结构变化、技能分裂合并、学习规则继承及改进器演化都留待一阶收益成立之后。这里列出的数据和执行负责人依赖是具体缺口，不是额外的用户批准流程；能基于现有仓库完成的只读准备和局部实现可以继续。

## 1. 从已有结果出发

| 研究 | 当前应保留的结论 | 下一项要回答的问题 | 已有可复用入口 |
|---|---|---|---|
| MEM-1 | 精确键 RAG 的检索优势保留；structured consolidation 在现有 retention 指标上劣于 uniform，不能称为语义记忆优势。 | 在跨文档关系、别名、状态修订和后续行动选择任务上，学习的结构化状态是否在同预算下提供增量？ | `FastMemoryV1`、native MEM-1 driver、owner-bound retrieval 与原 70-run 记账框架。[M1–M3] |
| VERIFY-1 | 真实模型 pilot 已执行；constant-prior / fixed-check 有相同接受结果，初始分数在每个臂内不区分 case；未建立校准或模型收益。 | 正确检查器、可校准风险分数、付费检查策略是否分别有效？模型是否降低了达到同等终局可靠性的真实成本？ | SQLite fault harness、host report/readback、MLX backend、trained readout、operation journal 和独立审计器。[V1–V3] |
| NDU/CTRL-1 | fixed-threshold hybrid 强；learned router 省计算却低效用；joint / mean MPC 在 96 对 case 一致；主矩阵不足以体现多动作取舍。 | 在真实执行任务中，新增观察、验证、修复、规划的成本能否由终局收益覆盖，学习路由是否超过强简单控制器？ | `scripts/ndu_ctrl1` 的目标 profile、收费、actor/router、CPU allowance 和完整尝试记录；目标定义保持原字节。[N1–N2] |
| HCSN | 18 次真实接口 fits 不是正式比较；容量不匹配、训练不足、开发窗口单类。正式比较 fits 仍为 0。 | 在一个实际不规则时间序列任务上，冻结物理的 HCSN 是否超过充分训练且公平匹配的普通时序模型和普通门控记忆？ | UCI localization 数据协议、真实模型适配器、数值资格、逐步 checkpoint/logit 审计及已写出的 formal recipe。[H1–H3] |

这些入口属于各自原实验源码。设计阶段可以复用实现；下一次执行必须绑定实际被运行的完整源码、依赖、配置、roster 和执行补充。多个现有 PR 的通过记录不能合并为一个已运行的新系统。

## 2. 四项共同的数据、成本和采用规则

### 2.1 数据与分割

每个任务有稳定的 `task_id`、原始来源、内容摘要、发生时间、派生关系、可见输入与 evaluator-only 标签。先按根来源分组，再切 train / development / calibration / confirmation；同一 issue、修复、事件、会话或序列的改写、窗口、重放和多个策略运行不能跨分割。给同一任务换 seed 不会产生一个新的真实任务。

现有报告、原确认记录、修复期间看过的失败以及本轮用于设计的样例，统一列入已暴露材料清单。它们可作为开发诊断，不能充作新的未见确认。预先冻结后续真实任务的入组规则，不能看到结果后筛选“确实需要记忆/验证/修复”的成功例子。确认由新来源组或新的前瞻任务流承担，任务不足时保持研究 pilot 身份。

各项目的真实任务 roster、可用独立来源组数量、实际预算与最小实用效应尚未完成盘点。本设计不填造样本数，也不把拟定配额当成已存在数据。正式冻结前必须把这些字段填成具体值；在开发材料上做预算/方差测量后确定样本量和阈值，记录探索成本。独立训练 seed、来源组、episode、事件、模型臂分别报告，不能互换分母。

### 2.2 成本与失败

每次工作保留计划身份和 `Started / Completed / Failed / TimedOut / Cancelled / NoCandidate / NoUpdate` 状态。测量的数据向量至少包含：数据与索引准备、编码、超参数搜索、训练、teacher/oracle 标签、在线推理/搜索、工具执行、验证、checkpoint、恢复、失败、审核，以及 CPU、wall、峰值内存和已知模型 token/forward 数。能测得的 GPU/能量/货币成本单列；缺测写明 `null` 和范围，不能记零。

相同资源上限不等于相同消费；相同 epoch 或 forward 请求数也不等于相同实际计算。吞吐和 p99 使用明确的冷启动/稳态范围。嵌套计时不能重复相加，静态缓存和共享预处理只有在部署中也能共享时才按预先规则摊销。

失败、超时、部分 epoch 和恢复进入全部尝试分母与成本。缺失最后完成记录是“工作量未完全可观测”，不能补造零成本。重试保留父 attempt；相同 seed 的确定性恢复不增加独立样本数，不能通过恢复选择更好 checkpoint。恢复后要核验实际来源资格、状态、优化器、RNG、ledger 和当前版本；重置必须作为重置报告。

先报告固定预算下的任务质量与真实成本前沿。当任务价值和资源价格已经由任务目标确定，才使用共同、预先声明的价格换算净收益：

`累计增益 = 后续任务价值增量 − 全部额外离线准备/学习成本 − 后续任务额外在线成本`。

不能把秒、tokens 或虚拟 credits 直接从无量纲成功率中相减。若没有可信的价值或价格，只能声称同预算质量提升或同等质量节省成本；在一组公开价格假设下的敏感性分析不等于已实现的经济收益。学习成本的摊销任务数也必须冻结，不能只挑足够长的任务流让成本看似回本。

### 2.3 科学结论与集成采用

独立研究可在真实工具、真实数据的隔离工作区完成，不要求先存在生产 Cell owner。研究 evaluator、数据保管和执行环境仍需具名并绑定实际实现。研究通过后，若要声称普通任务入口采用，必须另证候选选择、`NoUpdate`、实际 successor 消费、当前来源资格、失败恢复和回滚；本设计不把模拟 owner 或适配器当成生产接入。

## 3. MEM-NEXT：真实项目语义记忆与结构化状态

### 3.1 真实任务环境与数据形态

选择**真实仓库工作过程中跨多个任务延续的项目状态记忆**：问题约束、当前实现选择、变更原因、源代码版本、配置、证据出处、纠正/撤销以及之后任务的前提条件。使用实际 issue/任务描述、commit/diff、测试结果和工作记录的授权快照，不生成一套“看起来像用户历史”的虚构语料。

任务分为三个预先声明的面板：精确事实/来源检索；跨文档关系与别名消歧；经历修订后的当前状态与下一步行动前提。后两类必须由实际项目事实关系构成，例如哪个受测源码对应哪个配置、某项修复使哪条后续任务具备条件、一个旧决定是否已被后来证据替代。示例只是任务类型，不是已登记任务。答案要能引用当前有效来源；不能仅凭模型自述记忆得分。

对于真实后续执行任务，记忆输出交给完全相同的冻结任务执行器；终局结果由原测试/检查器核验。文本回答正确率与真实任务完成率分别报告，避免把“答对状态问题”当成“提高执行成功率”。当前收集到的 MEM/PRED/VERIFY 等审计材料已经被看过，只能作为开发来源。

### 3.2 学习变量与强对照

主要学习变量固定为**私有快速记忆状态及回放选择**；基础语言模型、encoder、RAG 可见候选集、prompt、任务执行器和 Cell 图固定。首轮不同时更新共享模型权重。

| 臂 | 作用 |
|---|---|
| RAG + exact-key/source-ID 通路 | 保留已有优势；精确事实 panel 不能因提出语义任务而被删除。 |
| RAG + 常规查询改写、时间/来源过滤 | 强语义检索基线；改写器与 learned arm 使用相同基础模型，成本全部入账。 |
| RAG + 明确的普通状态表/关系图更新 | 检查增量是否仅来自把事实结构化和正确处理修订，不能将规则图伪称学习优势。 |
| 相同底座 + 普通 recurrent/fast state，无 consolidation | 区分持续状态与额外回放的作用。 |
| 相同 fast memory + uniform consolidation | 已有强对照，保留同更新量、同 replay token/样本预算。 |
| 相同 fast memory + structured consolidation | 唯一主要候选。 |

stabilization 作为后续机制消融，不在第一轮同时更改 selector、学习率、encoder 和稳定规则。基线超参数在 development 上有相同选择机会；不以大量调过的候选对比未经配置的检索器。

### 3.3 先解决一个已有诊断缺口

在开发材料上做**回放覆盖度匹配**：原 structured 选择的独立来源覆盖少于 uniform，是一个候选解释，不是已确定原因。保持 replay 总次数、更新机会、时间窗和可用 source pool 不变，额外控制独立 source 数、重复上限与年龄分布。比较 uniform、原 structured、覆盖度匹配后的 structured，记录每次实际 replay 的原始来源和权重。此项只能解释旧负面机制，不能用旧确认指标选择新的最终算法。

冻结语义实验前，必须能说明最终结构化规则究竟改变了什么，并保留失败/不改善的开发候选。若覆盖度约束后仍不如 uniform，继续使用 uniform 或 `NoUpdate`，不把任务换成已知有利的确认子集。

### 3.4 仓库实现边界

可直接复用 `FastMemoryV1::{predict, update, checkpoint, restore, reset}` 和 native driver。原 driver 的固定符号特征不自动构成语义 encoder，需要真实共享 encoder、身份和输出校验。[M2]

已有 owner-bound 路径是 `CognitiveStore::lane_c_snapshot`、`observe_memory_retrieval`、`execute_owner_observation`、`revalidate_memory_candidates` 与 `revalidate_lane_c_snapshot`。最小接入保持 HNMF 的已选集合，只在相同集合内用 `FastMemoryV1::predict` 重排；不能用 fresh recall 的 `FastMemoryV1::rerank` 替换它而偷偷改变可见证据集。Replay 与 Recall 资格分开。[M3]

离线真实快照实验可以先实施；声称 live Agentd 使用则还缺真实 `CurrentMemoryRetrievalContext` 提供者、fast-state owner/写入 fencing、encoder、当前来源资格、恢复路径和实际调用方。当前审计只发现测试中的 provider 实现，不能把这些依赖写成已经满足。

### 3.5 主要指标、成本与冻结前缺口

主要候选指标为：同终局预算下后续真实任务完成率与来源支持的正确性；语义回答 panel 同时报 coverage、answered-error、修订/撤销错误及真实来源引用。保留 exact-key 面板作为退化监测。按项目/根任务来源聚类，另外按独立训练 seed 配对；不得用几千条 probe 冒充几千个独立用户或项目。

除共同账目外，必须单列索引/embedding、查询改写、状态字节、replay 选择、重复来源读取、训练、重建和撤销后恢复成本。预先定义候选可接受的精确检索退化上限及语义收益最小值，具体数值待真实开发 roster 与任务价值核实。

**冻结前仍缺：**真实来源 roster 与权限/来源说明、独立后续任务组、共享语义 encoder、结构化状态的确定字段与标签、真实任务执行器/独立 evaluator 绑定、覆盖度诊断及资源测量。下一项可实施改动是来源清单/分组构建器和 coverage-matched replay adapter；它们不需要先制造生产 owner。

## 4. VERIFY-NEXT：检查器、校准、策略收益分离

### 4.1 真实任务环境

选择隔离 checkout 中的**真实代码/配置修改与产物生成任务**：候选 patch、真实命令日志、目标约束与落盘产物均存在，最终由测试、schema、引用/摘要核对或任务特定 readback 判断。SQLite fault harness 保留作检查器单元和故障恢复验证；它不替代自然任务来源组。[V1–V3]

模型的公共输入应包含在当时确实可见、可能区分错误风险的证据，例如当前 diff、实际已完成测试及输出、目标约束、进度和剩余预算。原 pilot 初始输入主要为 tick/ACK，导致各 case 同观测；下一轮先做开发信息边界审计，保证模型没有未来标签泄漏，同时不能因为给它不可区分输入而把无排名能力误解成模型的普遍缺陷。

### 4.2 三个分别裁决的实验层

**A. 检查器正确性。** 冻结独立 outcome checker 与状态 readback，用已有合法/非法输入和实际故障机制做 positive/negative 测试；记录误接受、误拒绝、unknown 和重复 effect。checker 看到自己的检查输入，不应读取学习策略产生的“我已通过”自报。已知 mutation 测试只证明该检查器覆盖了这些故障；自然任务标签须按实际终局产物取得。

**B. 分数与校准。** 先锁定一个可检验事件，如“在此 snapshot 不增加可选修复的情况下，当前候选在指定终局检查会被拒绝”。从相同 snapshot 派生一个独立、不中断的标签面板；这条面板的继续执行和 outcome query 有真实成本。它与会改变结局的主动策略分开，避免把被策略修好的结果当成原风险标签，或只给存活轨迹评分。训练 readout 用 train，选择/校准规则用 development/calibration，确认只做一次固定分析。

**C. 策略选择收益。** 固定 A 的检查器，分别给各臂相同任务输入与实际资源上限。策略可选择廉价检查、昂贵检查、修复、延期/停止；必须依赖冻结的行动集合与真实收费。比较终局质量、coverage、预算违约和实际总成本，而非只比较检测提前几步。

### 4.3 强对照与学习变量

保留 `fixed_check` 和 `constant_prior`，并增加基于同一公共日志/任务类型的简单规则或小型 logistic 风险器。主要候选为现有冻结模型 feature 上训练的 readout，加在独立 calibration 材料上选择并冻结的映射；首轮不同时更换基础模型、加入新 prompt、改变 host checker 和调度策略。

现有 `MLXBackend`、`fit_heads`、`head_score`、`Pilot` 和 `Journal` 可复用，但新任务适配、可观测特征与标签面板必须实现并绑定新源码。需要在当前执行环境核对 MLX 设备和实际 pinned assets 是否可用；Mac 的既有执行 receipt 不说明 Linux host 已有同一后端。[V3]

共享底座不同角色、多个头和多个底座作为机制次要臂；它们的错误不能假定独立。必须保留原每个 voter 的预测、实际参数身份、共同错误及相关性。若 constant prior 在同预算下已达到相同正确率与检查时序，模型不得凭“确实执行了 forward”获得收益结论。

### 4.4 实际预算与指标

预算约束以实际时间、工具成本和模型计算为准。保留 request、实际 forward、输入 token evaluations、缓存命中、head fitting、校准、mandatory/optional checker 分别记账。两个 YES/NO 候选各需多少 teacher-forced forward 取决于实际 tokenizer；不能按“每臂一次请求”宣称成本相同。硬上限相同且不填充无用计算，比较实际消费及前沿。

A 报 checker 错误/unknown；B 报 Brier/log loss、实际 bin 分母、calibration slope/intercept 与 risk–coverage；C 报真实终局收益与错误接受/覆盖的共同分母。ECE 不是单独成功判据；单 bin、全同分数和全 abstain 必须显式暴露。早停策略对终局标签造成的删失按预先机制处理，不能删除漏检或未完成 case。

**冻结前仍缺：**自然任务 roster、独立 outcome checker 绑定、可观测 snapshot/不中断标签分支 adapter、已分割的 calibration 集、实际 backend/资产清单、真实时延/forward 成本标定，以及可接受错误率和覆盖下限的任务要求。可以先落地 snapshot→label-panel adapter 与 Journal 的实际预算核算，不必再跑同一 12-case 模板以增加“样本数”。

## 5. NDU-NEXT / CTRL-NEXT：继续、修复、验证、停止的真实取舍

### 5.1 环境与行动

采用隔离工作区中的**多步真实仓库修复/构建/产物验收任务**。具体自然任务从实际 backlog 或保留的历史故障中入组，必须具有终局可检验产物。控制器共享冻结的任务执行器、候选生成器和 verifier；首轮只学习快/慢计算路由或预算分配，固定 Cell 图和基础模型。

| 动作族 | 真实环境中的含义 |
|---|---|
| continue / execute | 执行下一段有界求解、候选修改或已有工具调用；付实际模型/工具费用。 |
| observe / recall | 读取当时可得日志、源文件或合格记忆；没有 evaluator-only 状态。 |
| verify | 执行某项真实测试/readback；检查有代价且信息粒度不同。 |
| repair | 根据已观察的故障修复候选或执行环境；重试、重建与回滚都计成本。 |
| stop | 成功提交通过终局条件的产物，或如实停止为 NoCandidate/未完成；停止不自动取得成功奖励。 |
| compute | 在相同行动集合上付费进行额外预测/规划，随后仍要保留执行预算。 |

故障注入可以验证超时、部分输出和恢复语义，但必须与自然故障结果分开报告。根任务从真实来源抽样；不能按确认中学习路由器是否获益筛选任务。现有隐 bit POMDP 和 3-action-horizon 矩阵保留作数学/代码回归，不作为新真实任务收益样本。[N1–N2]

### 5.2 先确认环境具有所需取舍

在训练/开发任务上核对：是否确实存在直接执行更好、先验证更好、修复后执行更好、直接停止更好的不同状态；有没有一种固定 `repair → execute` 策略几乎支配全部任务；新增规划是否会耗尽之后执行资源。此步骤是对任务环境的适用性诊断，不能通过重塑确认分布确保候选获胜。

若研究 joint vs mean，必须把“只改变联合依赖、保持相关边际相同”的开发对照与真实联合分布漂移分开。现有若干 confirmation case 同时改变了边际与相关方向，不能当作纯相关性因果测试。真实任务中的 outcome/latency/cost 联合预测还须有独立预测质量校验；已知完整模型上的 mean backup 对照不自动成为 learned predictor 比较。

### 5.3 强控制器与学习变量

第一轮主要对照为：原固定阈值 hybrid、development 上同等调参机会选定的简单阈值/成本规则、冻结 fast actor、固定调用额度的 bounded planner，以及 learned router。VOI、joint MPC、mean MPC 作为次要诊断保留。理论 oracle 只对能实际枚举的小分支子任务成立；在开放代码任务上不能把“试过的最好结果”命名为最优 oracle。

主要学习变量固定为 learned router 的付费调用决策。修正或明确 teacher continuation：训练 label 必须对应部署时将执行的 continuation 与未来收费规则；现有“一次慢调用后固定 fast”标签，不等于部署重复 learned routing 的完整 meta-Q。若继续用这种简化 target，要把它作为明确的方法定义并与部署全轨迹评价配对，不宣称精确策略改进。

`ndu_real_runtime/objective.py` 的已声明语义与 `hepta.ctrl1.resource-cost.v1` 收费边界保持独立且具名；新任务资源价格先在开发测量上定义。训练 adapter 更新参数，NDU 只供应值/advantage。信息增益、预测误差、熵或新奇度不能替代终局任务奖励。

### 5.4 成本和终局收益

保留现有 `budget_sensitivity.py` / `sensitivity_run.py` 的完整尝试与 CPU allowance 思路，接入真实任务 CPU/wall/forward/tool ledger。学习路由标签采集、teacher 搜索、没有改善的 rollout、失败候选、备用停止和恢复均收费；“节省慢调用次数”不等于正净收益。

主要分析是同预算下真实终局效用与质量，以及相对于最强简单控制器的配对增量；再显示把全部学习成本摊到预先冻结任务数后的收益。`stop_regret`、`compute_and_stop_regret`、`continuation_regret` 是局部诊断，不能相加冒充总 policy gap。对真实任务没有可证明 oracle 时，明确报告可识别的对照差异，而不是伪造 regret。

**冻结前仍缺：**任务 roster 与终局检查器、可重放工作区/动作 adapter、自然继续/修复/验证/停止任务覆盖证据、真实费用/时延单位、训练标签 continuation 与部署策略的确定关系、学习预算和未来摊销 horizon。最小可实现工作是给现有 router/evaluation 的行动接口接一个隔离真实工具环境，并以 fixed hybrid 与简单成本规则先跑 development；不需要先升级为完整随机 NDU 或组织演化。

## 6. HCSN-NEXT：先完成一个具体时序任务的公平比较

### 6.1 复用已有真实任务与披露历史

优先 UCI localization 的不规则时间事件分类，沿用已保留的官方数据摘要、原始整数时间、source row、subject、共享 25 维前端及官方模型接口。**不另造数据，也不再把 A01 前 128 / D01 前 64 的四步训练当成质量比较。**[H1–H3]

已有 formal recipe 的主体划分是 A/B/C 训练、D 开发/校准、E 评分，并规定先划 subject 再构造窗口。E 的原始记录已被用于 schema/clock/global-gap 元数据审计，0.2 秒 refractory 选择发生在这之后；后来的 ABC-only 审计不能擦除这段历史。E 尚未用于训练/调参/评分，但这不等于其输入分布完全未见。新报告必须保留这个限度；若要声称完全独立新主体/新采集条件泛化，还需另外取得并冻结当前不存在于这项已审材料中的数据。

### 6.2 收窄首轮科学问题

建议先做**冻结物理的 HCSN 是否在这一真实任务上有成本可接受的增量**，暂不学习漂移、扩散、边界、reset law，也不增加 maintenance/rollover。原 formal recipe 的完整消融仍然保留；这个收窄研究是新审阅稿，不能替代或宣称完成原完整协议。

核心强对照复用 GRU、官方 CfC、官方 recurrent PLIF、官方 S4D-Lin、causal Transformer，并加一个具名普通双门控 memory-bank 控制。最后观测/无时序的简单分类器用于显示任务是否实际需要记忆，不能替代强时序基线。S4D 按 S4D 报告，不能改名 Mamba。

至少把普通双门控与 HCSN 的 bank slots、content width、有效参数和实际状态字节说清。现有接口宽度固定且参数量相差很大，必须有容量可配置 constructor。有效 trainable 参数控制在既有 recipe 的 ±5%，不能以 dead/frozen/masked 权重填数；状态内存与实际计算另行报告，不因参数数目接近就声称完整成本公平。

### 6.3 训练与数值资格

复用已有 formal recipe 的候选训练方案：所有 A/B/C 来源事件、256-event 非重叠 episode、相同前端、相同种子的共享 window 顺序、真实 gap 保留；三 tuning seeds、每臂同 12 个学习率/decay/clipping 组合；最多 100 epoch，至少 30 epoch 后才按固定 patience 早停。S4 保留官方 optimizer 参数组；PLIF 记录 firing/tau、有限梯度和训练-only 多类 memorization，预算耗尽或静默神经元不构成 HCSN 获胜。

这些数值来自已有 specification，**不是已分配或已执行的预算**。六个核心臂已意味着 216 个 tuning fits 加 30 个 fresh-seed fits；加入普通 gate/control 会进一步增加成本。用真实 development 时间测量为全部尝试分配新预算，不能把历史 30-minute interface envelope 挪作正式研究额度。

现有 0.2 秒数值 receipt 只覆盖冻结物理与已测网格/窗口。完整 256-event 观测条件化 rollout 仍需数值资格：质量守恒、有限概率、梯度、边界/尾部/步长敏感性和真实数据 gap，全都使用实际将训练/评分的路径。不能把有限个 prior/window 通过外推为任意 posterior/full-domain 证书。

### 6.4 分数、机制与成本

主要评分采用完整 E 的宏 F1，并同时保留 accuracy、balanced accuracy、NLL/Brier、校准、逐序列和逐独立训练 seed 结果。temperature 只在 D 上拟合；评分后不能回调参数。模型 seed 是独立训练重复，event/window 不是；一个 held-out subject 限制总体泛化，序列聚类不消除这一限制。

如果冻结 HCSN 没有超过最佳充分训练基线，就停止扩张。若有改善，才用真实剪枝的物理读出移除与普通门控消融定位原因。content-only 必须从 likelihood、write gate、proposal、inter-layer messages 和 final readout 移除所有直接物理读出；保留概率加权内容运输和删除运输是两个不同对照。单纯把列置零留下无效权重不能支撑容量公平。独立 generators、mean-state、maintenance/rollover 没有真实动力学实现时应保持“未实现”，不能填写 on/off 结果。

必须分别测量 table build、数值资格、tuning、训练、数据/前端、calibration、推理、checkpoint、失败、迁移/恢复；另报 persistent state、peak RSS/VRAM、稳态吞吐、p99 及已测能量。CPU 运行不能填出“GPU 峰值为 0”的测量结果；无法测得的能量/VRAM 保留缺测。

**冻结前仍缺：**全上下文数值 profile、可调容量的官方适配器与正式 trainer、足够训练/收敛证明、普通双门控实现、明确读出消融、逐臂与全研究实际资源额度，以及对 E 元数据暴露后的声明范围。此线已有真实数据路径，先补上述实现和 development 计时最具体；当前 `run_interface.py` 只会执行旧的有界接口研究，不能把它当正式 trainer 使用。

## 7. 可直接转成实现任务的顺序

| 顺序 | 实作项 | 完成时应交付的实际证据 | 本设计仍不会授予的结论 |
|---|---|---|---|
| 1 | 共用真实任务/source-group 清单、派生关系、可见输入/隐藏标签、全部尝试 ledger | 真实来源条目及 SHA、分组冲突检查、明确已暴露材料清单；不生成虚构任务补数量 | 独立确认已完成 |
| 2 | MEM coverage-matched replay 与共享语义输入 adapter | 实际 replay 来源/重复覆盖、同消费对照、开发结果；encoder 身份与真实输入出处 | 结构化记忆已优于强 RAG |
| 3 | VERIFY snapshot→独立不中断标签 panel 与实际 forward/工具预算 | checker/评分/策略三个分母、可观测边界、实测成本 | 仅凭 pilot ECE 或零错误建立校准 |
| 4 | NDU 固定 hybrid 与简单成本控制在真实工具 adapter 上的 development | 实际继续/修复/验证/停止分布，终局 readback 与完整费用 | 新增计算已由终局收益覆盖 |
| 5 | HCSN 容量 constructor、完整窗口 trainer、冻结物理数值范围与普通 gate | 实际参数/状态数、训练曲线/PLIF adequacy、逐路径数值测试、真实耗时预算 | 当前 18 interface fits 是正式比较 |
| 6 | 各自完成方案冻结后，一次独立确认 | 源码、模型、roster、seed、阈值、预算、原始 attempt 和全部成本共同身份 | 自动集成、生产采用或组织演化 |

正式注册文件应包含：唯一主比较、最小实用效应、退化/错误接受界限、真实任务来源组数、独立训练重复数、固定选择规则、完整算力/费用预算、失败与恢复规则、标签/evaluator 绑定、确认不可见边界及最终源码身份。本文件故意将尚无证据支撑的数量和依赖保留为未冻结，而不是用模板数字伪造可执行性。

## 8. 依据与复用入口

以下是本次设计实际读取的本地证据与源码入口。路径是观察位置，源码复用仍需在新候选中重新固定完整身份。

- **[M1]** `/workspace/scratch/eb987333a9b4/memory-cell/code/qualification/memory-cell-mem1/RESULTS.md`、`PROTOCOL.md`：现有结果、七臂/成本/来源规则。
- **[M2]** `/workspace/scratch/eb987333a9b4/memory-cell/code/codex-rs/hepta-memory-retrieval/src/fast_memory.rs` 与 `examples/mem1_fast_memory.rs`：实际 Rust 状态 API 与符号 reference driver。
- **[M3]** `/workspace/scratch/eb987333a9b4/memory-cell/code/qualification/memory-cell-mem1/OWNER_INTEGRATION.md`：实际 owner APIs、既有 caller 和缺失 provider。
- **[V1]** `/workspace/scratch/c2de2179a824/evidence/verify1-live/CURRENT.json`：后续独立审计，scientific admission 仍 HOLD。
- **[V2]** `/workspace/scratch/771b9cd4d8d5/qualification/verify1-model-20261108/RESULT_SUMMARY.md`：108 个实际 policy trajectories、24 个 panel、652 forwards，以及校准/预算/分母限制。
- **[V3]** `/workspace/scratch/771b9cd4d8d5/model-formatted-v2/source/experiments/verification_cell_verify1/`：`model_backend.py`、`model_heads.py`、`model_policy.py`、`model_protocol.py`、`model_audit.py`、`model_runner.py`；格式化实现与实际旧运行源码的身份分开。
- **[N1]** `/workspace/scratch/839e1cbe28dd/hepta-private-ci/qualification/ctrl1-decision-cell-20261108/README.md`：原件、重复运行身份、负面结果和真实任务缺口。
- **[N2]** `/workspace/scratch/839e1cbe28dd/hepta-private-ci/scripts/ndu_ctrl1/README.md`，以及 `model.py`、`policies.py`、`routing.py`、`learning.py`、`evaluation.py`、`budget_sensitivity.py`、`sensitivity_run.py`、`verify.py`：可复用的有限环境与记账实现。
- **[H1]** `/workspace/scratch/6baff5d9b610/reporting_candidate/qualification/hcsn_differentiable/CURRENT.md`：当前已执行资格、18 fits/72 updates、528 审计检查、E 元数据历史与正式比较为零。
- **[H2]** `/workspace/scratch/6baff5d9b610/followup_candidate/proposals/localization-v2/PROTOCOL.md`：实际接口命令、数值/容量/正式 runner 缺口。
- **[H3]** `/workspace/scratch/6baff5d9b610/followup_candidate/proposals/localization-v2/formal_protocol.json`：已有 `specified_not_admitted_not_started` recipe。本工作区的 `reporting_candidate` 是局部报告快照，所需 proposal 文件实际在上述 `followup_candidate`；不能误把不存在的 reporting 路径写作可运行入口。
