# 独立来源上的联合证据续做

## 检验对象

本实验固定原 `repair_20261026` 的 FSDD observer，不更新其参数，使用此前该
observer 未训练或评分的 AudioMNIST 来源。这里的“新来源”指本实验链中未用过的
数据集局部 speaker 与 WAV 身份；没有把它扩大为所有历史研究均未见过、或已经
解析了跨数据集真实人物身份的声明。

目标 prior 与 observation likelihood 分开：

\[
q(y_1,y_2\mid c),\qquad
L(o_1,o_2,a\mid y_1,y_2),\qquad
p(y\mid c,o,a)\propto q(y\mid c)L(o,a\mid y).
\]

`c` 是公开任务 cue，prior 不读取 WAV、CNN 输出或事件 hash。`o` 是固定 CNN
对实际波形的输出，`a` 是两个已经到达的物理事件是否相同。没有把同一 WAV 的
特征同时当成独立 prior 信息和 likelihood 信息。

本研究沿用明确限定的 allocator：相等数字使用同一录音；不同数字使用同一
speaker 的两个不同录音。因此事件别名本身携带“目标相等”的信息。这个机制
是受控任务规则，**不是自然语音的一般性质**；两个相同数字也可以在其他任务
中来自不同录音，不能直接套用本模型。

## 数据与冻结顺序

官方来源为 [soerenab/AudioMNIST](https://github.com/soerenab/AudioMNIST)，固定
commit `630d7dab4c040882834de6fa21baf9a60372accd`。使用 speaker `01–20`，
每个数字的录音编号 `0–19`，共 4,000 个原始 WAV。`01–08` 拟合 likelihood，
`09–12` 选择超参数，`13–20` 测试。每个来源的贡献相同。波形下载和哈希检查
可以提前进行；测试模型特征直到拟合和选择冻结后才计算。

原 observer 的 SHA-256 为
`6c5391e2ea0ee6102977992cb14ebcee857e393a7c9c66b8b534c78951356e86`。
48 kHz PCM16 原始数据通过固定 polyphase FIR 重采样到 8 kHz，再使用原始
64×64 STFT 与归一化接口。这个跨数据集输入分布变化会单独报告。

旧 FSDD 试验的 3,000 个物理 WAV hash 与新来源全量比较。旧 `yweweler` 测试
结果不用于本轮选择，也没有把它重新称为新 qualification。

## v1 拟合阶段发现的问题与 v2 修复

最初冻结的 `PROTOCOL.json` 已完成 fit/validation，**没有计算新测试特征**。
独立模型选择边际 pseudocount 10，validation NLL 为 2.4004。两个联合族则
使用固定 .5 边际，即使强烈收缩也约为 2.623。这使“联合依赖”比较混入了
边际校准差异。该次拟合目录、完整执行源码与选择结果保留。

`PROTOCOL_V2.json` 在新测试特征计算前修订：先使用 validation 选择统一
边际；所有联合候选都投影到同一边际。额外加入明示的 independence 候选，
仅可在 validation 上选择。测试结果不能触发回退、换模型或更改阈值。

这次变更是基于开发集的模型修复，不伪装成最初未见任何开发结果的设计。

## 三种观测模型

1. **Pooled independence。** 以全部 fit speaker 的单事件计数拟合平滑边际，
   条件独立是明确标出的假设。
2. **Paired shrinkage。** 实测两事件联合计数，向明确的 pooled product 收缩。
3. **Speaker mixture。** 每个 fit speaker 的 confusion matrix 向 pooled
   confusion 收缩，再混合 speaker 条件下的两个事件分布。共享 speaker 是
   潜在依赖来源；speaker 内的条件独立仍是需要检验的建模假设。

对两种联合族的正表格做 information projection，使它们与强独立对照具有
相同的单事件边际。由此观测到的差异主要来自 coupling，而非不同的边际平滑。
联合候选可在 validation 上退回完整声明的独立模型；如发生，会报告“未选择
保留联合依赖”，不会把它描述为联合结构取得优势。

只有实际测量过的 target 列能够被平滑和投影。没有任何测量的列保持 unknown；
正 prior 覆盖 unknown 时拒绝推断。重复物理事件在拟合中去重，已到达的同一
事件在推断中只贡献一次 likelihood。

三个族接收相同 fit/validation 信息并共享同一组固定 CNN 观察。独立族搜索
7 个边际候选；联合族各有 7 个 coupling 候选及一个独立选项。拟合 CPU 成本
单独记录；不把不同搜索量包装成相同训练计算预算下的估计器优势。

## 单独的 prior 依赖检验

此部分使用公开 cue `uniform/plus1/plus3/plus7`。后面三个任务的目标联合
分布为 70% 指定模 10 关系加 30% 均匀分布，两个 marginal 均为均匀分布。
目标来源是公开声明的受控配对机制，实际观察仍来自相应的真实 WAV。

联合 prior 与 factorized prior 各自在 fit 目标记录上拟合，用 validation
目标 NLL 选择平滑强度。prior 模型只能读取 cue 与训练目标计数，不能读取
音频、观察者输出或隐藏测试目标。两者使用同一个已经冻结的 likelihood。

这提供“边际无法表达指定依赖”的机制检验和真实输出检验。它不证明自然
语音任务的目标分布本来就满足这些关系，也不构成新的神经生成器训练。

## 交付、评分与审计

推断写出器只接受 opaque sample ID、event IDs、观察值和可选 cue。若输入
含 target 或其他私有字段，直接拒绝。每个预测实际写成 UTF-8 JSONL，完成
后重新读取才计算准确率；likelihood NLL 与 posterior NLL 分开记录。

独立审计使用另一套数组公式重建选定联合表格和 prior，检查冻结时间顺序，
重哈希全部来源，重新读取全部交付并重算逐 speaker 指标。直接 lookup 的
全到达后验还与原 `EvidenceFilter` 的顺序/重复 receipt 路径对照。

主要统计单位是 8 个测试 speaker。派生 pair、重复使用同一录音、同一来源
下不同 cue 都不增加独立来源数。配对 bootstrap 对 speaker 重采样，给出
固定公开来源的敏感性区间；不认证普遍说话人总体、自然多模态大模型或实际
owner 的未来执行分布。
