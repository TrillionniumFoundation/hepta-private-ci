# Digital multiround feedback：32-fit 确认收尾报告

本报告补齐 PR [#4578](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4578) 已归档确认实验的分析与结论。审计输入固定在 `903946f15dd79bc53a39a479230e366df04a371f`，报告生成于 2026-11-04。原确认数据于 2026-11-02 生成；本次没有新增训练、生成新世界、调整模型、选择成功拟合或改变预注册门槛。

## 结论与当前决策

**32/32 个注册拟合全部完成且主比较输入完整。四个主收益门槛全部未达到；四个必需候选的 256 个 fit×domain×candidate 质量检查，整体通过数为 0。当前封存方案不予收益验收，`acceptance=false`。** 完成的实验应按该结论收尾，不再仅以“running”描述；缺失报告与统计文件的问题可以关闭。解析核优势、质量达标、完整历史成本、开放域能力等科学或产品门槛仍未通过，不能据此宣称全部研究 blocker 已闭合。

这是一个有限区间、固定物理动力学的读出与反馈实验。`fpt_feedback` 比较同一 FPT 家族内多轮与单轮反馈，`ordinary_feedback` 比较普通家族内多轮与单轮反馈。它们不是解析核替换的 D−B 主检验。预注册的 `analytic_increment` 只是未做多重比较校正的次级描述指标，仍须服从同信息、质量和成本边界。依据：[冻结协议](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/protocol.json)、[冻结统计方法](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/statistics.py)、[本次完整统计](evidence/ANALYSIS.json)。

## 一、确认设计与完整性

固定拟合为 6003、6005、…、6065，共 32 个。每个拟合在 IID、OOD 各有 64 个世界，同一 fit/domain 的 16 个候选共享配对世界；其中 15 个为训练候选，另一个为 Bayes 参考。确认主记录共 4,096 个世界、65,536 个 episode、360,155 个 decision、30,183 次事件、18,427 次恢复；另读取 4,096 条独立探针 episode 记录，用于留存的读出恢复诊断。世界和决策数量均不增加统计样本量，推断单位始终为 32 个 fit 均值。

37 个归档包括 32 个确认拟合包和 5 个阶段控制包，合计 30,735 个成员、179,515,856 字节压缩归档。采集与复算检查了每段保存字节 SHA256、解码字节 SHA256/长度、完整归档 SHA256/长度、成员清单与每一成员 SHA256/长度。所有注册候选与世界均进入汇总，无失败后删去拟合的 complete-case 分析。

原始记录复核完成 15,595,691 次数值比较与 9,911,041 次相等性比较，0 次违反；最大绝对数值差为 `4.440892098500626e-16`，判据为绝对容差 `1e-12` 加相对容差 `1e-10`。这不是数值逐位相等声明。依据：[复核记录与全部归档摘要](evidence/CONFIRMATION_COMPLETION_AUDIT.json)。

复核范围为字节、任务状态推进、动作合法性与留存 Q 的贪心一致性、费用、终态奖励/效用、内容记录与 payload 字节绑定、事件/恢复状态契约、原始 decision 与诊断表链接、八项质量指标复算，以及留存预测的 decoder MSE 算术。检查函数沿用固定 SHA 的 `audit/independent.py` 函数体；其中“independent”指独立计算实现，原作者已明确不代表第三方作者或独立数据。本次未重新执行全部模型 logits、teacher oracle、潜态随机抽样或 decoder 系数拟合，也没有重放 480 个模型的全部优化更新。质量复算调用冻结的 `quality.py`，因此它验证归档汇总一致性，不是另一份独立质量公式实现。依据：[原始检查器](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/audit/independent.py)、[收尾工具](audit/complete_confirmation.py)。

## 二、四个预注册主比较

方法为 fit 级配对 Student t，df=31，四个双侧 Bonferroni 区间控制家族 α=0.05。收益条件是区间下界严格大于效用差 `0.02`。方法依赖独立、近似正态的 fit 级差异假设；配对世界和共用候选随机流是设计的一部分，不可当作额外独立观测。

| 域 | 主比较 | 效用差均值 | Bonferroni4 区间 | 收益门槛 |
|---|---|---:|---|---|
| IID | `fpt_feedback` | -0.01121216 | [-0.07773520, 0.05531089] | 未达到 |
| IID | `ordinary_feedback` | -0.02268921 | [-0.10893720, 0.06355878] | 未达到 |
| OOD | `fpt_feedback` | 0.00387695 | [-0.05256245, 0.06031636] | 未达到 |
| OOD | `ordinary_feedback` | 0.00931152 | [-0.04519463, 0.06381768] | 未达到 |

四个区间都跨过零。**未达收益门槛不能推出伤害、零效应或等效。** 冻结方案本就以 32 fit 为资源上限；开发数据的条件功效模型要求最多 632 fit，资源上限生效，`planned_power_claim=false`。不能在观察结果之后增加 episode 数并把它当成独立 fit，也不能事后放宽实用差门槛。依据：[全部 fit 差异及区间](evidence/ANALYSIS.json)、[预先功效决策](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/protocol.json)。

## 三、质量门槛是实质未通过

四个必需候选 × 32 fit × 2 domain = 256 项整体质量检查，0 项同时通过八个条件；64 个 fit/domain 中，没有一个满足全部必需候选质量。下面的数值是各 fit 指标的等权均值，不能拿均值替代逐 fit 门槛。

| 必需候选 | 域 | 八项整体通过 | selected-Q RMSE 均值 | coarse-seen 比例均值 | teacher regret 均值 |
|---|---|---:|---:|---:|---:|
| `fpt_base_multi` | IID | 0/32 | 0.260457 | 0.836892 | 0.070406 |
| `fpt_base_multi` | OOD | 0/32 | 0.342695 | 0.777483 | 0.116837 |
| `fpt_base_single` | IID | 0/32 | 0.257327 | 0.822189 | 0.070242 |
| `fpt_base_single` | OOD | 0/32 | 0.347372 | 0.777078 | 0.118096 |
| `ordinary_multi` | IID | 0/32 | 0.245939 | 0.831897 | 0.063355 |
| `ordinary_multi` | OOD | 0/32 | 0.333787 | 0.779122 | 0.110163 |
| `ordinary_single` | IID | 0/32 | 0.251550 | 0.824162 | 0.068768 |
| `ordinary_single` | OOD | 0/32 | 0.333220 | 0.786112 | 0.110247 |

冻结门槛包括 selected-Q RMSE ≤0.1、coarse-seen ≥0.95、teacher regret ≤0.05；另外五项为 belief-teacher RMSE、排序误差、margin 误差、真实标签 Brier 与 ECE。下表给出每项在 256 个必需检查中的通过次数。

| 单项质量门槛 | 通过数量 |
|---|---:|
| `actual_label_brier` | 224/256 |
| `actual_label_ece` | 160/256 |
| `belief_teacher_rmse` | 8/256 |
| `coarse_seen_fraction` | 0/256 |
| `margin_absolute_error_mean` | 15/256 |
| `pairwise_ranking_error` | 2/256 |
| `selected_q_rmse` | 0/256 |
| `teacher_regret_mean` | 11/256 |

尤其 selected-Q 与 coarse-seen 门槛均为 0/256。真实标签校准中有较多单项通过，也不能抵消控制 Q、覆盖和排序质量失败。精确状态 seen 比例另行报告；当前必需候选的 fit 均值为 0，这对应声明的数值信息表示，不是普遍可达支持的证明。依据：[质量阈值](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/protocol.json)、[质量汇总](evidence/ANALYSIS.json)。

因此下一轮若继续该方向，应先在 TRAIN/开发集解决覆盖与控制质量，重新封存后使用新确认数据。此确认集现在已被读取，必须永久计入已知历史；不能用于调参后再次作为未见确认集。

## 四、解析增量与恢复诊断的边界

次级 `analytic_increment = fpt_base_multi − ordinary_multi` 的结果如下。区间是**未校正的描述性 95% 区间**，它不属于四项主收益家族。

| 域 | 均值 | 描述性 95% 区间 |
|---|---:|---|
| IID | -0.02270020 | [-0.08940572, 0.04400533] |
| OOD | -0.04896973 | [-0.09544907, -0.00249038] |

OOD 描述区间低于零，是应记录的负向迹象；因次级多重性、共同质量失败、有限任务和固定物理动力学，不能将其升级为普遍解析核劣势或严格 D−B 结论。也不能用“32/32 已完成”来代替收益验收。完整分析还保留其余 32 个次级对比，不挑选通过者。

成对线性读出恢复的 MSE 差定义为 after − before；负值表示该留存 decoder 的均方误差降低。先在每个 fit 内求均值，再等权汇总 32 fit：

| 域 | 群组 | 留存配对数量 | cell MSE 差 | full-state MSE 差 |
|---|---|---:|---:|---:|
| IID | event | 503 | 0.02884553 | 0.00472065 |
| IID | recovery | 223 | -0.05882241 | -0.00445819 |
| IID | combined | 726 | -0.00580057 | 0.00090615 |
| OOD | event | 609 | 0.03184102 | 0.00619214 |
| OOD | recovery | 242 | -0.07288057 | -0.01184432 |
| OOD | combined | 851 | 0.00239583 | -0.00126182 |

这些只是该读出器与配对群体的诊断，没有建立 reset 的因果效应、信息论不可逆性或普遍记忆擦除。事件、恢复和合并群组的符号不同也应完整保留。依据：[全部次级和恢复诊断](evidence/ANALYSIS.json)。

## 五、确认独立性与证据保管

封存链为：源码 `a149538fd01b2da0673af3591cbfba6eb5d38804`；模型发布 `b4baec8933ca0f97b338c2234bbd0cfbeb9163c2`；封存时刻 `2026-11-02T02:10:25.632787+00:00`。32 个确认启动时间介于 `2026-11-02T02:11:24.822407+00:00` 和 `2026-11-02T02:18:14.515470+00:00`，全部晚于封存。协议 SHA256 为 `1ef05b04457d12106ceed68000212e4c0d44720658fffed03a1fc0dd461a533c`；seal SHA256 为 `b6a5278d933697827c0b2f3713b9a76ad3cf2341dc610c47bfb959c6e01fd57b`。

当前检查逐一绑定确认 STARTED 的 seal、模型发布 commit、注册 fit/split/执行种子以及 cohort 文件散列；确认各 cohort 间重复 world ID 与重复 payload 均为 0。封存前的历史命名空间审计独立枚举了当前 11,268 个种子身份，并检查包含已发生及 planned-only 旧尝试的 28,504 项记录。旧正式训练使用 3003…3065，新正式拟合使用 6003…6065，协议记录旧正式确认未生成。

这些证据支持**已声明历史清单内**的隔离和顺序，不证明世界内容对所有历史系统绝对未见，也不以“不重复 payload”替代统计独立性假设。训练记录资格沿用封存前 480 收据审计；本次重新核验 32 个训练进程收据的 SHA 与 seal 一致，并绑定模型远程读取审计 SHA。依据：[seal](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/SEALED_MODELS.json)、[历史命名空间审计](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/evidence/FINAL_PROTOCOL_SOURCE_AUDIT_V2.json)、[480 收据审计](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/evidence/TRAINING_RECORDS_AUDIT.json)、[本次 custody 记录](evidence/CONFIRMATION_COMPLETION_AUDIT.json)。

## 六、完整成本：已核验部分与不可补造的缺口

各阶段的 worker `wait4` 用户态加内核态 CPU 可加总；有归档的控制器自身 CPU 是不重叠的附加项。开发 001、开发 002、被中止的正式训练 001 均未归档控制器自身 CPU 收据，因此下面是已知成本，而非完整历史总成本。

| 阶段 | 进程收据数 | worker CPU 秒 | 控制器自身 CPU 秒 | 已知阶段 CPU 秒 |
|---|---:|---:|---:|---:|
| `development_001` | 6 | 935.672778 | 缺失 | 935.672778（下界） |
| `development_002` | 6 | 940.851798 | 缺失 | 940.851798（下界） |
| `training_001` | 32 | 575.365677 | 缺失 | 575.365677（下界） |
| `training_002` | 32 | 4075.293354 | 4.014576 | 4079.307930 |
| `confirmation_001` | 32 | 1792.632372 | 2.399095 | 1795.031467 |

**已核验历史阶段 CPU 合计下界为 8,326.229650 秒（约 2.312842 CPU 小时）。** 其中先前两轮开发和被中止正式训练合计 2,451.890253 秒，均保留在总账。缺失控制器 CPU 不按零填补；源码/测试/旧审计、数据运输、能源和未记录的外围成本也未被该数字覆盖。

被中止的 `training_001` 有四个科学训练拟合、共 60 个候选训练尝试；留存 CPU 审计中 56 个有效、4 个不合格，4 个不合格候选的候选计时合计 35.995803 秒。协议将其余 28 个科学拟合标为开始前取消，但归档显示这 28 个保护性退出进程实际各有 CPU 收据且 `returncode=1`，总计 **55.072509 秒**；它们没有形成科学训练结果，却不是零成本进程。四个 `returncode=0` 进程也不代表其所有训练候选科学有效。

开发 002 的 90 个候选中，一个 `fpt_pooled_common` / fit1129 在首次优化更新完成前失败，0 个优化更新，候选 CPU 为 0.167520 秒；该阶段总 worker CPU 940.851798 秒仍完整计入。此类候选计时已包含在 worker 计时内，不再重复相加。依据：[开发 002 成本审计](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/evidence/COST_DEV002.json)、[旧正式成本审计](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/903946f15dd79bc53a39a479230e366df04a371f/tools/hcsn/digital_feedback_20261101/evidence/COST_FORMAL001.json)、[原始进程收据投影](evidence/CONFIRMATION_COMPLETION_AUDIT.json)。

有效正式训练 002 的 480 个候选均通过原定实际 CPU 与训练有效性门槛，候选 CPU 合计 3,787.864015 秒，范围 7.886206…7.907671 秒，目标 8 秒、单臂容差 0.16 秒；优化更新合计 1,550,849。候选预算包含设置、编码、收集、优化与最终导出；共享生成、持久化和整体 worker 是更外层计时。这个合格矩阵不等于完整项目成本已齐。

确认阶段完整已知 CPU 为 1,795.031467 秒，其控制器经过墙钟 460.528015 秒；训练 002 控制器经过墙钟 1,564.476583 秒。并行 worker 的墙钟相加不能当作阶段 elapsed。确认 episode 中留存 content CPU 599.258758 秒、execution CPU 839.364986 秒、diagnostic CPU 142.960428 秒属于不同嵌套计时口径，均不能再次加到完整 worker CPU 上。

本次收尾原始记录复核另外测得进程 CPU 157.983336 秒、经过墙钟 218.071595 秒，属于事后审计成本，未混入 2026-11-02 的实验预算；下载、传输、最终本地统计与写作没有完整统一计时，因此该次审计也不声称完整全成本。依据：[阶段收据、计时口径与本次复核计时](evidence/CONFIRMATION_COMPLETION_AUDIT.json)。

## 七、收尾与后续工作顺序

| 工作项 | 本轮结果 | 下一动作与验收条件 |
|---|---|---|
| 32-fit 报告、ANALYSIS 缺失 | 已补齐、可复算 | 将本报告及工具作为独立研究 PR 发布；保留原始 frozen commit |
| 原始确认记录一致性 | 37 归档与全部 32 fit 在声明范围内通过 | 保存复核记录；不能替代模型、teacher 或第三方复现实验 |
| 四个主收益门槛 | 0/4 达标 | 封存当前未达收益结论；不通过事后改门槛挽救 |
| 必需候选质量 | 0/256 整体通过 | 先用 TRAIN/开发集解决 selected-Q、覆盖及排序质量，再冻结新试验 |
| 历史完整成本 | 保留三个缺失控制器成本 | 只能从原执行环境的可信历史收据补回；若不可恢复，永久标记 unknown。新实验启动前使控制器收据强制归档 |
| 解析核 D−B | 本轮没有该主检验通过 | 单独预注册同信息、相同支持/质量、完整成本的 2×2 设计，使用新的确认身份 |
| 功效与规模 | 预先上限 32 生效 | 在下一轮确认之前决定资源/精度；不得在查看本轮结果后把继续采样当作同一未变试验 |
| 原生、前端、开放域、产品价值 | 本报告未建立 | 分别要求对应 workload、真实输入、失效成本、未见外部任务与采纳门槛 |

这里关闭的是“已有确认数据却缺报告和统计”的交付缺口。当前证据不支持把质量、收益、完整成本或研究外推等门槛标为成功闭合。重复执行方法见 [COMPLETION_REPRODUCE.md](audit/COMPLETION_REPRODUCE.md)。
