# CTRL-1：决策与协调 Cell — 冻结实验与完整证据

日期：2026-11-08。状态：**有限环境工程实验完成，原件与策略重放通过；真实任务和生产采用继续 HOLD。**

本次交付把“在固定 NDU 语义下分配行动、计算、观察和验证”做成了可执行的有限模型实验。源码位于 [`scripts/ndu_ctrl1`](../../scripts/ndu_ctrl1/README.md)。确认结果支持收费路由的重要性，也暴露了当前方法的不足：固定阈值 hybrid 在四个配置的平均效用最高；学习路由器节省计算但平均效用低于 hybrid；joint 与 mean MPC 在全部 96 对确认 case 中结果相同；32 epoch 主实验中的蒸馏改善没有转化为同 CPU allowance 下对 actor-critic 的优势。

这些结论来自通过审计的第二轮完整运行。两次首轮原件存在保留缺口或身份不一致，均被拒绝，没有补造缺失结果、重建检查点或并入正式均值。原因尚未确定。第二轮使用逐字相同的 PLAN、相同源码、种子、超参数和目标 profile，不增加独立训练种子数。CPU allowance 重复所得的完整 epoch 数、学习权重和实测时间可以不同。

## 1. 验收结论与入口

| 项目 | 结果 | 可检查的原件 |
| --- | --- | --- |
| Native 格式与定向测试 | 实际 `just fmt`、锁定 Ruff 0.15.13 通过；61 个测试通过 | [Native source receipt](diagnostics/native-source-final-v4.json) |
| 主实验原件 | 24 个 learner、12 个 router、96 条开发结果、864 条确认结果、13,824 条轨迹；996 个 attempt 身份 | [PLAN](primary_repeat_2/PLAN.json)、[REPORT](primary_repeat_2/REPORT.json)、[ARTIFACTS](primary_repeat_2/ARTIFACTS.json) |
| 主实验重放 | 96 / 96 开发结果、864 / 864 确认结果、13,824 / 13,824 轨迹；12 个开发选择全部复核，零差异 | [完整重放收据](AUDIT_PRIMARY_REPEAT_2.json) |
| CPU allowance 原件 | 72 个 worker、576 条确认结果、144 个事件；72 Available、0 NoCandidate | [CPU PLAN](cpu_repeat_2/PLAN.json)、[CPU REPORT](cpu_repeat_2/REPORT.json) |
| CPU allowance 重放 | 576 / 576 策略值重新计算通过，封存拷贝后的原件结构审计通过 | [重放](AUDIT_CPU_REPEAT_2.json)、[封存检查](AUDIT_CPU_PUBLISHED.json) |
| 开发集门控 | 9 Candidate、3 NoUpdate；只按预先冻结的开发集规则选择 | [主分析](primary-analysis.json) |
| Joint MPC 优于 mean MPC | 本轮未展示；96 对结果一致 | [主分析的配对项](primary-analysis.json) |
| 学习路由器优于固定 hybrid | 本轮未展示平均优势；计算较省，效用较低 | [主分析](primary-analysis.json) |
| 完整物理成本等价、外部结果评价、真实文档／工具／GUI、native owner 采用 | 未完成资格，HOLD；无生产授权 | [机器可读结论](QUALIFICATION.json) |

完整数值分别见 [primary-analysis.json](primary-analysis.json) 和 [cpu-analysis.json](cpu-analysis.json)。所有资格文件的内容身份由 [QUALIFICATION_MANIFEST.json](QUALIFICATION_MANIFEST.json) 绑定；它不把文件哈希当作外部执行证明。

## 2. 固定语义和职责边界

技术契约固定为 [`utility.ndu` @ `732e934ba496d90fbe042b8d41d479ef901643e5`](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/732e934ba496d90fbe042b8d41d479ef901643e5/docs/modules/utility.ndu/TECHNICAL.md)。实现依赖父 PR [#5336](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5336) 的 `9c6c18cec8c56260d633de5a6adf321de2a4e3d4`。核心代码 commit 为 `472c825a87220574acc5338afe59558e1ad2038f`，审计器 commit 为 `368ef32be4388d47f3faddf0ac78806e33d680cd`。

父版本的 `scripts/ndu_real_runtime/objective.py` 和 `finite_entropic_golden.json` 保持原字节不变。已有有限熵风险 profile 是 `hepta.ndu.finite-entropic.v1`；本次显式新增资源费用 adapter `hepta.ctrl1.resource-cost.v1`：

```text
edge(T, U) = -latency_weight * T + discount_per_second ** T * U
Q(s, a) = CE_risk(-resource_weight * C + edge(T, continuation))
CE_0(X) = E[X]
CE_risk(X) = -log(E[exp(-risk * X)]) / risk, risk > 0
```

每个联合分支分别带入结果、时间、费用和后继值，再在公共观察边界嵌套 CE。资源费立即计入、位于时间折扣之外和 CE 之内。这个声明是有限工程 profile 的数学语义，不覆盖全部 native NDU 随机模型。

效用层只提供声明过的 value／advantage。参数更新位于隔离的学习 adapter；研究候选不直接更新 native Cell。新奇度、预测误差和熵下降没有被替代成任务奖励。Q32 测试读取固定整数 golden 并使用独立 Python 参考实现；这不等于新执行了 Rust 路径，也不构成随机 FBSDE 验收。EFE 对照尚未实现；将来必须保留其独立目标定义。

## 3. 模型、控制器与冻结计划

隐藏 bit 表示执行能否成功。公共状态包含精确有理数信念、剩余时间、credits、行动步数和已经使用的功能标记。环境实现 `stop`、`execute`、`observe`、`recall`、`verify`、`repair` 六类真实有限转移；控制器另决定是否支付规划成本。信号、可见持续时间和费用共同参与 Bayes 更新，支持有重叠，控制器不能读取采样隐藏状态。

硬预算合法性检查覆盖所有正概率结果，STOP 始终可用。oracle 对可达信念状态做穷举动态规划，额外由小规模独立条件策略树枚举核对。概率和后验使用 Fractions；价值运算仍采用 FP64，因此“精确”指有限策略和概率分支的穷举，不是实数算术的形式化证明。

oracle 不支付在线控制器计算费，作为理想上界。其离线求解 CPU 单独记录。`policy_gap` 是同一 profile 下 oracle value 减去实际付费控制器 value，包含在线计算开销。

| 比较项 | 冻结配置 |
| --- | --- |
| 独立训练种子 | 17、23、41，共 3 个 |
| 主训练 | 每 profile 4 个训练场景，共 128 个公共状态；32 epoch、4,096 次 actor 更新机会 |
| 开发选择 | 每 profile 4 个开发场景；增益严格为正且额外平均控制器 credits 不增加才选 Candidate |
| 确认 | 每 profile 8 个场景，改变先验、传感器准确率、修复成功率和结果相关方向 |
| 任务边界 | 时间上限 8 秒、资源 10 credits、行动 horizon 3 |
| 控制器 | 固定、fast actor-critic、VOI、joint MPC、mean MPC、固定 hybrid、学习路由器、蒸馏候选、门控后的 fast，共 9 个 |
| 每次决策费用 | 基础 1 credit；慢路另预付不可退还的 3 credits 和 1 个模拟秒；步数或资源耗尽时免费应急 STOP |
| 规划边界 | 深度 1 / 2 / 3；最多 96 个 action forecasts；只允许采用已完整比较的深度 |
| 主矩阵 | 4 profiles × 3 seeds × 8 scenarios × 9 controllers = 864 行；每行 16 条采样轨迹 |
| CPU 敏感性 | 4 profiles × 3 seeds × 1 / 2 / 4 秒上限 × 2 learners = 72 workers；每个 8 行确认结果 |

共同时间折扣为每秒 0.97：

| 配置 | Profile hash 前缀 | 风险参数 | 每秒显式价格 | 每 credit 显式价格 |
| --- | --- | --- | --- | --- |
| A | 97e2016b00cc | 0.0 | 0.0 | 0.0 |
| B | 29d3a0540d92 | 0.0 | 0.01 | 0.02 |
| C | 6c4949f90c48 | 0.25 | 0.0 | 0.0 |
| D | 6d077dda5bd1 | 0.25 | 0.01 | 0.02 |

A、C 去掉的是显式时间／资源罚项，时间折扣和硬预算仍然有效。四个 profile 定义了不同目标，下面逐 profile 比较，不合并为一个“总体 NDU 收益”。

AC 与蒸馏共享状态样本、初始化、actor 架构、顺序及 actor 更新机会。AC 用冻结 critic 的 action-Q 和 `sum(pi * frozen_Q)` surrogate；它不是完整风险敏感轨迹目标的无偏梯度。蒸馏保留全部 bounded MPC teacher 标签，包括未改善、fallback 和停止标签。其教师是 standalone MPC，而不是本轮最优的 hybrid。

学习路由器拟合“一次慢调用后固定 fast continuation”相对于“全程 fast”的真实环境 advantage，保留正、负和零样本；部署的重复路由单独评价。不过，该 teacher 调用内部仍按 standalone MPC 的未来收费搜索，部署搜索预测的是 learned router 的收费。这个目标并非部署策略的精确 meta-Q，不能保证每次更新或整体策略改善。

## 4. 主实验结果

以下每格是 3 seeds × 8 scenarios 的 24 行描述性均值。独立训练重复只有三个，16 条轨迹不是额外训练种子。

### 4.1 同 profile 的 value 和 policy gap

| 控制器 | A：value / gap | B：value / gap | C：value / gap | D：value / gap |
| --- | --- | --- | --- | --- |
| 固定策略 | 0.350000 / 0.393621 | 0.330000 / 0.291461 | 0.350000 / 0.383464 | 0.330000 / 0.276491 |
| Fast actor-critic | 0.470559 / 0.273062 | 0.390559 / 0.230902 | 0.445974 / 0.287490 | 0.370800 / 0.235691 |
| VOI | 0.543612 / 0.200009 | 0.365302 / 0.256159 | 0.532731 / 0.200733 | 0.349070 / 0.257421 |
| Joint MPC | 0.474045 / 0.269576 | 0.354945 / 0.266516 | 0.461807 / 0.271657 | 0.342663 / 0.263828 |
| Mean MPC | 0.474045 / 0.269576 | 0.354945 / 0.266516 | 0.461807 / 0.271657 | 0.342663 / 0.263828 |
| 固定阈值 hybrid | 0.715778 / 0.027843 | 0.494564 / 0.126897 | 0.701334 / 0.032130 | 0.480043 / 0.126448 |
| 学习路由器 | 0.599481 / 0.144140 | 0.432982 / 0.188479 | 0.614597 / 0.118867 | 0.409089 / 0.197403 |
| 蒸馏候选 | 0.481130 / 0.262491 | 0.418769 / 0.202693 | 0.463532 / 0.269933 | 0.401157 / 0.205334 |
| 开发集门控后的 fast | 0.470559 / 0.273062 | 0.418769 / 0.202693 | 0.463532 / 0.269933 | 0.401157 / 0.205334 |

固定 hybrid 在四个配置的平均 value 最高，主要策略是一次慢调用后 `repair → execute`。它相对 fast AC 的平均增量分别为 +0.245219、+0.104005、+0.255360、+0.109243，但 B 中有 9 / 24 case 更差，不能说逐 case 支配。

学习路由器相对 fast AC 共 35 胜、60 平、1 负；相对 hybrid 共 8 胜、36 平、52 负。B 的 seed 23 平均增益为零，三个种子的变化明确保留。学习路由器的价值低于 hybrid，同时减少了慢路调用，显示的是计算费用与效用的折衷。

Joint MPC 和 mean MPC 的 96 对结果，在 value、gap、动作期望、预算、停止指标和展开量上全部相同。本轮没有联合预测改善策略的实证结果。Mean MPC 仍可访问完整已知联合模型的后验分支和合法性检查，仅在 backup 中压缩均值；它不是“训练出的均值预测器”对“训练出的联合预测器”的校准比较。

VOI 在 A、C 的平均效用高于 fast AC；在启用显式费用的 B、D，增量分别为 −0.025257 和 −0.021730。不能跨 profile 平均后宣称信息获取普遍有益。

### 4.2 净终局效用与停止损失

`net_terminal_utility` 是未折扣的期望终局 payoff 减声明费用，和风险敏感的嵌套 NDU value 是不同量。下表每格为净终局效用 / stop regret：

| 控制器 | A：净终局效用 / stop regret | B | C | D |
| --- | --- | --- | --- | --- |
| 固定策略 | 0.350000 / 0.393621 | 0.330000 / 0.271461 | 0.350000 / 0.383464 | 0.330000 / 0.256491 |
| Fast actor-critic | 0.500000 / 0.000000 | 0.420000 / 0.000000 | 0.500000 / 0.000000 | 0.422986 / 0.007789 |
| VOI | 0.618933 / 0.001591 | 0.416947 / 0.000000 | 0.618933 / 0.001370 | 0.421923 / 0.000333 |
| Joint MPC | 0.508333 / 0.169360 | 0.388333 / 0.111133 | 0.508333 / 0.159954 | 0.388333 / 0.101686 |
| Mean MPC | 0.508333 / 0.169360 | 0.388333 / 0.111133 | 0.508333 / 0.159954 | 0.388333 / 0.101686 |
| 固定阈值 hybrid | 0.833333 / 0.000000 | 0.603333 / 0.000000 | 0.833333 / 0.000000 | 0.603333 / 0.000000 |
| 学习路由器 | 0.666667 / 0.000000 | 0.482778 / 0.000000 | 0.712963 / 0.000000 | 0.484676 / 0.000000 |
| 蒸馏候选 | 0.504861 / 0.103809 | 0.442500 / 0.065079 | 0.504861 / 0.101164 | 0.442500 / 0.059518 |
| 开发集门控后的 fast | 0.500000 / 0.000000 | 0.442500 / 0.065079 | 0.504861 / 0.101164 | 0.442500 / 0.059518 |

`stop_regret` 在已经付完当前计算费的状态衡量停止时放弃的机会；`compute_and_stop_regret` 从支付计算费之前计入“计算后停止”的损失；`continuation_regret` 只在 oracle 选择停、控制器却继续时记账。这些是路径访问分布下的局部诊断，不是 policy gap 的可加分解。

Fast AC 在前三个 profile 几乎总是直接执行，所以 stop regret 为零，policy gap 仍达 0.23–0.29。D 中蒸馏提高 value，却增加 stop regret：停止可以优于 AC 的直接执行，同时低于 oracle 的修复再执行。本矩阵 continuation regret 全为零，没有区分能力。D 中 MPC 的 stop regret 为 0.101686，而 compute-and-stop regret 为 0.151936；其差值包含时间和预算导致的后续机会变化，不能解释成纯 CPU 价格。

864 行精确结果和 13,824 条采样轨迹的预算违约均为零。样本最大已记录总费用为 10、时间为 7 秒；这对应有限支持环境中的强制合法性，不能外推到未知工具费用或真实执行延迟。

### 4.3 控制器费用与机制解释

每条任务平均在线模拟控制器 credits：

| 控制器 | A | B | C | D |
| --- | --- | --- | --- | --- |
| 固定策略 | 1.000 | 1.000 | 1.000 | 1.000 |
| Fast actor-critic | 1.000 | 1.000 | 1.000 | 1.000 |
| VOI | 5.000 | 4.500 | 5.000 | 4.750 |
| Joint MPC | 4.000 | 4.000 | 4.000 | 4.000 |
| Mean MPC | 4.000 | 4.000 | 4.000 | 4.000 |
| 固定阈值 hybrid | 5.000 | 5.000 | 5.000 | 5.000 |
| 学习路由器 | 2.667 | 2.000 | 3.167 | 2.167 |
| 蒸馏候选 | 1.000 | 1.000 | 1.000 | 1.000 |
| 开发集门控后的 fast | 1.000 | 1.000 | 1.000 | 1.000 |

这里的 credits 是事先声明的调用价格；实际节点数、CPU 和 wall time 独立记录，不能把 credits 当作测得的硬件消耗。

初始 10 credits，慢路收费 4 后剩 6，repair 收费 2 后剩 4。Standalone MPC 在后继状态再次请求慢路会把剩余资源用尽，无法 execute。Hybrid 在 repair 后看到信念升到 7/9 或 8/9，超过固定 0.75 阈值，转用只收费 1 credit 的快策略，留下足够执行资源。这解释了本轮主要的 hybrid 优势：未来计算分配会改变环境行动的价值。

这次 MPC 实际展开 44–60 个节点，hybrid 展开 44–72 个，均未触及 96 上限；fallback 为零。不能把差距归因于本轮搜索 cap 耗尽，也不能把它读作规划方法普遍较差。

主矩阵中的学习控制器尚未全面协调所有动作族：hybrid 的 96 个 case 都先 repair 再 execute；router 有 36 个 case 做 repair，最终均 execute；fast AC 是 95 execute、1 stop；蒸馏候选是 68 execute、28 stop。只有 VOI 对照实际使用 observe／recall／verify。CPU 加长训练的 AC 行为单列在下一节，不与这个 32 epoch 结论混合。

### 4.4 开发集选择

| 配置 | 三个 seed 的决定 | 开发集平均 NDU 增量 | 额外控制器 credits |
| --- | --- | --- | --- |
| A | NoUpdate × 3 | -0.002093898 | 0 |
| B | Candidate × 3 | +0.013843602 | 0 |
| C | Candidate × 3 | +0.004456129 | 0 |
| D | Candidate × 3 | +0.020821664 | 0 |

共 9 Candidate、3 NoUpdate。A 的候选后来在确认集均值较高，仍保留开发集已经作出的 NoUpdate，没有倒用确认结果改变选择。Candidate 只是本研究的开发集门控状态，不授予 native owner 采用权限。

## 5. CPU allowance 敏感性

72 个隔离 POSIX worker 使用相同的 1 / 2 / 4 秒硬 CPU 上限，合作式阈值为上限的 90%，最多 512 epoch；只采用最后完整 epoch，不按开发集或确认集挑选检查点。Teacher 准备、拟合、失败／部分 epoch 工作和检查点序列化进入 worker CPU；共享 roster、parent supervision、后续评价有单独作用域。

全 72 个 worker 为 Available，其中 60 个 CooperativeCpuBudgetStop、12 个 Completed。12 个 Completed 全是 4 秒 allowance 下达到 512 epoch 的蒸馏。全部 576 行重新计算通过。下表 value / gap 每格为 24 个确认 case，CPU 和 epoch 为 3 个 worker 均值：

| 配置 | CPU 上限（秒） | AC：value / gap | 蒸馏：value / gap | AC：实耗 CPU 秒 / epoch | 蒸馏：实耗 CPU 秒 / epoch |
| --- | --- | --- | --- | --- | --- |
| A | 1 | 0.595333 / 0.148288 | 0.474490 / 0.269132 | 0.9192 / 87.0 | 0.9365 / 208.7 |
| A | 2 | 0.658066 / 0.085555 | 0.474490 / 0.269132 | 1.8316 / 171.7 | 1.8301 / 458.0 |
| A | 4 | 0.677729 / 0.065892 | 0.474490 / 0.269132 | 3.6266 / 358.7 | 2.0461 / 512.0 |
| B | 1 | 0.438706 / 0.182755 | 0.402615 / 0.218847 | 0.9300 / 88.0 | 0.9444 / 214.3 |
| B | 2 | 0.438706 / 0.182755 | 0.402615 / 0.218847 | 1.8264 / 198.7 | 1.8334 / 464.7 |
| B | 4 | 0.438706 / 0.182755 | 0.402615 / 0.218847 | 3.6443 / 347.7 | 2.1401 / 512.0 |
| C | 1 | 0.620208 / 0.113256 | 0.452990 / 0.280475 | 0.9300 / 83.0 | 0.9311 / 215.7 |
| C | 2 | 0.657436 / 0.076028 | 0.452990 / 0.280475 | 1.8337 / 173.0 | 1.8410 / 454.7 |
| C | 4 | 0.679544 / 0.053920 | 0.452990 / 0.280475 | 3.6342 / 339.7 | 2.0670 / 512.0 |
| D | 1 | 0.426045 / 0.180447 | 0.381232 / 0.225259 | 0.9333 / 83.0 | 0.9334 / 214.3 |
| D | 2 | 0.426045 / 0.180447 | 0.381232 / 0.225259 | 1.8327 / 173.3 | 1.8312 / 489.0 |
| D | 4 | 0.426045 / 0.180447 | 0.381232 / 0.225259 | 3.6370 / 359.0 | 1.9487 / 512.0 |

**在全部 12 个 profile × allowance 分组中，AC 平均 value 都高于蒸馏。** 这与主实验的 32 epoch 比较回答不同问题：多给定额训练后 AC 在部分配置学到修复，蒸馏进行了更多更新以拟合同一 standalone MPC 教师。确认结果不能支持“蒸馏在同计算 allowance 下普遍更好”。机制解释与因果归因仍需新实验，不从这批数据分解拟合、教师质量和训练分布各自的作用。

AC 在 A、C 随 allowance 增大而改善，B、D 平台化；蒸馏四组的确认 value 都平台化。仍保留一个逐 case 反例：A、1 秒、seed 41、`confirmation-06076c4a31b3bb9b`，AC 为 0.3185560833，蒸馏为 0.35。因此分组平均优势不意味着逐 case 支配。

CPU 矩阵每个方法有 288 个确认 case。AC 在 79 个 case 使用 repair，蒸馏在 0 个 case 使用 repair；两种方法 observe／recall／verify 的非零 case 总数分别为 0 和 0。因此加长训练展示了部分行动组合的学习，仍不构成全面信息协调的证据。

CPU 合计 134.585339 秒，其中 AC 76.736611 秒、蒸馏 57.848728 秒。4 秒 allowance 下，蒸馏通常约用 1.95–2.14 秒就达到 512 epoch，AC 约用 3.63–3.64 秒。相同上限不等于相同实耗，更不等于完整物理成本、能耗或金钱相等。主实验的 learner attempt CPU 约为 AC 3.985478 秒、蒸馏 1.503896 秒，router 训练另计 7.665715 秒，共享 roster 按每个 profile 一次共 0.764485 秒；这些作用域不能和内部嵌套计时重复相加。

## 6. 两次首轮拒绝与完整保留

| 运行 | 过程汇总声称 | 实际原件／身份观察 | 处置 |
| --- | --- | --- | --- |
| 首轮主实验 `primary` | 864 行、13,824 轨迹 | 精确结果 860 / 864，缺失同一场景最后 4 个 controller 行；对应轨迹存在，但不能替代精确结果原件 | 完整拒绝，原字节封存；全矩阵同 PLAN 重跑 |
| 首轮 CPU `cpu_allowance` | 72 workers、576 行 | 460 / 576 行、116 / 144 事件；4 个 final checkpoint 与 receipt 不一致，其中 3 个参数 hash 不同 | 完整拒绝，原字节封存；72 workers 全部同 PLAN 重跑 |
| 第二轮主实验 `primary_repeat_2` | 864 行、13,824 轨迹 | 原件完整，全部开发值／确认值／轨迹重放通过 | 作为本报告主实验数值来源 |
| 第二轮 CPU `cpu_repeat_2` | 72 workers、576 行 | 原件完整，全部检查点绑定及 576 行重放通过；封存后复核通过 | 作为本报告 CPU 数值来源 |

首轮主实验拒绝见 [验证收据](VERIFY_PRIMARY_ATTEMPT_1.json) 与 [原件观察](PRIMARY_ATTEMPT_1_INTEGRITY_OBSERVATION.json)。首轮 CPU 拒绝见 [验证收据](VERIFY_CPU_ATTEMPT_1.json) 与 [四项 checkpoint 观察](CPU_ATTEMPT_1_IDENTITY_OBSERVATION.json)。第一次 CPU 拒绝使用格式化前的审计器，原审计源码归档在 diagnostics；正式第二轮使用已提交的最终审计器。

被拒绝的原目录全部文件按原字节进入 [rejected_attempts](rejected_attempts/README.md)，逐文件和分片身份见 [INDEX.json](rejected_attempts/INDEX.json)。压缩只改变封装，不补齐缺行，也不把异常 checkpoint 改写为 terminal receipt 所声称的版本。CPU 原件中遗留的临时文件也保留。原目录的文件缺口原因尚未定位，不能仅凭 ctime／mtime 差异判断某个进程或人为原因。

第二轮 CPU 在隔离临时目录中完成训练和完整重放，关闭输出后再封存并复核。此操作避免本轮在写入时发布原件，但不证明已修复首轮异常的根因。第二轮主实验耗时 102.974377 秒，其完整重放另耗时 84.486103 秒；第二轮 CPU 的训练、重放和封存复核外层调用共 246.535933 秒。这些是调用 wall time，不能当作训练 CPU。

Native 格式工具最初的依赖下载超时、拥有者进程清理、字节 Range 下载与锁定 wheel SHA 核验等诊断也保留于 [diagnostics](diagnostics/native-preparation-index-v1.json)。它们是基础设施准备事件，不计入科学实验的失败分母。训练前计时校准保留其历史源码身份，不冒充最终源码运行。

## 7. 审计能证明什么

核心源码清单摘要为 `f9ed764f50edfc4a6a6e1408eeba964f7a0c75e11a5d2a5621f9f9bf185b30ee`，覆盖 18 个 CTRL-1 Python 文件和两个未改的父版本效用文件。Native 格式化后再执行正式实验；root 校验了全部导入文件，18 个 Python 文件的可执行 AST 全相同。严格 AST 的三处差异是四个 docstring 的缩进，`inspect.cleandoc` 全等。详见 [SOURCE_IMPORT.json](SOURCE_IMPORT.json)。

Native 测试在 Mac Python 3.14.3 上通过；完整实验在 Linux x86_64 Python 3.12.14 上执行。主审计器独立调用同一冻结实现，恢复 checkpoint、重算开发采用决定、全部有限策略值和 seeded 轨迹，并核对动作、费用和节点计数。CPU 审计器核对完整 Cartesian 分母、worker 终止、limits、plan、profile、seed、roster、checkpoint 与 receipt，再重新计算全部保留策略。只有明确的正常完成／合作停止或可识别的 CPU limit 信号允许检查 retained checkpoint；SIGKILL 或任意异常退出不能被自动说成成功的预算停止。

完整审计不重新训练模型，也不复刻实测 CPU／wall；它不是独立外部任务评价，更不是远端操作系统对每条执行的证明。文件 hash 用于检测相对封存清单的字节变化；来源、完整分母和重放共同构成这个工程证据包。

## 8. 复现与进一步实验

从该 PR 的完整 checkout 根目录，Python 3.10+ 可运行定向测试；CPU campaign 需要 POSIX `fork`、`wait4` 和 `RLIMIT_CPU`。运行目录必须不存在：

```sh
PYTHONPATH=scripts python3 -m unittest discover \
  -s scripts/ndu_ctrl1 -t scripts -p 'test_ctrl1_*.py' -v

PYTHONPATH=scripts python3 -m ndu_ctrl1.verify \
  qualification/ctrl1-decision-cell-20261108/primary_repeat_2
python3 qualification/ctrl1-decision-cell-20261108/audit_primary.py \
  qualification/ctrl1-decision-cell-20261108/primary_repeat_2
python3 qualification/ctrl1-decision-cell-20261108/audit_cpu.py \
  qualification/ctrl1-decision-cell-20261108/cpu_repeat_2 --recompute-results

PYTHONPATH=scripts python3 -m ndu_ctrl1.run --output /tmp/ctrl1-new-primary
PYTHONPATH=scripts python3 -m ndu_ctrl1.sensitivity_run --output /tmp/ctrl1-new-cpu
```

同 allowance 重训会因机器速度、CPU 开销和合作停止时刻产生不同完整 epoch；原件重放的对象是已封存 checkpoint，不要求不同机器训练结果逐位相同。原件中的绝对执行路径只作来源记录，CPU 审计读取相对 run 目录。

后续研究应另立版本和预注册卡：

1. 构建有识别能力的联合预测比较，固定边际、只变 coupling，并进一步比较真正学习的 mean／joint predictor 校准。当前确认先验 1/3、2/3 下翻转相关方向同时改变时间和费用边际，不能当作纯相关消融。已有先验 1/2 的单元 fixture 只证明机制可存在。
2. 扩大信息价值、repair 收益和计算价格覆盖，加入廉价 repair／execute 规则对照；用新冻结数据检验路由器目标与部署未来收费一致的版本。当前确认集没有证明学会全面协调观察、记忆和验证。
3. 对照更强教师与当前 standalone MPC，分开 matched updates、worker allowance 和实耗成本；不能把 32 epoch 下的蒸馏增益推广成任意训练预算下的优势。
4. 增加事先固定的训练种子，建立外部结果评价、真实费用与故障恢复，再进入真实文档、工具和 GUI；native owner 采用仍需契约规定的独立条件。

固定／可变时间条件还改变了信息结构和部分条件均值，不能解释成只改变时间方差。当前 profile 的风险参数只评价有限支持上的嵌套 CE；没有极端尾部实证、未知模型稳健性或实世界收益保证。

## 9. 研究来源的适用范围

- [Sousa et al., Nature 2025 / TMRL](https://pubmed.ncbi.nlm.nih.gov/40468078/) 为奖励大小与到达时间的联合表示提供神经实验依据。费用维度是 CTRL-1 的工程扩展，论文没有验证这里的控制器。
- [Lowet et al., Nature 2025](https://pubmed.ncbi.nlm.nih.gov/39972123/) 报告 D1／D2 纹状体群体对奖励分布两侧的偏好编码。它支持研究分布表示，不能直接证明风险校准或软件收益。
- [Mills、Gershman、Tenenbaum，2025](https://escholarship.org/uc/item/8f52z7hx) 是关于已学策略与在线元推理的一页会议摘要；本实验算法不是该文完整方法的复现。
- [Nuijten et al., UAI 2026](https://proceedings.mlr.press/v337/nuijten26a.html) 区分 planning-as-inference 目标。以后 EFE 对照保留自身数学语义，并在共同任务结果上评价。
