# A Parameter Field Theory of LLMs 与 Hepta neuron：V4 完成后的 comments

**截至这轮实际证据，普通参数训练有可验证收益；参数场指导的训练增量和 Hepta 状态控制的专属增量仍未建立。** V4 完成了前瞻登记、108 条训练路径、全部端点、独立训练/媒体核验和唯一六项资格判定。4/6 项通过，但两项参数场增量均失败，因此停止本候选后续 final/runtime。六项资格检查不能写成最初六类实验已通过四类。

本文沿用已审查的论文 R45 快照 [f8df0a6](https://github.com/TrillionniumFoundation/ICLR-2027/tree/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45)，不声称它是当前最新版本或已被会议接收。主要理论对应 [r45_main.tex](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex) 和 [r45_recursive_detail.tex](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_recursive_detail.tex)。历史论证与实现边界见 [V3 comments](../field_bridge_v3_20261027/PAPER_HEPTA_COMMENTS.md)。

## 1. 两层关系应以可检验问题来定义

参数场侧讨论参数/优化器演化、状态投影与训练决策；Hepta neuron 侧在运行期间维护反馈状态，并据此选择后续合法动作。它们可以组成分层系统：训练改变模型，运行控制改变同一模型的使用方式。共同使用“状态”和“控制”的语言，并不能自动证明两者是同一个动力系统或已经共同实现论文的最优控制结论。

应分别回答：在相同部署策略下，参数场能否比普通训练带来更多价值；在相同模型下，运行状态控制能否比强固定策略改善输出；在相同公开历史和相同预算下，Hepta 表示是否优于直接历史或轻量控制；最后，两层结合是否通过自己的独立联合比较。一个层面的可运行性或正效应不能补足另一层失败的增量。

| 用户提出的实验族 | 当前证据与判断 |
|---|---|
| 固定模型＋强固定策略 | 作为冻结参照持续保留；训练倍率选择与部署动作严格区分。V4 沿用固定部署下的普通训练比较。 |
| 常规局部训练＋同一部署策略 | V4 ordinary−frozen 的 reward/audit 净效用差值 +0.021425/+0.022656，校正区间均正；本轮 qualification clean NI 同时通过。原始 final 联合验收不由此替代。 |
| 参数场训练＋同一部署策略 | V4 origin_field−ordinary 为 +0.000160/+0.001286；两区间都跨 0，逐模型严格正向条件也失败。增量未建立。 |
| 固定训练＋Hepta 状态控制 | V3 native−fixed 仅 reward 条件通过，audit 未通过；本轮旧数据诊断和固定 honest-stage pilot 没有产生新的确认性 runtime 结果。 |
| 参数场训练＋Hepta 状态控制 | 原 V2 联合主要条件 0/6 仍是历史结果。V3、V4 前置门槛失败后没有开放新的 final 联合比较，不能把未执行写成零效应。 |
| 相同信息的历史／轻量控制 | V3 native−history 未建立双观察者增量；V4 field−richer 同样未通过。复杂度和状态敏感性不能替代这些比较。 |

来源：[V4 结果](RESULTS.md)、[V3 blocker 账本](../field_bridge_v3_20261027_review/BLOCKERS.json)、[V4 runtime diagnosis](../field_bridge_v4_20261027_review/RUNTIME_DIAGNOSIS.json)。

## 2. V4 检验了一种具体坐标修正，但没有证明参数场增益

V3 旧数据诊断显示，冻结 readout 的损失/效用坐标会随来源面板改变原点。V4 因此只预先加入 14 坐标的初始平移，保留旧 heads、normalizers、ridge、训练动作、完整 SGD 事务和 raw clean guard。首次合法 probe/guard 测量被复用；终点评分没有进入校准。所有 adaptive 参照获得相同的信息。

这个干预在实际闭环训练中确实发生作用：origin/raw 决策不同 47/72 次，最终参数不同 8/12 条路径。模型 43 的 origin_field 轨迹最大 H12 fit-scale 偏移从 19.1515 降至 4.6562；这只是相对冻结归一化器的坐标距离，不是显著性统计量。模型 29 的 origin_field 与强 ordinary 四条日程最终参数和优化器完全相同，正式增量因此为 0。

尤其不能用 guard 接受率替代有效训练：origin_field 接受 60/72 块，其中 19 块是零动作；实际接受的非零块为 41，raw_field 为 46，强 ordinary 为 47。决策变化、接受次数、模型变化与独立终点收益是不同量。源码和完整轨迹足以证明策略执行了，却无法把失败的增量门槛改判为成功。

| 正式增益比较 | reward：均值 [99.1667% 区间] | audit：均值 [99.1667% 区间] |
|---|---:|---:|
| ordinary−frozen | +0.021425 [+0.014677, +0.029479] | +0.022656 [+0.015530, +0.030905] |
| origin_field−ordinary | +0.000160 [−0.003410, +0.004172] | +0.001286 [−0.001775, +0.004138] |
| origin_field−origin_richer | +0.000095 [−0.002693, +0.003111] | −0.000409 [−0.003482, +0.003094] |

三个 clean 非劣效检查都通过 −0.01 界限，但它们不补偿增益失败。模型 29 的 0 差值不满足“每个固定模型严格正向”。不能由区间跨 0 得出等价，也不能据此否定整套理论。V3 与 V4 使用不同新来源面板，不应把跨研究均值变化归因于原点平移；本轮 raw/origin 轨迹比较只作为登记的机制描述，不提升为新的正式成功条件。

来源：[实际机制](evidence/mechanism/MECHANISM.md)、[完整机制身份](evidence/mechanism/MECHANISM.json)、[原始六项统计](evidence/QUALIFICATION.json)、[独立训练审计](evidence/INDEPENDENT_V4_TRAINING_AUDIT.json)。

## 3. 对论文实现主张的具体 comments

**状态预测能力与决策增量应分开报告。** 一个小向量能预测局部续策值，不意味着它保留所有与未来控制相关的信息。V4 的策略除了 H12 readout，还依赖 14 个冻结校准值、已拟合头、训练阶段与可行动作等上下文。不能将实现写成无需上下文的 12 维 Markov 充分状态。若要援引更强的状态闭合结论，需要显式给出状态映射、策略类、条件转移/价值假设以及实现中的投影、信息、执行与系数误差边界。

**Q_ref 的训练目标要与部署时的后续策略区分。** 当前冻结头对应固定参考续策的价值。部署阶段多次重新选择动作后，未来续策已经改变；固定参考续策价值并不自动成为当前自适应策略的价值，更不是最优 Q。V4 原点校准只处理坐标起点，并没有解决续策目标与闭环分布匹配。HJB、Riccati 或 FBSDE 的形式联系，仍须由实际满足的假设和误差界支持。

**需要把坐标稳定性与任务收益都作为独立证据。** 本轮看到原点修正能改变动作、降低某些坐标偏移，却未通过相对强基线的增量。由此可写的结论是“该坐标修正在这套冻结控制器中改变了决策”，不能写成“参数场已经提升学习效率”。对未来候选，续策目标、控制敏感状态与 guard 事务的关系值得研究；这些是未检验解释，不能反向改写本轮协议。

**复杂表示的优势必须超过同信息参照。** 若 Hepta 状态只是公开历史的确定性变换，其潜在优势应来自更好的归纳偏置、压缩、优化或计算代价，而不是凭空增加信息。在相同历史、标签、行动与调参机会下比较，才能估计这种实现优势。V4 让所有 adaptive 控制获得同一原点信息，保留 richer、generic、H7 参照；只有预先指定的 richer 比较参与正式门槛。

## 4. 对 Hepta runtime 的具体 comments

旧 runtime 诊断已经排除“native 状态根本没执行”的简单解释。固定 readout 使用的额外 native 坐标有活动与秩，替换为训练均值会改变许多选择；native/history 的完整动作路径也并非总相同。这证明状态有计算作用，不证明它在外部输出上有净收益。

V3 的双观察者 native 增益条件仍失败。对旧已公开数据进行的固定 honest-stage pilot 也不支持直接推进：history/native 各三个模型相对旧方法的 audit 效用六项都为负。该试点没有读取新 runtime holdout，不能用作新的确认性结果，也没有挑选其中某种方法去替换正式候选。

reward 与 audit 的收益差异提示结果依赖评分视角。现有分解能定位 image-fact 和跨模态一致性项的贡献，却不能据此判定哪个观察者代表真值，更不能直接指控 reward hacking。后续如果研究真实外部反馈，必须另外登记反馈何时到达、控制何时作出、可用信息和完整续行成本。

两层结合的可重复增益与“超加性”也是不同主张。要断言交互收益，需要预先定义诸如 `(E−C)−(D−A)` 的交互估计、共享对照和不确定性；当前六类问题以及 V4 资格检查没有自动检验这一更强命题。

来源：[RUNTIME_DIAGNOSIS.json](../field_bridge_v4_20261027_review/RUNTIME_DIAGNOSIS.json)、[受限的后续 runtime 设计说明](../field_bridge_v4_20261027_review/RUNTIME_NEXT_PROTOCOL.md)、[V3 原门槛与结果](../field_bridge_v3_20261027_review/BLOCKERS.json)。

## 5. 此次哪些工作真正完成，哪些结论仍开放

已完成前瞻注册、新来源排除、训练/端点屏障、108 路完整执行、所有 checkpoint/优化器事务核验、逐输出两观察者精确重算、唯一资格判定及机制诊断。340,992 个输出、681,984 个观察者效用值的最大重算误差为 0。原始证据归档与从 literal restore 重复相同六项算术的结果，以事后外部归档回执为准。

原 B03–B07 的最终科学验收尚未满足；本轮普通训练收益和 qualification clean NI 是正证据，但不替换原 final 条件。B09 的新来源与访问边界可核验，历史共享面板限制仍保留。B10 的完整原始归档持久保存还需要明确命名文件和 ChatGPT Library 目的地的授权：自动审核已经拦截，不能通过换出口、重复尝试或把 raw 包塞进 Git 来绕过。

LLM 规模、长时程外部反馈、理论充分性和生产 owner 接入都是另外的主张边界。当前 `DENY_ALL`、`requires_calibration=true`、`native_owner_integration=false` 不变。工程闭环让失败可信、可解释、可复算；它本身不构成参数场或 Hepta 的科学胜出。

逐项原始条件、历史结果与本轮更新见 [BLOCKERS.json](../field_bridge_v4_20261027_review/BLOCKERS.json)；实际执行、额外验证和成本边界见 [V4_EXECUTION_LEDGER.json](evidence/V4_EXECUTION_LEDGER.json)。
