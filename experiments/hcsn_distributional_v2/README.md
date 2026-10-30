# HCSN：保留分布的再生自由边界研究单元

本目录实现并验证一个受 He–Xiong 内生边界思想启发的神经研究单元：保留活动状态与不应期的概率分布，用包含后续再生收益的策略值和干预值驱动内容门控，并将任务级动作接入真实 Hepta owner。它是可复现的研究实现，不能由其数学正确性直接推出内容优势或大模型训练优势。

上游研究见 [hcsn_free_boundary_v1](../hcsn_free_boundary_v1/README.md)。本目录保留并修正第一版的均值闭合问题，没有重写第一版的协议、原始结果或失败记录。代码和证据随研究分支提交；生产 Rust 路径未作修改。

## 从哪里读起

| 目的 | 入口 |
| --- | --- |
| 确认 Call/Put、发放、复位、不应期、输出张量与价值单位 | [CONTRACT.md](CONTRACT.md) |
| 确认有限生成器、误差界、重映射、分布传播和局部梯度 | [MATH.md](MATH.md) |
| 复现环境、恢复原始数据与权重、运行和分析实验 | [REPRODUCE.md](REPRODUCE.md) |
| 查看主训练的冻结条件 | [CONTENT.md](CONTENT.md)、[CONTENT002_PROTOCOL.json](CONTENT002_PROTOCOL.json) |
| 查看传统硬脉冲 LIF 的独立补充协议 | [LIF_SUPPLEMENT001_PROTOCOL.json](LIF_SUPPLEMENT001_PROTOCOL.json) |
| 查看长度、宽度和深度的独立 CPU 扫描合同 | [SCALING.md](SCALING.md)、[SCALING001_PROTOCOL.json](SCALING001_PROTOCOL.json) |
| 查看真实任务收益、未来任务、owner 动作及成本分配 | [TASK_VALUE.md](TASK_VALUE.md) |
| 理解与金融模型、CfC、SNN、状态空间和注意力的关系 | [RELATED_WORK.md](RELATED_WORK.md) |
| 查看证据闭合与成本包含关系 | [ARCHIVE_CLOSURE.md](ARCHIVE_CLOSURE.md)、[CAMPAIGN_COSTS.md](CAMPAIGN_COSTS.md) |

最终主矩阵分析使用 `results/content_analysis002/`，LIF 补充分析使用 `results/lif_analysis001/`。只有完整执行收据和全部逐项完整性审计通过后，才可把这两处结果用于结论。运行中的 `PROGRESS.json` 只表示调度进度。

## 1. 正式语义

### 金融启发与当前实现

He–Xiong 原论文研究股权、债券及内生违约边界。股权在违约边界满足价值匹配与平滑粘贴，债券满足清算回收边界。债券不自动等于 Put；金融违约不自动产生神经复位或不应期。原始论文的资产过程也不是这里的归一化压力过程。原文及公式对应见 [合同第 2 节](CONTRACT.md#2-hexiong-原模型与-callput-标签)。

当前实现正式区分四个对象：连续标量再生问题的解析最优值；有限网格上所选策略的内部值；独立有限控制 QVI 的最优值；分类任务的 READ/FIRE 动作值。它们具有不同的状态、收益和最优性范围。代码中的两个内部值经可学习门控影响内容状态，没有直接把股权价值当成力，也没有直接把内部发放收益当成分类正确率。

### 再生收益

在连续标量参考问题中，活动压力满足 \(dX=\mu\,dt+\sigma\,dW\)。FIRE 获得 \(X-K\)，复位至 \(r<K\)，等待不应期后继续同一问题。设贴现为 \(\rho>0\)，固定不应期为 \(\tau\)，则

\[
\mathcal M J(x)=x-K+e^{-\rho\tau}J(r),\qquad
\max\{\mathcal LJ-\rho J,\mathcal MJ-J\}=0.
\]

定义

\[
\kappa=\frac{\sqrt{\mu^2+2\rho\sigma^2}-\mu}{\sigma^2},\quad
H(b)=\kappa(b-K)-1+e^{-\rho\tau-\kappa(b-r)}.
\]

在已声明参数域内，唯一边界 \(b_*\in(K,K+1/\kappa)\) 满足 \(H(b_*)=0\)，且

\[
J_*(x)=
\begin{cases}
e^{\kappa(x-b_*)}/\kappa,&x<b_*,\\
x-b_*+1/\kappa,&x\geq b_*.
\end{cases}
\]

这给出 \(C^1\) 的值函数、包含后续收益的 FIRE 值，以及通过边界方程隐式微分的一阶导数。完整 QVI 验证和适用条件见 [v1 数学说明](../hcsn_free_boundary_v1/MATH.md)。它不证明任意多层、输入依赖神经网络的任务最优性。

### 实际训练的有限过程

每层有 8 个物理通道；每通道保留 8 个活动网格概率与 2 个 Erlang 不应期阶段。自然越界进入第一阶段，最后阶段按插值复位。边界下降覆盖旧质量时，按原物理位置立即记录事件与收益。已有阶段质量不会因下一个 token 到来而重启。

对当前有限生成器的后向矩阵 \(A\)，当前所选策略的值满足

\[
(\rho I-A)J^\pi=g,\qquad
G_i^\pi=x_i-K+D\,J_r^\pi,
\quad D=\left(\frac{2/\tau_\phi}{2/\tau_\phi+\rho}\right)^2.
\]

阶段内没有合法的再次 FIRE 动作，对应值为强制续存。局部计算冻结当前系数，未预测未来输入。自由边界取自连续参考问题；随后按真实有限生成器计算其策略值。因此，内部值正确不代表该边界在八格模型上最优。独立 QVI 对照明确量化了这一差异。

层间保留 32 维内容路径；每层跨 token 还保存内容状态、\([8,10]\) 概率和八维边界。`activity` 是可超过一的期望发放次数。内部物理复位不会清空内容状态。任务级 RESET 会重新初始化整个模型，两者分别记录。完整接口见 [CONTRACT.md](CONTRACT.md)。

## 2. 实验与审计路线

| 工作 | 实现 / 原始证据 | 验收边界 |
| --- | --- | --- |
| 标量解析 oracle | v1 `oracle.py` 与冻结数值验证 | 指定标量无限期问题；不外推为整网最优 |
| 保留分布的有限动力学 | `distribution_kernel.py`；`results/kernel_validation003/` | 稠密矩阵指数、Monte Carlo、时间组合、重映射、误差界、局部梯度和因果性 |
| 独立最优控制参考 | `grid_control_reference.py`；`results/grid_control_validation001/` | 独立枚举全部有限策略，核对 QVI、受控流和奖励闭合 |
| 真正联合训练 | `model.py`、`content_training.py` | 仅任务交叉熵驱动；审计内容、动力学、边界、复位、不应期实际梯度和更新 |
| 贡献隔离 | 主矩阵中的条件边界、普通物理特征、均值闭合、双门控对照 | 同任务与初始化、相同选择机会、有效参数差不超过 3%、相同训练 CPU 预算 |
| 内容能力 | 主矩阵 176 搜索 / 352 LR 候选 | 6 个固定任务，3-seed 核心；两任务 8-seed 机制对比，4 项 Holm 校正 |
| 传统 SNN | 单独 18 搜索 / 36 LR 候选 | 硬 0/1 LIF 前向、替代梯度、学习漏电与阈值；仅描述性补充 |
| 运行与恢复 | `runtime_eval.py`、`runtime_report.py` | 完整 Adam 步、推理、持续状态字节、独立进程恢复；不推算能耗 |
| 任务控制与真实执行 | `task_value_run.py`、`distributional_native_smoke.py` | 真正 READ/STOP、owner/kernel/NDU 次数、Q24 一致性、quiet 与跨任务恢复 |
| 证据和成本 | `evidence_bundle.py`、`restore_artifacts.py`、各收据 | 含失败尝试、两 LR、全训练日志、所有检查点和原始预测；区分嵌套费用 |

主比较是相同训练 CPU 与验证选择机会，并非声称每个完整实验总成本相同。各模型的验证、推理、求解和启动费用均保留；不同 CPU 吞吐会产生不同训练更新次数。固定 128 步快照不增加主选择机会。

## 3. 目前已经成立的工程与数值结论

1. **当前有限数值问题可以核对。** 最终内核固定每段 uniformization 配置，以 token 自身的时间间隔独立分段。独立参考覆盖长间隔，禁止未来后缀或邻居样本改变另一个 token 的数值结果。其梯度是局部一阶导数，不是所有分支处的全局光滑性。
2. **粗网格上的策略最优性需要单独验证。** 有限 QVI 与全策略枚举一致；部分已声明情形下，允许活动格点立即 FIRE 会提高原策略价值。QVI 没有被回填到冻结的主内容网络中。
3. **实际执行链已打通。** 连续动作价值经固定规则进入真实 owner，改变 KEEP/STOP；STOP 后调用被拒绝，quiet 期间不执行模型；活动状态和 quiet 状态都做了独立进程恢复。
4. **当前 CPU 运行代价较高。** 已完成的 B4/T128 微基准中，分布双值模型完整 Adam 步约为双门控的 18.12 倍、测试中小型 Transformer 的 108.02 倍。数值核局部优化不能替代整模型成本证据。
5. **任务价值结构与预测质量不同。** FIRE 包含后续任务收益，但四置信度状态只是训练数据拟合的粗化模型；已有校准和 native 样例包含负面结果。旧 backbone 上的表格规划器改善不等于新分布架构或学习价值头获胜。

对应完整材料：[数值报告](results/kernel_validation003/REPORT.md)、[有限控制报告](results/grid_control_validation001/REPORT.md)、[运行报告](results/runtime_review001/REPORT.md)、[独立任务审计](results/independent_execution_review001/REPORT.md)、[新分布模型 native 验证](results/distributional_native001/REPORT.md)、[未来收益校准](results/task_future_calibration001/REPORT.md)。

## 4. 数据、统计与规模限制

选择性复制、MQAR 和不规则时间任务分别测试内容记忆与时序外推；合成 OOD 长度从 32 增到 64，不规则任务还将间隔分布乘三。真实任务使用 MNIST、FSDD，以及由真实图像和音频构造的模态选择任务。它们不能代替语义丰富的通用多模态预训练。

每项任务的 TRAIN/VAL/TEST 分别为 1,024/256/512 个 episode；三个合成任务另有 512 个 OOD episode。复制和 MQAR 每个 episode 评分四个目标 token；不规则时间任务评分速率 0.2 的精确漏积分符号。图像任务的三个 split 分别使用 1,024/256/512 张不同原图。音频总计 600 条不同录音，按说话者拆为 300/100/200 条，抽样组成上述 episode；512 个音频测试 episode 不能称为 512 条独立录音。模态选择使用这些真实图像和录音，再由查询指定应回答哪一种模态的数字。原始身份及任务合同见 [v1 data manifests](../hcsn_free_boundary_v1/data/study001/)。

核心仅三个训练种子，准确率、标准差和两百分点筛查是描述性结果。机制比较按八个种子配对，先在两个固定任务内平均，再进行已声明的符号翻转检验和四项 Holm 校正；不能把这两个任务当作随机任务总体。相同测试数据已在 v1 和部分 content001 被观察，因此本轮属于登记后的后续研究，不属于全新测试集的确认性证据。

全部测量在 CPU 环境完成；没有进行 GPU、分布式训练、大语言模型、全模态基础模型、芯片功耗或生产恢复时延测量。固定 recurrent state 字节数不等于固定训练内存，也不证明无限长内容召回。

## 5. 保留的失败与复现原则

早期自适应数值配置存在很小但真实的跨 batch / 未来后缀数值依赖，已保留反例与原源码。随后 content001 的单段时间域假设被真实训练间隔推翻：20 个搜索启动、16 完成、4 失败；剩余搜索未启动。该实验正常排空所有子进程，原日志、已暴露测试结果和完整费用都保留。content002 用独立分段域修复后重新登记，没有复用旧权重或删除失败。

新数据、新模型或新求解器必须建立新的协议与输出目录，不能覆写这些历史收据。恢复器验证每个分片、archive 和成员的 SHA256；已有不同内容会被拒绝覆盖。查看 [REPRODUCE.md](REPRODUCE.md) 的命令与限制。
