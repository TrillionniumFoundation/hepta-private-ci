# Hepta 连续边界研究总交付报告

日期：2026-10-29。仓库：[TrillionniumFoundation/hepta-private-ci](https://github.com/TrillionniumFoundation/hepta-private-ci)。研究权限保持 `DENY_ALL`；研究 PR 保持 draft，未合并主线，也未进行生产 admission。

**两项正式研究及其原始证据交付已经完成：封存源码、全部候选与 checkpoint、原始轨迹、实际二进制和审计均已有公开身份；两份完整包都从公开远端重新获取、恢复，并通过独立语义重审，完整审计分别与归档原件逐字节一致。** 科学结果仍为新读出 0/1、同协议复现 0/4。研究源码与报告通过[命名研究分支](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/research/continuous-boundary-flow-20261028)发布，精确最终提交和对应 CI 状态见 PR 与 Actions；本报告不声称全仓库 CI 通过。

## 1. 本轮得到什么结论

本轮完成了两项互相补充的工作。第一项用新二进制和完整新证据重新执行原 policy 协议，原八个 seed 的四项收益门槛仍为 **0/4**；四项主比较的完整数值对象与保存的历史摘要逐字段一致。第二项固定原生 Hepta encoder、输入与 42 系数读出预算，在新的 16 个配对 seed 上隔离读出训练目标，唯一收益门槛为 **0/1**。两项研究都没有建立预注册要求的收益提升，也没有进行正式等价性检验。[同协议复现报告](continuous_boundary_policy_reproduction/REPORT.zh.md)；[新读出研究报告](native_readout_objective/REPORT.zh.md)

| 研究 | 实际回答的问题 | 样本与确认规模 | 收益结论 |
| --- | --- | --- | --- |
| `continuous_boundary_policy_reproduction` | 原边界、输入通道、符号结构、复位消融能否在重建环境中重复 | 原 8 个 seed、13 臂、26,624 个 episode | 0/4；与旧摘要中的四项主比较完全一致 |
| `native_readout_objective` | 同一真实原生表示与读出容量下，策略目标是否优于迭代 Q 回归 | 新 16 个 seed、3 个学习臂加 DP、16,384 个 episode | 0/1；效用差区间跨越正负值 |

原 `continuous_boundary_flow` 的 **0/3**、原 `continuous_boundary_policy` 的 **0/4** 继续保留。此次同 seed 复现不增加独立样本，不与原结果合并推断；新读出研究也没有重选或追加旧确认集。完整证据审计验证数据、身份和算术是否符合冻结合同，收益门槛判断则检验预先指定的改进要求；两者分别记录。[复现比较](continuous_boundary_policy_reproduction/results/REPRODUCTION_COMPARISON.json)；[读出主比较](native_readout_objective/results/PRIMARY_COMPARISON.json)

**0/1 和 0/4 是已经冻结的科学结果，不属于可通过调参、追加样本或反复运行直到转绿来关闭的工程 blocker。** 后续研究须使用独立方案和新的公开冻结，保留本轮结论。

目前值得保留的成果是：任务价值和首达风险进入策略的明确接口、真实原生执行与成本收据、可核查的选择顺序、完整候选和轨迹，以及有限持久状态恢复证据。现有结果不足以把 signed dual 或连续预期复位提升为默认 neuron，也不足以宣布仅替换读出 loss 已解决原生表示下的任务学习问题。

## 2. 从原始构想到实际实现

最初目标是在 first-passage cell 上引入任务价值驱动的边界、续行与风险两个通道，让实际 Hepta 任务消费连续 margin、风险和活动历史。本轮实现的任务消费者是随机维护模拟：策略选择继续生产、维修或停机，环境计算漂移、扩散、物理失效、维修和状态重置。学习策略最终通过真实原 Rust NDU 产生动作；原生 sparse 对照及新读出研究还实际执行原 sparse kernel。[复现协议](continuous_boundary_policy_reproduction/PROTOCOL.json)；[读出协议](native_readout_objective/PROTOCOL.json)

现有 first-passage 计算提供窗口首达概率 \(F\) 与折现首达量 \(H\)。本次实现使用

\[
P=\text{failure cost}\times H,\qquad C=Q_{\mathrm{keep}}+P,
\]

再按任务尺度归一化；margin 是状态与有限 Bellman 干预边界的标准化距离。历史 flow 来自上一动作的窗口首达概率除以窗口长度，连续复位使用上一动作的预期失效概率。状态、成本、剩余期限和动力学参数向比较臂共同开放，公共训练探索和 DP teacher 也共享。[原封存特征实现](continuous_boundary_policy/features.py)；[复现模型与信息范围](continuous_boundary_policy_reproduction/REPORT.zh.md)

这些定义使价值、风险和活动历史能够被实际策略消费，但还没有实现用户设想的 He–Xiong 双自由边界闭式 Call/Put 动力学。本轮没有施加或验证 value-matching、smooth-pasting；有限网格 Bellman 边界没有成为端到端可微的连续时间自由边界求解器。历史风险比例和预期复位也没有求解概率密度 PDE 或证明边界通量守恒。系统仍包含离散维护/STOP 动作、有限网格和裁剪，所以本轮不能证明连续 margin 传递已消除全系统非光滑性。[复现报告中的数学范围](continuous_boundary_policy_reproduction/REPORT.zh.md)

### 与正在推进的 Hepta neuron 的具体关联

| 路径 | 本轮实际执行 | 能支持的判断 |
| --- | --- | --- |
| 连续 policy 臂 | Python 中的六维持久循环状态；Q24 分数交给原 Rust NDU | 可检验任务边界、通道输入、符号约束和复位方式对闭环任务的作用 |
| 原 `native_sparse` 参考 | width 20、top-k 4 的真实 sparse kernel，加原 NDU；冻结 420 个 encoder 系数，拟合 42 个读出系数 | 提供原生机制的实际执行和通信参考，但与连续 BPTT 模型的训练容量不匹配 |
| 新原生读出研究 | 所有学习臂共享真实 kernel 导出的激活；固定相同 encoder 与 42 个可训练系数，再实际执行 NDU | 隔离读出训练目标，减少上一轮模型家族、表示和训练程序同时变化造成的混杂 |

连续模型分配 464 个系数，完整输入的 dual、GRU、Elman 对照匹配参数和输入预算；掩码臂的部分通道权重没有梯度，不能把所有臂都称为具有 464 个同样活跃的参数。边界回归另有 20 个系数。新原生研究的梯度通过浮点读出训练器，没有穿过原生 Q24 kernel，也没有训练 encoder。因此研究已经接到真实 Hepta 决策组件，但尚未构成整个 neuron 的端到端可微训练。[两类执行范围与容量](continuous_boundary_policy_reproduction/REPORT.zh.md)；[原生训练合同](native_readout_objective/PROTOCOL.json)

## 3. 三个研究问题的实际答案

### 3.1 价值边界是否有用？

同协议复现同时保留固定、学习和价值导出的边界输入。固定、学习和价值 margin 的总体净效用分别为 **3.654023、3.624536、3.605182**；预注册主比较 `value_margin − learned_margin` 为 **−0.019354**，校正区间为 **[−0.203151, +0.164444]**，未建立价值导出边界的最小收益。[各臂结果](continuous_boundary_policy_reproduction/results/ARM_SUMMARIES.json)；[主比较](continuous_boundary_policy_reproduction/results/PRIMARY_COMPARISONS.json)

这里的“学习边界”是用训练 context 的边界 teacher 拟合 20 个回归系数，并非直接从任务奖励端到端学习自由边界位置。当前结论只覆盖所实现的输入构造与策略学习程序。所有方法取得相同的公开任务信息，不能用额外成本或期限信息解释某臂收益，也不能把当前结果扩张成对所有价值边界方法的否定。

### 3.2 双通道是否有用？

`dual_flow − value_call` 的平均增量为 **+0.065674**，但校正区间 **[−0.023117, +0.154465]** 仍未达到收益门槛。该消融同时开放损失通道 \(P\) 与当前窗口首达风险 \(F\)；两臂已经共有上一动作风险形成的历史 flow、失效和维修历史，也采用相同预期复位。因此它检验的是这组新增当前输入，不能把增量单独归因于 Put。[主比较](continuous_boundary_policy_reproduction/results/PRIMARY_COMPARISONS.json)；[通道掩码](continuous_boundary_policy/features.py)

在完整输入和 464 个活跃参数匹配的结构对照中，`dual_flow − generic_gru` 为 **+0.001318**，区间 **[−0.010378, +0.013014]**。这没有建立 signed dual 符号投影约束的额外收益，也没有证明两种结构等效。描述性排名或未经家族校正的 bootstrap 区间没有替代注册判据。

### 3.3 连续 flow 是否值得成本？

`dual_flow − dual_event` 为 **−0.000427**，区间 **[−0.004916, +0.004062]**；区间上限低于预先要求的 **+0.005** 最小改进。本任务和规模下，没有效用依据支持为这一收益目标用预期风险比例复位替换事件复位。[主比较](continuous_boundary_policy_reproduction/results/PRIMARY_COMPARISONS.json)

两臂都获得完整的当前价值和风险信息，差别在于上一动作之后的隐藏状态复位依据：预期失效概率，或实际观测的失效事件。这是可执行的有限窗口近似，不是完整连续概率流方案。普通 GRU、Elman、原生 sparse、事件机制与有限 DP 都保留了结果及实际成本；由于模型容量和训练程序不同，跨架构排名只作描述。

以上四项比较使用原八个配对 seed、df=7、Bonferroni 校正后的 **98.75% 单项区间 / 95% 家族置信水平**。通过条件为区间下限严格大于 **0.005** 且零稳定性失败。实际稳定性失败为零，四项效用条件均未满足，原 **0/4** 保留。

## 4. 新增原生读出实验：缩小一个混杂因素

新实验固定 width 20、top-k 4、420 个 encoder 系数、42 个可训练读出系数、任务信息和真实 kernel/NDU 路径。三个学习臂共享每个 seed 的公共原生训练激活：A 为闭式 ridge 参考，B 为迭代 Q-MSE，C 为 teacher-action 交叉熵加归一化期望 DP regret。唯一确认性比较为 **C−B**；A 同时改变求解器和训练程序，仅作工程参考。B/C 均为零初始化、120 次 Adam 更新、相同正则及三个学习率候选，用真实原生开发轨迹选取模型。[冻结协议](native_readout_objective/PROTOCOL.json)

16 个配对 seed 的结果为：

| 指标 | 结果 |
| --- | ---: |
| C−B 平均净效用差 | −0.005370044 |
| 双侧 95% 配对 t 区间，df=15 | [−0.114120162, +0.103380074] |
| 预注册最小收益 | 区间下限严格大于 +0.005 |
| 确认稳定性失败 | 0 |
| 收益门槛 | 0/1 |

这个区间包含正负差异，既不能宣布策略目标更差，也不能宣布两种目标等效。ID 的描述性 C−B 为 **−0.114318**，OOD 为 **+0.103578**，方向相反；它们不构成追加的确认性检验。[精确主比较与全部 seed 差值](native_readout_objective/results/PRIMARY_COMPARISON.json)

| 臂 | ID 净效用 | OOD 净效用 | 等权总体净效用 |
| --- | ---: | ---: | ---: |
| A：ridge | 4.174394 | 1.869991 | 3.022192 |
| B：迭代 Q-MSE | 4.154577 | 1.822518 | 2.988547 |
| C：策略目标 | 4.040259 | 1.926096 | 2.983177 |
| 有限网格 DP | 4.419771 | 2.772972 | 3.596372 |

DP 是同一有限任务的数学参考，未分配学习臂的原生接口预算；这张表不构成同硬件、同训练开销的产品比较。[各臂完整结果](native_readout_objective/results/ARM_SUMMARIES.json)

独立共同状态诊断为每臂 **6,144 个 ID 窗口**，三个头取得完全相同的原生激活。浮点 affine head 与实际 Q24 head/NDU 的动作差异均为零，因此这组面板没有提供读出量化造成所见动作 regret 的证据。但面板只有 **5 个 STOP teacher 状态**，不覆盖 OOD；不能据此概括 STOP 能力或所有状态下的量化性质。实际训练激活的非零列数为每 seed **9–13**，迭代训练中有非零梯度的系数坐标为 **20–28**。这是覆盖描述，尚不能把 0/1 的原因确定为容量、表示或优化问题。[共同状态面板](native_readout_objective/results/COMMON_STATE_PANEL.json)；[训练覆盖](native_readout_objective/results/AUDIT_SUMMARY.json)

本轮新实验固定了价值边界与输入，所以没有重新回答三种边界或双通道之间的效应。它只表明，在这套原生表示与预算下，仅改变读出训练目标尚未达到所注册的改进要求。

## 5. 风险、长期稳定性与工程验证的边界

### 风险校准

两项研究使用共同解析风险预测器；Brier 和 ECE 来自各策略实际访问、实际动作之后的暴露窗口。策略改变维修和停机行为，也改变暴露分布，因此校准差异不能解释为某个网络把共同预测器训练得更准确。STOP 没有后续风险暴露，不应作为一次零风险预测成功；没有暴露的统计量保持未定义。[复现各臂风险统计](continuous_boundary_policy_reproduction/results/ARM_SUMMARIES.json)；[读出各臂风险统计](native_readout_objective/results/ARM_SUMMARIES.json)

例如，复现中 dual flow / GRU / native sparse 的窗口加权 Brier 分别为 **0.010684 / 0.010497 / 0.017387**；新读出 B/C 分别为 **0.017892 / 0.024998**。C 每 episode 的平均物理失效事件为 **0.435791**，B 为 **0.279297**；失效后可重置继续，因此这不是“至少失效一次”的概率。物理失效事件与实现的稳定性失败分开记录。

### 有限持续状态与冷恢复

| 工程证据 | 实际覆盖 | 范围限制 |
| --- | --- | --- |
| 原生读出 owner | 6 个事先指定的已有 episode；84 步；6 次不同 PID 冷恢复；66 个恢复后继续步骤，轨迹核对一致 | 完整任务状态、剩余创新、模型/profile 与 owner 锚点均恢复；六例没有 STOP，相关后续 tick 拒绝探针覆盖为 0 |
| 同协议复现的连续状态 | 三个选定模型各 8,192 次主更新，共 24,576；21 个新 Python 进程各续行 16 tick，共 336 步，与原后缀精确一致 | 持久 Python recurrence 加真实 NDU；未调用 sparse kernel，不提供 durable native owner 证明 |

这些检查新增的确认收益样本为零，也不证明无限时域稳定性。准备期另有原生 STOP 拒绝语义测试，不能把它写成新选定头的六例 owner 已覆盖 STOP。[owner 结果](native_readout_objective/results/OWNER_SUMMARY.json)；[连续工程结果](continuous_boundary_policy_reproduction/results/ENGINEERING_SUMMARY.json)

## 6. 成本必须按实际执行和统计范围读取

正式数值环境记录在各归档的 `study/ENVIRONMENT.json`。本次使用 Linux x86_64、Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0，BLAS 线程为 1；CPU 型号记录为 AMD EPYC 9V74 80-Core Processor，型号字符串不代表任务独占这些物理核。两项研究的规模、执行程序不同，不能直接把下表当作算法速度竞赛，也不能与旧机器的历史时钟作未经控制的加速比较。[两研究成本记录](native_readout_objective/results/COST_SUMMARY.json)；[复现环境与成本](continuous_boundary_policy_reproduction/results/COST_SUMMARY.json)

| 非重叠科学窗口 | 新原生读出 | 同协议复现 |
| --- | ---: | ---: |
| 原始成本记录数 | 288 | 296 |
| wall 秒 | 130.174260 | 202.066299 |
| Python CPU 秒 | 113.777475 | 184.632007 |
| 已回收子进程 CPU 秒 | 16.639654 | 17.237287 |
| 上述 CPU 合计秒 | 130.417129 | 201.869294 |
| 正式科学阶段真实 sparse kernel 调用 | 290,648 | 69,801 |
| 正式科学阶段真实 NDU 调用 | 272,216 | 385,193 |
| 完整 RPC 请求 bytes | 77,230,404 | 159,387,058 |
| 完整 RPC 响应 bytes | 249,093,332 | 402,150,851 |

读出科学窗口包含训练/开发、确认及共同状态诊断；复现科学窗口包含原协议的训练/开发与确认。原生训练特征导出只运行 kernel，不做 NDU 决策，所以两种调用计数不必相等。模型构造、边界/DP 求解、native 子进程和序列化的子窗口均保留；已包含在外层科学窗口的成本不能再次相加。

完整命令还包括导入、核验、封存写入等开销。训练命令 wall 为读出 **63.301563 秒**、复现 **114.970060 秒**；确认命令为 **68.678786 / 88.931029 秒**。完整确认独立审计另花费 **137.148208 / 135.885586 秒 wall**；owner 工程命令为 **1.446968 秒**，连续状态工程命令为 **37.560465 秒**。这些外围窗口与科学窗口存在包含关系，两个研究又可并行，不能简单相加冒充端到端等待时间。[读出完整成本](native_readout_objective/results/COST_SUMMARY.json)；[复现完整成本](continuous_boundary_policy_reproduction/results/COST_SUMMARY.json)

共用 native 构建记录为 **74.126982 秒 child CPU、37.974985 秒 wall**，最终 score 增量构建为 **2.504603 / 1.515484 秒**。它们没有包含全部工具链下载和准备成本，不应称为完整冷构建成本，也不能在两项研究之间重复收费。打包、远端获取、解包和交付复审成本由相应外围回执另行记录。

效用中的通信价格按固定数值输入计算：每 byte 扣 `1e-6`；读出学习臂每决策 160 bytes，复现连续臂为 24 bytes，native sparse 为 160 bytes。复现四项主比较采用同一 24-byte 口径，读出主比较采用同一 160-byte 口径。完整 JSON 请求、响应与控制调用另行测量，数值输入字节没有替代实际传输成本。

**本轮没有硬件功率或焦耳测量，不作节能结论。** 事件数、观测数、稀疏活动、闭式拟合、CPU 时间与完整通信量都只能按各自的实际口径报告。

## 7. 源码与开发选择先公开，再开启相应阶段

研究使用指定远端分支 `research/continuous-boundary-flow-20261028`。初始化及确认代码检查真实 named remote 的祖先关系，以及公开文件与本地封存原字节一致；仅有本地 commit 字符串不足以满足条件。

| 顺序 | 已记录的公开身份 | 后续允许阶段 |
| --- | --- | --- |
| 两研究源码、协议、复现计划及前置证据 | [7908860](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/7908860cb959cbe1599379d4ecbfcc22fbccbe61) | 创建全新 run，训练与开发选择 |
| 同协议复现的选择封存 | [4fb7482](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/4fb7482ed8506d6646b833124c2975957c3a681c) | 原八 seed 的正式确认 |
| 新原生读出的选择封存 | [87b03617](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/87b03617077f9e5f275d291b7af06cd1418f87ce) | 新十六 seed 的正式确认和注册诊断 |

两次选择公开前都有独立预确认审计，拒绝确认产物；确认没有返回开发集重选、增加 seed 或排除失败样本。复现 source seal 继承原 67 个封存文件；新读出与复现各有自己的来源、协议、执行文件、选择、成本和完整 manifest。详细身份集中保存在 [读出交付来源](native_readout_objective/results/DELIVERY_PROVENANCE.json)与[复现交付来源](continuous_boundary_policy_reproduction/results/DELIVERY_PROVENANCE.json)，本文不重复罗列长哈希。

读出独立审计核验 1,048 个文件、64 个选定 checkpoint、144 个候选训练程序、9,216 个开发 episode、16,384 个确认 episode 和 143,262 个确认原生决策步骤。复现独立审计核验 104 个选定 checkpoint、208 个确认分片、26,624 个 episode、195,584 个连续 recurrent step 和 23,809 个 sparse head step。全部候选、选择、实际轨迹和成本都有原始证据，不只保留胜出模型。[读出审计摘要](native_readout_objective/results/AUDIT_SUMMARY.json)；[复现审计摘要](continuous_boundary_policy_reproduction/results/AUDIT_SUMMARY.json)

审计独立重算相应 Bellman、任务账本、训练/读出或连续 recurrence、Q24 算术及统计，但仍共享封存的数值网格构造器。原生 kernel 通过真实执行、身份及收据核验，没有再实现第二个独立 kernel 并宣称等价；代码与数据哈希也不是外部硬件远程证明。完整审计中的 `scope` 保留这些依赖边界。

## 8. 原始证据交付与历史缺口

### 两份新证据包

两套完整原始包共同保存在 `research/evidence-archive-20261029` 的不可变公开提交 [8dc7def](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8dc7defc17974d67766f35f340eb7bf6e692aefb)。各次独立下载使用的实际提交分别写入下表和原始回执。

| 研究 | 归档入口 | 名册文件数 / 原文件 bytes | 实际公开恢复与复审 |
| --- | --- | ---: | --- |
| 新原生读出 | [evidence/bundle/INDEX.json](native_readout_objective/evidence/bundle/INDEX.json) | 1,484 / 136,972,435 | 完整包已公开于 [b0907a0](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b0907a0eab889b9e1f346a452b7239661a96f9e3)；远端重新获取、文件校验和独立语义重新审计已完成 |
| 同协议复现 | [evidence/bundle/INDEX.json](continuous_boundary_policy_reproduction/evidence/bundle/INDEX.json) | 1,163 / 132,605,133 | 从公开提交 [8dc7def](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8dc7defc17974d67766f35f340eb7bf6e692aefb)重新获取，文件核验和完整独立语义重审均已完成 |

readout 的远端重新获取实际完成 278 次下载，均在首次尝试取得，响应 body 合计 132,561,201 bytes；恢复校验覆盖 1,484 个文件、610 个目录及 136,972,435 个原文件 bytes。该获取命令为 13.512499 秒 wall、2.808375 秒 CPU。[远端获取回执](native_readout_objective/results/PUBLIC_RETRIEVAL.json)与[逐文件校验名册](native_readout_objective/results/PUBLIC_FILE_VERIFY.jsonl.gz)保存实际结果。

随后在恢复出的 `study/` 上重新执行完整独立审计，重新生成的 **547,772 bytes** 审计与归档原件逐字节一致，收益结果仍为 **0/1**；新增训练和样本数均为零。这次交付复审另花费 **139.489895 秒 wall、139.454020 秒 child CPU**，没有写入恢复的科学 run。[重新审计回执](native_readout_objective/results/PUBLIC_ROUNDTRIP_AUDIT.json)；[审计文件绑定](native_readout_objective/results/PUBLIC_ROUNDTRIP_FILES.json)；[外围成本](native_readout_objective/results/PUBLIC_ROUNDTRIP_COST.json)

同协议复现的远端重新获取完成 **266 个对象**，全部首次下载成功，下载 body 合计 **126,454,391 bytes**；恢复核验 **1,163 个文件、428 个目录、132,605,133 个原文件 bytes**。实际获取窗口为 **14.440424 秒 wall、2.858062 秒 Python CPU**。[复现获取回执](continuous_boundary_policy_reproduction/results/PUBLIC_RETRIEVAL.json)；[逐文件校验名册](continuous_boundary_policy_reproduction/results/PUBLIC_FILE_VERIFY.jsonl.gz)

随后针对恢复出的完整 run 重新执行独立确认审计，同时核对两份真实执行文件，`actual_executables_checked=true`。**529,950 bytes** 的复审与归档原审计逐字节一致，原八个 seed、26,624 个 episode 和 **0/4** 结果保持不变，没有新训练或独立样本。复审另耗 **143.917908 秒 wall、143.897780 秒 child CPU**。[复现完整重审回执](continuous_boundary_policy_reproduction/results/PUBLIC_ROUNDTRIP_AUDIT.json)；[审计与二进制身份](continuous_boundary_policy_reproduction/results/PUBLIC_ROUNDTRIP_FILES.json)；[单列成本](continuous_boundary_policy_reproduction/results/PUBLIC_ROUNDTRIP_COST.json)

每个 INDEX 绑定压缩分片、完整 archive 与逐文件 manifest；全部文件身份按名册核验，不能用上述总文件数代替内容检查。两个包分别保存 `study/` 完整 run，以及 `engineering/` 中的原始审计、执行二进制、工程日志、交付身份与外围成本。readout 的工程恢复位于 `engineering/owner/`，复现的连续状态位于 `engineering/continuous_state/`。

新复现以自己的身份提供自含的恢复材料：两个实际执行二进制随完整包交付，也能由独立的 [runtime evidence 入口](continuous_boundary_policy_reproduction/preflight/runtime_evidence/INDEX.json)恢复。runtime 包的 168 文件回环已单独记录，但该准备期包不能替代正式确认轨迹。两份完整正式包的公开恢复和语义重审都已经由各自回执闭合；这些交付检查没有追加科学样本。

### 原 policy 历史档案仍未恢复

已恢复的旧 `continuous_boundary_flow` 档案包含 4,586 个文件；它不包含丢失的 `continuous_boundary_policy` 完整 raw archive，也没有找回两份旧执行文件。原 policy 留存的紧凑结果足以核对四项主比较与共同摘要字段，不能重建未保留的原始轨迹或响应字节。[历史恢复状态](native_readout_objective/RECOVERY_STATUS.json)

本次复现的四项主比较完全相同，共同科学摘要字段相同；实际响应字节存在差异。确认响应从旧摘要的 220,152,550 bytes 变为本次 220,149,644 bytes。响应含实测 RPC 时钟，序列化长度可能变化，但旧原始响应缺失，无法逐条归因。新 CPU、wire、二进制和来源身份均按实测保留，没有改写为旧值。[逐字段复现比较](continuous_boundary_policy_reproduction/results/REPRODUCTION_COMPARISON.json)

新轨迹提供一份单独可恢复、可重新审计的同协议研究；它不等于找回遗失的历史档案，也没有填补旧摘要省略的逐 seed/split 风险分箱和原始成本行。历史缺口作为事实保留，不能以新研究完成为由关闭或删除。

### 复核与全新 run

完整步骤见[读出复现指南](native_readout_objective/REPRODUCE.md)与[同协议复现指南](continuous_boundary_policy_reproduction/REPRODUCE.md)。复核者需要获取保留历史的指定远端分支，按 INDEX 解包到不存在的新目录，并验证实际二进制身份后对 `study/` 运行独立审计。输出放在封存 run 外，不向原 run 写缓存或额外文件。

有限 DP 使用精确数组 digest；复核应恢复 `ENVIRONMENT.json` 记录的 Python/NumPy/SciPy/Linux 数值环境并检查浮点执行差异。环境不一致时应保留并定位差异，不能修改封存协议、摘要期望值或容差来绕过验证。全新 run 必须重新生成并真实公开自己的 selection seal 后才能开启确认，不能复用此次选择提交，也不能把同 seed 的重复运行当作新增独立证据。

## 9. CI、审阅与未关闭状态

研究审计、归档验证和整个仓库的 CI 有各自的验收范围。已保存的 [CI_RUN_B244.json](native_readout_objective/results/CI_RUN_B244.json)对应 source head `b2445c8…` 的实际 workflow 观察，不是最终交付 head 的 CI 证明。截至该回执 2026-10-29 17:01:30 UTC 的更新，b244 的 source-head 架构任务已真实执行原生步骤并完成：31 条命令记录中含 29 个测试命令，失败为零，各记录均绑定 b244 和干净工作树；旧 base-merge 任务中跳过原生步骤的事实另行保留。其他 blocking 作业仍有失败及运行中状态，后续提交必须有自己的状态记录。[PR #4157](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4157)继续作为 draft 审阅，CI 使用的 prospective merge commit 不代表主线已经合并。

| 已观察问题 | 实际处理或保留状态 |
| --- | --- |
| Codespell 把压缩 evidence 当文本扫描 | 历史作业记录 651 条压缩字节诊断和 15 条普通文本诊断；六类 archive 路径已做狭义规则修复及真实工具验证，历史失败没有改写 |
| 普通文本与格式基线 | 15 条普通文本诊断涉及的文件与冻结基线相同；格式失败点为两个既有 scripts 文件；本轮没有改动这些继承字节 |
| Linux / Windows 编译、lint 或测试失败 | 已记录未改动 codex-rs 树上的具体错误；源码与冻结基线相同不等于已经证明历史 CI 当时同样失败 |
| macOS ARM Bazel 运行 | 记录线程/内存资源失败，不推断成科学实验失败 |
| cargo-deny | 作业失败已观察，失败日志获取受限，根因尚未建立；不归类为已经定位或修复 |
| Blob-size 检查 | 作业在完整历史获取阶段被取消，实际 size check 尚未执行；没有日志证据判断取消触发者 |
| 最终发布 head 的完整 CI | 通过 PR 与 Actions 按精确提交和观察时间读取，不复用旧 head 或被跳过步骤的通过状态 |

本轮配置修复保留旧无前缀规则，增加默认递归 `./` 路径对应规则，覆盖旧 flow/policy bundle、新两份 bundle、runtime parts 与 native preflight tar。官方 Codespell 2.4.3 的六项行为检查证明这些资产被排除，普通 Markdown 及相邻 INDEX JSON 中的错词仍失败。该版本 CLI `--skip` 采用追加行为，首轮误扫由 `./` 路径匹配问题复现；验证记录保留最初失败与解释修正。CI 回执中的历史错词诊断以可逆 base64 和 SHA 保存，修复后的新增回执单文件检查无诊断。[CODESPELL_CONFIG_VALIDATION.json](continuous_boundary_policy_reproduction/results/CODESPELL_CONFIG_VALIDATION.json)

新增研究 namespace、总报告与本轮其他改动文本有[明确范围的 Codespell 检查](continuous_boundary_policy_reproduction/results/CODESPELL_NEW_TEXT_LINT.json)，最终报告追加及两套公开回执另保留[最终增量检查](continuous_boundary_policy_reproduction/results/DELIVERY_FINAL_LINT.json)；两份记录各自只覆盖其中列明的文件快照，旧记录未被覆盖或改写。窄范围 workflow Prettier 检查和必需 `just fmt` 已完成，未修改封存科学文件；这不构成全仓格式或全部 CI 通过。既有基线问题、受限日志和最新 head 的状态都继续公开记录。`DENY_ALL`、draft 和未合并状态保持不变。

## 10. 交付索引与后续研究

| 交付对象 | 可核查入口与范围 |
| --- | --- |
| 研究源码与报告 | [命名研究分支](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/research/continuous-boundary-flow-20261028)；具体版本以 PR 的精确提交为准 |
| 两套完整原始包 | [不可变证据提交 8dc7def](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8dc7defc17974d67766f35f340eb7bf6e692aefb)，位于 `research/evidence-archive-20261029` |
| readout 远端获取与文件恢复 | [获取回执](native_readout_objective/results/PUBLIC_RETRIEVAL.json)和[逐文件名册](native_readout_objective/results/PUBLIC_FILE_VERIFY.jsonl.gz)，实际下载提交 b0907a0 |
| readout 完整重新审计 | [复审回执](native_readout_objective/results/PUBLIC_ROUNDTRIP_AUDIT.json)、[身份绑定](native_readout_objective/results/PUBLIC_ROUNDTRIP_FILES.json)、[外围成本](native_readout_objective/results/PUBLIC_ROUNDTRIP_COST.json)；完整审计逐字节一致，0/1 保留 |
| reproduction 远端获取与文件恢复 | [获取回执](continuous_boundary_policy_reproduction/results/PUBLIC_RETRIEVAL.json)和[逐文件名册](continuous_boundary_policy_reproduction/results/PUBLIC_FILE_VERIFY.jsonl.gz)，实际下载提交 8dc7def |
| reproduction 完整重新审计 | [复审回执](continuous_boundary_policy_reproduction/results/PUBLIC_ROUNDTRIP_AUDIT.json)、[身份绑定](continuous_boundary_policy_reproduction/results/PUBLIC_ROUNDTRIP_FILES.json)、[外围成本](continuous_boundary_policy_reproduction/results/PUBLIC_ROUNDTRIP_COST.json)；两份执行文件已核查，完整审计逐字节一致，0/4 保留 |
| 公开事务与恢复工具 | [归档公开名册](evidence_tools/ARCHIVE_PUBLICATION.json)保存 544 个 blob 和 14 个 commit 的公开流水；[格式等价记录](evidence_tools/FORMAT_EQUIVALENCE.json)绑定实际恢复工具身份 |
| 文本交付检查 | [DELIVERY_FINAL_LINT.json](continuous_boundary_policy_reproduction/results/DELIVERY_FINAL_LINT.json)列明最终增量文件和检查结果；原科学 seal 与历史 lint 回执保留 |
| 精确 head 的 CI / PR 状态 | [PR #4157](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4157)与 [Actions](https://github.com/TrillionniumFoundation/hepta-private-ci/actions)；历史 b244 回执继续保留，不推广为其他提交的通过证明 |

公开事务名册保留生成时的历史状态：独立证据分支已具备上述完整锚点，主研究 ref 的最后推进另行记录。研究交付与档案复审完成不会改写旧 policy raw 缺失，也不会把继承 CI 失败、受限日志或未执行检查改成通过。

科学结果仍按 **新读出 0/1、原八 seed 复现 0/4** 表述。未来若继续研究，优先另立能识别具体原因的方案：奖励驱动的边界学习、匹配表示学习预算，或预先覆盖 ID/OOD、维修与足够 STOP 状态的共同诊断。若目标转向 He–Xiong 特有的自由边界条件或概率密度边界流，应增加对应数学和数值验收；这些属于新的研究，不能追加到已经封存的确认样本或把当前未通过门槛改写为通过。
