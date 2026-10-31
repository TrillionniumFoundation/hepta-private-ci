# 已训练解析边界对真实内容执行的干预诊断

**冻结训练模型的解析边界参数确实能改变原生 owner 的内容执行。** 在 5 个训练 fit、每 fit 16 个原始 VAL session 上，240 次独立 native process 均成功完成；两个预声明干预合并后，**19/80 个不同 session 改变了动作轨迹，11/80 个不同 session 改变了 READ 的任务时序，8/80 个不同 session 改变了 READ 次数**。这些是按 `(seed, session)` 去重的 session 数，不是把两个干预的比较行混称为独立样本。完整结果与案例键见 [SUMMARY.json](SUMMARY.json)。

## 实验边界与冻结规则

本实验是 **DEV exploratory / secondary 机制诊断**，使用原训练阶段的 VAL 数据，不属于 IID/OOD confirmation。没有更新、重新选择或替换任何 primary 模型，也没有搜索额外敏感数据或调节 critic。

每个 fit 使用此前已冻结的 `analytic_value` 模型，分别运行原参数、`theta[3] = -3`、`theta[3] = +3`。只改变这一项 raw boundary 参数；critic 的全部权重、归一化、其余 10 个参数、公开数据、FullHX content model 和 seed 均保持一致。对应有限 CTMC 的物理边界为 `0.8 + 0.4*sigmoid(theta[3])`，两个干预值约为 0.81897035 和 1.18102965。模型和运行计划在首次 native 调用之前写入 [PLAN.json](PLAN.json)。

每条轨迹使用 fresh owner 和新 artifact hash，没有给现存 checkpoint 更换模型身份。主机不提供动作、后验、观察或 packet 选择。VAL archive 只提取原 public/packet 文件；public 只补充已经确定的 multiplier、latency price 和 packet SHA256。标签仍留在原 archive 中，直到同一 session 的三条 native 轨迹全部终止后才被解析评分。

## 全部案例的结果

| 相对原模型的干预 | 比较 session | latent 改变 | 动作轨迹改变 | READ 次数改变 | READ 任务时序改变 | 平均效用差 |
|---|---:|---:|---:|---:|---:|---:|
| `theta[3] = -3` | 80 | 80 | 11 | 5 | 6 | -0.05159375 |
| `theta[3] = +3` | 80 | 80 | 8 | 3 | 5 | -0.00273750 |

原模型合计完成 122 次真实内容调用，低边界干预完成 121 次，高边界干预完成 123 次。分别有 69/80、72/80 个 session 只改变 latent 特征而保持整条动作轨迹相同，因此 latent 敏感性并不等于每个案例都会改变内容调用。

比较器在每条轨迹的首次动作分歧之前，逐步要求完整任务状态与 62 个公开特征完全相同，然后记录 cell5、预测窗口内 expected latent event count、四个 Q 值及动作。窗口 expected count 由实际 native `cell_features[2] = count/(1+count)` 还原。两方向的最大相同前缀 expected-count 差分别为 0.08679430 和 0.07704473。首次动作分歧之后的结果只用于描述后续真实执行及效用，不再当作相同状态下的局部比较。

## 一个按既定案例顺序首先出现的 READ 分歧

在 `seed71031 / validation_seed71031_0000` 的低边界干预中，第 7 个决策之前，两条轨迹均处于 job 0、tick 6、budget 2、posterior 0.5、任务时间 6 秒。

| 指标 | 原训练模型 | `theta[3] = -3` |
|---|---:|---:|
| 窗口 expected latent count | 0.30028658 | 0.33888847 |
| `Q(SKIP)` | 0.21573299 | 0.20797470 |
| `Q(READ)` | 0.22104105 | 0.20101861 |
| 原生选择 | READ | SKIP |

原模型在任务时间 6 秒读取一次；干预模型随后在 7 秒和 8 秒各读取一次，最终效用相对原模型下降 0.2685。这个案例说明训练后的 cell 特征已进入实际动作选择和 FullHX 执行路径；它同时说明 latent 事件数和外部 READ 动作之间要经过 critic，不存在“latent 事件更多就立即读取更多”的直接等价关系。该案例没有按效用改善筛选，所有 80 个 session 和两个方向的比较都被保留。

## 成本、证据和解释范围

240 次 native process 的完整 child CPU 为 **2.648436 秒**。执行 campaign 的 parent CPU 为 **4.451229 秒**，wall time 为 **8.986355 秒**；另有 **0.147333 秒 parent CPU** 用于交付时的无损 gzip 封装和去重描述统计。后者单独列出，不与原逐次成本重复相加。没有测量能耗。

原始 stdout、stderr、process 参数、CPU、native receipts、acknowledged checkpoint 和输入文件按 seed 分片 gzip，全部经过回读字节校验，最大单片 408270 字节。较大的详细 JSON 已作无损 gzip 封装，未压缩原件移至仓库外 scratch 保留；原运行 summary 以 [EXECUTION_SUMMARY.json.gz](EXECUTION_SUMMARY.json.gz) 保留，变换映射和 SHA256 见 [PACKAGING.json](PACKAGING.json)。封装没有重新运行 native，也没有更改科学数值结果。实际执行脚本快照见 [INTERVENTION_SOURCE.py](INTERVENTION_SOURCE.py)。

这组证据支持“已训练的有限解析状态会因边界参数而改变真实内容执行”的机制结论。两种干预的平均效用差均为负，且数据来自用于开发和选 checkpoint 的 VAL；本诊断不能替代独立 heldout 的性能比较，也不能证明 continuum 解、全局最优边界或生产部署优势。
