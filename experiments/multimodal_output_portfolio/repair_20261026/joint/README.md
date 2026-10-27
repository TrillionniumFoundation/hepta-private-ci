# 原始 V6 生成器的实际联合训练

## 做了什么

恢复了原 `full002` 实验归档，逐文件验证原 manifest，重新构建完全相同的
MNIST 来源划分。归档 SHA-256 为
`ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e`。
这不是找一个新 toy model 替代旧模型，也不是恢复了缺失的 Oct25/26 四模态资产。

每个原始训练 seed（17、29、43）各建立 frozen、joint_mean、joint_entropic
三个比较臂。后两个臂均从同一个 seed 的原始 checkpoint 出发，共同更新公共
编码器、共享潜状态转移、文字和图像解码器及计划选择器。保留原模型为固定
teacher；训练 reward observer 冻结，独立 audit observer 在全部训练完成后才加载。

两个更新臂使用相同 batch、噪声、4 个两步计划、120 个 optimizer steps、
梯度裁剪与锚定项。frozen 是零更新的基础能力对照，因此只有两个更新臂具有
相同训练计算量；三个臂具有相同推理逻辑预算。推理时只读 Observation，
所有参数固定。实际写入并重开 UTF-8 与 PNG，再由独立 observer 评分。

训练使用可微语义概率与像素代理效用，含 straight-through 8-bit 量化，
文字 greedy 前缀的 argmax 不传梯度。训练的 soft plan 分布与部署 argmax
也有差异。此外，训练平均各输入的条件 CE，评价先跨输入计算每个 seed 的
经验 CE、再平均 seed；二者的风险聚合顺序不同。因此这不是已交付离散
输出上同一全局 NDU 的无偏梯度，更不是通用 FBSDE 求解。实际输出是否改善
只能由后续审计评分回答。

## 冻结结果

运行前协议 hash：
`1a2e292c9ac96cbea2b8c6e6636800d05f214e4b629aa25ed7a36e3cad4da18b`。
这是历史公开 MNIST 来源上的新开发试验，不能当作新 writer 人群确认。
test 与 retention 各 128 个不重复来源对；每个 test 对有 4 个 corruption，
跨训练 seed 与 corruption 的重复均留在同一个 bootstrap cluster 内。
共交付 5,760 份真实图文 bundle、11,520 个文件。

| 比较 | 独立 audit CE 差，γ=2 | 配对 97.5% 区间 |
| --- | ---: | --- |
| test: joint_entropic − frozen | -0.00747140 | [-0.03061854, 0.01488351] |
| test: joint_entropic − joint_mean | -0.00102311 | [-0.00373503, 0.00059576] |
| retention: joint_entropic − frozen | -0.00299901 | [-0.05200262, 0.04045087] |
| retention: joint_entropic − joint_mean | -0.00228541 | [-0.00705716, -0.00000260] |

**预先规定的收益与基础能力保留门槛未通过。**不能宣布有可重复的真实输出
增益；相对 frozen 的 retention 区间也不足以确认不劣于 -0.01 的保留界限。
test 相对 frozen 的逐 seed CE 差是 `+0.002629, -0.029535, +0.004492`，
相对 joint_mean 的三个差都为负。没有在看到结果后更换种子、删掉失败或
选择更有利的评价器。

## 核验

- 所有生成器子模块和计划 gate 的参数哈希均真实变化；冻结 teacher 和 reward
  observer 的参数未变化，6 个更新 checkpoint 均保存重载并验证身份。
- probability/pathwise 代理目标的中心差分最大误差为 `1.23e-10`。
- 新推理执行器与原 ControlledSnapshot 在相同输入、噪声、计划上的 token、
  图像 logits 与选择逐位一致。
- 独立重开并审计全部 5,760 份实际交付，重新绑定来源 ID/隐藏标签，audit
  utility 最大重算误差为 `0.0`。
- 独立方法审查确认了来源对整簇 bootstrap，也指出上述代理与部署差异。
  区间仅条件于这 3 个固定训练 seed，不推断训练 seed 人群。

`RESULT.json`、`INDEPENDENT_AUDIT.json`、`TRAINING.json`、`RUNTIME.json`
及原恢复 receipt 是摘要；完整模型、逐输出文件、原始行与执行源码快照保存在
配套 raw evidence 包。执行后只补了“非空运行目录禁止覆盖”的防护；原运行
源码快照与哈希另行保留，不把这个防护回写成已执行代码。

## 复现

```bash
python -m experiments.multimodal_output_portfolio.repair_20261026.restore ORIGINAL_ARCHIVE RESTORED_ASSETS
python -m experiments.multimodal_output_portfolio.repair_20261026.joint.run --assets RESTORED_ASSETS --output NEW_EMPTY_RUN
python -m experiments.multimodal_output_portfolio.repair_20261026.joint.verify --assets RESTORED_ASSETS --output NEW_EMPTY_RUN
```

这是文字/图像神经生成的联合训练。自然语音/视频神经生成、原生 owner 的
联合训练部署与更大人群确认仍未由本试验完成。
