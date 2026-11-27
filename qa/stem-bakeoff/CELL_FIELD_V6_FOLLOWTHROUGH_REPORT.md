# Parameter field × Hepta：V5/V6 全链路研究报告

日期：2026-10-25。科学结论：**V5 与 V6 均为 REJECT**。

本轮完成了两套预先冻结的新来源实验、完整状态重放、独立统计复算，以及实际训练头到原生 owner/snapshot 路径的接入与拒绝验证。V6 补上了有限窗口紧凑状态的数学闭合、逐步保留修复和完整执行；独立任务收益与独立保留证据仍未达到准入要求。完成实验与通过研究门槛是两个分别记录的结果。

## 1. 五项工作现在分别回答了什么

| 原工作项 | 已交付证据 | 判定 |
|---|---|---|
| P0：Loss2、增强状态/历史、Full 的同条件真实 H8 | 每轮 36 个共同起点 × 49 个固定动作，全部 1,764 条真实分支；V6 共 8 个预测器、14,112 条预测路径 | 完成。Loss2/四维经验状态丢失动作相关信息；有限窗口未来损失场保留全部局部线性输出 |
| P0：同范数方向、固定方向幅度、风险/保留/代价/CPU | 三档幅度、每档 16 个同范数方向，分别记风险、遗忘、参数惩罚和真实耗时 | 完成。目标计价能掩盖动作方向的预测差异；H8 与一步重规划频率不同，场不优于同频 Full |
| P0：冻结的保留压力实验 | V6 全 12 次搜索；9 次无越界保留；6 个实际检查点的 78 个槽位全部记录 | 完成。修复增加 27 个探针可认证轨迹；独立 old-test 未出现对应保留救回 |
| P1：新的独立来源与任务实例 | AG News、DBpedia；V5/V6 各 4,608 个组件，跨轮零重叠；标签在完整封存重放通过后解封 | 完成负结果。V6 仅 2/12 科学门槛通过，全部 8 项未来优势检验失败 |
| P1：原生 owner/snapshot、拒绝、恢复与回滚 | 全 12 个实际 linear/gated 头的类型化转换；真实负结果准入；独立开发生命周期测试 | 原生研究接入完成；实际候选维持拒绝，不具备生产激活资格 |

### 两轮结果总表

| 指标 | V5 | V6 |
|---|---:|---:|
| 声明候选 | `response_h8_guarded` | `future_field_h8_repaired` |
| 固定 H8 分支完整执行 | 1,764/1,764 | 1,764/1,764 |
| 全部策略完成 32 步 | 66/72 | 72/72 |
| 候选完成 32 步 | 9/12 | 12/12 |
| 候选及两项主基线完成门槛 | 33/36 | 36/36 |
| 科学门槛 | 0/12 | 2/12 |
| 具有完整执行资格的成本门槛 | 3/4 | 4/4 |
| 独立重放、统计复算 | PASS | PASS |
| 科学结论 | REJECT | REJECT |

V5 的三个 DBpedia gated 候选在第 24 步停下，另三个受保护一步诊断策略在第 25/26 步停下。其真实终态仍进入统计，缺少的更新没有补成零动作，也没有删除这些记录。V5 的第四组 CPU 比值数值低于 3，但因执行不完整不具备通过资格。[V5 评估](./evidence/20261025-cell-field-v5-v6/v5-evaluation.json)、[V6 评估](./evidence/20261025-cell-field-v5-v6/v6-evaluation.json)。

## 2. 预先冻结、来源独立性与实验对象

V5 协议在 [241172d0](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/241172d0d72b94b3b2c03a636cbcf1ccb81a2784) 发布，实际执行源版本为 [65a8892c](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/65a8892c4331e2ea98d85373a51434cb2db1d8ac)。V6 协议在 [e82f1247](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/e82f1247631270deb03ac4537b8ef0b9952d11b0) 发布，实际执行源版本为 [89033444](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/89033444ac55096ed4909e1ee38349543f82367e)。独立审计和报告工具在运行后添加，明确排除在历史执行源闭包之外。

V5 的动作惩罚和旧任务权重只在已知 V4 开发数据的九个预定配置中选择；最终代码在同一开发数据上复核，432 个行为结果完全相同。V5 主实验出现停步后，V6 修复规则仅使用这些已知训练/探针状态开发。V6 的来源、参数、评价门槛和代码在两轮最终标签解封前全部冻结；V6 的来源图排除 V5 全部 4,608 个已选组件。两轮标签均在 V6 全量独立重放通过后才解封。[协议 V5](./cell_field_protocol_v5.json)、[协议 V6](./cell_field_protocol_v6.json)、[标签访问 V5](./evidence/20261025-cell-field-v5-v6/v5-label-access.json)、[标签访问 V6](./evidence/20261025-cell-field-v5-v6/v6-label-access.json)。

来源使用原作者发布的 AG News 和 DBpedia 档案。AG News 采用原四类；DBpedia 固定采用原始类别 1–4，但去重和冲突闭包先在全部 14 类上构建。图涵盖 757,600 条记录、748,555 个组件；标题、正文、完整文本和截断文本均做规范化身份核对。冲突组件、跨官方训练/测试拆分组件、跨任务组件和此前 UCI/20 Newsgroups 身份均排除。V6 再排除全部 V5 角色。

每个任务 2,304 条、类别平衡：old/current 各有 train 256、probe 128、validation 256，另有 old_test 512 和 future_test 512。old/current 是官方训练集合中的散列分区，future 来自官方测试集；这不构成真实时间漂移实验。规范化身份检查不保证语义改写独立，也不能排除编码器预训练接触过这些公开语料。[来源与特征审计 V5](./evidence/20261025-cell-field-v5-v6/v5-source-feature-audit.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-source-feature-audit.json)。

模型固定为 Granite 97M 编码器、384→8 标签无关 QR 投影，以及 36 参数 linear / 52 参数 gated 头。编码器更新次数为 0。训练状态包括参数、一阶矩、二阶矩、Adam 时钟、RNG 和数据上下文；连续数值部分为 108/156 维。每个任务/头使用种子 7、17、29，共 12 次拟合。这是冻结大表示上的小模块控制实验，不能外推为完整 LLM 参数训练或全部 Hepta neuron 架构的验证。

## 3. 哪一种紧凑状态保留了未来动作信息

V5 以解析 Hessian-vector product 和 Adam JVP/VJP 替换在线稠密有限差分构造，并比较动作响应 SVD。SVD 压缩的是动作输入到损失输出的响应映射，不是一个仅靠观测损失即可自行演化的状态。本轮脉冲响应数值秩为 14–16；低维输出本身没有使整个响应降到二维。

V6 新增一个严格限定在已知参考轨迹上的有限窗口未来损失状态。令局部完整状态满足

\[
\delta x_{k+1}=A_k\delta x_k+E_ku_k,\qquad y_k=C_k\delta x_k.
\]

定义

\[
O_k=\begin{bmatrix}C_k\\C_{k+1}A_k\\\vdots\\C_HA_{H-1}\cdots A_k\end{bmatrix},\qquad z_k=O_k\delta x_k.
\]

因此

\[
z_{k+1}=\operatorname{drop}_2(z_k)+O_{k+1}E_ku_k.
\]

H8 的状态维数为 18、16、…、2；前两维给出当前损失扰动。这个恒等式对任意完整初始切向扰动和任意后续动作序列成立，不需要每步把两个损失伪逆回完整状态。它是一个可闭合的有限窗口输出表示，未宣称最小秩实现；其系数仍依赖完整参考、已知训练批次和时钟，每个 H8 块重新构建。[实现](./cell_field_observable_v6.py)、[独立前向 JVP 审计](./cell_field_replay_v6.py)。

### V6 同起点、同动作、同 H8 预测结果

下表在全部 36 个共同起点、每个 49 个动作、未来 8 步和两个探针上汇总。排序是每个起点内的描述统计，起点不是独立任务样本。

| 状态/预测器 | 损失 RMSE | 相对 Full | 当前风险排序平均 Kendall τ |
|---|---:|---:|---:|
| Loss2 | 1.2239e-4 | 14.39× | 0.680 |
| Q4：损失与梯度/动量摘要 | 1.6682e-4 | 19.61× | 0.462 |
| History4 | 9.8894e-5 | 11.63× | 0.571 |
| Structured4 | 1.0657e-4 | 12.53× | 0.543 |
| Full 稠密切向参照 | 8.5054e-6 | 1.00× | 0.987 |
| 解析完整响应 | 8.5054e-6 | 1.00× | 0.987 |
| 响应 SVD | 8.5054e-6 | 1.00× | 0.987 |
| V6 有限窗口未来损失场 | 8.5054e-6 | 1.00× | 0.987 |

未来损失场与解析响应的最大预测差为 5.97e-19；独立前向 JVP 构造的系数最大归一化误差为 2.28e-13（分母为 `max(1, abs(参照系数))`）。实际执行中，未来损失场与 Full adjoint H8 的最大动作差为 4.21e-15、完整状态差为 8.89e-16、概率差为 6.67e-16。它确实实现了这个局部 Full 控制器。因此本次外部失败不能由这种压缩的信息损失解释。[完整描述统计 V6](./evidence/20261025-cell-field-v5-v6/v6-descriptive-census.json)、[重放审计](./evidence/20261025-cell-field-v5-v6/v6-replay-audit.json)。

## 4. 方向、幅度、目标计价和计算成本

固定动作库是零动作加 16 个方向/符号乘三档幅度。实际参数脉冲为 `0.02u`，其余 7 步动作固定为零。每档参数惩罚相同，故可以把方向效果和幅度效果分开。

| 控制范数 | 参数脉冲范数 | 固定库参数惩罚 | 576 条分支中当前风险优于零动作 | 总目标优于零动作 | 场预测 RMSE |
|---|---:|---:|---:|---:|---:|
| 1/8 | 0.0025 | 0.000015625 | 289 | 0 | 2.2580e-7 |
| 1/2 | 0.0100 | 0.000250000 | 287 | 0 | 3.6120e-6 |
| 1 | 0.0200 | 0.001000000 | 286 | 0 | 1.4438e-5 |

幅度扩大四倍时预测误差约扩大十六倍，再扩大两倍时约扩大四倍，符合这一范围内的局部二阶余项表现。该描述不能保证更大动作或其他参考下仍成立。许多方向改善当前风险，却被冻结的参数惩罚抵消；因此“完整总目标排序很好”不足以证明未来风险预测很好。风险、遗忘、参数惩罚的加和最大残差为 2.17e-19；真实 CPU 另行记录。

在线策略采用另一个预先冻结的终点任务目标，参数价格 0.03、动作预算 4、旧任务权重 0，并施加原始 old-probe 阈值。所有 V6 主策略共享同一个逐步精确修复器。固定库诊断保留其原价格 0.1；两个计价实验不混为一个归因结论。

| 任务/头 | 一步控制 CPU，毫秒/32步 | V6 场 CPU，毫秒/32步 | 场/一步 | Full adjoint H8 CPU |
|---|---:|---:|---:|---:|
| AG News linear | 246.90 | 161.77 | 0.655 | 159.95 |
| AG News gated | 307.55 | 205.78 | 0.669 | 199.76 |
| DBpedia linear | 223.46 | 147.08 | 0.658 | 130.51 |
| DBpedia gated | 302.99 | 202.73 | 0.669 | 179.84 |

这些是三种子平均、单线程实测控制器 CPU，包括系数、求解、全部验证/修复试探和实际提交；共同特征提取、无标签评估预测与序列化另外列账。H8 每 8 步重规划，一步控制每步重规划。因此与一步基线相比的成本下降不能归功于场的维数；相同 H8 的 Full adjoint 更便宜。场的 18 维状态也不等于总内存：保存的系数约 98,496/142,272 字节，完整参考和控制序列仍存在。编码器特征计算在 V6 两任务另花费约 446/543 CPU 秒；未隐藏在上述毫秒数字里。[成本原始记录](./evidence/20261025-cell-field-v5-v6/v6-evaluation.json)。

## 5. 保留机制：精确探针保护、有限搜索和外部保留

V5 使用真实非线性 H8 验证与统一缩幅，所有候选验证都从相同完整状态克隆。对 V4 压力库复核时，149/149 个已知切向假可行轨迹均被阻止，假认证为 0；但缩幅没有成功修复那些危险案例。拒绝本身不等于能继续学习。

V6 在每个实际 Adam 更新后检查原始 old-probe 阈值；必要时沿旧探针梯度做预定有界网格搜索、两次细化，并在预算内尝试保持参数的动作。每个失败步骤最多 16 次头部损失评估。所有试探和重放均计费；完整块通过后才提交。失败保留为有限搜索未找到可行解，不能称为非线性全局不可行。切向求解器自身有不可行证明的条目则独立保留。

| V6 压力结果 | 数量 |
|---|---:|
| 原始搜索 | 12 |
| 达到首个原阈值越界 | 3 |
| 256 步内无越界、完整保留 | 9 |
| 实际 prevention/recovery 检查点 | 6 |
| 实例化候选槽位 | 78 |
| 原统一缩幅验证可认证 | 39 |
| 逐步修复可认证 | 66 |
| 仅修复可认证 | 27 |
| 仅原验证可认证 | 0 |
| 修复有限搜索拒绝 | 11 |
| 上游切向不可行、未执行 | 1 |

被认证的 66 条修复轨迹中共有 123 个修复步骤，原阈值与动作盒没有放宽。最大 312 个可能槽位中的其余 234 个属于无越界搜索，未伪造检查点填充它们。全部 78 个已实例化槽位、失败与不可行都在账。

**独立 old-test 上没有救回证据。** 这六个压力检查点都来自 AG News gated 的三个种子。进入分支前，old-test 相对 warmup 的平均 NLL 已增加约 0.0331–0.0379；因此不能把其后 66/66 条不满足独立保留的轨迹说成 66 次新增越界。准确结论是：27 个新增认证只证明控制器把已知 old-probe 拉回原阈值，既有的独立 old-test 违规没有被救回。原验证认证的 39 条路径也全部存在独立 old-test 违规。

V5 的来源不同：144 条探针认证路径在样本 old-test 路径上均可行，但家族校正的科学门槛仍为 0/12。跨轮比例变化不能归因于修复算法，因为来源和候选同时变化；V6 内部的配对 guard/repair 比较才固定了起点与意图动作。[独立保留 V5](./evidence/20261025-cell-field-v5-v6/v5-independent-retention.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-independent-retention.json)。

## 6. 外部任务检验：哪些主张未通过

冻结的主检验共有 12 项：4 个任务/头组合各有候选相对一步、相对 Loss2 的 future-test NLL，以及候选相对 warmup 的 old-test NLL。每项 512 个来源组件，先按样本平均三个种子，再进行 10,000 次类别分层组件 bootstrap。单侧分位数为 0.9958333333，对应预定 12 项家族；未来差值上界须严格小于 −0.001，旧任务上界须不大于 0。该近似 percentile 家族推断以这些来源和拟合为条件，三个种子不是三个独立来源样本。

下表的差值均为候选减参照，负值更好；括号内是单侧上界。

| 任务/头 | Future 相对一步 | Future 相对 Loss2 | Old 相对 warmup | 通过项 |
|---|---:|---:|---:|---:|
| AG News linear | +0.004362 (+0.008863) | −0.000995 (+0.003690) | +0.024124 (+0.080998) | 0/3 |
| AG News gated | −0.000925 (+0.001610) | −0.003148 (−0.0000558) | +0.012132 (+0.057975) | 0/3 |
| DBpedia linear | +0.007437 (+0.012598) | +0.007278 (+0.013573) | −0.073734 (−0.034130) | 1/3 |
| DBpedia gated | −0.001316 (+0.001917) | −0.001524 (+0.001431) | −0.052115 (−0.015564) | 1/3 |

AG News gated 相对 Loss2 的上界虽低于零，仍未达到 −0.001 的预定实用门槛。两个 linear 组合相对一步的均值本身更差；不能只把全部失败解释为样本量不足。两个 AG News 组合的独立旧任务均值也恶化。仅 DBpedia 两个保留门槛通过。

独立统计审计重新从封存概率与解封后的类别分层计算全部 228 条指标、72 条成本、36 条完成判定、12 个 bootstrap 对比和 4 个成本对比，指标和区间最大数值差均为 0。结论没有经过重新选样、改价、改门槛或候选选择。[独立统计审计 V5](./evidence/20261025-cell-field-v5-v6/v5-statistics-audit.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-statistics-audit.json)。

## 7. 原生接入与真实拒绝

原生新增有界 float64 `hepta.trained-cell-bundle.v5` 类型，精确表示本实验的 384→8 投影、归一化以及 linear/gated 推理。既有 Q24 仿射头不能忠实表达 gated 头，因此转换器保留实际模型结构。每个候选/前驱包包含全部 12 个拟合，绑定研究源包、协议、转换清单和模型内容。

owner 读取入口在每次读取时复核当前注册表前沿、完整来源和当前撤回状态；测试覆盖在注册表观测过期、来源撤回、重开和回滚情况下的行为。失败的科学门槛在发布前返回拒绝。实际候选的正向发布没有发生：科学审计的结果为 REJECT，研究签名钥匙没有用于批准实际候选。

V5/V6 原生转换、推理一致性、实际拒绝回执及代码资格记录随本报告归档。成功发布、重开、服务和回滚的路径另由明确标记为合成通过指标的开发测试验证；它们不构成真实候选有效性的证据。Python 完整优化器状态重放和原生服务参数回滚分别验收。该接入处于本地研究范围，未切换默认 Agentd/生产路由。[原生分支](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/dot/cell-native-typed-v6-20261025)、[V6 实际拒绝](./evidence/20261025-cell-field-v5-v6/v6-native-rejection.json)。

每轮原生推理逐项核对全部 12 个候选和前驱、共 55,296 次预测；最大 logit 差为 3.56e-15，最大概率差为 V5 的 1.12e-15 / V6 的 1.00e-15，均小于 1e-12 验收界。V5 的实际门返回 `GateUnavailable(task)`，因为必需策略未完成；V6 返回 `GateFailed(task)`，因为完整执行后的任务门槛失败。两者均保持 owner 全部文件字节与注册表 head 不变。V5 首次验证遇到 JSON 浮点 roundtrip 精度问题，随后启用精确 float64 roundtrip 解析重新核对；未放宽任何指标相等判断或科学阈值。

Rust 验证包含四个实际源码 crate 的隔离闭包：215 项测试通过，1 个既有 worker 测试跳过，其父级 crash/reopen 测试通过；独立研究驱动另有 7 项测试通过，9 种转换破坏被拒绝。测试源与最终 lint/格式化及解析修正后的源分别记录；修正后的最终二进制完成了两轮实际推理与拒绝。资格范围不包含整个 workspace、Bazel 或 Agentd 集成，详见[原生资格报告](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/dot/cell-native-typed-v6-20261025/qualification/trained-cell-v5/README.md)。

## 8. 对《A Parameter Field Theory of LLMs》的 comments

评价对象固定为 [R45/f8df0a60](https://github.com/TrillionniumFoundation/ICLR-2027/tree/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45)，尤其是其[优化器一致状态、投影剩余项、信息/动作/系数误差分账](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex)。论文自己的冻结模块限制、目标计价和非线性保证边界应保留。

1. **它为 Hepta 提供了可执行的审计语言。** 完整优化器状态、控制器可见信息、动作集合、未来目标和非线性验证可以分别对齐到 checkpoint、紧凑场、动作库、规划器和准入证据。当前实验支持这一分解的工程价值。
2. **任意命名的少数标量没有自动充分性。** Loss2、Q4、History4 和 Structured4 的同动作 H8 结果显示，增加解释性摘要没有普遍改善决策相关信息。评估应加入同范数动作排序和实际决策损失，不能只比较一个合计目标。
3. **有限窗口闭合有建设性实例，但仍要计系数成本。** V6 给出一个从完整参考构造、对局部输出精确的紧凑表示。它是有限窗口可观测性构造，不构成新的通用非线性充分状态定理；重新构造系数和完整状态访问仍属于控制器成本。
4. **局部 Full 一致性没有推出独立任务收益。** V6 近乎逐位实现 Full H8，却通过 0/8 未来优势门槛。剩余问题包括规划目标与外部收益的对齐、非线性控制的迁移和探针代表性；此次数据没有分别识别每项的因果贡献。
5. **保留应明确说出对象。** 精确 old-probe 认证、独立 old-test 保留和家族校正的统计门槛是不同结论。27 个探针救回、0 个独立保留救回是一个需要保留的反例。
6. **Hepta 的 owner/snapshot 层负责证据约束下的采用。** 类型身份、签名、来源撤回和回滚证明系统按规则接纳或拒绝；这些机制不创造模型效用。当前最有价值的真实集成结果是拒绝失败候选并保持已发布状态完整。

可以成立的主张是：我们实现并完整审计了一个有限窗口局部损失场，它在小型真实训练头上保留 Full 的动作相关输出，并能连接原生证据准入。当前数据不支持“该场在这些独立任务上提供达到预定幅度的未来收益并同时保持旧任务”的主张。

## 9. 复现与证据索引

协议、执行代码和后置审计工具分别固定身份。Python 环境为 3.12.14、NumPy 2.3.5、SciPy 1.17.0、Torch 2.10.0 CPU、Transformers 4.57.3。控制器/审计使用 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`；编码器使用 4 线程。原数据档案和编码器 revision/hash 见协议与来源回执。

在 `qa/stem-bakeoff` 中，完成来源封存和特征准备后运行：

```sh
python cell_field_run_v6.py --data "$PFT_DATA/cohorts" --features "$PFT_FEATURES" --protocol cell_field_protocol_v6.json --output "$PFT_RUN"
python cell_field_replay_v6.py --run-directory "$PFT_RUN" --output "$PFT_AUDIT/replay.json" --protocol-path cell_field_protocol_v6.json --expected-protocol-sha256 cdd777f64265acfd6b8e44960a4f3c3bfbd5d856f76bc7c9d9c696bf4e11f41f
python cell_field_summary_v6.py --root "$PFT_RUN" --protocol cell_field_protocol_v6.json --output "$PFT_AUDIT/descriptive.json"
```

完整重放通过后，评价器通过标准输入接收其持有的独立 AES 密钥，并调用 `cell_field_score_v6.py --run ... --data ... --protocol ... --output ...`。密钥不进入命令行参数、版本库或回执。评价后使用 `cell_field_export_statistics.py` 导出逐来源统计。`cell_field_statistics_audit_v6.py` 固定校验本次 V5/V6 审计清单，并额外读取封存原始概率与策略记录完成全部 228 行核对；它是本次归档的复核工具，不能原样充当任意新运行的通用审计器。公开的逐来源导出也允许其他实现独立复算 bootstrap。V5 的运行/重放/评分入口对应换版本号，描述统计与统计审计工具同时支持两轮。重新运行控制器应在执行时源版本的独立 checkout 中进行，后置审计使用另一个 checkout；输出需使用新的目录，封存运行目录禁止追加文件。

| 证据 | 路径 |
|---|---|
| 冻结协议 | [V5](./cell_field_protocol_v5.json)、[V6](./cell_field_protocol_v6.json) |
| 执行源闭包 | [V5](./evidence/20261025-cell-field-v5-v6/v5-executed-source.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-executed-source.json) |
| 完整实际重放 | [V5](./evidence/20261025-cell-field-v5-v6/v5-replay-audit.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-replay-audit.json) |
| 方向/幅度/预测/压力账本 | [V5](./evidence/20261025-cell-field-v5-v6/v5-descriptive-census.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-descriptive-census.json) |
| 全部主/诊断指标与成本 | [V5](./evidence/20261025-cell-field-v5-v6/v5-evaluation.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-evaluation.json) |
| 独立统计复算 | [V5](./evidence/20261025-cell-field-v5-v6/v5-statistics-audit.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-statistics-audit.json) |
| 准入结果 | [V5](./evidence/20261025-cell-field-v5-v6/v5-native-rejection.json)、[V6](./evidence/20261025-cell-field-v5-v6/v6-native-rejection.json) |
| 文件身份与范围 | [证据清单](./evidence/20261025-cell-field-v5-v6/manifest.json) |

这些研究结果解决了实现与证据缺口，也明确否决了当前候选的联合收益主张。进一步改善需要新的可检验机制与预先冻结的新评价；本次已解封结果只能作为开发证据，不能再次充当确认样本。
