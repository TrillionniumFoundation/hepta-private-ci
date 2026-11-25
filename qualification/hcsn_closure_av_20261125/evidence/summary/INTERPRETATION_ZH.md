# 新演员 AV 结果与可支持的结论

**当前 signed/QVI HCSN 可以完成真实音视频 encoder 的端到端参数学习；这轮试验没有证明其质量、检索或训练速度优于 Transformer 和 LIF。** 全9个训练均完成预定256次更新，没有CPU截尾或失败；全9个测试在共同封存后执行。源码、数据和18组 selected/initial 输出通过独立NumPy复核，最大指标误差2.78e−17。

这里的“端到端参数学习”指从已固定的低层音视频特征开始，共同学习frontend、时序核心、projection和分类head；原始媒体decoder与低层特征不是训练出来的。初次backward中，三类模型均无 requires-grad 参数缺少梯度或整张梯度为零。HCSN保留独立人口和signed content完整状态，训练最大概率质量误差8.99e−15，测试最大8.77e−15。

## 质量

每格为3个训练seed的mean ± sample SD；确认集为8位新演员、192 clips。

| 指标 | HCSN | Transformer | LIF |
|---|---:|---:|---:|
| Fused emotion accuracy | 31.424% ± 1.591% | 30.208% ± 2.387% | 32.465% ± 1.084% |
| Fused Brier，较低较好 | 0.76490 ± 0.00514 | 0.75870 ± 0.01993 | 0.77194 ± 0.00744 |
| Audio→video 同记录 R@1 | 0.868% ± 0.301% | 1.042% ± 0.902% | 1.215% ± 1.203% |
| Audio→video 跨actor同情绪 R@1 | 23.958% ± 10.838% | 22.396% ± 0.521% | 20.486% ± 7.298% |
| Audio→video 跨actor同情绪 mAP | 22.670% ± 3.388% | 23.297% ± 0.930% | 20.654% ± 1.244% |

HCSN相对其自身初始模型的fused正确率平均提高14.757个百分点。其相对Transformer的同seed正确率差为[0,0,+3.646]个百分点，平均+1.215；相对LIF为[−0.521,−3.125,+0.521]个百分点，平均−1.042。因此，既不能把单个正向差值写成稳定优越性，也不能把另一指标的负向差值写成该结构必然不能学习。

分类、配对检索和跨actor语义检索分开解释。跨actor检索彻底去掉查询演员的全部候选，以相同acted emotion为相关项；其mAP优劣与同记录R@1不同。这只是低分辨率、短序列、六类表演情绪任务，不验证语言、生成或大规模全模态预训练。

## 时间与容量

| 同口径成本/容量 | HCSN | Transformer | LIF |
|---|---:|---:|---:|
| 256 attempted updates CPU，3seed平均秒 | 452.033 | 2.812 | 7.578 |
| 完整fit launch→exit wall，3seed平均秒 | 484.701 | 7.712 | 13.241 |
| 全分配参数 | 4198 | 4070 | 3142 |
| requires-grad 参数 | 4182 | 4070 | 3142 |
| 扣除声明结构掩码后的活跃参数 | 3894 | 4070 | 3142 |
| Batch16逻辑核心状态bytes | 53248 | 32768 | 2048 |

在这台CPU、这个实现与任务上，HCSN的更新CPU约为Transformer的161倍、LIF的60倍；完整fit wall约为63倍和37倍。前一组不是完整训练时间倍数，后一组含初始化、开发集评估、读写、import与shutdown。尽管所用fast核已经独立验证，它仍未带来相对这两个小baseline的训练速度优势。

相同width不是相同容量。HCSN的projection输入为20维物理接收端特征，另外两个是8维；mask与这些差异均完整计数。逻辑状态bytes也不是总训练内存：HCSN记录概率、标记、phase及五张物理状态；Transformer记录token表示，LIF记录膜电位与spike。全进程峰RSS单列，不能用这三行局部字节直接宣称显存优势。正式试验最大单进程峰RSS为532,598,784 bytes。

## 时长捷径和独立性

源与协议冻结前，审查发现把同一个clip的真实elapsed/dt同时输入两模态，可能让模型凭片长识别配对。因此正式输入改为128维模态特征加所有clip相同的t/31、1/32；真实时间只保留在metadata。旧提案、原cache及修订记录保留，任何模型都未在弃用时长输入方案上训练。

全9封存后的duration-only负控结果为：全192候选同记录R@1 **31.771%**，同actor候选R@1 **78.646%**，只有61种独特时长。这表明在该数据上，共享片长足以造成很强的配对捷径。它不是HCSN或baseline的成绩，也不能当情绪语义理解。

新8位演员位于实际审过的三份历史清单之外；train/dev沿用固定公开缓存。不把这轮结果与旧8演员公开test的不同架构、预算成绩拼成一个改进百分比。3个seed与8个actor是不同统计轴，全部逐actor结果保留；没有把192条记录假设成192个独立演员来制造显著性。

## 费用与证据

全9 attempted-update CPU合计1387.270秒；fit body合计1480.420秒；完整worker到receipt合计1569.770秒。fit与test两个不重叠child阶段分别1510.042、70.140秒，可以合为1580.182秒；它们与前述body/worker口径相互包含，不能再相加。最外层正式run为538.225秒wall、1586.047秒subtree CPU，另含协调器与流程开销。能量未测。

数据获取192/192精确LFS SHA通过、实际68,564,335 bytes、无媒体获取失败。初次固定缓存组装的路径索引错误、独立恢复、隔离SciPy下载、解码、时长设计修订、两轮预检和等待费用全部保留。解码body为128.751秒wall、170.758秒parent+ffmpeg CPU；这是声明的body边界，不伪装成包含所有准备进程import的总CPU。

完整机器结果见[SUMMARY.json](SUMMARY.json)、[独立预测复核](INDEPENDENT_METRICS_VERIFICATION.json)。正式训练档含全部initial/selected/last/optimizer/RNG、预测和退出回执，见[TRAINING_ARCHIVES.json](../TRAINING_ARCHIVES.json)；数据档及精确排除范围见[DATA_ARCHIVES.json](../DATA_ARCHIVES.json)。原外部媒体、已公开base缓存和弃用时长输入的重复数组不重复塞进Git，保留逐文件SHA和原来源；最终采用的三份feature cache完整提供。
