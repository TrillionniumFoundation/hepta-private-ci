# 内容寻址：长度失败的定位与因果时钟修复

## 结论与范围

本轮把 token 长度与物理时间跨度拆开后，发现共同内容前端的时间外推是原有 Copy/MQAR 失败的重要来源。保留原模型参数，仅因果地限制共同编码器的时间特征，能够大幅恢复精确回忆。这个结果属于普通共同内容路径，不能计为解析神经元的收益。

同时实现了固定符号编码下的因果 delta-rule 地址记忆。它在 32、128、512 token 和两种期限的全部实验中精确回忆 100%，提供可复用的共同内容缓存和任务已知的结构参照。它没有证明自然内容编码、神经网络自动发现寻址规律或更一般的容量扩展。

基线为 `c5e159ec6c5ba174b36debacad166da635c57d48` / PR #4519。使用其已按验证集选择的三个 fitted seeds：81031、81032、81033；不训练、不重新选择 checkpoint。

## 1. 把长度与物理期限分开

先冻结 [PROTOCOL.json](results/memory/PROTOCOL.json)，再用新 seed 202610314201 生成每个任务 128 条序列。对同一条 32-token 序列插入无关 token 到 128 和 512 token，保留原四个绑定、查询顺序、原有 token 和其相对物理时间。32/128 token 分别交叉总期限 3.2/12.8。长度变化仍同时改变无关 token 数量和 ordinal 位置，因此本轮没有把这两个因素进一步分离。

共同内容路径、普通 two-gate adapter、解析 adapter 都使用相同输入；两个 adapter 均另做关闭诊断。18 个旧 checkpoint、120 个神经模型评估单元、12 个地址记忆参照单元均完成，未出现执行失败。每个单元保存全部四次查询的概率、标签和 episode ID。

下表是三个 fitted seeds 的平均**四次查询全部正确率**，并非逐 token accuracy。不同 seed 使用同一批新序列，不能视为三个独立数据集。

| 共同内容路径 | 32 tokens / 3.2 时间单位 | 128 / 3.2 | 32 / 12.8 | 128 / 12.8 |
| --- | ---: | ---: | ---: | ---: |
| Copy | 100.0000% | 99.7396% | 9.3750% | 6.7708% |
| MQAR | 100.0000% | 100.0000% | 72.6563% | 54.9479% |

相同物理期限下把长度扩展四倍，对共同 Copy 的损害很小，MQAR 没有损害；相同 token 长度下把期限扩展四倍则造成大幅退化。48 个 adapter-disabled 预测表与各自共同 donor 的预测概率逐元素完全相同。因此，至少这部分失败已经存在于共同编码器与寻址路径中，不能仅归因于解析状态压缩或复位机制。

启用 adapter 也没有关闭长时域内容问题：128/12.8 下，Copy 的普通/解析 adapter 精确回忆分别为 10.6771% / 12.2396%；MQAR 为 59.6354% / 58.0729%。完整逐 seed 结果见 [RESULTS.json](results/memory/RESULTS.json)。

## 2. 单一、另行冻结的因果时钟干预

在上述诊断完成之后，单独冻结 [时钟干预协议](results/memory_clock_repair/PROTOCOL.json)。它明确属于 **post-diagnostic exploratory**，使用已看过的输入，不是独立确认。只尝试以下一组固定阈值，没有以测试结果搜索阈值：

- 共同内容编码器的 `dt` 特征上限为 0.15；
- 共同内容编码器的累计时间及其时间位置编码上限为 3.2；
- 原模型权重、ordinal 位置特征、原始物理 `dt` 保持原样；
- 截断只用当前前缀的累计时间，不读取最终长度、总期限或未来内容。

实现位于 [memory_clock_repair.py](memory_clock_repair.py)。这里只执行无物理 adapter 的共同 donor；该干预没有产生任何“解析核心修复”结论。24 个单元的完整前缀编码均与截断到该前缀的独立编码逐元素相同。

| 任务及条件 | 原精确回忆 | 固定时钟截断后 | 三个 seed 截断后 |
| --- | ---: | ---: | --- |
| Copy，32 / 12.8 | 9.3750% | 100.0000% | 100%, 100%, 100% |
| Copy，128 / 12.8 | 6.7708% | 96.6146% | 100%, 89.8438%, 100% |
| MQAR，32 / 12.8 | 72.6563% | 100.0000% | 100%, 100%, 100% |
| MQAR，128 / 12.8 | 54.9479% | 100.0000% | 100%, 100%, 100% |

3.2 时间单位的四个条件均没有变化：Copy-128 为 99.7396%，其余为 100%。所有 outcomes 均保存于 [时钟干预结果](results/memory_clock_repair/RESULTS.json)。Copy-128 仍有一个 seed 未达到精确回忆要求，不能把它记为全部关闭。

这表明应把内容的地址与身份表示，同物理时间、风险和价值状态分开。下一轮可在未看过的数据上确认这一固定处理，再决定是否训练一个不依赖绝对时间的共同编码器。本轮不声称这个阈值普适。

## 3. 可复用的因果地址记忆

[DeltaMemory](memory_probe.py) 使用任务已知的归一化 one-hot 键与 one-hot 内容编码。写入更新为

\[
M \leftarrow M+k(v-M^\top k)^\top,
\]

其中按实现的矩阵约定，`M` 为地址数乘内容维度，等价的代码更新是 `M += k[:, None] * (v - k @ M)[None, :]`。读取为 `q @ M`。相同键的新写入替换旧内容，未见过的键明确返回未知。

Copy 使用四个因果 selected/query ordinal 地址；MQAR 使用原始输入提供的八维符号键。处理过程中只读当前 token，不使用标签、未来 token、最终长度或物理期限。

12 个长度/期限条件（每个 128 条序列，共 1,536 条、6,144 次查询）精确回忆均为 100%。六项行为检查另外验证查询重排、所有八个键并存、重复键最后写入获胜、后续写入不改变已完成读取、未知读取弃答及多重键拒绝。

Copy 的数组状态为 132 bytes，MQAR 为 264 bytes；这是 float32 记忆矩阵和 presence bitmap 的有效载荷，**不含** Python 对象、运行时、计数器、输入及输出缓冲区。每条序列仍检查所有 token，只有四次有效写入和四次读取。这里证明的是固定四条绑定与有限词表的长度不变性，没有证明任意容量或未知内容寻址能力。

## 4. 独立核验与成本边界

[memory_audit.py](memory_audit.py) 不导入候选生成器、记忆模型或打分函数，直接从输入 token 用列表/字典重建标签，独立核验 12 个数据集、132 张预测表和 67,584 次查询；所有分数一致。它还核验插入 token 后原内容与物理事件时间保持一致，以及全部 48 张 adapter-disabled 表与共同 donor 精确相等。

首次审计发现一个审计器数值容差问题：512 次 float32 时间累加与 double 时间戳的最大差约为 `4.87e-5`。保留了 [原审计源码与失败说明](results/memory/audit_history/INITIAL_FAILURE.json)，改用 float64 累加已保存的 float32 间隔检查时间戳，同时逐数据集公开实际 float32 累加误差。候选输入、模型和预测未因此修改。

[时钟独立核验](results/memory_clock_repair/INDEPENDENT_AUDIT.json) 重新计算全部 24 张配对表、12,288 次查询，确认 checkpoint、标签及 episode 身份一致。

原诊断进程记录约 17.67 CPU 秒和 258,824 KiB 峰值 RSS；时钟干预约 2.30 CPU 秒和 228,324 KiB。该进程在共享主机执行，包含已声明的导入、加载及评估范围；没有重跑历史训练，没有测量设备能量。这些是本轮诊断成本收据，不是隔离硬件上的模型经济性比较，也不把旧训练成本抹去。

## 复现

先按 v2 `REPRODUCE.md` 恢复 `content001` checkpoints，再选择有对应 PyTorch 的解释器，设置单线程环境。新输出目录不能覆盖现有证据。

```bash
python -m experiments.hcsn_causal_execution_v3.memory_probe \
  --output /new/output/memory \
  --checkpoint-root experiments/hcsn_mechanism_content_v2/results/content001/jobs --prepare
python -m experiments.hcsn_causal_execution_v3.memory_probe --output /new/output/memory --run
python -m experiments.hcsn_causal_execution_v3.memory_audit /new/output/memory
python -m unittest experiments.hcsn_causal_execution_v3.memory_probe_tests
python -m experiments.hcsn_causal_execution_v3.memory_clock_repair \
  --output /new/output/clock --memory /new/output/memory --prepare
python -m experiments.hcsn_causal_execution_v3.memory_clock_repair --output /new/output/clock --run
python -m experiments.hcsn_causal_execution_v3.memory_clock_audit /new/output/clock
```
