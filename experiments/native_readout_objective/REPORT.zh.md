# 固定 Hepta 原生内核的读出训练目标实验：0/1 收益门槛

日期：2026-10-29。研究状态：正式训练、开发选择、独立确认审计与六例持久化恢复验证均已完成。完整原始档案已公开，远端重新获取、恢复和独立语义重审均已完成，详见末节的实际交付收据。

## 1. 主要结论

**在本次固定的 16 个配对 seed、任务分布、冻结原生 encoder 和 42 系数读出预算下，策略目标没有通过相对匹配迭代 Q 回归的预注册收益门槛：0/1。** `policy_regret − iterative_q_mse` 的平均净效用差为 **−0.005370044**，双侧 95% 配对 seed t 区间为 **[−0.114120162, 0.103380074]**。门槛要求区间下限严格大于 **0.005**，并且稳定性失败为零；本次稳定性失败为零，但效用区间未满足要求。[主比较原始精度数据](results/PRIMARY_COMPARISON.json)

这个区间同时包含正负差异，**不能据此宣布两种训练目标等效，也不能宣布策略目标更差**。点估计靠近零不构成等效检验；有限样本的不确定性仍然较大。独立审计通过意味着来源、数据阶段、算术、轨迹、选择和统计符合冻结合同；它与收益门槛是否通过是两个不同结论。[独立审计摘要](results/AUDIT_SUMMARY.json)

旧 `continuous_boundary_flow` 的 **0/3** 与旧 `continuous_boundary_policy` 的 **0/4** 分别保留。本次采用新的 16 个 seed，没有追加旧确认样本、重新选择旧模型或合并三个研究的门槛。另行进行的旧研究复现也不能增加旧结果的独立样本数。[旧 flow 报告](../continuous_boundary_flow/REPORT.zh.md)；[旧 policy 报告](../continuous_boundary_policy/REPORT.zh.md)

## 2. 本次检验的具体问题

上一轮模型比较同时改变了模型家族、可训练表示、参数量与训练目标。本次把 Hepta 的原生 sparse kernel、原 NDU、宽度 20、top-k=4、冻结的 420 个 encoder 系数，以及 42 个可训练读出系数固定下来，检验改变读出训练目标是否带来收益。所有学习臂消费同样的任务状态、期限、成本、价值边界 margin、续行值、风险和历史活动信息。[冻结协议](PROTOCOL.json)

| 臂 | 训练程序 | 统计角色 |
| --- | --- | --- |
| A：`ridge_reference` | 沿用旧闭式 ridge；正则候选 0.001、0.01、0.1 | 整个训练程序的工程参考 |
| B：`iterative_q_mse` | full-batch Adam，拟合物理 keep/repair Q 除以 8 | 唯一主对照 |
| C：`policy_regret` | 同样 Adam，teacher-action 交叉熵加归一化期望 DP regret | 唯一主处理 |
| `finite_grid_dp` | 相同有限网格任务上的 DP 数学策略 | 数学参考，不分配学习或原生接口预算 |

B/C 均从精确零初始化开始，执行 120 次更新，学习率候选固定为 0.005、0.02、0.05；Adam 的 beta 为 0.9/0.999，epsilon 为 `1e-8`，梯度范数上限为 5，系数绝对值上限为 7.5。两者使用同样的非 bias 正则 `1e-4 × mean(40 个权重的平方)`。每臂恰好三个候选，由真实原生开发集净效用选择，平局选较小候选索引。A 与 B/C 同时改变求解器和训练程序，因此 A 的数值排名不能隔离为 loss 效应。[协议](PROTOCOL.json)；[选择与训练覆盖摘要](results/AUDIT_SUMMARY.json)

三个学习臂共享每个 seed 由真实 `NativeBridge.kernel_batch` 导出的公共探索激活矩阵，而不是分别仿真 encoder。物理 teacher 从原 `target_q × 8` 恢复，再追加恒为零的 STOP Q。读出使用 20 个原生激活和常数项，学习 keep/repair 两个 affine 分数；STOP 的权重和 bias 恒为零。原 NDU 消费 Q24 分数决定每一步实际任务动作。梯度经过浮点读出训练器，不穿过原生 Q24 sparse kernel；本次没有训练 encoder，也没有完成端到端可微 neuron 训练。[协议](PROTOCOL.json)；[源码封存](SOURCE_SEAL.json)

与价值边界和双通道构想的关系也限定在这里：**本轮三臂采用相同任务价值边界与输入，研究的是读出训练目标。** 它没有重新检验固定边界、直接学习边界与自由边界之间的差异，也没有重新消融双通道或连续概率流动力学。本轮结果不能替代这些问题各自的实验。

### 任务和数据规模

任务是含继续生产、维修与停机动作的随机维护模拟。物理环境模拟失效、维修和状态重置；任务消费者确实通过原生 Hepta kernel 和 NDU 闭环决策。它是模拟任务上的真实 Hepta 执行，研究权限保持 `DENY_ALL`，没有控制生产系统或外部设备。[协议](PROTOCOL.json)；[审计范围](results/AUDIT_SUMMARY.json)

每个 seed 的训练集为 12 个 context × 8 条公共探索路径；开发集为 8 个 context × 8 条路径；确认集包含 ID/OOD 各 8 个 context × 16 条路径。每臂确认 4,096 个 episode，四臂合计 **16,384** 个。每个 seed 的 ID/OOD 等权，最终 16 个 seed 等权；统计独立单位是配对 seed，不是把所有窗口或 episode 当成独立训练重复。[协议](PROTOCOL.json)；[主比较](results/PRIMARY_COMPARISON.json)

训练探索每个窗口以 0.8 概率继续、0.2 概率维修，不采样 STOP，运行完整期限。所有训练窗口等权；没有按目标函数重新采样或使用不同激活矩阵。训练、开发、确认和独立诊断使用分离的随机流；各臂在同一 seed/context/path/time 下共享固定创新槽位。确认期间没有追加 seed、排除样本或返回开发集重选模型。[协议](PROTOCOL.json)；[独立审计摘要](results/AUDIT_SUMMARY.json)

## 3. 主检验与任务表现

唯一主检验使用 16 个 seed 的配对净效用差，`df=15`，标准误为 **0.051021671**。净效用按每个学习决策 160 个数值字节、每 byte `1e-6` 的固定价格扣减；CPU 没有折算成任务效用，也没有折算电量。[主比较](results/PRIMARY_COMPARISON.json)；[成本摘要](results/COST_SUMMARY.json)

| 臂 | ID 平均净效用 | OOD 平均净效用 | ID/OOD 等权总体净效用 |
| --- | ---: | ---: | ---: |
| A：ridge reference | 4.174394 | 1.869991 | 3.022192 |
| B：iterative Q-MSE | 4.154577 | 1.822518 | 2.988547 |
| C：policy regret | 4.040259 | 1.926096 | 2.983177 |
| finite-grid DP | 4.419771 | 2.772972 | 3.596372 |

数据见 [ARM_SUMMARIES.json](results/ARM_SUMMARIES.json)。表中数值使用任务效用单位；不代表现实货币收益。DP 不走学习臂的原生消息接口，其数值字节计价为零，模型构造和规划成本另在公共成本中记录。DP 是有限网格数学参考，不能把这张表当作同硬件、同训练预算的产品性能比较。

C−B 在 ID 上为 **−0.114317879**，在 OOD 上为 **+0.103577791**，方向相反。这两个分组数值是预先要求报告的描述结果，**不构成两项额外确认性检验，也不能称为已证实的 OOD 优势或稳健的分布交互**。本次唯一可用于收益验收的结果仍是总体 C−B 的 0/1。[主比较与分组差](results/PRIMARY_COMPARISON.json)

### 行为差异

| 臂 | 失效事件 / episode | 维修动作 / episode | 确认 STOP 动作总数 | 平均有效步骤 / episode |
| --- | ---: | ---: | ---: | ---: |
| A | 0.271973 | 2.115723 | 327 | 11.560547 |
| B | 0.279297 | 2.166992 | 313 | 11.571777 |
| C | 0.435791 | 1.524902 | 0 | 11.843750 |
| DP | 0.112305 | 1.640625 | 338 | 11.670410 |

这些是各策略自身访问轨迹上的描述统计。失效后环境可以重置并继续，因此“失效事件 / episode”是次数均值，不是“该 episode 至少失效一次”的概率。C 在本次确认中较少维修且没有选择 STOP；这描述了行为，没有把其原因归结为某个未经单独检验的表示、优化或动力学机制。[各臂完整统计](results/ARM_SUMMARIES.json)

## 4. 风险校准反映各策略访问分布

所有策略使用同一解析的动作后首达风险预测器。校准观测来自各策略实际经历的风险窗口；STOP 没有后续暴露，不作为一次“零风险预测成功”加入窗口分母。Brier 越小表示该暴露集合上的平方误差越小；ECE 使用十个预先固定的概率区间，空区间不捏造事件率。[协议](PROTOCOL.json)；[各臂校准数据和完整 bins](results/ARM_SUMMARIES.json)

| 臂 | 风险暴露窗口 | 窗口加权 Brier | episode 等权 Brier | 固定十箱 ECE |
| --- | ---: | ---: | ---: | ---: |
| A | 47,025 | 0.017670 | 0.018013 | 0.001375 |
| B | 47,085 | 0.017892 | 0.018317 | 0.001454 |
| C | 48,512 | 0.024998 | 0.025140 | 0.001333 |
| DP | 47,464 | 0.009006 | 0.009743 | 0.000906 |

学习臂均有 4,096 个存在风险暴露的 episode；DP 为 4,080 个。episode 等权 Brier 在有风险暴露的 episode 上计算。[各臂数据](results/ARM_SUMMARIES.json)

C 的 Brier 较高，而其 ECE 没有按相同顺序排列。两类统计衡量不同性质，还受到策略访问分布、概率分布与有限暴露的影响。**不能把这些差异解释为某个学习臂把共同的风险预测器训练得更强或更弱**；本实验没有独立训练风险模型，也没有在完全相同的风险暴露分布上做风险学习对照。[审计范围](results/AUDIT_SUMMARY.json)

## 5. 同状态面板与量化诊断

独立诊断使用每 seed 4 个 ID context × 8 条公共探索路径 × 12 个窗口，共 **6,144 个相同状态窗口 / 臂**。其随机命名空间与训练分离，面板动作不改变共同探索轨迹；每个头在同一输入序列上都实际执行原生 kernel 和 NDU。审计确认三个头的 **native activation 逐项完全一致**。这些窗口没有用于训练或模型选择，也不增加确认样本；本面板不覆盖 OOD。[协议](PROTOCOL.json)；[COMMON_STATE_PANEL.json](results/COMMON_STATE_PANEL.json)

下表的 regret 是同一状态下物理 DP 最优 Q 与原 NDU 选中动作 Q 的差，按面板窗口平均；不是整条 episode 的累计 regret。

| 臂 | 全部状态平均 regret | teacher=keep，5,045 行 | teacher=repair，1,094 行 | teacher=STOP，5 行 |
| --- | ---: | ---: | ---: | ---: |
| A | 0.028272 | 0.017404 | 0.076056 | 0.539595 |
| B | 0.029454 | 0.017715 | 0.081255 | 0.539595 |
| C | 0.033846 | 0.006083 | 0.157412 | 1.009575 |

数据见 [共同状态面板](results/COMMON_STATE_PANEL.json)。C 在 teacher=keep 状态的描述性 regret 较小，在 teacher=repair 状态较大。**teacher=STOP 仅 5/6,144，约 0.081%**；不能把这五行作为可靠的广泛 STOP 能力评估。它们也不是 6,144 次独立模型训练。以上条件分组均为描述诊断，没有新的确认性收益门槛。

在同一原生激活上，将浮点 affine head 与实际 Q24 读出/NDU 比较，三臂各 6,144 行的动作差异均为 **0**；有符号量化 regret 差均为 **0**。最大绝对分数误差分别为 A `4.534020e-7`、B `5.073704e-7`、C `3.794735e-7`。[量化诊断](results/COMMON_STATE_PANEL.json)

因此，本面板没有提供“读出量化导致这些动作遗憾”的证据。这个结论限定在已观察的相同原生激活和 ID 面板；它不等于所有 OOD 状态都无量化效应，也没有比较全浮点 encoder 与原生 Q24 encoder 的动力学。没有把 action flip 的数量误当作损失；本次实际 flip 为零。

## 6. 原生执行、独立审计与有限工程验证

完整确认审计 **PASS**，覆盖 **1,048 个文件、64 个选定 checkpoint、144 个候选训练程序、9,216 条开发 episode、16,384 条确认 episode、18,432 行公共训练原生激活，以及 143,262 个确认原生决策步骤**。144 个候选中包括 ridge 闭式拟合与两种迭代训练，并不全是 Adam。所有候选的开发轨迹均有原始证据保留。[AUDIT_SUMMARY.json](results/AUDIT_SUMMARY.json)

审计独立重算 Bellman 关系、因果轨迹、物理奖励、候选优化器和 Q24 读出算术；它与运行器共享封存的数值网格构造器。原生 sparse kernel 是真实执行并核验身份与收据的组件，审计没有另外实现一个独立 sparse kernel 并宣称二者等价。这个依赖边界保留在完整审计的 `scope` 中。[审计范围](results/AUDIT_SUMMARY.json)

| 正式科学阶段 | 实际 kernel 调用 | 实际 NDU 调用 |
| --- | ---: | ---: |
| 公共训练激活导出 | 18,432 | 0 |
| 全候选开发轨迹 | 110,522 | 110,522 |
| 确认学习臂轨迹 | 143,262 | 143,262 |
| 共同状态诊断，三臂合计 | 18,432 | 18,432 |
| **合计** | **290,648** | **272,216** |

DP 数学参考没有 native kernel/NDU 调用。训练导出只取得公共激活，不做 NDU 决策；开发、确认和诊断中的学习决策均实际使用原 NDU。这些计数不含准备期检查、编译和另列的 owner 恢复验证。[成本与计数](results/COST_SUMMARY.json)

### 持久 owner 与完整任务冷恢复

工程检查严格采用事先固定的 seed 3301、三学习臂、ID/OOD 各 context 0/path 0，共 **6 个已有 episode**，没有增加效用样本。6/6 通过，覆盖 **84 个 owner 步骤、6 次不同 PID 的冷恢复和 66 个恢复后的继续步骤**。每一步重新建立本研究的 `FeatureMap`、物理状态与因果历史，比较原生激活、分数、有效动作、物理结果、奖励及总/净效用。[OWNER_SUMMARY.json](results/OWNER_SUMMARY.json)；[摘要与绑定](results/AUDIT_SUMMARY.json)

保存的完整 checkpoint 包含物理状态、已完成期限、此前失效/风险/维修历史、累计效用、剩余创新槽位、模型与 profile/binary/record 身份和 native owner 锚点。原生逻辑时钟与任务物理时钟分开保存；关闭进程后，从磁盘恢复并重放原有 journal/witness。[协议](PROTOCOL.json)；[工程名册](results/OWNER_MANIFEST.json)

这六例均没有 STOP，因而**新选定头的 post-STOP 唯一 tick 拒绝探针覆盖为 0**。准备期原生六项行为检查另有 STOP 拒绝语义测试，不能把它替写成这六例已覆盖 STOP。此次工程结果只支持这些预先固定的有限期限回放与恢复，不证明任意长时间运行稳定，也不构成生产 admission。[OWNER_SUMMARY.json](results/OWNER_SUMMARY.json)

## 7. 实际成本与通信口径

### 非重叠科学阶段

288 条成本记录的非重叠科学窗口合计 **130.174260 秒 wall、113.777475 秒 Python CPU、16.639654 秒已回收子进程 CPU，共 130.417129 秒 CPU**。这包括正式训练/开发、确认、共同状态诊断及其序列化；不含编译、准备期检查、独立审计、owner 工程命令和归档发布。[COST_SUMMARY.json](results/COST_SUMMARY.json)

| 阶段 | wall 秒 | CPU 秒，Python 与已回收子进程之和 |
| --- | ---: | ---: |
| 训练数据、模型与规划 setup | 11.362462 | 11.360891 |
| 公共原生特征导出 | 2.603176 | 2.640520 |
| 全候选拟合与开发轨迹 | 48.464459 | 48.445923 |
| 确认模型与规划 setup | 4.613910 | 4.611590 |
| 确认轨迹执行 | 42.104976 | 42.320637 |
| 确认轨迹序列化 | 14.455053 | 14.453159 |
| 共同状态诊断 setup | 2.910109 | 2.908991 |
| 共同状态诊断执行 | 3.660114 | 3.675418 |

模型构造 CPU **11.046506 秒**、DP 规划 CPU **0.501986 秒**和按 native PID 核算的 CPU **16.639500 秒**，都是上表包围窗口的**子集**，不能再相加。父窗口与按 PID 的子进程 CPU 总差为 **0.000154 秒**；独立审计按冻结的每阶段 `5e-6` 秒时钟舍入容差检查，没有用宽容差隐去额外计算。[成本摘要](results/COST_SUMMARY.json)

| 学习臂 | 三候选训练＋开发 wall 秒 | 对应 CPU 秒 | 确认执行 wall 秒 | 确认序列化 wall 秒 |
| --- | ---: | ---: | ---: | ---: |
| A | 13.413897 | 13.410354 | 11.638804 | 4.443338 |
| B | 15.293643 | 15.292081 | 11.570276 | 4.306170 |
| C | 19.756919 | 19.743488 | 14.989435 | 4.390974 |

这张表包含各臂实际开发轨迹和进程成本，没有把共享 setup 三次摊入。相同优化更新数不表示相同实际时间；这是一台运行环境上的实测，不能自动外推为不同硬件上的固定速度比例。[按臂成本](results/COST_SUMMARY.json)

### 命令外层与验证成本

外层命令计时还覆盖导入、身份核验、阶段间 bookkeeping 和结果写出。它包住对应的科学窗口，**不能把两层时间加在一起**。下表 CPU 包含该命令子进程及其已回收后代，并加上很小的包装器 CPU。[外层原始收据与 SHA](results/COST_SUMMARY.json)

| 完整命令 | wall 秒 | 包含包装器的 CPU 秒 |
| --- | ---: | ---: |
| 训练与开发 | 63.301563 | 63.321132 |
| 正式确认及共同状态诊断 | 68.678786 | 68.908946 |
| 选择后的独立审计 | 74.240026 | 74.238427 |
| 完整确认独立审计 | 137.148208 | 137.128946 |
| 六例 owner 工程命令 | 1.446968 | 1.434079 |

owner 内部的整体窗口为 **1.029990 秒 wall、0.944200 秒 Python CPU、0.072908 秒子进程 CPU**，包含在最后一行命令内。编译是本轮研究共用的独立原生构建；准备期检查、打包上传和发布等待也不包含在上面的科学运行时间里。这里没有将审计成本隐藏成零，也没有把并行任务的 wall 时长求和冒充端到端等待时间。[成本摘要](results/COST_SUMMARY.json)；[原生构建收据](native/BUILD_RECEIPT.json)

### 数值字节与实际传输字节

每次学习决策的计价输入固定为 20 个 i64，即 **160 bytes**。确认阶段 A/B/C 的计价数值字节分别为 **7,576,320 / 7,583,680 / 7,761,920**；差异来自实际决策步骤数量，而不是给某臂更宽的输入接口。[各臂计数](results/ARM_SUMMARIES.json)

确认 native 进程的完整 RPC 请求/响应分别为 **37,954,826 / 125,666,686 bytes**，包含身份、profile 等控制调用；它与逐条任务记录分摊的决策请求/响应口径不同。全部正式科学阶段合计请求 **77,230,404 bytes**、响应 **249,093,332 bytes**。JSON 收据和控制信息带来的传输成本没有被 160-byte 数值计价替代。[成本摘要](results/COST_SUMMARY.json)

**没有测量硬件能耗。** 稀疏活动、较少事件、闭式拟合、少量传感观测或较低 CPU 时间，都不能直接推出更低焦耳数；本报告不作节能结论。净效用只使用冻结的数值字节价格，CPU 和实际 RPC 字节另外报告。

## 8. 解释范围与下一步价值

本次没有支持“仅替换读出 loss，就能在此原生表示和预算下达到预先要求的收益提升”。它也没有证明 Hepta neuron、任务价值边界或双通道机制整体无效；这些更广问题不在本轮唯一主比较中。[协议](PROTOCOL.json)；[主比较](results/PRIMARY_COMPARISON.json)

冻结 encoder 与 42 系数读出构成明确的模型限制。实际训练导出的 20 列激活中，各 seed 观察到非零值的列数为 **9–13**；B/C 训练收据中具有非零梯度的系数坐标为 **20–28**，不是所有分配的 42 个坐标都收到训练信号。这些描述说明“分配参数量”与“该训练集合实际覆盖”应分开报告，**不能据此把失败原因确定为容量不足或冻结表示**。优化目标、样本覆盖、表示与动作分布之间可能存在交互，本轮没有单独识别它们。[训练覆盖摘要](results/AUDIT_SUMMARY.json)

最值得保留的下一步约束是：把新的原因诊断作为新研究，继续维持相同任务信息、实际原生动作、完整成本与公开冻结。若重点是 STOP/维修能力，应事先规定同时覆盖 ID/OOD、边界附近状态和足够 STOP teacher 状态的共同诊断面板；本次只有五个 STOP 状态的面板不足以承担这个判断。若重点是表示能力，应另行冻结匹配的表示学习预算对照，不能把当前失败后修改 encoder 的结果并入这一检验。[共同状态面板](results/COMMON_STATE_PANEL.json)

本报告不启动新的重采样、调参或 seed 扩展。后续研究需单独冻结假设与门槛；本次 0/1、旧 flow 0/3 和旧 policy 0/4 均保持原样。

## 9. 来源、封存与交付

源码、协议和重建二进制身份先发布于 [`7908860cb959cbe1599379d4ecbfcc22fbccbe61`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/7908860cb959cbe1599379d4ecbfcc22fbccbe61)。正式开发选择随后发布于 [`87b03617077f9e5f275d291b7af06cd1418f87ce`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/87b03617077f9e5f275d291b7af06cd1418f87ce)，确认在该选择发布后才启动。发布证据来自指定远端分支的 commit 祖先关系与精确文件字节核验，不用本地时间代替发布。[审计来源绑定](results/AUDIT_SUMMARY.json)

| 对象 | SHA-256 |
| --- | --- |
| 完整确认审计 | `4db0de9b32926b4415c2179715f520ad8b852362b112b103218d447de415a8fb` |
| 正式科学 MANIFEST | `861468d3cd2f1841291dfcd32c93f3efe1db58f494c02e549979376fb26e60b7` |
| SOURCE_SEAL | `83f5243f7b7c7aead3742baccd01caaf619759658f320e824589ff016269d2e9` |
| SELECTION_SEAL | `28477204d0ef4a94fc990295196d5c51f792a95e2546750217a2a5592f682d66` |
| PROTOCOL | `3d19c2f0aef69da5d368da01e34308f1344ec98b10fd0aaefa1ba4877aa9baff` |
| 本次重建的 native binary | `fa9dc78b129b0ec3b072e9fc8c8fdd49479515c79aeb2660f355e38f41e54dce` |

完整审计文件为 547,772 bytes，超过本仓库的单对象研究发布预算，因此公开结果目录保留五份紧凑派生文件，每份都绑定上表中的完整审计和科学 MANIFEST。完整审计、原始轨迹、所有候选、checkpoint、native profile、公共训练激活、成本和 owner journal/witness 随 `evidence/bundle/` 原始档案交付；派生表不能替代这些原始字节。

| 可直接阅读的结果 | 内容 |
| --- | --- |
| [AUDIT_SUMMARY.json](results/AUDIT_SUMMARY.json) | 独立审计覆盖、门槛计数、训练覆盖与 owner 概要 |
| [PRIMARY_COMPARISON.json](results/PRIMARY_COMPARISON.json) | 唯一主比较、16 个配对 seed 差、精确区间与描述性 split 差 |
| [ARM_SUMMARIES.json](results/ARM_SUMMARIES.json) | 每臂、每 split 的效用、风险 bins、动作与 native 计数；配对 seed 净效用 |
| [COST_SUMMARY.json](results/COST_SUMMARY.json) | 非重叠阶段、每臂成本、实际调用与字节、外层命令收据 |
| [COMMON_STATE_PANEL.json](results/COMMON_STATE_PANEL.json) | 相同原生激活的条件 regret、量化诊断及每 seed 面板结果 |
| [OWNER_SUMMARY.json](results/OWNER_SUMMARY.json) | 六例有限期限的持久 owner 与冷恢复验证 |

研究 PR 的审阅基线固定在原注册提交 `5898cd8…`，没有把移动基线的新提交并入封存研究，也没有主线合并或生产推广。GitHub CI 与本报告的科学审计分开记录；`results/CI_*.json` 只支持各自指定 head 和观察时间的状态，不把较旧 commit 的检查结果移作当前 head 的通过证据。

## 10. 公开档案恢复与完整复审

本研究的完整证据包从已公开的 [b0907a0](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b0907a0eab889b9e1f346a452b7239661a96f9e3) 独立下载恢复；没有使用本地归档复制来代替远端获取。实际 278 个下载对象均在首次尝试取得，响应 body 合计 **132,561,201 bytes**；恢复并逐项核验 **1,484 个文件、610 个目录、136,972,435 个原文件 bytes**。获取窗口为 **13.512499 秒 wall、2.808375 秒 Python CPU**。[远端获取回执](results/PUBLIC_RETRIEVAL.json)；[逐文件校验名册](results/PUBLIC_FILE_VERIFY.jsonl.gz)

对新恢复目录重新执行完整独立科学审计后，**547,772 bytes** 的输出与归档中的原审计逐字节一致。重新核验的 16,384 个确认 episode、64 个选定 checkpoint 和 143,262 个确认原生步骤保持原结果，收益门槛仍为 **0/1**；没有新训练或新增样本。复审命令额外消耗 **139.489895 秒 wall、139.454020 秒 child CPU**，与原科学成本分别记录。[重新审计回执](results/PUBLIC_ROUNDTRIP_AUDIT.json)；[完整审计身份绑定](results/PUBLIC_ROUNDTRIP_FILES.json)；[复审成本](results/PUBLIC_ROUNDTRIP_COST.json)

两套新研究的完整原始包共同保存在证据分支 `research/evidence-archive-20261029` 的不可变提交 [8dc7def](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8dc7defc17974d67766f35f340eb7bf6e692aefb)。本研究此次实际下载使用的仍是上述 b0907a0，回执保留真实来源。源码和报告入口为[研究分支](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/research/continuous-boundary-flow-20261028)，操作步骤见 [REPRODUCE.md](REPRODUCE.md)，跨研究结论与交付范围见[总交付报告](../RESEARCH_DELIVERY_2026-10-29.zh.md)。公开恢复和数学复审完成不代表所有仓库 CI 通过，最终提交的检查状态以 [PR #4157](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4157)与 [Actions](https://github.com/TrillionniumFoundation/hepta-private-ci/actions)的精确 head 记录为准；权限保持 `DENY_ALL`，PR 保持 draft，未合并。
