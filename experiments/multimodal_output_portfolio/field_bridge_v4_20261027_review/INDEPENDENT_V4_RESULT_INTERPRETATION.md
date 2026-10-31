# V4 终态结果与解释的独立审阅

**审阅结论：终态文件与唯一正式 qualification 相符。实验完整执行，参数场候选资格失败；原 B03–B07 仍不能关闭。** 六项注册检查中，普通训练增益与三项 clean 非劣条件通过，两项参数场增量失败。本文复核已记录的统计量、判定、文件身份和叙述，没有新模型调用、端点重评分、bootstrap 抽样、策略选择或第二次推断。机器记录见 [INDEPENDENT_V4_RESULT_INTERPRETATION.json](INDEPENDENT_V4_RESULT_INTERPRETATION.json)。

## 1. 正式结果与失败的具体条件

以下数字直接来自冻结的 [QUALIFICATION.json](../field_bridge_v4_20261027/evidence/QUALIFICATION.json)，没有重新估计。区间为每观察者、六比较修正后的 99.1666667% 双侧近似配对 bootstrap 区间。

| 注册比较 | reward 均值 [区间] | audit 均值 [区间] | 判定 |
| --- | --- | --- | --- |
| ordinary-frozen | +0.021425427 [+0.014677202, +0.029478808] | +0.022656302 [+0.015530279, +0.030904954] | 通过 |
| origin_field-ordinary | +0.000160487 [-0.003410429, +0.004171901] | +0.001285569 [-0.001775289, +0.004137581] | 未通过 |
| origin_field-origin_richer | +0.000095250 [-0.002693143, +0.003111138] | -0.000409308 [-0.003481510, +0.003094465] | 未通过 |
| ordinary-clean-NI | +0.005317685 [-0.000022241, +0.010642517] | +0.004267880 [-0.001046221, +0.009583407] | 通过 |
| origin_field-clean-NI | +0.003990285 [-0.001360354, +0.009200783] | +0.003253794 [-0.001978108, +0.008526419] | 通过 |
| origin_richer-clean-NI | +0.004325648 [-0.000810346, +0.009501145] | +0.002360315 [-0.002452421, +0.007519172] | 通过 |

每项 gain 同时要求校正区间下界严格大于 0、三个固定模型的平均差值均严格大于 0，并在 reward 与 audit 两个观察者下都通过。两项 field 增量的下界在两个观察者下都为负，逐模型条件也失败：

| 增量／观察者 | seed 17 | seed 29 | seed 43 | 严格正号失败的位置 |
| --- | ---: | ---: | ---: | --- |
| origin_field-ordinary / reward | -0.002196935 | +0.000000000 | +0.002678396 | 17, 29 |
| origin_field-ordinary / audit | +0.000305506 | +0.000000000 | +0.003551199 | 29 |
| origin_field-origin_richer / reward | -0.001050974 | +0.000000000 | +0.001336723 | 17, 29 |
| origin_field-origin_richer / audit | -0.000593210 | +0.000000000 | -0.000634712 | 17, 29, 43 |

因此不是“只差一个总体显著性条件”。seed 29 的平局也不满足预先指定的严格正向规则。反过来，失败不能推出效应等于零、方法等价、确认性劣势或整个参数场理论为假。

三项 clean NI 仅要求两个观察者的校正区间下界均大于 −0.01，不附加 gain 的逐模型正号条件。结果 JSON 中这些 NI 项的 `model_signs_pass=true` 表示该约束不适用；例如 seed 29 的 reward clean 差值为 −0.001320602，并不能被写成三个模型全部改善。非劣通过也不等于 clean 收益显著为正或已经证明完全无损。

## 2. 比较族和推断范围没有改变

本轮六项是三个 task gain 加三个 qualification clean NI；它们不是用户最初六类实验各通过与否的计数，也不是未来 final 的六个增益对比。未来 final 的六 gain／十 retention 设计没有在本轮执行；历史 V2 的原 retention 比较族也没有被追溯改写。

每个观察者使用 α=0.05、α/6 修正，两观察者的门槛取合取。文件明确没有宣称十二个观察者区间具有联合 95% 覆盖。固定 4,000 次抽样、种子 271042 和既有分位数方法没有改变；这些是近似 bootstrap 区间，不是有限样本精确保证。

推断条件于固定模型 17/29/43 和四个任务条件。四个日程刻画模型内训练变化，不能记作四个独立模型。任务面板的 512 个源对在四个条件间保持配对；clean 有 1,024 个源对。原先冻结的 ordinary 索引为 17→2、29/43→3，正式 adaptive 参照为 origin_richer；没有根据新结果重选。raw_field、origin_generic、origin_h7 和未选 ordinary 的描述均不提升为新成功门槛。[PROTOCOL.json](../field_bridge_v4_20261027/PROTOCOL.json)

## 3. 与最初六类实验的逐项对应

| 最初的问题 | V4 实际贡献 | 仍不能作出的主张 |
| --- | --- | --- |
| 固定模型＋强固定策略 | 保留三个原模型的固定部署基线；部署动作来自此前冻结的候选选择 | 该策略是所有可想象固定策略的最优者 |
| 常规局部训练＋同一部署 | ordinary task gain 和 qualification clean NI 在两个观察者下通过 | 原最终 B−A 与独立 retention 联合验收已经完成 |
| 参数场训练＋同一部署 | 单一原点修正候选完成完整路径；相对 ordinary 和 richer 的增量都未获资格 | 已证明参数场超越普通训练或同信息 adaptive 参照 |
| 固定训练＋Hepta 状态控制 | 本轮没有新 runtime holdout 或 native tick；保留 V3 的失败结果 | 新的双观察者运行增益已经建立 |
| 参数场训练＋Hepta 状态控制 | 前置资格失败后没有开放新的 final 联合比较 | 未执行等于零效应，或两层已经具有可重复增益／超加交互 |
| 同信息的历史／轻量控制 | 训练侧 origin_richer 是正式参照，generic/H7 是诊断；旧 runtime history 结果保留 | H7 学习特征就是 Hepta runtime，或本轮已经检验 native 超越 history |

原 B03 需要最终 ordinary gain 与独立 retention；它本身不增加 runtime 收益这一前提。B04 还需要其原 C−B/E−G 条件；B05/B06 需要各自运行及同信息比较；B07 的原最终 retention 不由本次 clean 资格面板替代。十项原 blocker 的 `closure_criteria` 已逐字比对，新文件完整保留。[BLOCKERS.json](BLOCKERS.json)

## 4. 机制证据的价值与限度

仅用已经发布的 [MECHANISM.json](../field_bridge_v4_20261027/evidence/mechanism/MECHANISM.json) 作描述性算术核对：origin/raw 在 72 次决策中有 47 次不同，12 条配对路径中 8 条最终参数不同。校正减少了部分相对旧归一化器的坐标偏移，并且实际影响动作；这不是新的显著性检验，也不能证明已消除所有面板或续策失配。

origin_field 的 60 个接受块含 19 个零动作，保留的非零块只有 41 个；raw_field 为 46 个，预先选定 ordinary 为 47 个。零动作和被拒绝块的梯度计算均已执行并计费，因此保留微步数不能替代总计算成本。seed 29 的 origin_field 与所选 ordinary 四条日程的最终参数及优化器身份逐条相同，与正式差值为零一致。

第一次动作分歧后，两种方法访问不同轨迹，不能把后续日志当作同状态反事实比较。Q_ref 依然对应原冻结 reference 续策；本轮没有更换目标或重新拟合，不能据此宣称已解决闭环目标错配。112 字节仅是每路径 14 个 float64 的活跃校准载荷，不含头、原始／映射状态、日志或进程总内存。[TRAINING_FINAL_COMMENTS.md](TRAINING_FINAL_COMMENTS.md)

## 5. 来源、冻结顺序与旧失败的保留

本轮 6,352 张官方 train 图像使用独立新角色，排除完整 V2/V3 已登记的 57,048 个图像身份，包括 V3 原先没有物化为任务的八角色、12,496 张图像。各角色之间与旧登记之间的像素交集均为零；余下未分配 train 2,648、test 3,952。qualification task/clean 现在已经被模型评价，不能再标回未见 holdout。

六个旧 V3 关键文件匹配新研究开始前 proposal 中的 SHA；新 blocker 未改写旧学习或运行失败。58 个外部冻结源码／证据和 25 个旧输入重新逐字节核对均通过。三个 train START 只列适配四角色与 reward；三个 evaluate START 只列新 task/clean 与两观察者。保留元数据的时间顺序为训练注册、训练、108 路 seal、endpoint freeze、端点、最后的资格数据绑定与唯一统计调用。

资格数据绑定文件是在终点及媒体审计之后形成，不能被宣称为终点之前的公开注册；实际算法、候选和端点开放屏障的前瞻身份另有保留。这些检查证明记录与冻结身份相容，不是排除未记录 I/O 的操作系统级隔离证明。来源独立性限定于完整暴露登记，不保证新书写者或未知预训练独立；原始 corpus 之前已作像素哈希。[来源独立审阅](INDEPENDENT_V4_SOURCE_REVIEW.json)、[执行账本](../field_bridge_v4_20261027/evidence/V4_EXECUTION_LEDGER.json)

## 6. 完整性、费用与交付说明复核

执行账本的 710 个绑定、377,531,919 字节重新核验全部一致；按其既定排除规则，实际 run 文件没有遗漏或多余。33 个仓库 evidence 副本与实际 run 一致。训练和端点费用等于三个 seed 的原始回执逐项和；八 phase CPU 工作合计 3,509,512,073,466 ns，不把并行 wall 时间之和当作延迟。

已完成的独立媒体审计覆盖 222 个文件、340,992 个输出、681,984 个观察者效用值，重算最大误差为 0；它没有重新运行 generator。其额外真实 observer 计算为 724,992 个 digit examples，逻辑覆盖为 1,363,968 个，二者已分开计费。缓存核验不是新增独立样本。本解释审阅读取这份既有审计及其绑定，没有再次神经评分。[硬评分审计](../field_bridge_v4_20261027/evidence/INDEPENDENT_V4_ENDPOINT_HARD_SCORE_AUDIT.json)

本次已审阅 README、RESULTS、PAPER_HEPTA_COMMENTS、BLOCKERS、终态处置、执行账本及训练 comments。提出的三处措辞均已收紧：B03 没有额外 runtime 前提；未建立不写成理论或广泛能力已被否定；坐标干预不写成排除一切失配。原 B03–B07 的结论仍开放，`DENY_ALL`、`requires_calibration=true`、`native_owner_integration=false` 保持。

本解释报告形成时，包含它的完整归档尚待打包及外部恢复验证，因此本文不认证归档本身或持久保存成功。归档及 literal restore 的精确复算必须由后续外部回执报告；持久保存授权按已记录的自动审核限制独立处理。不得把工程完整性审阅通过改写成参数场科学资格通过。
