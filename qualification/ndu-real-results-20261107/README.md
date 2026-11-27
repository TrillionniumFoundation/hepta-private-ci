# NDU 真实 pipeline 与既有分析：独立只读审查

## 结论

**执行已经完成，当前科学结论仍是 `Inconclusive / HOLD`。** 原 pilot owner 与分析 watcher 的原生回执均为 `succeeded`、`exit_code=0`，输出完整且持久化已确认。真实训练材料存在：既有绑定记录了 8 个 content jobs、144 个 fit jobs，152 个 grid receipts；每个 core 有 4 个不同初始化，分析使用 4 个独立训练重复。不能将这些网格任务、搜索 episode 或 source-group 配对数当作更多独立训练重复。

本审查没有新增训练、访问 heldout 答案、重新评分原始任务行、重新运行原分析或 bootstrap，也没有改变阈值或重新选择 strongest 对照。读取的原始分析与 followup 逐字节哈希匹配；92 项身份、计数和算术一致性检查全部通过。这里的“通过”只指本次审查，**不改变原来的 `HOLD`**。

分析保留 `native_owner_authentication=SEPARATE_REQUIRED`；followup 保留 `formal_final_use=BLOCKED`、`adoption_authorized=false`、`confirmation_access=false`。原生进程成功结束，不能直接补足研究准入、最终使用或部署授权所要求的其他证据。

## frozen 与 joint 的 2×2 因果对照

沿既有协议，A 为 Ordinary + Light，B 为 Ordinary + NDU，C 为 Hepta + Light，D 为 Hepta + NDU。以下数值是原分析的 `net` 差值及描述性 bootstrap 区间，原先规定的最小有用差异为 **0.05**。

| 对照 | frozen 估计 | frozen 描述性区间 | joint 估计 | joint 描述性区间 |
|---|---:|---|---:|---|
| B − A：Ordinary 上 NDU 的增量 | 0.020429 | [0.002585, 0.043278] | 0.023278 | [−0.035832, 0.084135] |
| D − C：Hepta 上 NDU 的增量 | 0.030098 | [0.001013, 0.079020] | 0.028837 | [−0.037159, 0.102174] |
| D − B：同一 NDU 下 Hepta 的增量 | 0.017449 | [−0.027278, 0.068036] | 0.002921 | [−0.052900, 0.081644] |
| (D − C) − (B − A)：额外交互 | 0.009669 | [−0.025839, 0.056372] | 0.005559 | [−0.063072, 0.093002] |

这些对照已真正分别执行和报告；本次审查也逐个训练重复、逐个 source group 验证了交互恒等式。最大绝对残差为 `5.5511e-17`。两种训练方式下的交互区间均包含零；所有净差值的点估计及区间下界均未超过 0.05，当前不能宣布达到预先规定的有用收益。

frozen 的 B − A、D − C 区间下界为正，是值得保留的探索性信号；这不足以证明达到最小有用差异。原分析对全部结果仍判定 `Inconclusive`，本审查维持这一结论。

## 相对既有 selection lock 中 strongest 对照

| 对照 | frozen 估计与描述性区间 | joint 估计与描述性区间 |
|---|---|---|
| B − strongest | −0.006933 [−0.053076, 0.036183] | 0.002916 [−0.039997, 0.053011] |
| D − strongest | 0.010515 [−0.022454, 0.045541] | 0.005837 [−0.034479, 0.056772] |

这里沿用被冻结且已绑定的 selection lock；没有利用当前结果重新挑选对照。所有区间都包含零，也没有达到 0.05。`strongest` 仅指该注册研究选择过程中的对照，不据此宣称覆盖全部可部署模型。

同一 strongest 参照下，`(D − strongest) − (B − strongest) = D − B` 的逐格检查也通过，最大绝对残差为 `6.9389e-17`。

## joint 相对 frozen

| 模型 | joint − frozen 估计 | 描述性区间 |
|---|---:|---|
| A | 0.012423 | [−0.048216, 0.068804] |
| B | 0.015272 | [−0.047764, 0.084369] |
| C | 0.002006 | [−0.037335, 0.039455] |
| D | 0.000744 | [−0.076081, 0.082304] |

当前没有足以宣布 joint training 带来最小有用净增益的证据。

## 八项旧能力保持对照

原分析使用 `gross` 差值，保持判据对应的下界为 **−0.02**。表中保留分析原始名称，避免混淆两个参照。

| 原分析对照名 | 估计 | 描述性区间 | 区间下界超过 −0.02 |
|---|---:|---|---|
| retention:A | −0.0250 | [−0.1625, 0.1125] | 否 |
| retention:B | −0.0375 | [−0.2500, 0.1875] | 否 |
| retention:C | −0.0500 | [−0.2375, 0.1125] | 否 |
| retention:D | 0.0500 | [−0.1125, 0.2875] | 否 |
| incumbent-retention:A | −0.0250 | [−0.1625, 0.1125] | 否 |
| incumbent-retention:B | −0.0375 | [−0.2500, 0.1875] | 否 |
| incumbent-retention:C | −0.0500 | [−0.2375, 0.1125] | 否 |
| incumbent-retention:D | 0.0375 | [−0.1125, 0.2875] | 否 |

八项区间均不能排除超过容许幅度的旧能力退化。D 的点估计为正，仍不能据此宣布旧能力保持通过；A、B、C 的负点估计也不等同于已经精确确定退化幅度。

## 统计单位与解释范围

24 项对照全部完整，各有 **4 个独立训练 fit × 20 个 source groups = 80 个配对单元**。这是交叉配对设计；80 个单元不是 80 次独立训练。既有训练绑定给出的训练 seeds 为 `104729`、`130363`、`155921`、`196613`。同 seed 下 Ordinary 与 Hepta 共享配对初始化标识，不应把两侧再合计成 8 个独立重复。

24 项包括：8 项 frozen/joint 2×2 因果差值、4 项 strongest 对照、4 项 joint − frozen，以及 8 项 retention。机器表完整保存全部对照，没有移除不利结果。

原分析使用 20,000 次 bootstrap，独立重采样 fit 和 source 的多项式权重，比较家族大小 24，名义 alpha 0.05。每侧尾部概率为 `0.05/(2×24)`，每个尾部预期约 20.83 次抽样。原报告明确称其为描述性 percentile 区间：只有 4 个训练 fit 时，没有有限样本覆盖保证。本审查没有把这些区间改称确认性结论。

部分方差分量估计为负，原报告同时保留原值及非负化值；不能将被截为零的点估计理解为不存在训练差异。所有功效规划的 `admissible_power_plan` 仍为 `false`，不能直接据此开放确认性实验或最终使用。

任务家族的探索性均值显示，NDU 的较大正差值集中于 `preparation_required`：B − A / D − C 在 frozen 下为 0.091675 / 0.123612，在 joint 下为 0.118237 / 0.134693。这些是原分析的分家族描述值，没有独立替代总体 MUD、保持或成本门槛。

## BudgetStop、失败与覆盖

| 记录范围 | 总数 | Completed | BudgetStop |
|---|---:|---:|---:|
| primary roster | 11,520 | 10,200 | 1,320 |
| incumbent retention roster | 160 | 160 | 0 |
| 合计 | 11,680 | 10,360 | 1,320 |

原分析中的全部 11,680 条计划记录均已观察，部署时长均有测量；未知部署时长、outer-wall fallback 和 failure-penalty 行各为 0。**1,320 条 BudgetStop 被完整保留，不是 1,320 条 Completed。** 报告中的 `noncompleted_rows=[]` 也不能被误读为 BudgetStop 为零。

以上覆盖是这些被绑定研究记录的覆盖，不推断其他准备、历史失败或本研究范围外的成本不存在。分析后续没有重新启动训练或 episode。

## 成本及未闭合条件

| 已记录时间 | 秒 | 范围 |
|---|---:|---|
| 11,680 条记录的部署 episode 时长之和 | 28,973.767553 | 各 episode 的时长相加，含并行执行重叠 |
| pipeline wall | 8,353.254944 | 原 pipeline 回执的端到端时间 |
| watcher wall | 4,238.672347 | 包含等待和其分析子进程 |
| 既有分析子进程 wall | 1.116040 | watcher 时间的内含部分 |

这些范围有嵌套或并行关系，不能直接相加成“总耗时”。原研究的训练、搜索、评估及预算停止记录继续保留在原 owner 的账本中；当前分析报告本身不是全生命周期成本闭合证书。

物理电能和 provider charges 均保持 `null`。没有以 TDP、理论运算能耗或时长乘功率替代实际测量。现有聚合报告也不足以单独给出完整的延迟分位数、吞吐、全过程峰值显存，以及 encoder/decoder、状态存储、准备、搜索和失败的完整成本边界。

因此，扩大或升格所需的“相对最强注册对照超过 MUD、旧能力保持、完整成本边界、独立确认与最终 owner 审核”尚未同时成立。

## 协议与证据身份

原图文协议：[PROTOCOL.md at 006e744fbb10a6ee393166eed2e5d1e91f2fab1f](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/006e744fbb10a6ee393166eed2e5d1e91f2fab1f/qualification/ndu-text-image-20261106/PROTOCOL.md)。本目录公开已完成 pilot 的科学聚合结果与独立复核，不包含原任务答案、权重、个人设备路径或凭据。

- [完整 24 项对照](all-24-contrasts.json)
- [独立审查](independent-review.json)
- [任务家族分层](TASK_CLASS_COVERAGE.md)
- [任务家族机器表](task-class-coverage.json)
- [原分析和冻结输入的哈希身份](PROVENANCE.json)

本次独立审查只核对既有聚合值、原生终态及身份和算术一致性，没有重新运行训练、评估、bootstrap 或原分析。152 项训练网格材料与 65 个 checkpoint 的验证结论沿用被绑定的既有 followup，未冒充本审查重复读取全部权重与训练记录。

这些结果属于独立 NDU pilot，不给原 170-run 或 HCSN/S81 机制研究增加完成或成功信用。
