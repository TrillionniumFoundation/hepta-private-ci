# Shared Stem、Memory 与 NDU 的下一轮实验协议

状态：**PROPOSED / NOT EXECUTED / SHADOW_ONLY / DENY_ALL / NO_GO**。
本文件把用户要求落实为可验收的后续实验和接口约束，不声明新模型能力、训练收益、
System2 涌现、全局最优 Stem 或生产授权。已执行结果见
[research/RESEARCH_STATE.md](research/RESEARCH_STATE.md)。

## 1. 从已经读过的实现出发

本轮核对的 #2695 head 为 `74bbcc9b0bb330649cd54d9881ae3676d3968bae`。
[SharedEncoderOwnerV1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/74bbcc9b0bb330649cd54d9881ae3676d3968bae/codex-rs/hepta-neuron/src/shared_encoder.rs)
在校验请求与 Cell 列表后调用一次 driver，再验证结果并用不可变 Arc 共享特征。
这是一次请求内的接口和内存共享性质；底层是否使用真实预训练 Encoder、不同输入间
是否能缓存、延迟与质量如何，需要另外测量。
[shadow_system2.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/74bbcc9b0bb330649cd54d9881ae3676d3968bae/codex-rs/hepta-ndu/src/shadow_system2.rs)
是有界确定性建议器，最多 64 层、有限预算，返回 DENY_ALL；它没有训练出的 critic，
其中配置的 value_gain 和 uncertainty_decay 不是观测到的能力增长。

#2688 head `55088dd78b4950407f77a43f054efed0816409cb` 的 MemoryCell 契约
在 recall 前绑定来源、代际、遗忘边界与快照，返回候选证据，不增加 writer 或 topology apply。
这些边界应作为后续实验的前置条件，不能用模型输出绕开。

## 2. Stem 选择与分化：先固定比较口径

不预先宣布某个模型是最佳 Stem。每个候选必须先冻结模型 revision、完整文件清单、
权重与 tokenizer 哈希、license、数据版本、runtime patch、精度和设备信息。
在同一组任务与预算上比较下列方案，候选不可在看到 holdout 结果后换名重选。

| 方案 | 必须测量的收益与代价 | 必须保留的控制组 |
| --- | --- | --- |
| 冻结共享 Encoder + 各 Cell 轻量 head | 单输入一次 forward、各 head 参数和吞吐；跨任务迁移 | 每 Cell 独立 Encoder、共享但无个性化 head |
| 冻结 Stem + 各 Cell adapter/低秩参数 | 训练成本、adapter 切换和撤销、干扰 | 相同参数预算的线性 head、同数据无训练 |
| 有限 Stem 层可训练 | 质量增量与旧任务回归、checkpoint 体积 | 同预算冻结 Stem；独立新任务与旧任务测试 |
| 稀疏路由与专家复用 | 实际激活计算、路由误差、尾延迟和热点 | 均匀或静态路由、单专家；记录所有拒绝/退避 |
| 蒸馏或量化 | 教师生成/蒸馏成本、压缩后校准和引用正确性 | 原精度原模型、同数据同预算的小模型 |
| 共享缓存 | hit/miss、隔离、失效、内存占用与撤销时延 | 禁用缓存、不同租户/代际/隐私标签强制 miss |

参数内存的规划估算可用 `Stem + sum(Cell heads/adapters)`，但实测必须另加
activation、optimizer、缓存和运行时开销。相同输入、模型与授权域才可能复用表示；
不同输入的 N 个 Cell 不自动等于一次物理 forward。缓存键至少绑定 tenant/privacy
domain、模型/adapter revision、输入摘要、tokenizer/预处理版本、generation、
source/forget frontier。撤销或删除后必须失效所有受影响缓存与派生索引。

多模态阶段先做各模态独立投影与可追踪的时间戳/时间窗，再测试共享表示。
文档、图像、音频、视频、传感器与动作分别记录采样/分块、对齐误差和缺失模态。
动作 head 只产生 shadow proposal；设备 effect 仍须原 owner 的 admission 与 Final-use。
在单模态基线、配对跨模态和打乱对齐的负控上同时测量，避免把同步线索泄漏当作推理收益。

## 3. Memory 40+72：保留历史证据，新增独立数据

已重验的历史 40 次校准为 8 tasks × 5 个 k，72 次评估为 8 tasks × 9 臂，
不是 112 个独立样本。它们使用已暴露的开发集；本轮没有重新执行这 112 次推理。
新 Reader 64 calls 另属 Laya 诊断，不能替代该目标。

下一轮先建立数据登记簿，再在校准集冻结超参和停止规则，最后解封独立来源/时间窗
holdout。保持原九臂配方以便审计历史差异；额外控制组独立编号，不把多跑的调用
计入原目标。至少分别识别：检索召回、单跳筛选、关系/程序遍历、版本纠错、Reader
容量、组织结构和参数学习。只有训练数据、初始参数、训练步骤与学习后 checkpoint
均留存，并且固定检索/提示/预算，才可把差异解释为参数学习证据。

每次调用保存：原始答案、逐项来源与精确引用位置、prompt/dataset/model 哈希、
seed/temperature/运行时实际采用值、输入与输出 tokens、设备、墙钟时延、峰值内存。
无法测量 FLOPs 或能耗时标 null 与测量缺口，不能用估算冒充设备测量。
成本账本另计 extraction、index build、存储、维护、遗忘/删除、撤销与崩溃恢复。
保留拒答和失败行，不只统计成功返回；按独立来源/任务聚类计算区间，不能把同题九臂
或同 prompt 重复调用当作九个独立样本。引用链需独立语义复核，不仅是 ID 可解析。

外部证据以可校验、可撤销 provenance 为事实来源；有损参数记忆只能提供候选。
Memory split/merge 先生成带 lineage、成本上限和可回滚版本的 proposal，比较
split 前后质量、延迟、存储、forgetting 与引用完整性；不能由收益分数直接执行拓扑写入。

## 4. NDU / Merton：把类比写成有约束的控制问题

以下是拟议数学建模，不是已验证的最优性定理。
令状态 `s_t` 包含 belief、任务证据、Cell/模型版本和权限状态；预算向量
`b_t = (tokens, wall_time, compute, energy)`；动作包括检索、Reader 调用、
继续推理、rollout、换专家和 stop/abstain。每步必须满足逐维剩余预算与硬权限约束。

拟议有限时域目标：

`max E[task_utility(s_T) - sum_t lambda dot measured_cost(s_t,a_t) - risk_penalty]`

其中价值增量必须由受控任务结果校准；lambda、风险函数和效用定义预先登记。
安全与权限不折算成可用收益抵偿的软惩罚：未经授权的动作从可行动作集剔除。
预算是会耗尽的资源，不假定像金融财富一样可按连续市场模型增值；动作收益相关、
有延迟且分布漂移，不能从经典 Merton 假设直接推出 LLM 的最优 token 配比。

先与固定预算、固定深度、静态按任务路由和简单边际收益阈值比较，再考虑
contextual bandit 或离散动态规划。HJB/FBSDE 仅在状态、动力学、边界条件、
校准误差和求解残差有证据时作为候选求解器；先跑通数学近似不等于 Hepta native
集成或真实模型收益。日志策略要留 propensity，离线 IPS/SNIPS/DR 评估必须报告
support/overlap、有效样本量与权重敏感性；无重叠时结论为不可识别，不能强行评分。

训练侧分别比较任务 mixture、课程/梯度预算、rollout 分配与 credit assignment；
推理侧分别比较 reasoning、Memory、Tool 与 Reader 预算及停止规则。Group 只汇总
可审计建议与成本，不能通过跨 Cell 调度获得新的 effect 权限。实验保留 shared-only、
independent-only、固定路由、随机但有预算的 shadow 路由与 ablation；System2 的收益
必须来自预注册的新任务结果，并同时检查负迁移、遗忘和安全拒绝率。

## 5. 验收和停止条件

先冻结任务/来源与软件树，补齐模型、设备、成本与引用 receipts；完成 baseline、
负控和 holdout，再独立复核统计与安全证据。任何完整 provenance 缺失、未知权限、
预算溢出、跨租户缓存命中、删除后仍可召回或旧任务显著退化都保持 NO_GO。
候选仅在预先登记的准确率、尾延迟、峰值内存、吞吐、能耗与总成本指标上作 Pareto
比较，不在看到结果后更换加权公式选胜者。生产 promotion 还需要独立授权及
当前源码/当前基线的全部 required gates；本协议不构成该授权。
