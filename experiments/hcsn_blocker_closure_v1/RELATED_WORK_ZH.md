# HCSN 的相关工作与优势主张边界

**“连续、解析、可反传”均已有直接先例，不能单独证明 HCSN 是全新架构或优于 SNN/Transformer。** 本文只选与当前设计最接近的原始论文及作者实现；它不是穷尽的优先权检索，也不把 Mamba-2 当作当前最新版本。新的研究价值应落在可检验的机制组合与完整成本下的任务收益，而不是名称或金融类比。

## 1. 最接近的比较对象

| 工作 | 已经提供的能力 | 对 HCSN 比较的含义 |
|---|---|---|
| LTC，Hasani 等，2021 [1] | 非线性门控的一阶连续动力学；状态、输入影响有效时间常数；数值积分与梯度训练 | 学习连续时间常数和状态相关动力学并非新增能力 |
| CfC，Hasani 等，2022 [2] | 对 LTC 积分结构构造有界解析近似，并据此设计显式含时间的连续网络，减少对 ODE 求解器的依赖 | “用解析式替代积分并训练”已有先例；CfC 也不声称任意神经 ODE 都有精确闭式 |
| EventProp，Wunderlich、Pehle，2021 [3] | 对声明的 LIF 混合动力学，用伴随方程与事件导数跃迁计算精确梯度 | 硬脉冲不等于无法训练；应区分精确事件梯度、替代梯度和概率期望梯度 |
| Mamba，Gu、Dao [4] | 输入依赖的选择性状态空间递推，以及面向硬件的并行 selective scan | 连续隐状态、输入选择性和线性序列计算并非 HCSN 独有 |
| Mamba-2，Dao、Gu，2024 [5] | 以结构化状态空间对偶联系 SSM 与注意力变体，重构可高效实现的核心算法 | 不能把“连续状态模型”与“注意力模型”当成互不相干的阵营；还需比较优化后的算子 |
| Zoology / MQAR，Arora 等，2024 [6] | 研究注意力与门控卷积的关联召回差异，提出更贴近其语言分析的多查询关联召回测试 | 复制能力不代表内容寻址能力；其结论有模型族与任务范围，不能推广为所有无注意力模型都失败 |

EventProp 的精确性尤其需要说明：事件时间导数依赖非退化阈值穿越；脉冲出现或消失的临界参数可导致导数发散。它并未把混合系统变成处处光滑的普通网络。因此，HCSN 的隐式边界梯度应与这类已有方法比较适用域、误差和成本，不能把“消除阶跃函数”描述为反向传播唯一可行的道路。[3]

## 2. 我们真正提出的假设

当前组合是：**带发放后延续价值的自由边界、完整活动/不应期概率状态、首事件与重复计数的独立算子，以及与内容向量共同学习的价值特征**。其机制假设是，这些统计量在需要复位、等待和不规则时间处理的任务中，比普通时间门控或阈值提供更合适的归纳偏置。这个假设需要对照结果支持；本文不声称上述部件各自首次出现，也没有排除已有再生控制或概率神经元文献中的相近组合。[模型规范](RESEARCH_MODEL_ZH.md)

具体说，\(J^\pi\) 表示执行策略后的全部周期价值，\(G^\pi\) 表示现在干预再延续；首达 \(F/H\) 与可超过一的期望计数 \(C\) 分开。完整概率分布保留了平均电位不能恢复的信息，但也增加网格状态、传播和价值求解成本。它是否比 CfC/LTC 更有用、更稳定或更便宜，目前都属于待验证问题，不能由解析可解性推出。[内容算子](content/models.py)

还需保留两个已知限制：连续标量最优边界不自动成为有限网格最优边界；新增后验任务的最优策略可以被普通双阈值精确表达。因此，任务 oracle 正确与架构优越是不同结论。我们的物理分布也不是未经证明即可解释为标签后验。[已有反例与对照](oracle/MATH_AND_STATUS_ZH.md)

## 3. 当前基线覆盖了什么，遗漏了什么

已登记内容实验包含普通双门控、Transformer、使用替代梯度的 LIF，以及串行 PyTorch Mamba-1 参考模型。它们用于已固定的小型复制/MQAR问题与机制消融；Mamba-1 在固定更新组，等训练 CPU 的外部对照仅为双门控、Transformer 和 LIF。不能将后者的结果扩写成“等预算击败全部 Mamba”。[设计](content/DESIGN.json)、[实现](../continuous_spiking_network/baseline.py)

这些实验尚未加入 CfC、LTC、EventProp 或 Mamba-2；也未进行这些近邻的充分超参数搜索。当前自建 MQAR 是受控内容探针，不等于复现 Zoology 的完整语言模型实验。即使探针成功，也仍需检查更长上下文、更大键空间、多个查询、干扰与内容分布变化；这些是后续验证方向，不在本文件中追改已冻结实验门槛。[数据生成](content/data.py)、[6]

硬件比较同样有缺口：串行 CPU Mamba-1 不能代表官方融合 selective-scan 实现。Transformer 的注意力实现也必须明确；FlashAttention-2 已展示通过 GPU 工作划分和内存访问设计改进精确注意力计算。因此，渐近复杂度或一次 CPU 时序不能直接证明 GPU 吞吐和能耗优势。[4][7] 当前硬件探针可以记录冻结实现的设备成本，却不等于完成所有架构的专门优化。[硬件合同](hardware/HARDWARE_DESIGN.json)

## 4. 怎样陈述可能的优势

相对 SNN，可以检验连续期望是否减少梯度估计困难、完整不应期状态是否改善任务表现；也要同时计入失去实际事件稀疏执行的代价。相对 Transformer，可以检验固定持久状态在长流恢复和内存上的价值，以及其内容召回是否足够；固定状态本身也由其他递归/SSM方法提供。[3–5]

真正有意义的结论应同时回答：在相同输入信息、参数容量和调优预算下，边界与双价值通道是否各自贡献可重复收益；计入传播、训练、验证、数据搬运和持久化后，质量—延迟—内存—实测能量是否改善。全模态 encoder 或大模型还需要对应规模与任务证据。现阶段可称为有明确机制和可证伪假设的研究架构，不能称为已证明的通用替代品或 SOTA。

## 5. 更直接的神经概率流与停止文献

补充检索发现，神经动力学中的自由边界和连续概率表示也已有直接先例。Carrillo、González、Gualdani、Schonbek 的神经群体 Fokker–Planck 模型把阈值处的概率通量解释为发放率，并以 delta 源表示复位；经过变量变换得到 Stefan 型自由边界问题。[8] 这里的移动边界来自方程变换，与本研究通过收益最大化得到的 QVI 干预边界有不同定义。因此，“神经元＋概率流＋自由边界”本身不能作为首次创新声明，也不能据此声称两种模型相同。

Qi 等的 moment neural network 使用发放统计量的一阶、二阶矩构造可进行梯度学习的连续表示，并在其噪声驱动与平稳统计近似下映射回 SNN；论文还报告了 Loihi 实现。[9] 这使它成为“通过连续统计量绕开发放离散性”的直接比较对象。当前 HCSN 保留活动／不应期状态分布，但未建立跨神经元联合噪声相关性的完整模型；更细的单通道状态网格不自动意味着比二阶矩方法携带更多有用信息。现有实验没有包含 MNN，不能宣称在它之上取得优势。

Zhu 等研究 SNN 的正确性、置信度与推理停止，提出同时塑造决策与置信度的训练目标及停止策略。[10] 它与当前 native 消息探针的目标不同，却直接说明“根据连续置信信号停止”已有研究。HCSN 若进一步把停止与任务损失关联，应与这些方法比较同等质量下的停止时间和实测代价，而不能将工程上可触发 STOP 等同于最优任务停止。

这些补充改变的是相关工作覆盖范围，不改变任何实验或验收门槛。本次检索仍不是穷尽的优先权或专利检索，检索中没有找到某个名称也不能证明全球首次。

## 原始论文与作者实现

1. **LTC** — [AAAI 2021 原文 PDF](https://cdn.aaai.org/ojs/16936/16936-13-20430-1-2-20210518.pdf)；[作者代码](https://github.com/raminmh/liquid_time_constant_networks)。
2. **CfC** — [Nature Machine Intelligence 原文](https://www.nature.com/articles/s42256-022-00556-7)；[MIT 保存的论文 PDF](https://cap.csail.mit.edu/sites/default/files/research-pdfs/Closed-form%20continuous-time%20neural%20networks.pdf)；[作者代码](https://github.com/raminmh/CfC)。
3. **EventProp** — [作者论文全文，Scientific Reports / PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8213775/)，尤其事件时间导数条件与临界点讨论。
4. **Mamba** — [Gu、Dao 原文](https://arxiv.org/abs/2312.00752)；[作者实现，亦包含后续版本](https://github.com/state-spaces/mamba)。
5. **Mamba-2 / SSD** — [ICML 2024 原文入口](https://proceedings.mlr.press/v235/dao24a.html)。
6. **Zoology / MQAR** — [ICLR 2024 原文入口](https://proceedings.iclr.cc/paper_files/paper/2024/hash/448fc91f669c15d10364ee01d512cc10-Abstract-Conference.html)；[作者实现](https://github.com/HazyResearch/zoology)。
7. **FlashAttention-2** — [Tri Dao 原文](https://arxiv.org/abs/2307.08691)。本文不转引其速度倍数作为 HCSN 的比较结果。
8. **神经群体自由边界** — [Carrillo 等作者 PDF](https://web.ma.utexas.edu/users/gualdani/Pdf/CGGS.pdf)；[期刊原文，Communications in Partial Differential Equations 38(3), 2013, 385–409](https://doi.org/10.1080/03605302.2012.747536)。
9. **MNN / SNC** — [Learning and inference with correlated neural variability，PNAS Nexus 2025 原文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12512019/)；[作者预印本，题为 Toward stochastic neural computing](https://arxiv.org/abs/2305.13982)；[作者代码](https://github.com/BrainsoupFactory/moment-neural-network)。
10. **SNN 自由响应与停止** — [Zhu 等作者预印本](https://arxiv.org/abs/2404.10599)；[期刊原文，Neural Computation 37(3), 2025, 481–521](https://doi.org/10.1162/neco_a_01733)。

以上为文献与范围说明，未新增实验、改动代码或修改已冻结验收合同。
