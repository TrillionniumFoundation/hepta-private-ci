# PFT 与 Hepta：已完成轮次的研究 comments 与 blocker 闭合审阅

**证据截止：V5/V6 已封存评估、原始 V7 全量开发网格及其独立附加诊断；不包含 V7b 的新结果。** 本稿只复核既有源码与完成回执，没有读取未封存结果，没有增加实验、改变阈值或修改原始执行文件。下文证据链接已适配发布目录；成本归因表述作保守收紧，原始审阅稿及哈希核对回执保留在完整归档。

修正版 V7b 的完整结果及最终交付状态见 [V7/V7b 执行报告](./CELL_FIELD_V7_CLOSURE_REPORT.md)。

## 1. 首要结论：工程可验证性显著加强，科学准入仍未成立

现在可以支持的结论是：Hepta 的小型真实训练头已经实现完整优化器状态下的局部参数场、同动作比较、实际非线性保留检查、完整控制器恢复，以及原生表示与恢复链路。**这些成果没有使既有候选通过预先声明的联合科学门槛。** V6 尤其重要：场控制器已近乎逐位复现 Full H8 的动作和轨迹，仍未通过任何未来收益比较。这把“局部压缩信息不足”和“对外部任务有效”分成了两个需要分别验证的问题。[V5 评估][eval5] [V6 评估][eval6] [V6 描述统计][summary6]

| 完成轮次 | 完整执行与成本 | 科学/开发结论 | 可以支持的判断 |
|---|---|---|---|
| V5，72 个策略输出 | 候选 9/12 完成；主策略完成门槛 33/36；具备资格的成本门槛 3/4 | 科学条件 0/12，联合拒绝 | 原非线性 guard 仍会停止；不能把短轨迹成本当完整任务收益 |
| V6，72 个策略输出 | 候选 12/12、主策略 36/36 完成；成本 4/4 | 科学条件 2/12；其中未来优势 0/8、DBpedia 保留 2/2，通过联合门槛为否 | 局部 Full 一致性和完整执行可以成立，同时外部目标失败 |
| 原始 V7，864 个开发槽位 | 739 完成、125 停止；停止中保留 29 个实际异常 | eligible 与 plausible 均为空，`selected_index=null`；没有执行新确认实验 | 该次冻结运行没有合格候选；不能据此证明所有工程修正版或其他目标必然失败 |

V5 第四组 CPU 比值本身低于 3，但候选未完成规定更新，所以没有通过资格；“成本 3/4”不是四组中有一组数值超过 3。原始 V7 的 864 槽位来自 12 配置 × 24 历史 fit × 3 策略，不能作为 864 个独立任务或独立训练模型。[V5 评估][eval5] [V7 独立审计][audit7] [原始选择][selection7]

这里的任务范围仍是两个四分类任务族、固定预训练编码器，以及 36/52 个可训练参数的 linear/gated 私有头。它没有覆盖全 LLM 微调、共享底座同时更新、真实长期任务漂移，也没有检验三因子学习规则优于 Adam。开发版 old/current 划分不能自动解释成真实时间漂移。[V5/V6 完整报告][report6] [V7 冻结协议][protocol]

## 2. 原五项 P0/P1：完成了什么，尚缺什么

| 原工作项 | 工程/实验闭合状态 | 仍不能据此推出的命题 |
|---|---|---|
| **P0：Loss2、增强状态/历史、Full 的同起点、同动作真实 H8** | V5/V6 每轮 36 起点 × 49 动作的 1,764 条真实分支完成；V6 八预测器共 14,112 条预测路径。原始 V7 又在全部 71 个 Loss2 停止点执行四分支同状态诊断 | 两损失状态普遍充分；低维经验量是完整非线性 Markov 状态；Full 局部一致性自动带来独立收益 |
| **P0：方向、幅度、风险、保留、动作代价及 CPU 分解** | 固定动作库及分量记账已完成；系数、求解、失败试探、修复与提交均进入相应控制器成本。V6 同频 Full 对照揭示成本归因限制 | 总目标排名好就等于未来风险预测好；H8 比 H1 便宜就证明压缩产生速度收益；相同动作单价就等于共同的 32 步优化目标 |
| **P0：冻结压力与真实非线性保留** | 原阈值、零松弛、逐步实际验证、完整状态克隆及整块原子提交已经实现；有限搜索失败保持拒绝/未解决。V6 配对压力证据明确记录 27 个修复专属认证 | 切向可行意味着真实安全；有限搜索失败意味着全动作空间不可行；反复查询的 old 面板认证等于独立总体保留 |
| **P1：独立来源、预声明候选与统计门槛** | V5/V6 已完成标签隔离、执行封存、独立重放、逐源配对统计和门槛算术复核；两轮都保留真实负结论。V7 原始开发选择算术完整审计 | V7 可以继续把已用于选择的 V5/V6 样本当新确认数据；没有合格候选等于已经批准；增加种子、动作或窗口即可替代独立来源 |
| **P1：原生 owner、拒绝、恢复和回滚** | 类型化推理语义与完整训练/控制器交接分别验证；原始 V7 实际 92 个可恢复切点及全部 23 个可用 step17 续跑通过；停止与缺失保留 | codec、签名、CURRENT、崩溃恢复或合成正例能替代科学 gate；转换成功意味着真实研究候选已准入或生产激活 |

上述“闭合”指具体实现、审计或实验问题已得到可复查答案，包括失败答案。**“同时达到未来优势、保留、成本和完成条件的候选存在”仍未被这些已完成结果支持。** 原始 V7 工程异常的修订运行必须单独报告，不能覆盖原运行，也不能先于它的封存与审计宣称异常已经在全网格消失。[summary6] [audit7] [native7] [resume7]

## 3. 与论文 PFT 的真正关系

### 3.1 支持的是优化器一致的分析方法，不是 Hepta 架构充分性定理

R45 区分完整优化器状态、事先声明的观测、未来代价和可施加动作；随后分别处理可达方向上的模型残差、信息不足、动作空间限制及系数误差。Hepta 最直接的对应是：把私有训练头的完整 Adam 状态作为受控系统，把损失面板作为观测，把参数干预作为动作，再用真实非线性 rollout 验证局部模型的预测。[论文 R45][paper] [V7 响应实现][response]

连续向量可以写成 \(s_k=(\theta_k,m_k,v_k)\)，但可恢复系统还必须携带步数、采样器/RNG、上下文、数据身份和控制器动作游标。仅保存 \(\theta\)，或者仅保存两项损失，都不能一般地确定下一次 Adam 更新。V7 的完整状态与 pending-plan 绑定解决的是这个明确的工程前提。[V7 控制器][controller] [native7] [resume7]

论文的投影残差 \(R_k=C_{k+1}A_k-F_kC_k\) 提醒我们：缺失方向是否重要，取决于实际可达状态与行动。低秩协方差、低维损失或某一次良好排序都不是闭合证明。原始 V7 的同状态反例正是行动相关的证据，强于把不同策略各自到达的终点直接相减；但它仍不是论文 LQ Bellman 最优价值恒等式的直接数值验证。[paper] [mechanism7]

### 3.2 72→8 场的精确含义

V7 在实际受控名义轨迹附近定义局部时变线性系统：

\[
\delta s_{k+1}=A_k\delta s_k+E_k\delta u_k,
\qquad \delta y_k=C_k\delta s_k,
\qquad E_k=[\Delta t I;0;0].
\]

八项输出是四个 current 面板与四个 old 面板。令

\[
O_H=C_H,\qquad
O_k=\begin{bmatrix}C_k\\O_{k+1}A_k\end{bmatrix},\qquad z_k=O_k\delta s_k.
\]

则 \(z_{k+1}=\operatorname{drop}_8(z_k)+O_{k+1}E_k\delta u_k\)。H8 的坐标长度随窗口从 72 缩至 8，保留此名义轨迹、此窗口、此组输出的全部局部线性响应。它不是从 72 个神经元训练出 8 个神经元，也不是总系统只需 8 个数。系数仍由完整状态生成，参考轨迹、系数存储与行动序列仍存在。[V7 场实现][field] [response]

这里应使用“有限窗口局部输出闭合”或“局部线性实现”。尚未证明一个固定维数、无需完整状态侧信息、对任意新任务长期闭合的自治 Markov 场；也未证明 72 维是最小实现。重新规划时窗口重新建立，不能把窗口内的精确递推直接升级为全局非线性充分状态定理。[field] [paper]

Loss2 对照只把跨步状态压缩为 current/old 两项均值，但保留八面板即时输入到输出的直接项。因此第一步和最后动作的直接响应与 Full 一致，早期动作的传播才经过两维状态。这是有意义的压缩对照；它没有免除对实际动作轨迹、非线性余项及不同名义参考的核对。[response]

### 3.3 Exact cache 与 Hepta 共享底座不是同一项定理

R45 的全词表聚合保持特定分组偏移适配器的原始 softmax 分母与 token 损失，代价是组内概率比及冻结底座不变。它不证明任意共享 Encoder 加私有头都等价于全 LLM 可训练系统。Hepta 缓存固定编码器特征使小头反复训练可执行；特征身份一旦改变，原缓存和响应系数就不再适用。两者共同的优点是明确冻结边界和可训练模块，不能据此宣称任意 LLM 更新都廉价。[paper] [report6]

## 4. 原始 V7 的全量结果与 71×4 诊断能证明什么

独立审计覆盖原始 **864/864** 输出、**26,238** 次真实更新和 **3,275** 个已保留规范控制器切点；逐源损失与选择算术的最大差为 **0**。原始状态分布为完成 739、修复拒绝 53、切向不可行 35、未解决 37；29 个实际异常作为未解决记录保留。eligible/plausible 均为空，条件式 Full 24-fit 主对照没有执行。[audit7] [selection7]

后置机制诊断预先固定了全部停止的 Loss2 槽位，而非挑选有利例子。在 288 个注册 Loss2 槽位中，217 完成、71 停止；71 个原点的完整已提交状态均精确恢复，再以相同配置、训练数据、八面板、原始 old 锚点及动作盒运行 Full、Loss2、field、参数保持四分支，共 **284** 个分支记录。仅使用 planning-only 包，未读取 future/old selection 标签，未改变原选择。[diag7] [diagnosticplan]

| 原 Loss2 停止类别 | 原点数 | 实际安全 Full H8 | 实际安全 field H8 |
|---|---:|---:|---:|
| 切向 QP 不可行 | 35 | 35 | 35 |
| 非线性修复拒绝 | 24 | 23 | 23 |
| 未解决，包含真实实现异常 | 12 | 11 | 11 |
| 合计 | 71 | 69 | 69 |

**最强的反例结论：全部 35 个 Loss2 切向不可行点，都存在同状态、同盒内、通过四个原 old 阈值逐步验证的真实 Full/field H8 续行。** 因而这些局部压缩 QP 的不可行不能解释成真实非线性动作空间不可行。Full 与 field 在全部诊断中的最大动作差为 \(5.48\times10^{-10}\)，完整状态差为 \(2.06\times10^{-11}\)。[mechanism7]

69 个证据只认证这八步的已知面板保留；它们不证明整个 32 步策略会完成、不证明外部 future 损失更好，也不证明 Full 是全局非线性最优控制。剩余两个原点分别是 Full 规划未解决和修复拒绝；不能把它们称为已证明无可行控制。全部 71 个“精确抵消 Adam 位移”的参数保持提议都超出原动作盒，因此没有参数保持安全证据，也没有扩大动作盒。[diag7] [mechanism7]

为比较预测器，诊断把**同一条实际执行、已经修复的 Full 动作序列**代入各自的“名义观测 + maps × (实际动作−名义动作)”公式。不同模型最后参考可能不同，所以另列 41 个名义动作和参考状态完全相同的原点：八面板 pooled RMSE 为 Full/field **0.004300**，Loss2 **0.008086**；old 四面板为 **0.004373** 对 **0.009221**。这些是条件于已停止原点的描述统计，不是独立重复实验或新总体优势检验。[mechanism7]

原始完整网格没有执行的 Full 24-fit 主对照，不能由上述后置 Full 分支补名额。诊断 CPU **34.842747520 秒**单独计费。原诊断 case 文件中一个重复状态字段保留初始化值；已有逐项 metadata note 指明 authoritative case table，原始数值和状态回执未被重写。[diag7] [metadata7]

## 5. 两项工程缺陷：因果定位和证据修复必须分别记账

**动作盒浮点溢出。** 全部 29 个原始实际 ValueError 已在其原状态上复现：QP 提议处于盒内，选中的线搜索比例均为 1，但 `nominal + (proposal - nominal)` 使共 48 个坐标超出边界恰好 1 ULP，最大绝对超量为 \(1.11\times10^{-16}\)。直接复制全比例提议可消除此代数路径的溢出；部分比例需保持精确盒约束。它是实现缺陷，原版本运行因此不合格，异常必须保留；不能用这些异常证明模型机制被科学证伪或真实安全不可行。[rounding7]

原始运行的 29/29 复现关闭了“是否真实存在、来自何处”的问题；完整工程修订是否在全网格消除异常属于单独 V7b 运行的证据。本稿没有读取该运行结果，因而不预先宣称修订网格通过，也不把更小容差或较宽盒界当作修复方案。

**终端控制器原始字节缺失。** 原独立审计如实记录 93 个缺失终端预像。补充恢复后来对 **93/93** 得到与原 trace 中既有 SHA 完全一致的规范字节，0 未解决：57 使用保留的同计划意图，8 由 resolved=intended 的完整哈希证明，28 在最后实际已提交原点调用一次冻结 planner。原时间和 paid ledger 从原记录恢复，28 次额外规划计费 **2.273962512 CPU 秒**，没有替换原成本或生成新实验结果。[recovery7]

独立复核再次核验全部 93 个原始控制器承诺、93 个 paid ledger 和 93 个完整优化器 checkpoint，额外优化器控制调用为 0。这关闭的是“既有终态证据是否可完整恢复”；原 stopped 状态仍拒绝续训，恢复成功不使停止候选变成 completed。[recoverypeer7]

## 6. 成本、共同目标与自适应保留：三个仍需限制的归因

### 6.1 相同动作单价不等于同一个 32 步最优控制问题

V7 各方法共享每个名义窗口的终端风险

\[
\bar L_{\mathrm{current},H}
+\gamma\sqrt{\tfrac14\sum_{i=1}^{4}(L_{\mathrm{current},i,H}-\bar L_{\mathrm{current},H})^2+10^{-12}}
+w\bar L_{\mathrm{old},H}
+\tfrac12\Delta t\rho\sum_{k<H}\|u_k\|^2.
\]

四个 old 面板各有独立锚点约束。内层 QP 线性化终端损失及 dispersion，选中的线搜索动作再由真实终端 merit 评价；非线性逐步修复仍是另外一道检查。它不是精确求解该非线性鲁棒目标的全局 SOCP，也不是整个 32 步的 Bellman 最优解。[planner] [qp] [repair]

H1 每步重规划，H8 每八步重规划。即使每步动作预算和 effort 单价相同，二者的窗口终端、策略重算频率和未显式计入的中间风险也不同。不能将局部 J 的下降或局部 J 的简单加总当作共同 32 步目标上的信息价值差，更不能直接套用论文要求相同目标、相同初始分布和相同动作集合的 Bellman gap 公式。[paper] [protocol]

### 6.2 观察维数、总体计算成本和信息来源应分别列账

V6 场/H1 CPU 比在四组中为 **0.6552–0.6691**，但同频 H8 的 Full adjoint 更便宜：场/Full 比为 **1.0114、1.0301、1.1270、1.1273**。这些实测成本对应不同规划频率，不能单独识别频率的因果贡献，也不支持场维数本身造成加速。编码器提取、预测输出和 I/O 必须按已声明范围另列，不能用小头的毫秒数代表完整系统开销。[eval6]

完整 Adam 状态、已知训练批次及八面板用于产生参考和系数；这没有偷看未见标签，却确实使用了低维状态之外的侧信息。“未来场”是名义模型的未来输出响应，不是获取未知未来样本的 oracle。要主张廉价 observer，仍需证明如何以相应信息预算估计这些系数，并把估计误差、非线性误差及查询成本计入。[response] [field] [paper]

原始 V7 没有登记其实际 BLAS 线程设置，不能事后补称该网格是单线程。23 次 native 续跑已记录当时 OpenBLAS 为 9 线程并且轨迹仍逐项一致；新增 CPU/墙钟只用于该续跑回执，不替换原网格成本，更不与历史运行混算因果速度收益。[resume7]

### 6.3 四面板约束是经验鲁棒性，不是独立保留证书

四个面板可以减少对单一均值的依赖，但它们被反复用于规划、修复及配置开发。组件不重叠也不改变这种自适应使用事实；不能称为未经选择影响的独立 cross-fitting 证书。零松弛实际检查准确回答“这条轨迹是否违反所查询面板的原阈值”，不会自动回答总体旧任务风险是否上升。[protocol] [repair]

V6 压力实验的实际分母是 78 个槽位：guard 认证 39、repair 认证 66，其中 27 个只有 repair 通过；另有 11 个有限搜索拒绝和 1 个切向不可行，9 次没有找到压力越界的搜索也保留。独立 old-test 没有相应救回，且被实例化压力原点已经存在 old-test 违规；不能说这些违规全由修复新造成，也不能说探针认证关闭了独立保留问题。[summary6] [retention6] [report6]

V6 AG News 两头 old-test 样本均值分别增加 **0.024124、0.012132**，其单侧上界为 **0.080998、0.057975**；DBpedia 两头均值为 **−0.073734、−0.052115**，上界 **−0.034130、−0.015564**，因此后两项通过。均值和预声明上界应同时报告：上界未过门槛是未证明合格，不能一概改写为显著总体伤害；反之，负均值也不能替代家族校正的通过条件。[eval6]

## 7. Native 已经证明可执行交接，仍不生产科学有效性

原始 V7 固定 config00 的工程 fallback 注册 96 个切点：**92** 个完整状态精确恢复、**1** 个 stopped 控制器拒绝、**3** 个原切点缺失。它们覆盖 **211,968** 次原生推理比较；最大 logits 误差 \(4.00\times10^{-15}\)，概率误差 \(1.12\times10^{-15}\)。这是未准入的实际开发状态转换与 serving 语义核验，`candidate_published=false`、`scientific_acceptance=false`。[native7]

全部 **23** 个可用 step17 状态又从 native 解码字节恢复，先核验剩余七个冻结动作，再用冻结策略重新规划。共 **337** 个实际续步的动作、receipt、每个完整状态 SHA、终端向量及 receipt_chain 与原运行一致；22 到达原 step32，一个保留原 stop24。额外 policy CPU **7.489484841 秒**、墙钟 **3.630591977 秒**单列。新验证计数、时间与失败尝试 ledger 没有被伪称为原控制器字节相同。[resume7]

因此，“只有推理参数回滚、没有优化器恢复”的缺口已有完整训练与控制器实证补充。仍须区分三种命题：表示和恢复正确、owner/签名允许哪一个 immutable candidate、该候选是否达到独立科学门槛。前两项的工程通过不能推出第三项。原始 V7 没有 selected candidate，config00 的固定工程 fallback 不是研究选优结果，更不是准入或生产激活。[native7] [selection7]

## 8. 建议写入论文与项目的明确 comments

1. **将 Hepta 实验定位为 PFT 方法在受限可训练模块上的检验。** 完整 optimizer state、真实非线性重放和失败保留是强证据；全 LLM、通用神经元充分性、三因子学习与生物合理性须另证。
2. **将场闭合与任务收益拆开。** V6 支持局部 Full 输出实现，却未通过任何一项未来优势门槛（0/8）；这已经反驳“局部 Full 等价自然保证所声明外部收益”的推断，不反驳 PFT 的有条件数学恒等式。
3. **把原始 V7 的 35 个同状态安全替代作为具体反例报告。** 它反驳将压缩切向不可行当成真实不可行的做法；69 个续行证据不应升级为长程完成或泛化优势。
4. **按目标、信息、动作和成本逐项声明比较条件。** 特别注明 H1/H8 的终端窗口与执行频率，完整状态生成系数的成本，以及 field/Full 同频比较；避免用总目标排序掩盖原始损失、保留或 effort 的方向。
5. **让科学准入始终保持联合条件式。** 保留 12 项 Bonferroni 家族、未来上界严格小于 −0.001、old 上界不大于 0、CPU 比不大于 3，以及全部规定策略完成 32 步。三种子先按来源平均，再做 10,000 次类别分层 source-component bootstrap；动作、窗口与种子不充当新独立来源。[eval6]

这些 bootstrap 区间是既定拟合与来源下的近似条件式 percentile 推断，不应宣传成任意分布、任意自适应策略的有限样本保证。V5/V6 对各自冻结候选的历史负结果依旧成立；一旦用于 V7 配置开发，它们对 V7 就不再是新确认样本。没有合格候选时，正确的系统结果是保留拒绝/未选择，同时完成诊断和工程修复；不能以不断查看新来源、删除失败对照或放松门槛来定义“全部 blocker 已闭合”。[eval5] [eval6] [protocol]

## 9. 固定身份与可复核证据

| 对象 | 固定身份 |
|---|---|
| 论文 R45 | `ICLR-2027@f8df0a6075f58f3ab9431a889b773cdf8d6e771d`，`revision_2026-09-26-r45/sections/r45_main.tex` |
| 原始 V7 执行源码 | `hepta-private-ci@79860d4a2b16c4234124bfb3e544d5922925eabd`，103 文件闭包 SHA `5052eda981b73dd578e34fb1835daa3598bbd79ccddf934cce4a08a37398ff82` |
| 原始 V7 协议 | SHA `75def1fe5a2610f76f5fe02db082bb4f0d01d02f683da0ee500a9af1f7e5e0e6` |
| 原始 V7 seal | SHA `c590a7487d1a6f229d7d03f14f03f3141e23b529a531cdd37978ef568818082d` |
| 原始网格独立审计 | SHA `2437865dd33179faac0cdd6189e9b44e4bcebaf898f50b4f832b99d7c4b43b4f` |
| 全部停止点诊断 | SHA `935bf50502ebb85cf400b8c8d30de3639c0e8f1920662c0ee44ac00948b2900e` |
| 29 个浮点异常复现 | SHA `a5f175ff42f6599de946dd7dd6c2e7a7c5240291a63d9c3fc464ad49ec7f628d` |
| 93 个控制器预像恢复 | SHA `8038e1f0a480f4fcfa065995d983a985c7ba74c3a467fa5934e3b8fabdecd090`；独立复核 `846e162b596c92cc50ed3064da867f8e8fa87d9c0393b5038da78381b2097d84` |
| 实际 native roundtrip | SHA `de4d4249b8e6e83fbe0b1c0b4f162fd6d6c4a1a98b7b75660eb23050af98367d` |
| 全部实际 native step17 续跑 | SHA `6cdf00a739ace4063a735d3837bcbcf04bc078d456aed4ff6bfa57ac9ee00387` |

[paper]: https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex
[protocol]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/79860d4a2b16c4234124bfb3e544d5922925eabd/qa/stem-bakeoff/cell_field_development_protocol_v7.json
[response]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/79860d4a2b16c4234124bfb3e544d5922925eabd/qa/stem-bakeoff/cell_field_response_v7.py
[field]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/79860d4a2b16c4234124bfb3e544d5922925eabd/qa/stem-bakeoff/cell_field_observable_v7.py
[planner]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/79860d4a2b16c4234124bfb3e544d5922925eabd/qa/stem-bakeoff/cell_field_planner_v7.py
[qp]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/79860d4a2b16c4234124bfb3e544d5922925eabd/qa/stem-bakeoff/cell_field_qp_v7.py
[repair]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/79860d4a2b16c4234124bfb3e544d5922925eabd/qa/stem-bakeoff/cell_field_repair_v7.py
[controller]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/79860d4a2b16c4234124bfb3e544d5922925eabd/qa/stem-bakeoff/cell_field_controller_v7.py
[report6]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/79860d4a2b16c4234124bfb3e544d5922925eabd/qa/stem-bakeoff/CELL_FIELD_V6_FOLLOWTHROUGH_REPORT.md
[eval5]: ./evidence/20261025-cell-field-v5-v6/v5-evaluation.json
[eval6]: ./evidence/20261025-cell-field-v5-v6/v6-evaluation.json
[summary6]: ./evidence/20261025-cell-field-v5-v6/v6-descriptive-census.json
[retention6]: ./evidence/20261025-cell-field-v5-v6/v6-independent-retention.json
[audit7]: ./reviews/20261026-cell-field-independent-v7/v7/receipts/audit.json
[selection7]: ./reviews/20261026-cell-field-independent-v7/v7/receipts/selection.json
[diagnosticplan]: ./reviews/20261026-cell-field-independent-v7/mechanism-v7/receipts/diagnostic-protocol.json
[diag7]: ./reviews/20261026-cell-field-independent-v7/mechanism-v7/receipts/report.json
[mechanism7]: ./reviews/20261026-cell-field-independent-v7/mechanism-v7/receipts/mechanism-summary.json
[metadata7]: ./reviews/20261026-cell-field-independent-v7/mechanism-v7/receipts/metadata-note.json
[rounding7]: ./reviews/20261026-cell-field-independent-v7/mechanism-v7/receipts/action-rounding-reproduction.json
[recovery7]: ./reviews/20261026-cell-field-independent-v7/v7/receipts/controller-recovery.json
[recoverypeer7]: ./reviews/20261026-cell-field-independent-v7/v7/receipts/controller-recovery-peer-audit.json
[native7]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7dae7c2fd66bb2f998451b5ab5e4d6dc97400984/qualification/trained-cell-v7/actual-grid/roundtrip-qualification.json
[resume7]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7dae7c2fd66bb2f998451b5ab5e4d6dc97400984/qualification/trained-cell-v7/actual-grid/continuation-qualification.json
