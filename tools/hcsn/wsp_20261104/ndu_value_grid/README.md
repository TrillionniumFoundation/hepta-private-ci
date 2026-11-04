# NDU 完整任务价值的有限 bias 网格规划：独立探索

日期：2026-11-04 UTC。**搜索与复现证据通过；新增模型效力未通过验收。**

本轮直接最大化完整策略 expected utility，完成五个真实公开 joint checkpoint 的 625 次候选评分。它没有使用 Q-MSE 代理目标。五个 TRAIN 最优候选均未达到相对当前 incumbent C 的原验证门，全部回到 C；独立新世界上的原始收益差置信区间也跨零。因此不能把有限网格搜索完成、TRAIN 收益上升，或未通过门控的正测试均值记为可部署提升。

本目录独立于此前 joint 和 Belief 冻结研究，没有改写它们的协议、门槛或结果。所有源 checkpoint 和数据来自公开仓库 `TrillionniumFoundation/hepta-private-ci` 的固定提交 `5b69a046d886cf4c2a73c50e58197360ea15d8f5`。目录中没有新增 HeptaTrader 数据或实际 FullHX packet。

## 1. 固定问题及时间顺序

原始模型 A 的表示、Belief、物理转移表保持不变。C 是此前已经固定的 continuation-only 修改。新候选 V 只在 C 的 WAIT、READ、REPAIR 三个输出 bias 上添加：

`[-0.10, -0.05, 0, 0.05, 0.10]^3`

每 fit 完整枚举 125 点，包含精确 no-op C。先对全部五个 C 核验原半径，任何一个越界就停止整个研究。对每个候选，以存储的 binary64 参数为准，对全部 147 个 continuation 参数相对原始 A 的差逐项转换为 `Fraction`，作精确平方和，要求不超过原研究已记录半径的精确平方。未放宽半径、投影参数或重试。

选择目标是每 fit 原始 64 个 TRAIN public world 的等权完整策略 expected utility：终止效用减去所有读取、等待和修复收费。使用原 `policy_value` / `eval_worlds` 递归期望、原有限 CTMC law 和原 TRAIN 拟合的 decoder confusion。没有执行新的 FullHX 解码、交易或全模型训练。

在可行点内，排序严格为：最高计算 TRAIN utility、最小相对 C 的精确实际平方改变量、nominal offset 字典序。utility 相等按 binary64 计算值精确相等处理。每个 fit 的全部 125 点，包括若存在的不可行点，其逐世界得分和精确预算记录都保留。

协议和 exact executed driver 于 **05:10:34 UTC** 固定，早于候选评分和新世界生成；这是工具轨迹可核对的本地冻结，不是外部公开预注册。

| 固定证据 | SHA-256 |
|---|---|
| PROTOCOL_BEFORE_RESULTS.json | `3c20de99d8a5a141d0cac9fb63d3c03219bde8d675a91306f412ae12e106eca7` |
| run_value_grid.py | `5d306747d36d85662964f5f8a14fa9b404826d5dfe55b0a65ef668af881cadb4` |
| 全五 fit 选中参数及 VAL 门控收据 | `32715a76fccf9715d7777c882bd1a405922da3ad3853af74ff3a36f92aef9e64` |
| RESULTS.json.gz | `dd3ec5fad2b426b7257acff67b5048488e8cbc5476980e64f8559fb31ddc5b1e` |

全部五个 TRAIN 选择和原 VAL 决策写入 `ALL_SELECTIONS_AND_VAL_BEFORE_TEST.json` 后，才生成 seed **870150000** 的 IID/OOD 新世界：每 fit、每域 32 个，共 320 个。原 16-world VAL 门为 `utility(V) − utility(C) >= 0.005`，不比较原始 A 来接受组合修改。C 原本曾使用该 VAL 集选择，这一复用限制也由独立新世界评估约束。

## 2. 所选候选及验收结果

全部五个 C 和 **625/625 个网格候选**都满足原精确平方和半径。偏移顺序为 WAIT、READ、REPAIR。

| Fit | 选中偏移 | TRAIN V−C | 原 VAL V−C | VAL 接受 |
|---|---|---:|---:|---|
| 11 | (−.05, −.05, +.10) | +.007827875 | −.006093319 | 否 |
| 23 | (−.05, −.05, +.10) | +.001752626 | +.004924966 | 否 |
| 37 | (0, 0, +.10) | +.000691520 | +.000272441 | 否 |
| 53 | (−.05, −.05, +.10) | +.012702428 | +.002965666 | 否 |
| 71 | (0, −.05, +.10) | +.033612004 | −.025065351 | 否 |

TRAIN 平均 utility 从 C 的 **.2513658602** 升至 V 的 **.2626831509**。因为 C 是可行网格点，这种 TRAIN 非退化是选择规则的预期性质，不是独立泛化证据。五个最优点都使用 +.10 的 REPAIR 偏移，但没有扩大网格来追逐这个观察。

## 3. 新世界的原始及门控效果

| 模型／策略 | IID 平均 utility | OOD 平均 utility |
|---|---:|---:|
| A：原始模型 | .2264638538 | .0977506770 |
| C：冻结 incumbent | .2448791185 | .1057026421 |
| V：TRAIN 网格最优，未经门控 | .2486607084 | .1212417190 |
| V：通过固定门后的有效策略 | .2448791185 | .1057026421 |
| R：一次固定随机偏移，未经门控 | .1178886961 | .0440693400 |
| R：通过固定门后的有效策略 | .2448791185 | .1057026421 |

未经门控的 **V−C**：

| Fit | IID | OOD |
|---|---:|---:|
| 11 | +.006189626 | +.026772288 |
| 23 | −.010151405 | +.012143491 |
| 37 | −.000244700 | +.001369567 |
| 53 | −.000874004 | −.005130564 |
| 71 | +.023988431 | +.042540602 |
| 五-fit 均值 | **+.003781590** | **+.015539077** |
| 描述性配对 95% CI | **[−.011999380, +.019562560]** | **[−.008463981, +.039542135]** |

CI 使用五个原始独立训练 fit 为单位、Student-t 自由度 4，未作多重比较修正，不把 320 个世界误作 320 个独立训练实验。两组 V−C 区间均跨零。所有 V/R 均拒绝，门控后的逐世界结果与 C 完全一致，五 fit 均核验了参数精确回退；这不是磁盘事务回滚实验。

同一新 seed 也提供了已有 C 对照的事实：C−A 的 IID 均值为 +.018415265，描述性 95% CI 为 **[+.000718887, +.036111643]**，不跨零；OOD 均值为 +.007951965，CI 为 [−.029576568, +.045480498]。不能笼统称本轮所有区间跨零。这是探索性、未经多重比较校正的已有 C 对照，不是新 V 的收益资格，也不追溯修改原冻结研究的结论。

R 每 fit 只作一次固定种子的 signed permutation，不按收益挑选。其 nominal L2 范数精确匹配 V；binary64 加法后 fit37/71 的实际增量平方范数差约为 −2.7755575615628915e−18，另三 fit 为零，完整精确有理数保留在结果记录。五个 R 均预算可行，但全部未过 VAL。125 候选搜索与一次随机控制不是搜索预算匹配的比较，不能用这里的差异声称优化算法或算力优势。

## 4. 任务价值与 Q 校准分开验收

原固定 TRAIN/VAL probe 仅作描述性诊断，没有参与选择、追加门或重选候选。

| 五-fit 平均 masked Q-MSE | C | V |
|---|---:|---:|
| TRAIN | .0030736502 | .0038323517 |
| VAL | .0079100362 | .0088814558 |

V 的 TRAIN Q-MSE 在五个 fit 上全部变差，VAL Q-MSE 在四个 fit 上变差。直接改善 TRAIN argmax 策略价值不意味着输出重新成为 Bellman 一致、数值校准的 Q。原始 Belief 行、表示与转移表未改；所有记录中的 TRAIN/VAL Belief Brier 完全相同。这里只能称这些新输出为用于动作选择的 scores。

## 5. 实际计算成本及数值核验

| 项目 | 观测值 |
|---|---:|
| 完整研究计时段 CPU | 62.480971 s |
| 进程 CPU 到测量时点，含此前初始化 | 62.553426 s |
| 完整研究计时段 wall | 62.616644 s |
| 峰值 RSS | 163,430,400 bytes，约 155.9 MiB |
| 独立计时 pilot CPU | .320903 s |
| 严格参考矩阵乘法 | 1,917,311 次 |
| 诊断 BLAS 与参考最大绝对差 | 1.3322676295501878e−15 |
| 非有限结果、stderr | 0、0 |

脚本设置 295 CPU 秒软信号和 **300 CPU 秒硬上限**，290 秒主动检查，4 GiB 采样 RSS 门；操作端 wall 上限 360 秒。没有重试或追加候选。实际平台是 macOS arm64、Python 3.9.6、NumPy 2.0.2。所有执行矩阵乘法使用原显式归约结果，BLAS 仅独立比较；执行路径设置 overflow/invalid/divide 为 raise。

pilot 只在 fit11 的原 TRAIN 世界对冻结 C 作冷／热计时，不比较候选，也不生成新 TEST。它给出的 30.85 CPU 秒 warm-cache 外推不是实际总耗时。上表完整研究计时包括缓存建立、全部候选评估、原 VAL 门、固定 probe 及新世界评估，测量截止于最后 `RESULTS.json.gz` 压缩和 qualification 写入之前；不含原始训练、资产获取、Agent 设计、证据传输和后续只读审计。300 CPU 秒硬上限覆盖整个进程。没有重新训练模型作计算匹配基线，因此不能声称比梯度训练更高效。

## 6. 独立验收及复现

本包依赖同一发布目录的 `joint/` 固定源包和 `exploratory_belief/OLD_CONTINUATION_HEADS.json.gz`。所有命令显式传入路径，目录重组时可修改参数，无需改冻结代码或协议。

只读验证不运行模型，核对固定源身份、全部 625 个 Fraction 范数与最优排序、全部原 VAL 门、320 个世界记录、回退和统计汇总：

```bash
PYTHONDONTWRITEBYTECODE=1 python verify_value_grid.py \
  --study-root ../joint \
  --old-heads ../exploratory_belief/OLD_CONTINUATION_HEADS.json.gz
```

本次该验收通过。独立子 Agent 另行只读审计了全部 147 参数约束、五 C 前置核查、完整 utility 排序、全部选择先于新 TEST、相对 C 门控、随机控制六项实现，未发现错误。静态与记录审计不替代重新执行 utility。

重新执行首先用 `joint/acquire_inputs.py` 获取固定公开输入；可用 HTTPS、已有 Git 对象，或提供经验证的原 archive。脚本校验全部 3550 archive 成员后，仅提取五个 renewal checkpoint 及其原 TRAIN/VAL 数据：

```bash
python ../joint/acquire_inputs.py --output /absolute/path/to/new-public-inputs

OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
VECLIB_MAXIMUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
python -B run_value_grid.py \
  --study-root ../joint \
  --inputs /absolute/path/to/new-public-inputs \
  --old-results ../joint/records/results_strict.json.gz \
  --old-heads ../exploratory_belief/OLD_CONTINUATION_HEADS.json.gz \
  --output /absolute/path/to/new-grid-run
```

需要 NumPy 和支持 POSIX `RLIMIT_CPU` 的系统，不需要 Torch、GPU 或额外优化器。输出路径必须不存在。保留新执行自己的成本和 receipt，不覆盖本包历史记录。数值期望、argmax 边界和精确 tie 可能受浮点平台影响；重新执行应报告差异，不能把旧 timing 换入新 receipt。

## 7. 发布内容与结论边界

`records/fit_*_ALL_125_TRAIN.json.gz` 保留所有候选、逐世界 TRAIN 效用及精确有理数预算；`fit_*_BEFORE_TEST.json` 和总冻结收据保留原 VAL 门；十个 `WORLDS` 文件保留新公开日程；`RESULTS.json.gz` 保留 raw/gated 全部逐世界结果、参数和统计。`QUALIFICATION.json` 是执行完成资格，`PROCESS_VERIFICATION.json` 是已脱敏的 durable 进程资格；它们都不声称任务价值验收通过。其余清单和审计记录支持独立核对。

目录中的少量 head 参数来自原公开 checkpoint 或其本轮确定编辑，没有完整模型权重、原始 FullHX packet、私有交易行、账号、订单、实际主机操作路径或后台 job 标识。原 joint/Belief 冻结文件执行前后身份不变。

可复现的实际效果是：在约一分钟 CPU 时间内，直接对三个真实 head bias 完成有限候选集的完整价值规划，并由冻结的原 VAL 门以当前 incumbent 为基准拒绝全部不合格修改。该 VAL 集已用于旧 C 的选择，不能称为全新独立验证；新生成的 IID/OOD 世界另外用于描述性泛化评估。**有限网格最优性已经核对；可接受任务收益提升没有建立。** 这不能外推为连续权重空间最优、完整 NDU 全局最优、通用电路理解或传统训练的替代证明。
