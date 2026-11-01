# HCSN R14：判别性验证与可恢复证据

本目录交付同信息、真实动作后续、完整后端冻结／共同训练和完整模型成本的实际实验。**已登记实验执行完成；新的通用基础核心准入仍未建立。** 数值正确性、动作期望、内容学习和硬件费用分别验收，来源不同的模型不合并计分。

## 结果入口

| 内容 | 可直接审阅的入口 |
|---|---|
| 总结、全部主要四格、限定与判定 | [REPORT_ZH.md](REPORT_ZH.md) |
| 机器可读判定和冻结身份 | [ACCEPTANCE.json](ACCEPTANCE.json) |
| 零延迟完整状态、连续参照、梯度与负对照 | [numerics/RESULTS_ZH.md](numerics/RESULTS_ZH.md) |
| 所有到访前缀的实际 Qπ | [value/RESULTS_ZH.md](value/RESULTS_ZH.md) |
| 六臂实际轨迹、完整 27 时钟和修复成本 | [value/rollout_repair/RESULTS_ZH.md](value/rollout_repair/RESULTS_ZH.md) |
| 完整后端冻结、共同训练、全部数据域 | [content/RESULTS_ZH.md](content/RESULTS_ZH.md) |
| 60 个均值、180 个逐 fit 对比、240 个八族域聚合 | [content/results/formal_01/RESULTS_COMPACT.json](content/results/formal_01/RESULTS_COMPACT.json) |
| 八族全域 CPU、质量与成本 | [cost/results/formal_02/FINAL_REPORT_ZH.md](cost/results/formal_02/FINAL_REPORT_ZH.md) |
| 完整恢复与新尝试运行 | [REPRODUCE.md](REPRODUCE.md) |

## 主要结果

有限动作任务的全 27 时钟期望 D−B 为 IID **+0.000353418**、OOD **+0.002418906**；对应第二批实际采样为 **+0.003803752**、**−0.011125133**，两个描述区间均跨零。新控制修复没有建立收益—成本改善，RESET 收益仍未激发。旧负向轨迹已零误差复现。[动作结果](value/rollout_repair/RESULTS_ZH.md)

内容共同训练的 IID D−B 对匹配普通双头为 recall **−0.009060**、binding **−0.004117**；对验证集选出的普通族为 **−0.059319**、**+0.004552**。保持与长度等部分压力域有正结果；全部方向和三种子范围均保留。该内容实现仍为固定 renewal 门，尚未接入数值线的完整条件分布。[内容结果](content/RESULTS_ZH.md)

历史内容模型的完整 warm 前向，解析／普通 CPU 中位比为 batch 1 **2.704553×**、batch 32 **6.433376×**，180/180 匹配条件均更贵。新动态 actor 成本另测，不能套用历史固定前向数字。物理焦耳未测，保持 null。[成本结果](cost/results/formal_02/FINAL_REPORT_ZH.md)

## 证据与来源

基线为 `9c97642cea5478cd9e7d078a192399bef9c9efc8`（PR #4544）；独立动作引用为 `b0802dc314251f5332bd026cb2984a0b5c75f768`（PR #4542）。内容沿用基线中的 R12 模型，另开新的数据种子与完整冻结实验。见 [SOURCE_BASELINE.json](SOURCE_BASELINE.json)。

大体积原始证据以可逆、逐成员哈希校验的归档保留。每个上传分片都是完整 gzip 容器；单文件小于仓库限制。原始文件没有截断或改写来迁就上传大小。

- [cost 发布清单](cost/archives/PUBLICATION_MANIFEST.json)：继承输入包 1,446 个成员；成本结果包 2,994 个成员。
- [value 发布清单](value/PUBLISH_FILES.json)：665 个原始成员，80 个完整 gzip 容器。
- [content 发布清单](content/PUBLISH_FILES.json)：991 个原始成员，56 个完整 gzip 容器。

每套归档均已在新目录实际恢复。独立内容审计通过 24,479 项检查，修复动作审计通过 162,036 项检查；这些数量是检查项，不能当作独立拟合次数。

工作仅增加 R14 研究目录；没有修改继承实验的原始证据或生产网络。Rust 路径、GPU 和物理能耗不是本轮已执行范围。
