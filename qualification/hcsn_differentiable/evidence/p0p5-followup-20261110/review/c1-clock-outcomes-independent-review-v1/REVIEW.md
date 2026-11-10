# C1 实际结果的第二次独立复算

**限定范围内的复算通过。** 本次读取并逐 hash 核对 105 个已保留小件，重算七条 C1 链的全部 351 个双采样区间、300/900/1800 秒截点、首次达到预声明 0.30 阈值和完整 plateau 历史；另外从 43 份混淆矩阵重算 accuracy 与 11 类 macro-F1，并从六个 core 的全部 36 个候选重新选共同 LR、核对全部候选费用。没有重新加载模型、重复 forward 或读取仍活跃的 HCSN checkpoint。

## 时钟、来源与训练启发式门槛

每条 C1 记录都与原 baseline terminal outer 的 report SHA、原 C1 controller 的 child report SHA 相连。351 个区间全部满足：

`0 <= raw early phase <= original cumulative - complete parent outer <= complete child outer`。

双采样间隔最小约 **1.292µs**、最大约 **11.297µs**，全部为正。适配器保留原始 report 和 cumulative，未改旧 helper 容差；原失败审查因此仍是失败原件，补充审查是另一次执行。七条链的 300/900/1800 秒截点均由原始较晚 cumulative 直接筛选，不插值、不扣除父进程启动或诊断费用。

七条链的累计 epoch 分别为 123、101、160、101、235、139、192；独立递推得到的第一次 plateau 都恰在各自终止 epoch。严格 best 与所有历史 score 一致，旧诊断没有重做。原 36 baseline 中 **26/36** 通过其训练启发式门槛；接上七个被机械选中的 cap 后为 **33/36**。三个诊断失败保持失败：`snn_plif-s101-lr0.001`、`cfc-s211-lr0.001`、`snn_plif-s307-lr0.001`。

这些数字不表示全局收敛或独立科学确认。HCSN 六个 fit 不在这次完成子集内；最终 42-fit 审查尚不能由此替代。终态 Torch RNG/Adam、首次 sample order 和源码等价性可支持所声明的恢复证据，但没有历史 resume-start checkpoint，不能追称直接观察到第一步之前所有恢复状态。

## 同一 D 数据上的共同 LR 选择

每个 core 都保留两种 LR 的三个 seed。按预声明规则重算三 seed 平均 D macro-F1 后，六个 core 都选择 LR=0.003。这里的 D 是同一个开发/选择 subject，不是独立确认集；seed 标准差只描述初始化波动。

| Core | 共同 LR | 三 seed 平均 D macro-F1 | 所选三条链通过启发式门槛 | 全六候选 + C1 的 active process wall |
|---|---:|---:|---:|---:|
| GRU | 0.003 | 0.4249747469 | 3/3 | 784.2627707 s |
| CfC | 0.003 | 0.3490250772 | 3/3 | 1701.8565245 s |
| PLIF | 0.003 | 0.1499786952 | 3/3 | 1308.9980340 s |
| Event-time LIF | 0.003 | 0.3130305208 | 3/3 | 3926.9682609 s |
| S4D | 0.003 | 0.3668656109 | 3/3 | 817.0979199 s |
| Attention | 0.003 | 0.4026165224 | 3/3 | 1461.6004569 s |

上述费用都包含同一 core 的全部六个原进程及其全部 C1 进程，不只计获选 LR。六行合计 **10000.783966976218 秒 active process wall**，其中 C1 七个 child outer 合计 **492.04821365186945 秒**。它们不是并发运行的日历耗时；C1 controller 的约 198 秒 calendar wall 与约 499 秒 waited-child CPU 有不同作用域，不能简单相加。这里也未把更早 PLIF 调参、数值资格、其他失败探针、审查或归档成本混进每行；那些仍需独立全局总账，不能把此表冒称完整历史架构研发成本。

## 保留的限制

原生 reviewer 报告七个 C1 fresh no-grad forward 与所存 logits 的最大差均为零；本次重核的是绑定的小件、混淆矩阵和表，不再次读取或执行大 logits 文件。两个完整 RESULT 原件当时未包含在 small 包中，本次没有把它们称为已读；它们的 SHA 由原 launch receipt 和 summary 连接，后续单独回读可补强。

CORE_TABLE 的“首次达到 0.30”列有一个应披露的小口径差：未续 fit 使用 v8 report 在 epoch row/journal 后另采的 `process_time_to_quality_seconds`；C1 链的 parent crossing 使用其 epoch row 时钟。两者都是真实采样，但整列不能描述为全部从同一个 epoch 字段统一重算。本次严格重算了七条 C1 的原始 epoch 曲线，未重新导出其余原 fit 的原始每 epoch 日志来统一该列。该差异不改变已核对的质量、共同 LR 或 33/36 计数。

原失败 native 审查完整子进程成本为 **22.93758828798309 s wall / 21.723336 s CPU**；新补充审查为 **16.16734547005035 s wall / 15.326924 s CPU**，分别保留。当前纯 JSON 复算另有 **0.07350931499968283 s wall / 0.072479 s child CPU** 的独立回执。三者没有相互替换；SOURCE、stdout/stderr 与 RESULT 均保留，科学资格仍为 HOLD。
