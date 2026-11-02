# 风险单因素执行补充

本轮只验证一个可分离的服务风险输入：v8 `ServiceEstimate.deadline_miss_probability`。完整风险与置零风险两臂的共同内容头、未来正确率（已经包含 timeout 后保留旧内容的回退）、预计请求数和预计时间完全相同。实际传感载荷及快慢服务结果按世界固定，控制器只能读已接受的内容和公开服务分布。

这是已知二元对称传感器和独立快慢进程服务的受控合成任务。它没有拟合或恢复强 AV 头，没有新录制，也不检验金融 Put 通道或解析动力学的必要性。

`results/development001/PLAN.json` 在执行前冻结了源码、16 个完整因子世界及其公开分布权重、8 个实际执行世界、费用和四臂。实际子集是预先指定的平衡半分数设计，报告描述均值，不生成随机样本置信区间。每个世界按预先声明的 Latin 旋转次序执行四臂；子集并非按真实传感器错误率抽取，不能把其未加权均值当总体期望。

| 结果 | 完整逻辑分布（16 世界 × 4 臂） | 真实单调时钟（8 世界 × 4 臂） |
| --- | ---: | ---: |
| full − zero 净效用 | +0.398225 | +0.5232223184 |
| 固定动作后的内容概率 | 全部精确一致 | 全部精确一致 |
| timeout 运行（含固定动作臂） | 16 | 8 |
| 迟到 video 被纳入输出 | 0 | 0 |

所有世界中，完整风险选择在共同首音频后停止，置零风险选择追加 video。`full_on_zero` 与 `zero_on_full` 固定另一臂的动作，内容概率全部相同。因此改变的是选择动作，未证明风险改变内容表示或有不可替代的内容收益。真实运行先把最终 JSON 写入文件并 `flush`、`fsync`，再排空并丢弃迟到子进程；请求费用包含超时请求。原始 receipt、实际输出、动作、时间和子进程 CPU 全部保留在 `runs.jsonl`。

**正效用结论强烈依赖本轮输出截止合同。** v8 在硬 deadline 处停止等待，然后才 flush；因此 timeout 的实际输出略晚于 deadline，触发罚项 1。完整风险的优势主要来自避免该罚项。不能据此宣称普遍的风险机制净优势。

独立的 `SENSITIVITY.json` 保留同一批实际动作，只改变评分中的每次输出超时罚项。罚项置零时，完整逻辑分布的 full − zero 变为 **−0.101775**；实际 8 世界子集为 **+0.0232223184**，后者来源于这组描述性内容结果和少发请求费用，不能代表总体期望。此敏感性是事后评分重算，不是策略重新优化；尚未运行预留 flush 时间的新执行协议。

实际正式执行只有一次，由 `../economics/family_cost.py` 包裹，收据位于 `../economics/results/risk_execute001/`。正式 study 壁钟约 52.756 秒；外层 task CPU 4.269031 秒，包含实际 worker。内层 CPU 统计只是诊断，不能再叠加到外层成本。初期准备、四项行为测试及一次逻辑预查不在该正式执行包络内；设备能量和历史准备成本依然没有完整账。

复现使用新的输出目录，避免覆盖冻结记录：

```bash
python -m unittest experiments.hcsn_v9_followup_20261101.risk.test_study -v
python -m experiments.hcsn_v9_followup_20261101.risk.study prepare --output /tmp/risk-new
python -m experiments.hcsn_v9_followup_20261101.risk.study execute --output /tmp/risk-new
python -m experiments.hcsn_v9_followup_20261101.risk.validate_results /tmp/risk-new
python -m experiments.hcsn_v9_followup_20261101.risk.sensitivity /tmp/risk-new
```

四项行为测试检查独立风险干预、未来载荷隔离、固定动作内容不变和输出冻结后 drain。标准库 JSON 复算通过 1,067 项检查、96 次运行。该复算是仓内可重复校验，不冒称独立审稿。
