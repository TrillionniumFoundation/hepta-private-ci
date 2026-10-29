# 同种子、新二进制的 Hepta continuous policy 复现报告

## 结论

**本次完整复现通过独立证据审计，四项预注册收益门槛仍为 0/4。四项主比较的完整数值对象，包括八个 seed 的差值、同时置信区间、描述性 bootstrap 和通过状态，与保存的原研究摘要逐字段相同。** 这支持原注册实验在本次重建执行环境中的可重复性，未建立价值边界、增加风险输入、signed dual 结构或连续预期复位的额外收益。

这是一项明确标识的**相同八个 seed、原算法、新二进制、新轨迹和新成本**复现。它不增加独立训练重复，不与原研究合并推断，也不替换原 policy 0/4 或更早 flow 0/3 的历史结论。原 policy 完整 raw archive 和两份旧二进制仍未恢复；新记录不能改称遗失原记录的恢复。范围预先写入 [REPRODUCTION_PLAN.json](REPRODUCTION_PLAN.json)，新旧结果的精确比较见 [REPRODUCTION_COMPARISON.json](results/REPRODUCTION_COMPARISON.json)。

这里的证据支持继续研究可消融的 margin、价值和风险输入接口，但不支持将 signed dual 结构或连续 flow 直接升为默认 neuron。原生 sparse 与连续网络的容量和训练程序仍不匹配，应由另行注册的 [native_readout_objective](../native_readout_objective/README.zh.md) 隔离读出训练目标，而不是用本次描述性排名判定原 sparse kernel 的优劣。

## 公开顺序、身份和实际规模

源码、原字节协议、新复现计划及前置证据先公开于 [7908860](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/7908860cb959cbe1599379d4ecbfcc22fbccbe61)，之后才初始化、训练。训练完成后，独立预确认审计通过，选择封存先公开于 [4fb7482](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/4fb7482ed8506d6646b833124c2975957c3a681c)，之后才开启确认。驱动器实际核对 named remote 祖先关系及公开文件原字节。

| 对象 | SHA-256 |
| --- | --- |
| 新 source seal | `6608ee0c6ddd33862096a3c7d5085ab670b05a7c4c45d728f9f59efaa064b717` |
| 与原研究相同的 protocol | `c55747dd06640b92aca2198dcbfa21a0a5bf53f5890daf6bc51aa257f887865a` |
| 新 selection seal | `c996086ace2ab38f25b24a8b8f29e1eeba447100b2dcb212a4438e595bb7fa56` |
| 新完整科学 manifest | `6bed365c60eec46e588b9a0ffa21e4f3c05d4f43928350dcdd13a3fdbe64b790` |
| 完整确认审计 | `7cb7b95f62bfc32218830e1c10bed2997bde8f2ffa1ffc238648fe99a9fac42f` |
| 预确认审计 | `89109cf2ea45406c09aff6be3f752742647e2454082c5b1821aae60c4f1bce6b` |

八个 seed 为 2203、2207、2213、2221、2237、2239、2243、2251，全部来自原注册协议。每 seed 的 12 个训练 context 各有八条公共探索轨迹；八个开发 context 各有八条轨迹；确认包含各八个 ID/OOD context、每 context 16 条轨迹。两种确认分布等权，统计单位是八个配对训练/环境 seed。

| 核验项目 | 本次实际完成 |
| --- | ---: |
| 学习方法 / 控制策略 | 9 / 4 |
| BPTT 候选 / native ridge 候选 | 192 / 24 |
| 选定 checkpoint（含控制） | 104 |
| 预确认 train/dev contexts / 训练收据 / 成本窗口 | 160 / 72 / 80 |
| 每方法确认 episodes | 2,048 |
| 确认 episodes / shards | 26,624 / 208 |
| 独立重算的连续 recurrent steps | 195,584 |
| 核验的真实 sparse head steps | 23,809 |
| 全部方法与控制合计决策步骤 | 294,384 |
| 全部确认稳定性失败 | 0 |

预确认阶段没有确认产物，也没有生成确认随机流；最终审计检查全部确认分片，并验证两个实际执行文件的字节身份。紧凑视图见 [AUDIT_SUMMARY.json](results/AUDIT_SUMMARY.json)，完整原审计为 529,950 bytes，保存在归档 `engineering/audits/CONFIRMATION_AUDIT.json`。紧凑视图明确省略原始成本行和逐 seed 校准分箱，完整值仍在原审计中。

## 三个研究问题与一项结构检验

四项预注册比较采用配对 seed Student-t 区间，df=7；Bonferroni 校正后每项置信水平 98.75%，家族置信水平 95%。收益要求为**区间下限严格大于 0.005，且零稳定性失败**。以下均未满足收益条件；不是因执行异常丢弃样本。

| 比较 | 平均净效用差 | 校正置信区间 | 收益通过 |
| --- | ---: | --- | --- |
| value_margin − learned_margin | −0.019354 | [−0.203151, +0.164444] | 否 |
| dual_flow − value_call | +0.065674 | [−0.023117, +0.154465] | 否 |
| dual_flow − generic_gru | +0.001318 | [−0.010378, +0.013014] | 否 |
| dual_flow − dual_event | −0.000427 | [−0.004916, +0.004062] | 否 |

原精度、每 seed 差值和全部推断字段见 [PRIMARY_COMPARISONS.json](results/PRIMARY_COMPARISONS.json)。这不是第二组独立证据，不重新累计显著性，也不以描述性区间替换注册区间。

### 价值边界是否有用？

固定、拟合和价值导出 margin 的总体净效用分别为 3.654023、3.624536、3.605182。主比较 `value_margin − learned_margin` 为 −0.019354，区间包含较大的正负差，没有建立价值导出边界的最小收益；三个均值的排序本身不是追加的显著性检验。

所有方法获得相同公开状态、成本、剩余期限和动力学参数，并共用训练探索与 DP teacher。这里的 `learned_margin` 用训练 context 的边界 teacher 拟合 20 个回归系数；它**不是以任务奖励端到端训练边界位置**。价值法使用同一有限任务的 Bellman 干预边界。比较因此回答“所实现的边界输入构造是否帮助这个策略学习程序”，不能扩张成对所有直接奖励学习自由边界方法的否定。

### 双通道输入与结构是否有用？

`dual_flow − value_call` 的均值为 +0.065674，七个 seed 的差值为正；ID 增量为约 +0.013051，OOD 增量约 +0.118296。其描述性 bootstrap 95% 区间为 [0.019686, 0.116102]，但四项校正后的注册区间下限仍为负，故门槛不通过。

这项消融同时开放 **P 与当前窗首达风险 F**。两臂已经共同获得上一动作风险形成的历史 flow、失败和 repair 历史，并采用相同风险比例复位。因此它识别的是损失/当前风险输入包的增量，不能单独归因于 Put，也不能声称新增了一条原本不存在的历史 flow 通道。具体掩码见原封存 [features.py](../continuous_boundary_policy/features.py)。

结构比较 `dual_flow − generic_gru` 则保持完整输入、状态维数、初始化的有效权重、优化预算和 464 个活跃参数匹配，比较符号投影约束。均值仅 +0.001318，注册区间仍包含正负差，没有建立 signed dual 结构的额外收益，也没有进行正式等价性检验。

### 连续 flow 是否值得成本？

`dual_flow − dual_event` 为 −0.000427，区间上限约 0.004062，低于所设 +0.005 最小收益线。本任务和注册规模下，没有效用依据支持为所设收益目标把事件复位替换为预期风险比例复位。这个区间不能被改称预注册等价性结论。

两臂均获得完整当前风险和价值信息，差别是隐藏状态复位使用上一动作的预期失败概率，还是使用已观察到的失败事件。它不是将整个系统转换成概率密度 PDE 的试验。事件、连续网络、普通 GRU、Elman、原 native sparse 以及有限 DP 的结果与实测成本都保留；不同架构间的描述性排名不补成额外主比较。

## 全部方法的确认表现

每行包含 2,048 条 episode；ID、OOD 各 1,024 条。物理失败次数与稳定性失败分开报告，后者所有方法均为零。完整校准分箱、动作账本和原精度见 [ARM_SUMMARIES.json](results/ARM_SUMMARIES.json)。

| 方法 | ID 净效用 | OOD 净效用 | 总体净效用 | 平均步骤 | 物理失败次数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| dp | 4.481739 | 3.047225 | 3.764482 | 11.741699 | 217 |
| dual_event | 4.472524 | 2.889743 | 3.681134 | 11.937500 | 319 |
| dual_flow | 4.476239 | 2.885173 | 3.680706 | 11.937500 | 324 |
| generic_gru | 4.479685 | 2.879091 | 3.679388 | 11.937500 | 319 |
| elman_mlp | 4.477093 | 2.866221 | 3.671657 | 11.937500 | 328 |
| fixed_margin | 4.443296 | 2.864750 | 3.654023 | 11.937500 | 318 |
| learned_margin | 4.467505 | 2.781567 | 3.624536 | 11.937500 | 358 |
| value_call | 4.463188 | 2.766877 | 3.615033 | 11.937500 | 419 |
| value_margin | 4.459989 | 2.750376 | 3.605182 | 11.937500 | 430 |
| native_sparse | 4.148133 | 2.089840 | 3.118986 | 11.625488 | 602 |
| always_keep | 2.641324 | 0.404099 | 1.522712 | 11.937500 | 2,708 |
| always_repair | 1.533210 | −1.032059 | 0.250576 | 11.937500 | 142 |
| always_stop | 0 | 0 | 0 | 1 | 0 |

物理失败合计 6,484 次是跨 13 策略的汇总，不是单个部署策略的失效率。所有连续学习臂的确认 STOP 次数均为零；DP 每 episode 平均 0.063965 次，native sparse 为 0.087402 次。访问分布不同，不能仅凭这些均值判断某一步动作错误，但也不能称连续策略已经完整学会 DP 的全部动作区域。

共同解析风险预测器在不同策略访问分布上的校准如下：

| 方法 | Window-weighted Brier | ECE |
| --- | ---: | ---: |
| dp | 0.008245 | 0.000956 |
| dual_flow | 0.010684 | 0.001742 |
| dual_event | 0.010533 | 0.001818 |
| generic_gru | 0.010497 | 0.001923 |
| elman_mlp | 0.010348 | 0.001967 |
| native_sparse | 0.017387 | 0.001864 |

这些值描述策略访问和动作后的风险曝光，不证明某个网络学到了更准确的风险预测器。`always_stop` 没有风险曝光，Brier/ECE 为未定义，而不是零误差。

## 模型、信息预算和原生执行范围

连续模型分配 464 个可训练系数、六维持久隐藏状态。对完整输入的 dual/GRU/Elman，参数和输入预算进行匹配；margin 等掩码臂的某些当前通道权重没有梯度，不能把“分配 464”说成所有臂均有 464 个同样活跃的参数。`learned_margin` 另有 20 个边界回归系数。原 sparse 参考冻结 420 个 encoder 系数，只用 ridge 拟合 42 个 head 系数，并不是与 464 参数策略 BPTT 的容量匹配对照。[PROTOCOL.json](PROTOCOL.json)明确保留这一限制。

连续模型的 recurrence 在 Python 中执行，分数转 Q24 后送入真实原 Rust NDU；它们没有调用原 sparse kernel，也没有由 Python 替代最终动作选择。`native_sparse` 才同时调用真实 width-20、top-k-4 sparse kernel 与原 NDU；18 项公共信息通过 20 个原生输入传递，其中两项是明确的重复通道。正式确认核验 219,393 次 NDU 决策，其中 23,809 次带 sparse kernel。

因此，GRU 的 3.679388 与 native sparse 的 3.118986 之差不能单独归因于 neuron 动力学。训练目标、训练容量和结构同时变化。相邻的原生读出目标研究固定相同 sparse encoder 和 42 个 head 参数，将迭代 Q-MSE 与策略目标作为主比较，才针对其中一个混杂因素；其结果应单独报告，不能反过来修改本复现的判定。

## “自由边界、Call/Put、flow”在这里的准确含义

本任务的状态是受漂移/扩散和维护动作影响的有限决策过程。基础 first-passage 实现提供当前窗口首达概率 F，以及折现首达量 H；由它们构造风险和期望损失输入。这里采用 `P = failure_cost × H`，`C = Q_keep + P`，随后按同一任务尺度归一化；margin 是状态与有限 Bellman 干预边界的标准化距离。[features.py](../continuous_boundary_policy/features.py)给出实际公式与裁剪。

这没有求解用户设想的 He–Xiong 双自由边界 Call/Put，也没有施加或验证 value-matching、smooth-pasting 条件。有限网格 DP 是任务 teacher 和参考策略，不能称为原连续时间模型的闭式精确解；独立有理数 DP 夹具的精确性只针对其小型有限 MDP。

历史 flow 使用上一动作的窗口首达概率除以窗口长度，隐藏状态复位使用该概率比例。它不是连续状态概率密度的 PDE 边界通量，没有求解密度守恒方程或给出网格收敛后的 flux 证明。模型仍有离散维护/STOP 动作、有限网格边界及裁剪，也没有将边界求解器纳入完整端到端梯度。因此本研究不能证明以连续 margin 传递就消除了全系统非光滑性。

## 新执行环境中的实际成本

正式环境记录为 AMD EPYC 9V74 80-Core Processor 型号字符串、Linux 6.18.55 x86_64/glibc 2.39、Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0，BLAS 线程设为 1。型号名称不代表本任务独占相应物理核。新 CPU/wall 和 wire 收据按实际测量保留，不能把它们换成旧研究时钟，也不能因新旧测量条件未经控制就宣称加速。

### 科学窗口

296 条互不重叠的科学成本记录合计 **201.869294 CPU 秒、202.066299 wall 秒**；CPU 含 Python 184.632007 秒与已回收子进程 17.237287 秒。逐 PID native CPU 为其中的子集，不能再次相加。[COST_SUMMARY.json](results/COST_SUMMARY.json)保留原精度、分臂窗口、实际通信和外围收据。

| 阶段 | Python CPU 秒 | 已回收子进程 CPU 秒 | Wall 秒 |
| --- | ---: | ---: | ---: |
| 训练共享模型/teacher/边界准备 | 6.877563 | 0 | 6.878454 |
| 训练与开发选择 | 98.221412 | 8.654499 | 107.188610 |
| 确认共享模型/DP准备 | 1.933259 | 0 | 1.933423 |
| 确认 rollout | 53.729781 | 8.582788 | 62.191338 |
| 确认序列化 | 23.869991 | 0 | 23.874475 |

每臂的 CPU 包围窗口如下，已包含该窗口内 native 子进程；共享准备成本另在上表，不重复按臂分摊。

| 学习臂 | 训练+开发 CPU 秒 | 确认 rollout CPU 秒 | 确认序列化 CPU 秒 |
| --- | ---: | ---: | ---: |
| fixed_margin | 12.794181 | 5.280934 | 2.478095 |
| learned_margin | 13.102494 | 5.500324 | 2.274216 |
| value_margin | 12.706507 | 5.685623 | 2.403943 |
| value_call | 12.685785 | 5.732840 | 2.380978 |
| dual_flow | 12.642219 | 5.632311 | 2.514672 |
| generic_gru | 12.310120 | 5.482631 | 2.472099 |
| dual_event | 12.685484 | 5.499077 | 2.425242 |
| elman_mlp | 10.438360 | 5.227372 | 2.572457 |
| native_sparse | 7.510760 | 6.459272 | 2.214017 |

这些是本次实现和运行的描述性成本，没有新增速度显著性检验。训练拟合、实际原生动作、完整运行与序列化分别可见，不能用较少事件替代完整成本测量。

### 数值负载和完整 wire

确认的计价数值输入合计 **8,503,456 bytes**；完整请求 **86,876,198 bytes**，完整响应 **220,149,644 bytes**。连续策略每次决策输入三个 i64 score，即 24 bytes；native sparse 每次为 20 个 i64 特征，即 160 bytes。按每 byte `1e-6` 从效用扣减的只是前述数值输入，不是全部 JSON framing；四项主比较使用相同 24-byte 计价。

训练/开发加确认的完整 native process 计数为 69,801 次 sparse kernel、385,193 次 NDU；全程请求 159,387,058 bytes、响应 402,150,851 bytes。它们包含训练/开发过程，不能与只含确认的原始决策计数相混。

### 编译、审计和工程外围窗口

| 包围命令 | Child CPU 秒 | Wall 秒 |
| --- | ---: | ---: |
| 完整训练命令 | 114.652958 | 114.970060 |
| 预确认独立审计 | 4.458464 | 4.459104 |
| 完整确认命令 | 89.040007 | 88.931029 |
| 完整确认独立审计 | 135.841220 | 135.885586 |
| 连续状态工程命令 | 37.188111 | 37.560465 |

完整训练/确认命令包含导入、验证、封存写入和内层科学窗口，不能再加到科学窗口上当作额外科学成本；审计与工程是另外的命令。wrapper 自身 CPU 另保留于原始收据。归档、解包、公开等交付成本以各自外围收据为准，不填入尚未测量的数字。

共用 native 构建计时为 child CPU 74.126982 秒、wall 37.974985 秒；最终 score 增量构建为 child CPU 2.504603 秒、wall 1.515484 秒，预格式构建和实际测试收据也保留。这些构建在核验和准备之后计时，不能称为包含全部工具链下载的冷构建总成本，也不能在两个研究间重复收费。

**本研究没有测量硬件功率或焦耳，没有节能结论。** CPU、wall、事件数、数值负载和完整 wire 都不能单独推出硬件能耗降低。

## 有限持续状态与冷恢复工程结果

本次对 seed 2203 选定的 `dual_flow`、`generic_gru`、`elman_mlp` 各运行 8,192 次主状态更新，合计 **24,576**；每 1,024 tick 存 checkpoint，21 个全新 Python 进程各续行 16 tick，合计 **336** 个 replay step，全部与原后缀精确一致。新增确认样本为零。[ENGINEERING_SUMMARY.json](results/ENGINEERING_SUMMARY.json)绑定完整原工程 summary SHA：`c2cc57d23df0aac12134bbec81eb712895d1332ce82d1a36a75bb0e99e964001`。

工程内部总窗口是 Python CPU 20.199766 秒、已回收子进程 16.494327 秒，即合计 **36.694093 CPU 秒、37.066261 wall 秒**。其主循环、native、序列化和冷启动子窗口已包含其中；外部完整命令窗口如上表。

同一组 4,096 行 warm 输入上，单次 Python cell 推理平均 CPU 为 dual 161.143 µs、GRU 130.529 µs、Elman 67.094 µs。这一子窗口含输入/参数检查，排除特征生成、环境、序列化、NDU 和 IPC；不能用它代表整个任务运行，也不对优化过的原生实现作速度结论。

工程执行的是持久 Python recurrent policy 加真实原 NDU，未调用 sparse kernel，不构成 durable native owner 证明，也不能证明无限时域稳定性。相邻原生读出研究的 owner 冷恢复属于另一份证据。

## 与原研究一致的部分，以及真实保留的差异

对保存的原 [AUDIT_SUMMARY.json](../continuous_boundary_policy/results/AUDIT_SUMMARY.json)逐字段核查得到：

- 四项 `paired_comparisons` 完全相同；0/4、确认数量、检查点数量、连续/sparse 步数和有限 DP 核验均相同。
- arm summaries 的所有共同科学字段相同；27 个不同叶字段均为实际 `wire_response_bytes`。
- seed summaries 的共同科学字段也相同；142 个不同叶字段仍只涉及实际响应字节。
- 原紧凑摘要明确省略逐 seed/split 的 calibration bins 和原始成本行。本次完整审计含 208 组相关分箱，不能把旧摘要未保存的内容误称为“已比对相同”或“数值发生变化”。

确认响应字节由旧摘要的 **220,152,550** 变为本次 **220,149,644**，相差 **−2,906 bytes**。两个 host 的响应 JSON 都带实测 `physical_rpc_micros`，其位数可以改变序列化长度；这为变动提供了协议层面可能解释。因旧原始响应未恢复，不能作逐条历史归因。新 wire、CPU、二进制、source/selection/manifest 和 audit 身份均原样保留，不为获得字节一致而改写。

这次完成的是：以明确的新身份保存一份可重新审计的同协议运行，并复现原统计摘要中的科学结论。历史缺口仍须在文档中保留，不能把复现成功说成原 archive 已找回。

## 证据入口与下一步

新原始归档入口为 `evidence/bundle/INDEX.json`；解包后 `study/` 是完整 run，`engineering/continuous_state/` 是工程记录，`engineering/audits/` 是独立审计，`engineering/bin/` 是实际执行文件，外围成本与交付身份另存。完整新归档已完成公开远端获取、逐文件核验和独立语义复审，实际回执见末节。恢复与新 run 的严格公开流程见 [REPRODUCE.md](REPRODUCE.md)。

本目录 `results/` 的六份 JSON 都绑定完整新审计 SHA；它们是机械提取和比较，不重新训练、不重新观察，也不新建统计检验。完整审计重算全部确认步骤，验证所有候选预算、teacher/输入摘要、开发收益和选择算术；没有重新运行每个开发 native 过程。有限网格构造器仍是共同封存依赖，独立 Bellman、首达标量、连续 recurrence、Q24 head 和统计检查的范围分别保留。数据哈希与原生收据不是外部硬件远程证明。

下一步应把原生读出训练目标的独立研究结论与本报告并列，再决定是否需要新的边界学习或结构方案。若未来要证明 He–Xiong 特有的自由边界/光滑黏贴或概率流机制，须另立能够区分这些机制的数学与数值验收；不能在当前有限 DP 结果上补贴该名称。研究保持 `DENY_ALL`，不触发生产 admission 或主线合并。

## 公开档案恢复与完整复审

本次新复现的完整 raw 包已公开在证据分支 `research/evidence-archive-20261029` 的不可变提交 [8dc7def](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8dc7defc17974d67766f35f340eb7bf6e692aefb)。从该公开提交独立下载的 **266 个对象**全部首次成功，下载 body 合计 **126,454,391 bytes**；恢复并逐项核验 **1,163 个文件、428 个目录、132,605,133 个原文件 bytes**。实际获取窗口为 **14.440424 秒 wall、2.858062 秒 Python CPU**，没有用本地原包复制替代公开远端获取。[公开获取回执](results/PUBLIC_RETRIEVAL.json)；[逐文件校验名册](results/PUBLIC_FILE_VERIFY.jsonl.gz)

对恢复出的完整 run 重新执行独立确认审计时，实际核查了包内 `continuous_host` 和 `boundary_policy_score_host` 两份执行文件，`actual_executables_checked=true`。完整复审输出为 **529,950 bytes**，与归档原审计逐字节一致；26,624 条 episode、104 个 checkpoint、208 个 shard、195,584 个连续 step 和 23,809 个 sparse head step 均保持原结果，四项收益门槛仍为 **0/4**。原八个 seed 未变，没有新增训练或独立样本。[完整复审回执](results/PUBLIC_ROUNDTRIP_AUDIT.json)；[审计与二进制文件身份](results/PUBLIC_ROUNDTRIP_FILES.json)

本次公开档案的独立语义复审另耗 **143.917908 秒 wall、143.897780 秒 child CPU**，包装器 CPU 另列于[复审成本回执](results/PUBLIC_ROUNDTRIP_COST.json)。它属于交付验证成本，不加入原科学计时，也不改变科学推断。这里闭合的是新身份复现包的公开恢复与复审；原 policy 历史 raw archive 和旧二进制的缺失仍然保留。

源码和报告入口为[命名研究分支](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/research/continuous-boundary-flow-20261028)，完整恢复流程见 [REPRODUCE.md](REPRODUCE.md)，跨研究交付见[中文总报告](../RESEARCH_DELIVERY_2026-10-29.zh.md)。最终提交与对应仓库 CI 通过 [PR #4157](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4157)及 [Actions](https://github.com/TrillionniumFoundation/hepta-private-ci/actions)定位；本次回环不构成全仓库 CI 通过、生产 admission 或主线合并。
