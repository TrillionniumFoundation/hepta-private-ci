# 解析 Belief 旁路的只读源码依据

本论证在新消融结果产生前写入。源固定于公开 hepta-private-ci commit `5b69a046d886cf4c2a73c50e58197360ea15d8f5` 的 joint 交付；实际模型身份见 `SEMANTICS_BEFORE_RUN.json`。本次是执行图结构消融，新增权重修改数为零，不是纯 Weight-Space Programming 成功证明。

## bank[7] 与终止事件对应

`joint_task.py` 的 schema 为 `joint-current-at-due-fixed-deadline-v1`。`validate_public` 强制 deadline=target_tick=6。提前提交也预测固定第6步的隐状态正类；`Oracle.posterior()` 将当前条件 mass 传播至第6步，然后对 `law.positive` 求和。`joint_law.py` 定义 positive 为归一化 coordinate>0，零点归class0，上refractory归class1。

`joint_deploy.py::NumpyPolicy.represent` 对 renewal 从公开初始质量出发，按每段实际公开duration/drive使用checkpoint的`core.tables`传播。所有已完成history在`observation_tick`用当次reliability及checkpoint的confusion更新，最后归一化。它不读取teacher posterior。READ是current-at-due；不能套用旧静态标签/source-time posterior。

33维质量包含31个active状态及lower/upper两个refractory状态。若当前质量为m_t、模型转移为P_i、e_+表示coordinate>0，则模型自己的终止概率为：

`p_model = m_t P_t ... P_5 e_+`。

模型forecast bank按三组horizon排列：min(t+1,6)、min(t+2,6)、6；每组依次为严格阈值−.5、0、.5。因此zero-based `bank[7]` 是deadline6正类概率。在85维原输入`public43 + mass33 + bank9`中，它等于`raw[83]`。t=5/6时horizon重复不改变这一索引的语义。

`joint_model.py::Policy.representation/forward_row/export` 的训练路径、NumPy部署路径和导出bank_semantics一致。五个实际checkpoint的target、bank_semantics、33状态、最后两个coordinate−1/+1、85→48→4维度已在不运行forward的只读预检中确认。

## 此消融改变什么

保留现有head的三个continuation输出，只将用于终止决策的概率改为模型bank[7]，相应submit scores为`1-2p`与`2p-1`。不计算解析logit，因此p=0或1也有定义。不注入Oracle质量、真实law转移或teacher posterior。

A与P使用相同原始checkpoint；C与CP使用相同旧冻结continuation checkpoint。C相对A的历史修改不是本轮新增修改。本轮不更新任何weight、transition table、decoder confusion、物理raw或head。旁路是显式执行图分支；不能冒充一次49参数Belief权重编辑。

旧learned Belief仍使用原`NumpyPolicy.sigmoid`，其既有`np.clip(logit,-700,700)`保持不变。新projection不做裁剪：bank[7]必须有限且严格属于闭区间[0,1]，否则整个运行失败。每个新feature状态另用同一checkpoint的mass与剩余转移表直接传播，核对其deadline6正类概率与bank[7]，容差2e−12。该核对也不使用teacher law。

## 能证明的范围

若初始分布、转移矩阵、emission/confusion和观测时点全部与Oracle给定模型一致，滤波递推归纳保证model mass=Oracle mass，继而bank[7]=Oracle.posterior。当前实际checkpoint使用自己的学习后转移表；不能无条件把model posterior当作真实或Oracle posterior。原learned Belief可能补偿core错设，旁路是否改善Brier或utility必须实测。

只给mass33而不给tick和剩余日程，通常不足以确定deadline概率；当前public43与bank已包含所需公开量。已知有限CTMC中两个refractory状态与指数恢复足以描述该模型的reset；若任务变为非指数恢复、恢复年龄、累计reset次数或自episode开始曾触及某边界，可能需要额外age/计数/事件状态。

终止p正确也不自动给出WAIT/READ/REPAIR的Bellman值：这些动作还依赖预算、pending完成时点、broken状态、未来信息价值、失败与费用。原public43确实包含这些资源和日程量，head却没有硬编码Bellman关系。任务REPAIR修复传感器broken状态；CTMC边界reset/recovery是另一套隐状态动力学。

本任务的正/负deadline分类穷尽状态，两submit reward因此相反。它们不能直接等同于一般First-Passage Call/Put，后者可保留survival residual及历史事件语义。

物理raw参数的可识别性与状态充分性也不同：`joint_law.generator`通过扩散/边界、漂移/边界、reset位置/边界、reset宽度/边界等比值和recovery构造归一化law，部分物理尺度可以不唯一，而对应转移和模型后验仍可唯一确定。部署读取`core.tables`；仅改未被读取的raw而不更新表不会改变部署输出。

## 源码定位

- `joint_task.py`: `validate_public`, `successor`, `Oracle._uncached_mass`, `future_mass`, `posterior`, `q`, `evaluate_terminal`。
- `joint_deploy.py`: `THRESHOLDS`, `NumpyPolicy.represent`, `predict`。
- `joint_model.py`: `Policy.representation`, `forward_row`, `export`。
- `joint_law.py`: `IndependentLaw.generator`, `emission`, `positive`定义。
- `legacy_task.py`: `public_features`字段；joint仅复用此特征函数。
- `joint_train.py`: posterior BCE、mass KL、bank MSE与Q loss，均非解析一致性硬约束。

本文件是执行前的源码论证，不是新模型效力结果；旁路的结构一致性与任务价值资格分开报告。
