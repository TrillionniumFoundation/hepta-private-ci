# Hepta E2：真实冻结 mmBERT-small Feature 的五档 Head 容量实验

**执行来源**：GitHub Actions 实际预训练作业 `38518482426`（PR #1808），读取实际公有 AG News 128 行与冻结 128×384 float32 Feature Snapshot。该作业原始模型权重未包含在本实验的成果包中。新增研究代码提交至 [PR #1848](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1848)，精确提交 `3264d26f7eb177e11e479b87c928ef59196b6d59`。

## 实验方法

使用相同已封存特征，不执行任何额外 Encoder forward。训练划分 64 条，校准 32 条，Holdout 32 条。两逻辑 Cell 独立训练；每 Cell 20 次 AdamW 更新，批次 16，固定学习率 0.01；预先固定种子 11/23/47，训练抽样索引流在所有种子和预算间相同。

容量上限为 2,048 / 8,192 / 16,384 / 65,536 / 262,144 参数。Head 是独立的双层、tanh、因子分解读出结构（并非原 Gated Head）。公式为 `p = rank*(width + classes + 1) + classes`，`width=384`、`classes=4`。本研究在看到 Holdout 标签前训练并封存全部预测。测试分数由不导入训练器的 NumPy 复核器随后计算。

## 实测结果

| 预算上限 | 实际每 Cell 参数 | Seed 11 正确 /32 | Seed 23 正确 /32 | Seed 47 正确 /32 | 三种子平均准确率 | 三种子平均 Brier |
|---|---:|---:|---:|---:|---:|---:|
| 2K | 1,949 | 17 | 10 | 9 | 37.50% | 0.70905 |
| 8K | 8,173 | 18 | 19 | 12 | 51.04% | 0.64167 |
| 16K | 16,342 | 17 | 15 | 17 | 51.04% | 0.63473 |
| 64K | 65,356 | 19 | 20 | 20 | 61.46% | 0.53060 |
| 262K | 261,801 | 12 | 14 | 21 | 48.96% | 0.63301 |

原生产者中**已训练的 Linear Head** 在这些同一 32 条 Holdout 上是 18/32（56.25%）；这不是生产 no-change，也不是同预算/同随机种子的对照。不能把它直接用于因果增益判决。

60 个物理 checkpoint（30 次训练 × trained/frozen）逐一读取 safetensors，独立重算校准和 Holdout 共 1,920 组概率向量，最大概率绝对误差 **4.76837158203125e-07**，没有预测类别翻转。全部 checkpoint 的 SHA-256、实际参数数目、训练步数、输入行序和 Cell/Scope 身份均经验证。新增 8 个本地机制测试以及 5 个真实封存工件篡改测试通过。

## 解释与限制

在本固定训练预算和极少量训练样本下，64K 的均值高于 262K，显示增加参数并非自动提高学习质量；更大模型可能需要不同学习率、训练步数、正则化与独立调参集，但不能用本轮 Holdout 事后调参来证明其优越性。

三个种子共享同样 32 条 Holdout，并不是 96 个独立应用样本；source group 目前是公有原始记录 ID，没有独立作者/事件族认证。因此无法由这些数字建立统计意义上的“64K 最优”。此实验也**不是**全部 E2 的六种 Head 架构公平对照，尚无真实未来窗口、生产 no-change、Laya 教师、外部签名 NDU、OOD/负迁移长期保持、原生 Worker Q24/4,096 Cell 以及能耗验收。

研究回执均为 `production_accepted=false`、`e2_full_selection_qualified=false`、`future_ndu_evaluated=false`，不修改任何生产模型、路由、注册表或授权。

## 重现

在拥有原始真实公有 `manifest.json`、原始 dataset、`execution/report.json`、`execution/predictions.json`、`execution/frozen-features/`、16 个已保存原始 Head 文件的机器上，执行：

```bash
REPORT_SHA=$(sha256sum /real-study/execution/report.json | cut -d' ' -f1)
python -m experiments.shared_stem_cell.e2_budget_sweep \
  --manifest /real-study/manifest.json --producer /real-study/execution \
  --report-sha256 "$REPORT_SHA" --output /new/e2-budget
python -m experiments.shared_stem_cell.e2_budget_review \
  --manifest /real-study/manifest.json --producer /real-study/execution \
  --report-sha256 "$REPORT_SHA" --sweep /new/e2-budget \
  --output /new/review.json
python -m experiments.shared_stem_cell.e2_budget_integrity \
  --manifest /real-study/manifest.json --producer /real-study/execution \
  --report-sha256 "$REPORT_SHA" --sweep /new/e2-budget \
  --output /new/integrity.json
```

`e2_budget_sweep.py` 运行时需要 torch/numpy/safetensors，独立审核器仅需要 numpy/safetensors。缺少真实模型工件时应直接拒绝，不能自动转为合成模型。
