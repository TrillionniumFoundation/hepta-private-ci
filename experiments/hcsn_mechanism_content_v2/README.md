# HCSN: mechanism, content and complete execution cost

本轮执行四项验收：解析传播是否改变内容与动作；普通门控与解析核心的
2×2 归因；共同内容寻址、精确回忆与真实 AV；同质量下的完整执行成本。
正式结论见 [REPORT_ZH.md](REPORT_ZH.md)，独立检查见
[INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md)。

## 固定来源

基础代码来自 `9709af902dc029efc007e4122425c6a72f0559b9`，177 个复用文件
逐一匹配该远端源码。原始研究的后续负面结果保留在来源清单中。
全部正式矩阵、模板与候选源码在执行之前发布于
[`1a5434f361d2df8a0505b6069fe6d48736f9ff30`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/1a5434f361d2df8a0505b6069fe6d48736f9ff30)。

| 证据 | 位置 |
| --- | --- |
| 基础源码及历史范围 | `SOURCE_BASELINE.json`、`provenance/source_files.jsonl` |
| 真实 AV、归一化、许可、旧 cohort 身份 | `DATA_IDENTITY_VERIFIED.json`、`provenance/` |
| 机制实验全部 12 作业 | `protocols/mechanism001/plan.json` |
| 内容实验全部 108 作业及 108 模板 | `protocols/content001/` |
| 初始与最终状态、选点、预测、访问及成本 | 正式结果的 multipart evidence archives |
| 开发过程、失败与源码局限 | `artifacts/development001/` |
| 复现与归档读取 | [REPRODUCE.md](REPRODUCE.md) |

## 两个互补的研究对象

### 连续更新过程的内容与控制

`renewal.py` 给出固定首达边界、常系数扩散、固定复位及确定性不应期下的
重复事件分布。第 n 次事件发生的概率由首达 CDF 计算，内容按

\[
z_T=\sum_n \Pr(N_T=n)M^nz_0
\]

传播。真实标签独立采用 inverse-Gaussian 事件采样与 Markov 内容转换生成；
读取的物理状态来自联合一致的 first-passage bridge。
`mechanism.py` 实行有一 tick 延迟的 READ、WAIT、STOP 和三个读取的预算。
读取不会重置外部世界；STOP 之后仍需完成四个预定内容输出。

主 2×2 的普通核心为 23,712 参数 gated feedforward propagator，解析核心
带有已知 stationary renewal 结构；它们使用相同的观测、参数校准和内容矩阵。
两个 task-value 臂共用 one-planned-read receding heuristic；两个 lightweight 臂
共用轻量阈值控制器。原始日志支持分别重算
内容差异、实际动作差异和观测成本。数学范围见
[MECHANISM_CONTRACT.md](MECHANISM_CONTRACT.md)。

### 共同内容能力与可训练动力学

`content.py` 让 shared-only、普通 two-gate 和 finite-grid regenerative adapter
共用因果 SDPA、encoder、readout 及确切相同的内容预训练 checkpoint。
复制任务还共用仅由过去标记导出的顺序地址。所有输入派生信息都提供给各 arm。

四项任务为 selective copy、MQAR、CREMA-D 情绪识别、同 actor 的音视频
正负配对。后两项使用既有 48 条录像的因果特征。训练／验证／测试 actor 数为
4／2／2；数据已经在早期研究中观察过。本轮的配对任务保证两种单模态的
正负输入边缘逐字节平衡，并加入 metadata-only 诊断。

每项任务比较冻结共同内容模块与联合训练，分别采用 256 次更新及 20 CPU 秒
预算。验证 CE 允许选择 step 0；选择到初始状态时，记录会明确其尚未训练。
本轮使用的共享 SDPA 保留注意力寻址的计算成本。

## 成本和证据约定

`study.py` 在完整独立进程结束时使用 Linux `wait4` 记录 CPU、墙钟与峰值 RSS。
这些成本覆盖导入、数据准备、训练、选择、推理和保存；共同预训练在研究总账中
只计一次。模型的传播、边界与恢复计算已包含在真实执行里。

推理 profile 使用验证集、batch=1，测量准备张量、整段前向、监督读出及
ID／时间提取，报告逐请求 p50/p95。运行在共享 CPU 主机上，允许最多两个正式
实验 worker 并行，并非隔离负载。原始媒体解码、现场传感器、
网络和设备能量不在该 profile 的测量范围；能量字段保持空值。

`accuracy - READ fees` 表示含观测收费的任务效用。计算成本作为另一个实测轴。
局部解析核和独立积分的同精度比较、完整网络质量和完整网络成本分别报告。
