# 四条神经科学研究主线：冻结协议 v1（2026-11-12）

**状态：SHADOW_ONLY / RESEARCH_ONLY / DENY_ALL。** 本文件冻结比较逻辑与验收规则，不是训练、效益、原生接入或采用报告。
实验执行前必须补齐下述登记字段并冻结 manifest；字段缺失即 `HOLD`，不得用本文替代真实 owner、模型、数据或效果证据。
继承 [#6097](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6097) 的研究代码；`real_time.py` 与 `source_contrast.py` 只是时间参考运算和输入／来源簇统计检查，不认证来源或产生部署权限。
保留历史负结果：HPCA 旧面板逐 seed 准确率差为 0、B2 AUC < 0.5；[#6132](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6132) 的 96 个开发题／624 次计划 generation 不是 624 个独立新来源，也不是本协议的确认实验。

## 1. 原始研究登记：8 项启发、9 篇论文

日期为首次在线发表日；未提供日级元数据时保留其真实精度。以下工程假设均须独立验证。

| 来源 | 日期 | 可转化机制与结论限界 |
| --- | --- | --- |
| [Masset：Multi-timescale reinforcement learning in the brain](https://www.nature.com/articles/s41586-025-08929-9) | 2025-06-04 | 小鼠多巴胺信号具有不同折扣时间范围；支持多时间范围值预测对照，不给出任意 Cell 的最优时钟。 |
| [Francioni：Vectorized instructive signals in cortical dendrites](https://www.nature.com/articles/s41586-026-10190-7) | 2026-02-25 | 小鼠 BCI 中树突信号与神经元因果角色有关；同向量正确／打乱路由可检验教学归因，不等于一般脑反传已证实。 |
| [Thompson：Replay of procedural memory is independent of the hippocampus](https://www.nature.com/articles/s41593-026-02362-5) | 2026-07-23 | 小鼠背侧纹状体程序回放在海马损毁后仍存在；支持独立技能回放实验，不证明所有记忆系统必须分库。 |
| [Senne：Hippocampal astrocytic sequences emerge during learning and memory recall](https://www.nature.com/articles/s41593-026-02448-0) | 2026-09-16 | CA1 胶质钙活动出现情境相关序列；跨日稳定性有个体异质性，不能据此认定新增第八谱系或因果门控必需。 |
| [Armendariz：Single-neuron encoding of rapidly learned visual information reshapes human perception](https://www.nature.com/articles/s41593-026-02496-6) | 2026-11-04 | 人类退化图识别涉及枕叶额外处理时间，MTL 响应更晚；循环处理是解释，不构成指定网络或 MTL 反馈的因果证明。 |
| [Burke：Duration between rewards controls the rate of behavioral and dopaminergic learning](https://www.nature.com/articles/s41593-026-02206-2) | 2026-02-12 | 小鼠学习率随奖励间隔变化；回溯 ANCCR 与 TD/RPE 是待比较机制，不能与 Masset 结果拼成同一已证实算法。 [2026-08-03 修订](https://www.nature.com/articles/s41593-026-02425-7)仅修正 Fig. 4b 顶排 raster 错位。 |
| [Wakhloo／Slatton／Chung：共享潜在结构与神经群体几何](https://www.nature.com/articles/s41593-025-02183-y) | 2026-02-04 | 为共享／私有表征与迁移提供研究动机；工程收益必须排除额外容量、任务标识泄漏和额外调参。 |
| [Nested Learning](https://proceedings.neurips.cc/paper_files/paper/2025/hash/4309616aaed8e848009bc4a7ef73b493-Abstract-Conference.html)；[Dohare：Loss of plasticity in deep continual learning](https://www.nature.com/articles/s41586-024-07711-7) | NeurIPS 2025（官方页未给日）；2024-08-21 | 分别启发更新频率分层与新任务学习能力测量；不证明某种更新频率普遍最优，也不能把旧任务遗忘与可塑性损失混为一项。 |

## 2. 共同冻结项与时间语义

每个运行登记：代码／模型／adapter／tokenizer／数据／配置／evaluator hash、owner 身份、原始输入载荷及来源回执、任务来源簇、train/calibration/test 分割、全组调参预算、完整成本单位、planned denominator、主要比较、样本量与停止规则。
记录 `observed_at`、`information_available_at`、`decision_at`、`action_started_at`、`outcome_available_at`、`update_at`；由真实 owner 证明次序。跨进程／冷恢复不直接相减无共同基准的 monotonic 时钟，必须保存时钟域、锚点与误差界。

| 独立时钟／记忆量 | 冻结定义 | 必须单独变化的对照 |
| --- | --- | --- |
| 回报折扣 | `gamma(dt)=exp(-dt/tau_return)`；用真实等待时间 | 固定 trial 折扣、单一／多个 tau；容量与调参预算匹配 |
| 状态响应 | `rho(dt)=exp(-dt/tau_state)`；状态对输入变化的响应 | 同一回报折扣下单独改变状态时间常数 |
| 参数更新节奏 | 实际时间触发或预注册事件触发；记录机会与实际更新 | 相同总更新／计算上限的固定节奏与分谱系节奏 |
| Eligibility（单列） | 动作发生时记录局部 eligibility；仅在反馈可用后使用，按真实 lag 衰减／过期 | 正确对齐、时间打乱、无 eligibility；不能用未来结果重建动作时特征 |

`tau_return`、`tau_state`、更新周期、eligibility 衰减／窗口是不同参数；不得用同一 logical step 代替四者。
所有策略可见字段以 `information_available_at <= decision_at` 为界；完整审计可含未来记录，但选择器／训练输入只能读取当时前缀。

## 3. 四线因子表与强基线

| 主线 | 主比较（每线一个） | 机制因子／强基线 |
| --- | --- | --- |
| T：时间对齐局部教学 | 相同完整反馈向量下，正确路由且对齐 − 打乱路由且对齐 | 路由 × eligibility 对齐；标量反馈是信息不同的附加基线；普通 gradient／policy-gradient、固定时间、TD/RPE 与回溯 ANCCR 竞争模型 |
| R：独立情景与技能回放 | 等总离线预算下，E+S − 开发集冻结的最佳单路回放 | E/S 2×2、统一池、uniform replay、exact-key RAG、固定 workflow／macro；单独测协调顺序 |
| V：感知／检查价值 | 真实付费信息动作下，学习调度 − 开发集冻结的最佳固定调度 | 同信息循环计算与付费再观察分面板；随机／固定 ROI、从不／总是／固定阈值检查，保留最强普通策略 |
| L：长期可塑性与保留 | 相同累计资源下，候选更新方案 − 开发集冻结的最佳普通持续学习基线 | 更新频率 × 回放 × 特征更新；固定更新、冻结骨干＋私有 head、普通 replay、连续反传／特征更新基线 |

T 的主要路由对照必须匹配逐次完整反馈载荷、可用时刻、参数组维度、更新／调参预算；标量对照不得冒充同信息归因。密集重复和稀疏新信息另列 moderator，统计唯一新来源及真实等待成本。
R 的 2×2 为 E0S0/E1S0/E0S1/E1S1；报告 `I=U11-U10-U01+U00`。两路开启可能增加资源，不能把此面板称为等实际计算。
R 另跑总预算 B 面板：E-only B、S-only B、E+S 各 B/2、统一池 B；相同字节／更新／时间上限，报告实际用量与未用预算。按事实情境变化 × 技能程序变化分层，禁用 MEM 验证 ACT 路径独立性。
回放记录绑定版本／来源／适用条件；撤销、墓碑、过期和冲突按原 owner 契约执行；旧 episode 不得携带独立测试的答案。
V 的同信息面板固定原始字节与释放时刻，比较 1/2/4 轮、学习停止和同预算普通计算；多轮不产生新来源数。
V 的付费面板真实执行新 ROI／新帧／checker 调用，计入全部延迟与成本；另以相同观测集合／释放时刻检验调度归因，不把新增输入优势称为循环结构优势。
VERIFY 保存检查前选择、原始 checker 输出、检查后选择和独立最终效果；评分答案不进入策略。少检查伴随低成功率不得单独称为提效。

## 4. 长期矩阵、共享容量与慢情境

按时间顺序运行新任务、漂移、旧情境重现和延迟反馈阶段；冻结评估矩阵 `P[k,j]`（阶段 k 后对任务家族 j 的独立能力），缺测保持 null。
令 `a(j)` 为任务 j 首次学完的阶段；旧保留分别报告 `P[a(j),j]-P[k,j]` 与 `max_{a(j)<=h<k}P[h,j]-P[k,j]`，不只看总体平均或最近训练 loss。
新学习同时报告达到任务预注册阈值 `q_j` 的唯一新样本数 `N_j`、实际时间 `T_j`、资源成本与学习曲线面积；未达阈值按右删失／未达标报告，不删除慢学习任务。
区分“仍会旧题”和“仍能学新题”：候选须通过旧保留非劣效门，且新学习效率不能退步到预设界外。
共享骨干＋私有 head、完全私有、分裂实例须匹配总可训练／常驻参数、推理 FLOPs、状态／回放字节和调参预算；不能匹配的轴如实报告，不能作纯结构归因。
迁移任务分别含共享潜结构、无关结构及相冲突结构；按来源分组留出，禁止把任务标识或 latent 标签泄漏给单一方案。
慢情境门控先作可替换消融：无慢状态、仅慢特征、正确情境门控、打乱情境门控、同平均开放率门控。分别测跨阶段／冷恢复稳定性、错误更新和新旧能力；未通过不新增默认谱系。

## 5. 统计冻结、计划分母与效应门槛

主要结果为 `U=Q-lambda_t*T-lambda_c*C-lambda_r*R`；Q 使用冻结的 [0,1] 任务质量，成本换算及风险项在开发阶段登记并锁定，另报告未折算的成功率、时间、资源与风险。
开发阶段先对候选工程门槛 `delta_U=0.01/0.02/0.05` 和旧能力／完成率非劣效容限 `0/0.01` 做功效与成本敏感性分析；这些数值不是论文结论，也不是已批准的应用损失容限。G2 必须按实际任务价值与风险冻结唯一门槛，确认集的同时置信下界须超过它；关键失败／额外未授权效果不允许以平均收益抵消。
`q_j`、学习效率非劣效界、每项成本系数、任务家族权重和预期备择效应必须在接触确认结果前数值化；需改规则时另建版本并换用未接触确认来源。
独立单位是经来源 owner 验证的原始任务／文档／环境来源簇；同一来源的切片、改写、trial、seed、反馈与重复 generation 均在簇内聚合。自报 ID 或不同 digest 不自动建立独立性。
先冻结全体计划任务及各 arm：失败、超时、取消、缺失输出和 UNKNOWN 均留在 planned denominator。报告 observed/planned 与各缺失原因；UNKNOWN 保持未知，不能只做完整案例分析或改写为成功。
对未知质量给出预注册范围下的保守效应界；成本未知也必须界定，否则收益门为 `HOLD`。仅当最不利允许值下仍过门，才可排除缺失结果翻转结论。
主要分析先求来源簇内配对差，再按冻结权重汇总；置信区间／重采样保留来源簇结构。置换需真实随机分配和可交换性；输入检查不证明这些假设。
四线主要比较控制 family-wise alpha=0.05（Holm）；通过反演相应检验或更保守 Bonferroni 构造同时区间。交互、时间常数和任务子组均为次要分析，额外确认主张另登记检验族。
用独立开发来源估计簇方差、簇内相关与缺失率；以主要门槛、预期备择效应和保守 alpha=0.0125 规划 90% power，保存计算／模拟原件。固定 toy n、seed 数或显著性最小可达值均不等于 power。
确认样本量、采集截止与停止规则先冻结；不得反复查看后追加到显著。样本不足或未达到功效仅说明不确定，不能宣布等效、无效或成功。

## 6. 阶段门与仍未执行项

| 门 | 必须取得的原件 | 当前资格 |
| --- | --- | --- |
| G0 机制检查 | 时间／输入／未来泄漏／重复来源／计划分母的参考与对抗验证 | 仅 SHADOW_ONLY；参考检查不授予效益资格 |
| G1 原生归属 | 普通入口真实 owner、签名来源、时间域、原始效果、候选模型与全部成本 | 本协议未执行；缺项 HOLD |
| G2 冻结研究 | 开发／校准／确认隔离、数值登记、power 原件、冻结强基线与 manifest | 本协议未完成执行登记；缺项 HOLD |
| G3 独立效益 | 新来源确认结果、四线多重校正、净收益／旧保留／新学习门、完整分母 | 未运行；不宣称真实训练或收益通过 |
| G4 普通后续使用 | A→训练→独立 B→选择或 NoUpdate→不同 C→不同 worker 冷恢复，版本／回执绑定 | 未运行；任何前门缺项仍 NoUpdate |

现有局部测试、旧分支结果、96 开发题或 624 计划 generation 不得拼接替代 G1–G4。失败与负结果保留；任何默认采用都必须通过原 StageOwner 的独立授权链。
