# PFT × Hepta：四步验证的实跑结果与边界

本轮已完成局部求解器、真实进程间及跨主机统计交换、既有实验原件复核、新的物理消息干预、延迟信息控制实验，以及原 A→B 准入检查。它是原 E1–E6 下的补充证据，不替换旧实验、旧门槛或旧预算。原 E1/E2 collection 没有重跑；原 native E6 没有增加一次运行或编译预算。

**当前证据支持：在共同冻结接口与线性二次目标下，局部参数求解可以正确组合，且能在独立主机上执行。它尚不支持从输入和最终输出直接恢复任意大模型全量权重，也没有完成真实跨用户能力迁移。现有性能结果不支持宣称整体训练更快，或 Hepta 普遍优于普通网络。**

## 1. 四步结果总表

| 用户要求 | 本轮实际完成 | 判定范围 |
|---|---|---|
| 集中、PFT 压缩、P2P 求解等价 | 54 个 LQ 案例；3 个非 IID 回归案例；9 个真实 HCSN 冻结特征父模型上的四进程求解；另完成双主机 TCP | 数学及工程前提通过；不等于全量非线性模型训练 |
| Hepta 结构提供额外能力 | 对现有 63+27+9+21=120 个候选复算原始预测；新增9父×3消息干预的真实物理 forward | 通信依赖成立；特征增益有条件；完整同容量连接学习优势未建立 |
| 多步控制超过单步编辑 | 冻结9组、108条延迟信息轨迹；全维/PFT/受限单步/固定32步GD及信息消融；135项因果前缀检查 | 已知 LQ 模型中的规划机制通过；没有非线性 HCSN/LLM 优势证明 |
| 真实 A→B | 实际调用原 #7029 checker；另绑定一个真实 HCSN 父文件、P2P 候选及特征声明 | 原候选被 retention 门拒绝；本轮真实采用链未闭合 |

这些数量没有混计：120 个是既有保存实验的审计；9×3 消息干预是新运行；108 条控制轨迹是合成 LQ 机制实验；双主机验证是一个小规模合成统计交换。

## 2. 直接求解与组合：通过了什么

实现位于 `pft_linear.py`、`pft_peer.py` 和 `pft_ring_qualification.py`。固定特征下，每个节点形成

\[
G_i=X_i^\top X_i,\qquad h_i=X_i^\top y_i,
\]

全局目标为

\[
\frac12\sum_i\|X_iW-y_i\|_F^2+\frac\lambda2\|W\|_F^2,
\qquad W^*=\left(\sum_iG_i+\lambda I\right)^{-1}\sum_i h_i.
\]

全局正则只加一次。实现用线性求解而非显式求逆。PFT 分支保留所有被计费的未来响应方向；多步版本支持非对角正定动作代价、可变有效秩、答案与 retention 观测的增广。它不处理任意非线性动力学、交叉熵、坐标 box constraints 或未知模型识别。

54 个 LQ 案例的全维 Riccati、压缩动作空间与独立 condensed KKT 解一致：最大动作误差 `3.33e-16`，最大总成本差 `2.22e-16`。新增终端方向却继续用旧子空间的负对照确实失败：旧 rank=1 的成本0.5，重建 rank=2 与全维的成本都为0.25。

实际 HCSN 部分固定全部9个父模型，使用原 `programs-v1` 的 train/dev 特征原件。新读出只拼接两条输入流的末状态特征和常数列，采用训练 RMS 缩放，目标为 AND/OR/XOR 的三列平方损失。它不是原 known-relation program 的四维非线性字典，也不是全量网络权重。192个训练对按12个 source 分成1/2/3/6源的四个非IID分片。

| HCSN单元数 | 每输出参数维数 | 有效秩（三种子） | P2P对集中解最大参数误差 | 冷进程预测 |
|---:|---:|---|---:|---|
| 8 | 41 | 41/41/41 | 2.12e-12 | 逐位相同 |
| 32 | 161 | 161/161/161 | 4.16e-12 | 逐位相同 |
| 64 | 321 | 192/192/192 | 5.76e-12 | 逐位相同 |

9/9父模型全部通过。每次四个独立进程通过真实TCP ring转发统计量，节点各自求解，没有中央 reducer。直接平均局部最优权重在全部9例上都有更高的全局训练目标；即使按样本量加权，目标超额仍为0.436%–11.243%。这不意味着集中最优解必然有更高的开发集分类准确率，原开发集各方法结果均保留。

范围必须具体：协调器仍负责分片、训练 RMS 和共同接口；压缩分支的 SVD 在集中分支构造，P2P 分支传的是完整 Gram。本轮没有联合验证压缩后的分布式基构造。冷重载读取保存的参数和缓存特征，并非原 native E6 或完整模型冷启动。哈希是字节绑定，不是用户身份或对抗性认证。

证据：[线性案例汇总](pft_fourstep_evidence_20261125/pft-linear-qualification-summary.json)、[HCSN四进程汇总](pft_fourstep_evidence_20261125/pft-ring-summary.json)、[完整ring原件](pft_fourstep_evidence_20261125/pft-ring-evidence.tar.gz)、[外层成本](pft_fourstep_evidence_20261125/pft-ring-outer-receipt.json)。

### 真实跨主机追加验证

`pft_network_probe.py` 在 desktop、pocket4 两台独立主机各自产生11/19行、8维的合成数据，只交换 Gram/rhs/计数，各自求解。两端解差为0，与独立 NumPy pooled reference 最大差 `1.11e-16`，正规方程残差 `1.78e-15`。两个 durable job 都退出0、输出完整；结束后均无残留试验监听。

应用层发送量为4581字节，两个方向各计一次；源码和协议分发另为25808字节。完整trial耗时85.622秒，包括分发、启动等待、取回结果及监听检查。pocket4先启动后等待约24秒；这段成本没有删去。控制面仍由协调器启动；两机属于同一operator；网络使用已有私网overlay，未证明底层没有relay。因此这里证明跨主机求解可行，不代表不同用户、开放参与、隐私聚合、恶意节点容错或可扩展性优势。

[公开证据投影](pft_fourstep_evidence_20261125/pft-network-public.json)保留完整合成统计量、解、数值核验、回执及原件hash；去掉网络地址和无关基础设施信息，明确不是完整raw。[协议模板](pft_fourstep_evidence_20261125/pft-network-protocol-template.json)没有执行过，不与实际协议hash混同。

## 3. Hepta结构：证据包含正结果，也包含反例

`pft_structure_audit.py` 在保存原件的主机运行，验证120/120个候选的封存、checkpoint绑定、原一次测试声明和原始logits，并独立复算准确率、CE、Brier、晚到信息前指标和停时。最大重算差 `2.22e-16`。这里是新closure63及其27基线、9joint、21communication，不包含旧formal72，也没有重跑原训练。

全部120个训练完成512 updates；学习门通过数为63/63、25/27、3/9、12/21。以下是selected checkpoint结果，三种子SD不是置信区间。

| 比较 | 平均准确率 ± 种子SD | 解释 |
|---|---:|---|
| N32 QVI/value-risk | 91.960% ± 0.343pp | 相同组内参数与物理状态条件 |
| N32 QVI/tanh | 90.951% ± 0.650pp | value-risk配对增益1.009pp |
| 1186参数GRU | 96.061% ± 0.789pp | 同数据，但状态容量和初态不同 |
| joint signed-only | 91.341% ± 1.297pp | 1186活跃参数，3/3过门 |
| joint boundary+signed | 73.763% ± 0.314pp | 1954活跃参数，0/3过门 |
| communication signed-only | 91.960% ± 0.665pp | 1186活跃参数 |
| unsigned-centered+signed | 93.717% ± 0.589pp | 1954活跃参数，不能把增益全归通道语义 |

N32在fixed/learned/QVI三种边界中，value-risk相对tanh的三个配对种子均为正；但N8 QVI和N64 learned的平均差分别为−0.260pp和−0.326pp。联合boundary+signed相对signed-only平均下降17.578pp。当前短序列任务上的GRU准确率更高、训练更快；不能用结构叙述替代这个结果。

完整参数、物理状态、初态、各源表现、41组种子配对差值以及完整成本见[结构审计报告](pft_structure_audit_evidence_20261125/SUMMARY_ZH.md)。learned boundary增加N个可训练标量；joint增加768个活跃连接；GRU初态、状态容量及dtype不同。分配相同张量字节也不等于相同有效记忆容量。严格同容量的固定/学习拓扑及完整Circuit六臂优势未建立。

### 新任务上的真实消息干预

`pft_interventions.py` 在原Torch2.8环境逐时钟执行原SignedHCSN物理forward。先冻结8个新synthetic source IDs，再生成512个例子；全部9父在完整、删除、固定置乱三种消息条件下各运行12个时钟。权重、缓冲区、readout、连接mask和初始状态相同；之后的动态状态允许因干预分叉。

| 单元数 | 完整消息 | 删除消息 | 置乱消息 | 删除下降 | 置乱下降 |
|---:|---:|---:|---:|---:|---:|
| 8 | 90.30% | 48.31% | 48.11% | 41.99pp | 42.19pp |
| 32 | 91.60% | 44.92% | 45.31% | 46.68pp | 46.29pp |
| 64 | 91.08% | 51.69% | 52.02% | 39.39pp | 39.06pp |

9父×3条件全部成功，零更新。最大概率质量误差 `4.66e-15`；从保存NPZ独立重算27组总体及每源指标，最大CE误差 `2.22e-16`。删除条件进入连接的signed消息范数为0，所有父模型权重和缓冲区前后hash不变。

该架构本来就让sender接收原输入、readout只读receiver，所以干预证明现有信息通路及来源配对的重要性，不证明学习图优于固定图。13824条预测轨迹共享512例、8个源，不能当成13824个独立样本。

证据：[干预汇总](pft_fourstep_evidence_20261125/pft-interventions-summary.json)、[完整原件分片与hash](pft_fourstep_evidence_20261125/pft-interventions-parts.json)。

## 4. 延迟信息：多步机制成立，算法优胜必须限定目标

`pft_horizon.py` 先冻结源码、数据law和全部9组配置，再执行108条轨迹。状态包含可编辑参数theta与当前目标belief；新信息只在中途transition之后进入信息集。所有方法使用同一参数块和包含任务误差、retention及动作代价的二次目标。

| 参数维数 | PFT/全维Riccati平均总成本 | 受限单action ridge/RLS | 完整horizon固定32步GD |
|---:|---:|---:|---:|
| 8 | 0.100270 | 0.158555 | 0.100198 |
| 32 | 0.465761 | 0.726468 | 0.467238 |
| 64 | 0.999445 | 1.574690 | 1.001745 |

PFT与全维动作最大差 `3.03e-15`，受限目标的direct与RLS最大差 `2.00e-15`。135次改变未揭示future suffix的检查，揭示前动作全部逐位不变。

受限对照只允许当前一个动作自由、将其余未来干预设为0；它的较差总成本来自规划限制。RLS本身不是天然短视，给它完整condensed horizon也可以解出同一LQ最优。多步策略更节省动作代价，未必逐项获得更低任务误差或retention误差。因此不能把表格写成“FBSDE普遍击败RLS训练”。

实得样本中N8的GD均值略低，9组中有3组GD-minus-full为负，原值全部保留。随后新增的只读解析审计传播相同初态和创新law的均值/协方差，并用独立backward quadratic value复算：期望成本差的两种计算误差最多 `2.66e-15`，27个初态中精确控制的期望成本都不高于GD或受限对照。这是post-run数学复核，没有增加新样本，也未改原协议或算法。

这些是已知线性二次模型中的Riccati/PFT特例，不是对一般FBSDE、非线性Hepta训练、主动选择等待/采样动作或LLM学习的确认。真实长期训练优势仍需在相同非线性参数块上成立。

证据：[冻结协议](pft_fourstep_evidence_20261125/pft-horizon-protocol.json)、[结果汇总](pft_fourstep_evidence_20261125/pft-horizon-summary.json)、[完整轨迹分片](pft_fourstep_evidence_20261125/pft-horizon-parts.json)、[后置精确期望审计](pft_fourstep_evidence_20261125/pft-horizon-analytic-audit.json)。

## 5. 全成本：目前没有系统加速结论

| 单元数 | 集中Gram构造及求解均值 | SVD压缩及求解均值 | 四进程ring启动到退出均值 | 原父训练启动到退出均值 |
|---:|---:|---:|---:|---:|
| 8 | 0.005742s | 0.004276s | 0.275396s | 197.893s |
| 32 | 0.030644s | 0.058472s | 0.595828s | 394.944s |
| 64 | 0.111334s | 0.109398s | 1.546629s | 665.940s |

这些是本轮一次工程运行的实测值，不是重复随机次序的速度基准。压缩在N8/N32没有降秩；N64降到192维，但SVD成本抵消大部分求解收益。JSON传完整Gram、独立进程启动和通信均有实质成本。

原每父特征构造成本约6/13/20秒，另有原父训练成本。本轮缓存工程运行的外层完整启动到退出为12.048秒（含9父全部方法、验证、进程导入与最后写盘），不是重新训练9父的时间。双主机完整trial为85.622秒；新增物理消息干预含预检/导入/退出为211.923秒；现有120候选独立审计为21.823秒。它们各自有不同工作量和时钟边界，不能相加后宣称某个训练算法的端到端加速。

控制实验另记录互不重叠的feature/response、solve、validation和overhead区间，总1.617秒，通信为0，因为该实验没有通信。所有并行peer耗时、内部body和外层wall分开保留，不重复相加。助手编写、工具编排及完整历史发现成本没有完整计量，不能记作0。

## 6. 真实 A→B：原检查确实拒绝，未用工程替身补齐

`pft_transfer_gate.py` 对16份原checker模块逐一核验固定Git blob，再调用未修改的 #7029 `paired_source_dispatch.verify_originals`。实际返回：

```text
ORIGINAL_CHECKER_REJECTED
source retention gate did not permit prospective dispatch
```

该封存候选的原决定为 `no_update_retention_regressed`；operation明确是engineering_fixture，未消费新的前瞻B记录。另一次故意提供不同candidate digest得到 `CANDIDATE_MISMATCH`，不会把旧报告套到新候选。

本轮也制作了具体可审查的HCSN材料：一个实际父checkpoint、P2P生成的新readout、特征接口及预先保存的三项绑定hash。独立进程复核返回 `ARTIFACTS_VERIFIED`。这只证明文件绑定正确；原paired_cold目前没有该HCSN family loader，也没有本候选的原owner冻结、真实双方授权、旧能力冷验证、采用或native重启回执。

因此本轮可宣称的真实A→B成功数为0。这个结论限定于本次检查及封存operation，不是对所有私有设备或用户的普查。

继续真实A→B所需的是：原身份/授权owner中的两名真实参与者与授权经验；候选确定前独立封存的B新任务；同一候选的源端retention通过；原loader与采用路径实际接入；B采用和重启后对同一候选的一次封存评估。B最终测试不得反馈候选选择。当前旧候选的retention失败也必须先修复，不能只补身份文件。

证据：[原准入读回](pft_fourstep_evidence_20261125/pft-transfer-readback.json)、[原checker来源核验](pft_fourstep_evidence_20261125/pft-owner-source-verification.json)、[具体候选绑定](pft_fourstep_evidence_20261125/handoff/HANDOFF.json)、[绑定核验与未闭合阶段](pft_fourstep_evidence_20261125/handoff/AUDIT.json)。

## 7. 复现与源码冻结

所有代码位于现有 `qualification/hcsn_closure_20261124` 下，按可独立审查的阶段提交。没有修改原protocol、原checkpoint或原实验目录。数值原件使用无损gzip；大包按480000字节分片并提供原始/压缩/分片hash。跨机网络原件保留于原执行所有者，公开版是明确标注的投影。

最终仓库格式化可能改变源码字节而不改变语义。**复现旧冻结协议应先使用[frozen-executed-source.tar.gz](pft_fourstep_evidence_20261125/frozen-executed-source.tar.gz)及[逐源hash](pft_fourstep_evidence_20261125/FROZEN_EXECUTED_SOURCE.json)**，或对应的格式前Git提交；不要把当前格式化源码的hash冒充当时执行源码。每个实验的自己的protocol记录才是具体执行身份。

原始线性实现的第一次尝试也保留，但不算作第二批独立样本。一次可选远端post-run原件重哈希请求返回launch_unknown，随后没有可读job目录；没有重放，也没有宣称它成功。已完成的本地36个候选文件、9个冷载文件和原冻结训练承诺核对单独存档。

当前研究命题可缩小到已经有证据的部分：共同冻结响应接口下的局部二次更新，能够通过正确充分统计量融合保持全局最优，并跨主机执行。下一次能够改变研究结论的实验，应针对非线性长期训练、严格容量/预算约束下的结构收益，以及真实独立用户迁移；本轮结果没有替这些目标提前通过。
