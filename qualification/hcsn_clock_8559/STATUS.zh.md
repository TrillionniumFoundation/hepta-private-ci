# HCSN 原目标的实证进展

本记录更新于纽约时间 2026 年 11 月 27 日晚。在 20:56 固定的快照中，8,336 个分支头对应 7,943 个不同提交和 7,874 棵根树，递归索引 205,832 个不同文件内容对象。157,283 个源码、文档、配置和结构化结果对象进入全文筛查。相对 19:38 快照新增 242 个文本对象，逐字节读取和哈希校验共 2,656,491 字节，11 个旧对象退出分支头集合。全文对象共 3,312,891,741 字节。全仓范围指所有当时分支头，历史中已经删除的文件、每份权重的语义以及每条 CI 作业不在逐项重跑范围。默认分支仍为 732e934b。

| 原问题 | 直接观察 | 结论边界 |
|---|---|---|
| 能否用内生违约边界建模？ | 原平稳式、有限期限到期债务和两状态扰动已分别实现。两状态数值平滑贴合给出 69.76317/71.33297。在 V=100，以每格 30 万条独立路径核对两项发行价，偏差为 0.56 与 1.41 个蒙特卡洛标准误。局部隐式梯度与独立重求解方向差不超过 2.7e−6。 | 站立参数下有闭式。状态切换扩展给出局部可微的数值解，尚无全局唯一性证明。 |
| 能否忠实表示突触事件？ | 外部 8 个新标本、59,326 个时间点/时距组合，固定、切线、原式、三次边界的 NLL 为 .061144、.060672、.059956、.059857。真实两次噪声输入和不同预测时距参与外部验证。 | 字面金融式点估计胜过固定阈值，数据不能把它与更灵活的风险模型拉开。 |
| 发一个边界，够不够？ | 在指定的有限支持集上构造两份群体分布，B、平均权益和平均首达概率的 FP32 输出相同，但指定冲击后的季度事件概率相差 37.30 个百分点。另有有限字典测试显示查询式端口节约多少带宽取决于是否需要回传查询编号。 | 对任意接收方未来查询，单个 B 或 B 加两个均值均不充分。可以按任务限制历史族或传额外状态。 |
| 图文 encoder 是否依赖边界？ | 从零训练的 RSICD→2,099 张 UCM 图上，HCSN 配对一致率 .6046，匹配平滑/注意力均 .6026，CCA .6404。在冻结权重的端口消融中移除权益通道下降约 .04485，关闭跨层边界线的点差 −.00047，区间跨零。 | 此模型利用权益特征，但证据未把任务效果归因于边界传递。保留残差通道是解释该消融的必要条件。 |
| 是否真能编辑多层隐藏权重？ | 在已训练的三只音频父模型上，前向灵敏度法改写两层共 336 个真实标量。两个独立说话人面板达 84.97%、79.68%，未改父本为 71.63%、66.22%。同位 Adam-BP 为 83.72%、78.43%。同等验收门槛的实测中位总墙钟 LM/BP=1.049。 | 局部编辑能力得到验证；同质量训练时间优势在此次实测中未出现。费用从已取得语音文件开始。 |
| 算子本身是否太慢？ | 24 对真实 SHD 批次、两层48宽，修正版 CPU 训练算子相对原 eager 实现的成对中位速度比 2.65。精确接触处单步前壁梯度最大差从 2.4256 降至 5.73e−6。 | 该倍数是同一个 HCSN 的实现比较。相对其他架构的同质量完整耗时需等独立训练与冷测。 |
| 是否已从零训练全模态基础模型？ | 新增 SHD 原时钟语音、双来源图文、更大规模编辑及原始三模态 MELD 实验有独立方案，1B 工作已找到短片阻塞；共享设备与训练预算独立计量。 | 真实图文或音视频文本 encoder、十亿参数分配、一次梯度更新、完整预训练和可迁移基础模型属于不同证据层次。 |

## 固定研究证据

- [两种自由边界求解、蒙特卡洛和普通反传](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/811b7242ecd34c1c2a6ca48ee5f0b39b525e5b6b/qualification/hcsn_clock_8559/switching/RESULTS.md)
- [有限带宽端口的实际编码账](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/75a3c42d2cfcfdca7ec07e1620681abcd00ca110/qualification/hcsn_query_intervention_20261127)
- [外部神经生理和相同双价格输出的尖锐反例](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/bdde9361bd1daf8e0693dd9b7a929c53c590f67b/qualification/hcsn_query_intervention_20261127)
- [图文外部冷测及配对区间](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/caff3c40a6c97623ee1ebe9408d70b99734e1bb2/qualification/hcsn_cross_corpus_8559/RESULTS.md)
- [两层语音写入的实际拟合证据](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/9db378b9a7d1f6d317eca0ddc2afa2d6abed9aba/qualification/hcsn_finite_multilayer_edit_20261128)
- [SHD 高速算子的源代码、梯度和实测耗时](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2b7db73a68f25c6ef9255e7cb06e47ac55de9d7d/qualification/hcsn_clock_8559/fused/RESULTS.md)
- [全部 21 个 CPU 首档权重与原始回执](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/dafdaac79117872feff10ef519f232a2aee00698/qualification/hcsn_shd_cpu_8559/runs)

## 已开启的第一档语音冷测

原始 2,264 段录音，三种子，单核 CPU 30 秒/模型。按说话人等权，原式 9.73%，同宽平滑 8.26%，固定壁 4.93%，关闭直接价格反馈 11.39%，LIF 46.20%，Transformer 86.48%，CNN 89.68%。两位全新说话人上的平均值依次为 9.50%、8.12%、4.73%、11.26%、44.55%、78.56%、81.25%。相对平滑模型的差为 +1.47 点，边际 95% 区间 [−0.06,+2.96] 点，三个预定门均未通过。三种子同时达到 60% 开发准确率的是 CNN 与 Transformer，达到 70% 的只有 CNN，80% 尚无人共同达到。独立优化实现 V1 的三个种子冷测为 28.48%、27.33%、27.97%，同一组已训权重在两套推理引擎上自然输入的标签全一致。[原始 21 模型](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/996ebaee42951428c55de61b4c9e8bc9ada0d654/qualification/hcsn_shd_cpu_8559/cold-30) · [快速实现](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/68510b44a9390f8ba1646c3c3707eaacec91056a/qualification/hcsn_shd_cpu_8559)
