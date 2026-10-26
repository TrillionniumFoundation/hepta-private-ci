# 联合四模态正式运行：独立完成审计

复核者：`control_next`。**独立核验通过，原两项质量门均未通过。** 本次完整保留 entropic 训练 arm 相对 mean arm 的负结果，没有更换模型、来源、观察器、阈值、bootstrap 方法或输出文件。

审计脚本在读取任何本次中途质量结果前完成，身份记录见 [PREPARATION.json](PREPARATION.json)。收到完整 child `exit 0` 和主分析完成的通知后，使用同一个脚本执行，见 [EXECUTION_RECEIPT.json](EXECUTION_RECEIPT.json)、[AUDIT.json](AUDIT.json) 和 [独立审计源码](audit_completed.py)。没有重新运行模型、ASR、codec 或主分析函数。

## 原质量结论独立复现

以下均为固定三个训练 seed 面板上的 pooled 结果；差值方向是 entropic − mean。区间使用原登记的 24 个 connected writer/speaker cluster、4,000 次配对 resample、95% percentile interval。

| 主指标 | mean arm | entropic arm | 差值 | 95% cluster interval | 原门 |
| --- | ---: | ---: | ---: | --- | --- |
| Entropic CE，γ=2 | 0.6798279014 | 0.6729749353 | −0.0068529661 | [−0.0147229818, −0.0011904477] | superiority FAIL：下界须大于 0 |
| 四模态 strict joint success | 80.72917% | 79.42708% | −1.30208 个百分点 | [−3.33333, +0.50505] 个百分点 | noninferiority FAIL：下界须至少为 0 |

CE 差值的原区间整体低于零；这套训练、数据和 greedy 物理输出执行配置没有产生所需的风险效用收益。严格 joint 的区间也不支持原登记的零容差非劣门。`quality_claim_eligible` 保持为 `false`。

| 描述性指标 | mean arm | entropic arm |
| --- | ---: | ---: |
| 四模态平均 utility | 0.8470052083 | 0.8411458333 |
| Image success | 84.37500% | 84.37500% |
| Text success | 86.19792% | 85.15625% |
| Audio success | 87.50000% | 87.23958% |
| Video success | 80.72917% | 79.68750% |

这些分量和逐 route/seed 数据保持描述性地位，没有从中另挑一个成功端点替代注册主比较。该负结果也不直接识别失败原因：训练使用采样输出和 pre-codec proxy，正式执行使用 greedy 输出、物理 codec 与另立观察器；不能仅据此次比较把差异归因到某一个未经单独消融的机制。

## 样本和训练身份

逐项验证了原 protocol 的全部 **181 个 pins**，以及实际 process argv、完成记录和主分析的 SHA 链。六个 checkpoint 恰好为 `17/29/43 × mean/entropic`，实际文件路径和 SHA 均与训练记录、正式协议一致；每个 seed 内两 arm 的初始参数身份和外生 schedule 相同。原训练源码 pins 同样全部匹配。

完整 census 为 **128 source pairs、256 unique digit IDs、32 个 image writers、24 个 speech speakers、768 个 seed/profile/case 输出**。审计直接读取并校验官方 QMNIST metadata 和像素字节，逐个验证 source ID、NIST digit、writer、pixel SHA；目标左右顺序以纯 Python 的 MT19937 初始 draws 独立重建，不调用 Torch 或原数据 loader。240 个实际公共 speech source 文件也逐一核验身份。

根据真实 writer 与 speaker ID 独立建立连通图，确认 16 个 cluster 各含一个 writer、8 个各含两个 writer，总共 24 个 cluster。所有 768 行的 route、writer assignment 和 cluster ID 均匹配。三个 seed、重复 route 和同 cluster 中的两个 writer，没有被当成额外独立 cluster。

## 实际文件与目标隔离

审计校验 768 条完整 `observation.json` 与 completion 中缩减记录逐字段相等，并重新计算 **3,072 个唯一实际输出文件**的 SHA 和字节数。与媒体 bridge 的输入/输出混合文件计数不同，这里 3,072 个文件均为 768 个联合生成 bundle 的四个输出模态。

对每条输出，独立读取实际 caption 和 WAV PCM，核验 PNG header、音频 sample clock、两个事件的 PCM SHA、原 ASR segment 到 transcript 的拼接、固定 parser 和 V3 ensemble 规则。四模态 success、严格 joint 和平均 utility 从这些实际输出对应的 target-free observation 字段重新计算，之后才使用按官方来源重建的标签评分。768 条全部一致。事件计数为 **60 次真实事件观察、1,476 次字节身份缓存命中，总共 1,536 个事件请求**；缓存命中未被当成额外 ASR 推理。

本次遵守不重跑模型和 codec 的限制。Image/video 神经分类、视频解码帧和原物理 presentation clock，仍采用冻结执行时已保存的观察和 lossless readback 记录，再以实际文件身份绑定；本审计没有把这一层描述为独立重新分类或重新解码的结果。先前源码复核确认 `observe_bundle` 接收实际媒体路径和观察器，目标只在随后评分调用中出现。

## 独立数学复算

审计没有 import 或调用主分析的 `metrics`、`paired_interval`。它从各 cluster 的整数 utility histogram、strict-joint count 和四个模态 count 建立充分统计量，使用 `math.fsum/exp/log` 计算均值与 CE，并独立实现线性分位数。仅复用原登记 seed 的 NumPy 随机 draws，以便逐次比较同一组 cluster resamples。

每个抽中的 cluster 都保留其全部 source、arm 与 seed，并保留一 writer/two writers 的不等大小。所有主统计点估计和 CI 与原报告的最大数值差为 **1.1102230246251565×10⁻¹⁶**；逐 route/seed 指标及描述性时间分位数也一致。原 superiority 与 strict-joint noninferiority gate 逐项独立重现为 FAIL。

## 保持的推断边界

这是构造数字任务、有限 voice decoder 和运动变换视频上的固定训练面板结果；它不授予开放域音视频或 foundation-model 能力。六 arm 均已继续训练，缺少保持原生成器不训练的 arm，因此本比较区分两种继续训练目标，不能单独估计“继续训练本身”的收益。固定 arm 顺序和实际缓存使成本差异保持描述性；ASR point qualification 也不证明所有输出分布或未知预训练语料的独立性。

| 关键身份 | SHA256 |
| --- | --- |
| 正式 protocol | `6a305d92578da4d6e41ebc104101b7af58ebc02306ea6c54d9e73ae724222f08` |
| 预先准备且实际执行的独立审计脚本 | `f43937c74a06a45adaefa8696f06397d1cdee0e11d20134e2b353800d40087b3` |
| 独立 AUDIT | `ddbd240ee34d2c4bb34e92ffe0655a8697966601635629e041d71ea607584235` |
