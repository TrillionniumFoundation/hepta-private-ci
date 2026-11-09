# M6：五项下一实验完整审阅稿（新整理副本）

**DRAFT_FOR_REVIEW；confirmation_admitted=false。** 本稿没有启动新训练、生成确认任务、打开 PRED 确认材料或发出生产采用／NoUpdate 回执。五项研究分别作出结论；它们共享同一套成本和隔离约束，不拼成一个已获证的“全能学习系统”。

## 1. 文件身份、现有结果与固定图

这是一份**新整理稿，不是旧 NEXT_EXPERIMENTS_M6 两文件的原字节恢复**。旧 JSON 16,286 bytes，SHA256 `391a6c3e639123ee78e45c3f42365229028081c1c044bca7f379c7e941791654`；旧中文稿 16,038 bytes，SHA256 `016087f6444cff881be82ebc1dba22b2c7884075ae2707a5f8be48ce1b2d34d9`。原文在本轮汇总前确实已读取；随后 Cloud scratch 失联。root033 已封包未找到两名，functions 保留的 a51/M3/M4/M5 上传 payload、M6 worker payload 与 M6 原始 109 成员 manifest 也未包含它们。旧 pins 保留，不能对本稿套用旧 SHA。详细恢复范围和局限见同目录 NEXT_EXPERIMENTS_M6_REVIEW_COPY_RECOVERY.json。

本稿以当前已提交的完整设计文稿、实际 M6 开发回执和重新取到的 HCSN 原规格为依据，补齐五条研究的可审步骤、对照、分析与拒绝条件。M6 源码为 `885dae0f3285267e9e9c49d8b43b0d009779f9e8`，tree `293ece7ffdffa2332ccfdec4fbbc4b7dcb3363cb`；这里绑定的是设计可复用源码，不代表全部未来 trainer/环境已经存在。

固定 Cell 图采用三个角色：Memory 只接收当时可见的合法来源，返回同候选集的引用与状态；Decision 根据同一信息、候选动作和剩余预算选择下一动作；Verifier 执行固定检查并记录实际结果。日志与计费由旁路记录器观察，隐藏终局标签只供独立 evaluator 使用。首轮不改变 Cell 数量、连边、基础模型、工具语义或终局检查器；不同时做组织演化、学习规则继承和改进器更新。

M6 MDV 已实际执行两个已曝光开发任务、一个 R/S 故障家族、一次私有状态更新；第二个进程确实消费状态与原回执。驱动是 M6，真实任务仍为历史 R→S Clippy 修复和 S UI 33 项；这 33 项不计为 M6 UI。排序与选中文档未变，完整基线终局臂未执行，独立确认任务为 0。结论仍是 HOLD／production_not_adopted；私有 marker 是 not_requested，正式 adoption receipt 为 null。此开发链证明有实际状态消费，不证明语义记忆或终局收益。

### 1.1 可复用开发入口与不得外推的部分

M6 已有 `scripts/cell_repo_mdv/{contracts,memory,runner}.py`、训练 source/budget admission、bounded subprocess supervisor、实际 stdout/stderr、成本与 checkpoint/receipt 绑定。现有 MDV 是有界词法状态和已授权 recipe 执行器；它还没有合格共享语义 encoder、真实独立 roster 或全基线执行矩阵。下面是既有开发接口的真实参数形式，路径必须来自登记输入；本稿没有执行它们：

```bash
PYTHONPATH="$M6_SOURCE/scripts" "$PINNED_PYTHON" -B -m cell_repo_mdv.runner \
  --task "$REGISTERED_TASK_1" --corpus "$SHARED_CORPUS" --output "$NEW_TASK_1_OUTPUT"

PYTHONPATH="$M6_SOURCE/scripts" "$PINNED_PYTHON" -B -m cell_repo_mdv.runner \
  --task "$REGISTERED_TASK_2" --corpus "$SHARED_CORPUS" \
  --state "$NEW_TASK_1_OUTPUT/state.json" \
  --state-receipt "$NEW_TASK_1_OUTPUT/result.json" --output "$NEW_TASK_2_OUTPUT"
```

输出目录须全新。Task2 的 manifest 必须是正确绝对路径；不得把原先相对 manifest 的失败和恢复抹掉。M6 使用预热自有 target，CPU quota 200%、内存上限 8 GiB；这些是已执行开发链的 profile，不自动成为未来五项研究预算。普通生产入口的授权 owner/bootstrap 与独立评价、采用、NextUse 装配仍另缺；研究工具不能自签正式回执。

### 1.2 真实任务的前瞻选择与独立保管

可用来源是获授权仓库中的实际 issue／任务、commit/diff、CI 故障、工具结果与后继工作。已读的 R/S、先前 CI 修复和本轮审计材料全部归开发。未来确认须先冻结时间截点、仓库和来源范围、去重根键、连续入组顺序、排除规则及样本量，再由不参与调参的保管者保存未曝光快照和标签。

资格规则只用入组时已知事实：有真实任务目的、可归档输入、隔离执行权限、实际终局检查器、可计量预算；不能按候选结果或修复难度事后挑样本。相同根 issue 的多次 CI、patch、改写或重放只能形成同一来源组，不能跨 train/dev/holdout。若候选来源已经被开发者阅读或用于调试，立即记为 exposed/dev，不能事后重命名 blind。无真实独立输入或 custody 未到位时保持 HOLD，不能用自编任务生成器补确认分母。

## 2. 五项共同的数据、成本和采用规则

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

## 4. PRED-1：保留两次 HOLD，仅做训练／开发诊断

### 4.1 固定结论与数据边界

原 PRED-1 的 HOLD 保留；此前另行冻结、在原归档源码上完成的 16 个 fresh seed／114 fit 确认也保持 simulation_gain_not_established／HOLD。114 包括 18 个家族选择 fits 与 96 个 fresh fits；16 是配对确认 seed 分母，不能把 fits、steps 或数据 presentations 当成 114 个独立结果。模拟净效用差不是成功率百分点，也不是当前 M6 的生产收益。

两次确认已被使用：不读取其标签／预测作设计，不据其结果调整模型、阈值、seed、样本选择或早停，不删除“大正 seed”，不重跑以取更好 p 值。本稿不另准入第三次确认。本轮 M6 Python 中 14 个 PRED 诊断控制只是既有合成／输入防泄漏单测，不是确认样本。

可用诊断输入限既有 input-only 归档中的 **48 个 training JSON、原 registered config 和原 run.py**；读取配置和 runner 是核对实际 train/dev 工作口径，绝不执行原 runner 的确认阶段。禁止从完整 campaign 便利地 glob 所有 JSON；建立显式允许清单并记录 SHA。诊断输出须全新目录，原 FREEZE、guard、旧诊断与确认结果不覆盖。

### 4.2 seed 202 的具体诊断与对照

按相同模型家族、recipe、预算和数据定义，在 training/dev 上比较 seed 202 与其余原 seed；保留全部原始成员，不把 seed 202 从汇总中删掉。核对实际初始化与源代码接线、train loss／dev NLL 曲线、最佳开发 checkpoint 与最终 checkpoint、实际 optimizer steps、training presentations、早停触发、非有限值、失败和恢复。检查“计划 steps”与真实循环消费是否不同，并区分选中 checkpoint steps 与训练过程中已消耗的全部 steps。

诊断臂是既有同 recipe 的 seed 分层统计、按家族／recipe 条件化的全 seed 汇总，以及原配置静态审计；不借新确认结果增加一个更有利的模型臂。最小输出为逐 fit 来源/配置/源 SHA、曲线摘要、成本、消费与选中点差异、seed 条件化比较和原始输入 manifest。若某份训练记录缺失或 schema/身份不匹配，报 incomplete/HOLD，不用确认文件补齐。

这只能形成开发解释或待证假设；训练收敛差不自动证明 seed 202 是旧确认负面结果的因果来源。开发上若需新增消融，应先另记源、输入和预算并保留全部失败；任何新方案冻结之前都不能查看确认结果选择它。两枚较大正 seed 的描述不是事后排除理由。

### 4.3 现有只读入口与成本

M6 已有 `scripts/hepta_pred1/diagnose_training.py`；源码参数已核为：

```bash
"$PINNED_PYTHON" -B "$M6_SOURCE/scripts/hepta_pred1/diagnose_training.py" \
  --campaign "$TRAINING_ONLY_CAMPAIGN" \
  --config "$ORIGINAL_REGISTERED_CONFIG" \
  --source "$ORIGINAL_RUN_PY" \
  --output "$NEW_DIAGNOSTIC_OUTPUT"
```

这里 `--source` 是归档 runner 源文件，只读静态审计，不是运行器命令。输出 DIAGNOSTIC.json 和 RESULTS.zh-CN.md；记录诊断实现 SHA。现有 bounded read 拒绝 symlink／非普通文件，使用有界读取；不得以测试样例替代 48 份真实训练记录完整性检查。

预算分开记输入读取/解析、静态 source audit、曲线统计、报告与新增开发消融。既有训练费用仅引用旧完整账本，不重复记成本为零，也不把已完成 114 fits 再算成本轮实际消费。当前诊断若仅作元数据只读分析，则新增 model training fits=0；若未来选择开展新的 train/dev 消融，先单独冻结 all-attempt 数值上限，不能把元数据分析预算当训练授权额度。

### 4.4 判据、停止与未冻结项

诊断的完成判据是允许输入完整、每条记录身份可追溯、实际消费与成本口径一致、seed 202 与其他 seed 的比较可复核；它没有“p<阈值就推翻 HOLD”的科学判据。遇到 confirmation 文件、身份不符、缺必要 train/dev 字段、未知恢复或越预算即停止并保留已花成本。未来独立研究还需新的、未使用的确认材料及保管安排、完整数值预算、主比较/最小实用效应/停止规则与独立执行规格；这些均为 null/未准入，现有两次确认不得复用。

## 5. VERIFY-NEXT：检查器、校准、策略收益分离

### 5.1 真实任务环境

选择隔离 checkout 中的**真实代码/配置修改与产物生成任务**：候选 patch、真实命令日志、目标约束与落盘产物均存在，最终由测试、schema、引用/摘要核对或任务特定 readback 判断。SQLite fault harness 保留作检查器单元和故障恢复验证；它不替代自然任务来源组。[V1–V3]

模型的公共输入应包含在当时确实可见、可能区分错误风险的证据，例如当前 diff、实际已完成测试及输出、目标约束、进度和剩余预算。原 pilot 初始输入主要为 tick/ACK，导致各 case 同观测；下一轮先做开发信息边界审计，保证模型没有未来标签泄漏，同时不能因为给它不可区分输入而把无排名能力误解成模型的普遍缺陷。

### 5.2 三个分别裁决的实验层

**A. 检查器正确性。** 冻结独立 outcome checker 与状态 readback，用已有合法/非法输入和实际故障机制做 positive/negative 测试；记录误接受、误拒绝、unknown 和重复 effect。checker 看到自己的检查输入，不应读取学习策略产生的“我已通过”自报。已知 mutation 测试只证明该检查器覆盖了这些故障；自然任务标签须按实际终局产物取得。

**B. 分数与校准。** 先锁定一个可检验事件，如“在此 snapshot 不增加可选修复的情况下，当前候选在指定终局检查会被拒绝”。从相同 snapshot 派生一个独立、不中断的标签面板；这条面板的继续执行和 outcome query 有真实成本。它与会改变结局的主动策略分开，避免把被策略修好的结果当成原风险标签，或只给存活轨迹评分。训练 readout 用 train，选择/校准规则用 development/calibration，确认只做一次固定分析。

**C. 策略选择收益。** 固定 A 的检查器，分别给各臂相同任务输入与实际资源上限。策略可选择廉价检查、昂贵检查、修复、延期/停止；必须依赖冻结的行动集合与真实收费。比较终局质量、coverage、预算违约和实际总成本，而非只比较检测提前几步。

### 5.3 强对照与学习变量

保留 `fixed_check` 和 `constant_prior`，并增加基于同一公共日志/任务类型的简单规则或小型 logistic 风险器。主要候选为现有冻结模型 feature 上训练的 readout，加在独立 calibration 材料上选择并冻结的映射；首轮不同时更换基础模型、加入新 prompt、改变 host checker 和调度策略。

现有 `MLXBackend`、`fit_heads`、`head_score`、`Pilot` 和 `Journal` 可复用，但新任务适配、可观测特征与标签面板必须实现并绑定新源码。需要在当前执行环境核对 MLX 设备和实际 pinned assets 是否可用；Mac 的既有执行 receipt 不说明 Linux host 已有同一后端。[V3]

共享底座不同角色、多个头和多个底座作为机制次要臂；它们的错误不能假定独立。必须保留原每个 voter 的预测、实际参数身份、共同错误及相关性。若 constant prior 在同预算下已达到相同正确率与检查时序，模型不得凭“确实执行了 forward”获得收益结论。

### 5.4 实际预算与指标

预算约束以实际时间、工具成本和模型计算为准。保留 request、实际 forward、输入 token evaluations、缓存命中、head fitting、校准、mandatory/optional checker 分别记账。两个 YES/NO 候选各需多少 teacher-forced forward 取决于实际 tokenizer；不能按“每臂一次请求”宣称成本相同。硬上限相同且不填充无用计算，比较实际消费及前沿。

A 报 checker 错误/unknown；B 报 Brier/log loss、实际 bin 分母、calibration slope/intercept 与 risk–coverage；C 报真实终局收益与错误接受/覆盖的共同分母。ECE 不是单独成功判据；单 bin、全同分数和全 abstain 必须显式暴露。早停策略对终局标签造成的删失按预先机制处理，不能删除漏检或未完成 case。

**冻结前仍缺：**自然任务 roster、独立 outcome checker 绑定、可观测 snapshot/不中断标签分支 adapter、已分割的 calibration 集、实际 backend/资产清单、真实时延/forward 成本标定，以及可接受错误率和覆盖下限的任务要求。可以先落地 snapshot→label-panel adapter 与 Journal 的实际预算核算，不必再跑同一 12-case 模板以增加“样本数”。

## 6. NDU-NEXT / CTRL-NEXT：继续、修复、验证、停止的真实取舍

### 6.1 环境与行动

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

### 6.2 先确认环境具有所需取舍

在训练/开发任务上核对：是否确实存在直接执行更好、先验证更好、修复后执行更好、直接停止更好的不同状态；有没有一种固定 `repair → execute` 策略几乎支配全部任务；新增规划是否会耗尽之后执行资源。此步骤是对任务环境的适用性诊断，不能通过重塑确认分布确保候选获胜。

若研究 joint vs mean，必须把“只改变联合依赖、保持相关边际相同”的开发对照与真实联合分布漂移分开。现有若干 confirmation case 同时改变了边际与相关方向，不能当作纯相关性因果测试。真实任务中的 outcome/latency/cost 联合预测还须有独立预测质量校验；已知完整模型上的 mean backup 对照不自动成为 learned predictor 比较。

### 6.3 强控制器与学习变量

第一轮主要对照为：原固定阈值 hybrid、development 上同等调参机会选定的简单阈值/成本规则、冻结 fast actor、固定调用额度的 bounded planner，以及 learned router。VOI、joint MPC、mean MPC 作为次要诊断保留。理论 oracle 只对能实际枚举的小分支子任务成立；在开放代码任务上不能把“试过的最好结果”命名为最优 oracle。

主要学习变量固定为 learned router 的付费调用决策。修正或明确 teacher continuation：训练 label 必须对应部署时将执行的 continuation 与未来收费规则；现有“一次慢调用后固定 fast”标签，不等于部署重复 learned routing 的完整 meta-Q。若继续用这种简化 target，要把它作为明确的方法定义并与部署全轨迹评价配对，不宣称精确策略改进。

`ndu_real_runtime/objective.py` 的已声明语义与 `hepta.ctrl1.resource-cost.v1` 收费边界保持独立且具名；新任务资源价格先在开发测量上定义。训练 adapter 更新参数，NDU 只供应值/advantage。信息增益、预测误差、熵或新奇度不能替代终局任务奖励。

### 6.4 成本和终局收益

保留现有 `budget_sensitivity.py` / `sensitivity_run.py` 的完整尝试与 CPU allowance 思路，接入真实任务 CPU/wall/forward/tool ledger。学习路由标签采集、teacher 搜索、没有改善的 rollout、失败候选、备用停止和恢复均收费；“节省慢调用次数”不等于正净收益。

主要分析是同预算下真实终局效用与质量，以及相对于最强简单控制器的配对增量；再显示把全部学习成本摊到预先冻结任务数后的收益。`stop_regret`、`compute_and_stop_regret`、`continuation_regret` 是局部诊断，不能相加冒充总 policy gap。对真实任务没有可证明 oracle 时，明确报告可识别的对照差异，而不是伪造 regret。

**冻结前仍缺：**任务 roster 与终局检查器、可重放工作区/动作 adapter、自然继续/修复/验证/停止任务覆盖证据、真实费用/时延单位、训练标签 continuation 与部署策略的确定关系、学习预算和未来摊销 horizon。最小可实现工作是给现有 router/evaluation 的行动接口接一个隔离真实工具环境，并以 fixed hybrid 与简单成本规则先跑 development；不需要先升级为完整随机 NDU 或组织演化。

## 7. HCSN-NEXT：先完成一个具体时序任务的公平比较

### 7.1 复用已有真实任务与披露历史

优先 UCI localization 的不规则时间事件分类，沿用已保留的官方数据摘要、原始整数时间、source row、subject、共享 25 维前端及官方模型接口。**不另造数据，也不再把 A01 前 128 / D01 前 64 的四步训练当成质量比较。**[H1–H3]

已有 formal recipe 的主体划分是 A/B/C 训练、D 开发/校准、E 评分，并规定先划 subject 再构造窗口。E 的原始记录已被用于 schema/clock/global-gap 元数据审计，0.2 秒 refractory 选择发生在这之后；后来的 ABC-only 审计不能擦除这段历史。E 尚未用于训练/调参/评分，但这不等于其输入分布完全未见。新报告必须保留这个限度；若要声称完全独立新主体/新采集条件泛化，还需另外取得并冻结当前不存在于这项已审材料中的数据。

### 7.2 收窄首轮科学问题

建议先做**冻结物理的 HCSN 是否在这一真实任务上有成本可接受的增量**，暂不学习漂移、扩散、边界、reset law，也不增加 maintenance/rollover。原 formal recipe 的完整消融仍然保留；这个收窄研究是新审阅稿，不能替代或宣称完成原完整协议。

核心强对照复用 GRU、官方 CfC、官方 recurrent PLIF、官方 S4D-Lin、causal Transformer，并加一个具名普通双门控 memory-bank 控制。最后观测/无时序的简单分类器用于显示任务是否实际需要记忆，不能替代强时序基线。S4D 按 S4D 报告，不能改名 Mamba。

至少把普通双门控与 HCSN 的 bank slots、content width、有效参数和实际状态字节说清。现有接口宽度固定且参数量相差很大，必须有容量可配置 constructor。有效 trainable 参数控制在既有 recipe 的 ±5%，不能以 dead/frozen/masked 权重填数；状态内存与实际计算另行报告，不因参数数目接近就声称完整成本公平。

### 7.3 训练与数值资格

复用已有 formal recipe 的候选训练方案：所有 A/B/C 来源事件、256-event 非重叠 episode、相同前端、相同种子的共享 window 顺序、真实 gap 保留；三 tuning seeds、每臂同 12 个学习率/decay/clipping 组合；最多 100 epoch，至少 30 epoch 后才按固定 patience 早停。S4 保留官方 optimizer 参数组；PLIF 记录 firing/tau、有限梯度和训练-only 多类 memorization，预算耗尽或静默神经元不构成 HCSN 获胜。

这些数值来自已有 specification，**不是已分配或已执行的预算**。六个核心臂已意味着 216 个 tuning fits 加 30 个 fresh-seed fits；加入普通 gate/control 会进一步增加成本。用真实 development 时间测量为全部尝试分配新预算，不能把历史 30-minute interface envelope 挪作正式研究额度。

现有 0.2 秒数值 receipt 只覆盖冻结物理与已测网格/窗口。完整 256-event 观测条件化 rollout 仍需数值资格：质量守恒、有限概率、梯度、边界/尾部/步长敏感性和真实数据 gap，全都使用实际将训练/评分的路径。不能把有限个 prior/window 通过外推为任意 posterior/full-domain 证书。

### 7.4 分数、机制与成本

主要评分采用完整 E 的宏 F1，并同时保留 accuracy、balanced accuracy、NLL/Brier、校准、逐序列和逐独立训练 seed 结果。temperature 只在 D 上拟合；评分后不能回调参数。模型 seed 是独立训练重复，event/window 不是；一个 held-out subject 限制总体泛化，序列聚类不消除这一限制。

如果冻结 HCSN 没有超过最佳充分训练基线，就停止扩张。若有改善，才用真实剪枝的物理读出移除与普通门控消融定位原因。content-only 必须从 likelihood、write gate、proposal、inter-layer messages 和 final readout 移除所有直接物理读出；保留概率加权内容运输和删除运输是两个不同对照。单纯把列置零留下无效权重不能支撑容量公平。独立 generators、mean-state、maintenance/rollover 没有真实动力学实现时应保持“未实现”，不能填写 on/off 结果。

必须分别测量 table build、数值资格、tuning、训练、数据/前端、calibration、推理、checkpoint、失败、迁移/恢复；另报 persistent state、peak RSS/VRAM、稳态吞吐、p99 及已测能量。CPU 运行不能填出“GPU 峰值为 0”的测量结果；无法测得的能量/VRAM 保留缺测。

**冻结前仍缺：**全上下文数值 profile、可调容量的官方适配器与正式 trainer、足够训练/收敛证明、普通双门控实现、明确读出消融、逐臂与全研究实际资源额度，以及对 E 元数据暴露后的声明范围。此线已有真实数据路径，先补上述实现和 development 计时最具体；当前 `run_interface.py` 只会执行旧的有界接口研究，不能把它当正式 trainer 使用。

## 8. 可实施顺序、判据与预算冻结表

| 次序 | 可实施开发工作 | 必须留下的证据 | 当前缺口 |
|---|---|---|---|
| 1 | 真实 source-group／派生关系／曝光登记，旁路成本 ledger | 实际来源 URI/commit/SHA、可见时间、分组冲突、全部 attempts | 独立 roster 与 custody 尚未取得 |
| 2 | MEM 共用 encoder 适配与覆盖度匹配 replay | 每次检索/回放实际来源、重复、年龄、更新量和成本 | encoder/标签与独立后继任务 |
| 3 | PRED 允许清单内 seed 202 train/dev 诊断 | 48 training JSON 身份、源接线、消费/选中 checkpoint 区分 | 不新增确认；新消融额度另冻 |
| 4 | VERIFY 不干预标签分支与真实模型/检查成本 | A 检查器、B 校准、C 终局策略三个独立分母 | 自然 snapshots、标签和真实后端 |
| 5 | NDU 真实动作 adapter 与强简单控制器 dev | 实际继续/修复/验证/停止覆盖和终局 readback | 独立任务、continuation target、数值预算 |
| 6 | HCSN 容量构造器、formal trainer、普通 gate 和数值资格 | 每臂有效参数、训练足够性、完整 episode 的数值检查 | 不能用旧 run_interface.py 冒充正式 runner |
| 7 | 每项单独通过输入/实现核对后冻结确认协议 | 源、运行环境、roster、阈值、统计、预算、失败恢复共同身份 | 当前五项一律 confirmation_admitted=false |

### 8.1 主比较和可识别的成功条件

MEM 首先回答同预算下，结构化快速状态能否超过开发上选定的最强 RAG／普通状态控制，同时不超过预冻的 exact-key 退化与撤销错误上限。把回答正确性与真实执行成功分开，主效应按根任务/项目组配对。uniform consolidation 必须保留，不能在看到确认后换对照。

VERIFY A 的检查器误接受/误拒绝/unknown、B 的校准/风险排序和 C 的终局政策收益分别裁决。B 使用独立不中断标签分支；只有 C 能支持策略收益。固定检查或常数先验达到相同可靠性与成本时，模型不取得增量结论。

NDU 的主比较是 learned router 对开发上预选的最强简单控制器；同上限、不填充无用计算，报告实际质量—成本前沿。只有额外离线学习和后继在线成本都被纳入、且预冻摊销 horizon 下净效益为正时，才讨论“额外计算回本”。没有可信价格时仅比较同预算质量或等质量成本，不能混用单位。

HCSN 的首轮主比较是冻结物理 HCSN 对充分训练、同有效容量的最强预选时序基线；普通双门控是必要机制控制。若未超过最佳公平强基线，停止扩大采用；单 held-out subject 的结果不能外推为跨总体优势。完整 formal recipe 的所有消融与本稿建议的收窄研究应分开登记，不能把收窄研究称原完整协议完成。

### 8.2 必须填成数值的预算字段

下表是冻结 schema 的必填项，**null 表示未分配，不是零或无限**。除 HCSN 历史规格中已写出的数字外，当前没有事实支持给自然任务/运行时间编造样本数；缺任一实际执行所需值就不准入确认。

| 层级 | 必须冻结的量 |
|---|---|
| 任务与独立性 | 各 split 的根来源组数、独立任务数、独立训练 seed 数；按来源组切分的 manifest |
| 开发选择 | 各臂可用配置数、搜索/teacher/标签预算、选择和 tie-break 规则；相同调参机会 |
| 每次 attempt | wall、CPU、RAM、模型 token/forward/tool/verification 上限；有 GPU 则实际设备/显存/计量方式 |
| 全研究 | 数据/encoder/index、所有失败候选和恢复、训练/校准/评分、审核/封存总额度 |
| 主统计 | 唯一主比较、来源聚类/配对方法、置信范围、最小实用效应、错误/退化界限、缺失/删失处理 |
| 停止与重复 | 固定 look 次数、无窥视确认、最大重试和恢复策略、sample replacement 规则 |
| 成本回收 | 实际任务价值/成本价格，或明确不用净效用；预冻未来任务 horizon 与缓存摊销 |
| 生产声明 | 另绑定正式 owners、当前来源资格、采用/NoUpdate、独立不同后继 NextUse；研究通过不自动满足 |

HCSN 原规格的六核心臂 × 12 configs × 3 tuning seeds＝216 tuning fits，六臂 × 5 fresh seeds＝30 fresh fits；若最小研究加入同机会普通 gate 第七臂，则候选工作量是 252＋35 fits，全部为计划算术、尚未分配/开始。任何额外消融再增加额度，不能把旧 30 分钟 interface envelope 承当这些 fits 的资源保证。正式 HCSN 数值和 training-seed IDs 在随附原规格中；本稿没有生成数据或执行这些种子。

### 8.3 失败、恢复与拒绝准入

输入缺失、source/配置/数据身份不符、schema 错误、隐藏标签越界、模型/数值资格不成立或资源预算缺失，均在确认前拒绝；明确记录 disposition 与已消费成本。运行时失败、超时、取消、partial output、无候选、未决提交和恢复都保留原 attempt，不把失败样本删除或替换成更容易的任务。相同任务重复 seed／确定性恢复不增加独立分母。

已知无外部 effect 的可重现失败可按预冻次数恢复；effect 或训练完成状态不明时只读核实，不换 key 盲目重放。崩溃后的状态、优化器、RNG、ledger、版本和允许数据必须同一身份。后端不在场时研究记录为 HOLD/未执行，不能伪造正式 NoUpdate。未知 peak/能量/计费/RPC 成本为 null；嵌套计时只能按单一外层或不重叠窗口合并。

## 9. 依据、原件与本稿审阅范围

1. **已提交的完整四线设计依据**：[M6 NEXT_INDEPENDENT_DESIGNS.md](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/885dae0f3285267e9e9c49d8b43b0d009779f9e8/qualification/cell-integrated-20261108-08b6/NEXT_INDEPENDENT_DESIGNS.md)，31,079 bytes，SHA256 `39df57778404a52216d84fadcacb156e315ae5240a46af7cfac8f29d44646d01`。本稿的 MEM/VERIFY/NDU/HCSN 细节从该原文保留；M1–M3、V1–V3、N1–N2、H1–H3 是其历史引文代号。本轮没有重新宣称这些旧 scratch 路径均可访问。
2. **HCSN 原正式规格**：[formal_protocol.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/5f7f55e015dde7fab0c174081fef090ff45501de/proposals/localization-v2/formal_protocol.json)，5,488 bytes，SHA256 `8d7d321a9f538b5d3ae323ae2827e56688b47795f936eca4badaf8acd21bf5f4`，Git blob `39a326a4d5c4dd486a4822f2bd67cc7fcc5170a8`。本轮重新读取原规格，不读取数据标签。仍为 specified_not_admitted_not_started，formal_fits_started=0。
3. **实际 M6 开发证据**：共同 evidence 的 raw/mdv/M6-complete-evidence.tar.gz，118,128 bytes，SHA256 `ad4a1eedbb1c5368368159a14f589d04145990f00bfd9c7b56bf4cf2046a8a9a`；外层 28 成员，内含原始 109 成员包。历史 a51/M3/M4/M5 不计入 M6 分母。
4. **实际入口源码**：M6 的 cell_repo_mdv.runner 及 hepta_pred1/diagnose_training.py；本次只读核对参数，不启动它们。正式训练缺口继续显式标记。
5. **本稿来源与恢复记录**：NEXT_EXPERIMENTS_M6_REVIEW_COPY_RECOVERY.json 保存旧文件 SHA、已检查的保留范围、新文件身份和写稿操作；原件未恢复的事实不能因新稿完整而消失。

所有新内容都是供审阅与后续实现的草案，不能作为预注册时间戳、确认准入或研究成功证据。先取得完整真实输入、实现缺口和预算冻结，再运行独立确认；组织演化和改进器改善继续等待稳定一阶收益。
