# V4 学习资格试验：一次性面板原点校正

状态：**可执行设计建议；本文件本身不构成数据开放许可或已冻结注册。** 根代理将以新 study ID、新 SOURCE_REGISTER、新协议 SHA 和新 runner 注册实施；此文不改写 V3 的 passed=false，也不调用其 audit phase。独立科学审阅已核对本设计的单一干预、源角色和 6 比较族。

## 问题与唯一干预

问题：冻结的参数场训练控制头，在跨面板时消去初态的绝对难度偏移，能否在同等 288 步预算下稳定优于预先固定的强普通训练，并优于有同样信息的 richer 控制参照？

干预仅为 [TRAINING_DIAGNOSIS.md](TRAINING_DIAGNOSIS.md) 第 5 节的 14 维原点平移。原 V3 bank、控制头权重、ridge=1、归一化器、generic 投影、Qref 标签/固定续策、四个 action、batch、48/288 步、优化器及 guard 规则均冻结。每条完整路径用本阶段合法 probe/guard 的首个 raw30 状态一次确定 observed_initial；无额外 baseline 模型调用。ordinary 仍运行完整 288 步常数策略，不缩成一块；初态测量的统一仪器开销与 ordinary 最小运行实现分别记账。

不同时改 Qref、ridge、guard 或候选家族。原始 H12 保留为机制诊断，使是否缓解旧偏移有直接参照；它不进入确认性选择。

## 方法、配对与预算

固定模型为 17、29、43。候选主协议固定新的完整 schedule ID 为 14000、14001、14002、14003；同一 ID 在所有方法间共享 batch/forward 随机表，与 V3 fit/development/audit/final 保留 ID 区分。它们仍须随新协议正式冻结后才可执行。

| 方法 | 每模型路径 | 地位 |
|---|---:|---|
| ordinary action 0、1、2、3 | 各 4 | 仅已固定 17→2、29→3、43→3 进入主比较；其他常数作机制参照 |
| raw H12 | 4 | 原实现机制参照；不参与新赢家选择 |
| origin H12 | 4 | 唯一主要干预 |
| origin richer | 4 | 新数据前固定的主要自适应比较器 |
| origin generic | 4 | 次要机制参照 |
| origin H7 | 4 | 次要机制参照 |

总计 9 方法 ×3 固定模型 ×4 日程 = **108 条完整路径**。每路径 288 梯度微步，合计 **31,104 微步**；每步 64 adaptation +32 rehearsal 样本，合计 **2,985,984 个梯度样本消费**（1,990,656 adaptation +995,328 rehearsal）。共有 **648 次决策状态测量**，其梯度/方向导数、panel forward、teacher forward、guard、endpoint、磁盘写入和 CPU/wall 分账，不能折进“31,104 步”后隐去。所有拒绝块、零动作梯度、测量与原点计算均收费；不因结果差而删路径。

新增完整数据 cohort 的冻结模型 baseline 可在授权阶段测一次并共享，但其 observer/生成开销单独统计。执行前精确可预知的是路径、微步和消费样本数量；实际 wall time、拒绝率和内存由运行记录给出，不伪造资源上界。

ordinary 主要比较器动作 2/3/3 来自公开旧 development，进入新试验即固定。richer 也在新资格结果前固定。不在新结果中从 ordinary/H7/generic/richer/rawH12 挑赢家。若未来需要“超过所有轻量参照”的主张，须在开数据前另行扩展比较族及预算；本设计只支持指定 richer 比较。

## 新源分配与信息防火墙

主资格分配只来自 V3 尚未分配的官方 train 9,000 张中的 6,352 张。新 source register 使用 pixel hash 加固定 salt 的排序，按连续区段分配角色；salt 为 hepta-field-v4-20261027-panel-origin-qualification-1。不按类别或结局分层、重抽；须验证源图像及组合 pair 不交叉并绑定原始内容身份后才可执行。建议角色如下：

| 新资格角色 | 源图像数 | 可访问的阶段 |
|---|---:|---|
| gradient | 2,000 | 优化更新 |
| rehearsal | 512 | 优化更新 |
| probe | 256 | 状态/动作，含 observed_initial |
| guard | 512 | 接受/恢复和状态，含 observed_initial |
| task | 1,024 | 完成路径后的资格终点；控制器不可见 |
| clean | 2,048 | 完成路径后的资格 clean 终点；控制器不可见 |
| 总计 | 6,352 | — |

余下未分配 train 2,648、test 3,952 全部继续封存。旧 V3 未开放的 8 个角色及其 12,496 图像保持原样；不得借用旧 audit/primary/retention 角色的名称绕过其失败门槛。资格终点的“双观察者”包括名为 audit 的第二观察者；这是新资格 cohort 的观察者输出，不是打开旧 V3 audit 数据。

source role 的图像数不等于 bootstrap 的有效独立样本数。task 1,024 图像形成 512 source-pair clusters；clean 2,048 形成 1,024 clusters。4 条路径是同一固定模型和同一源池上的随机更新日程，不是 4 个独立模型。结论仅条件于已注册的三个历史模型。

## 一次性资格门槛：原 6 个比较，不做新的 development 赢家选择

固定 4,000 次层级 paired bootstrap，候选主协议的新 bootstrap seed 为 271042；算法沿用 V3 配对结构：每个固定模型内重采样 4 条完整 schedule ID，同一组抽样作用于全部方法；源 pair 在方法/模型/条件间使用同一抽样，模型和条件等权。task 与 clean 分别使用本角色的完整 pair cluster 维度。禁止把条件、单个重复观测或 microstep 当成独立模型。

family alpha=0.05，6 个比较，各比较使用 equal-tail 两侧区间，单比较 alpha=0.05/6，NumPy quantile method=linear。双观察者都须通过；它是同一预注册主张的合取，不通过后从观察者中选择显著者。

| 比较 | 两个观察者均需满足 |
|---|---|
| ordinary−frozen：任务增益 | 校正区间下界 >0，且每个模型均值 >0 |
| origin H12−ordinary：任务增益 | 同上 |
| origin H12−origin richer：任务增益 | 同上 |
| ordinary−frozen：clean NI | 校正区间下界 >−0.01 |
| origin H12−frozen：clean NI | 同上 |
| origin richer−frozen：clean NI | 同上 |

六比较全部通过才称“该学习干预资格通过”。此筛选不给 final 主张盖章；更不关闭 runtime 或组合增益 blocker。保存全部 endpoint 数组及 paired 轨迹，失败不能仅发布有利子集。

作为研究序列的建议，若根代理注册新 epoch，第 1 次真正 final 使用总 alpha=0.025，gain /NI 各 0.0125，并保持既有 6 gain /10 NI 比较分母。它必须在任何新 final 数据开放前随整个序列预算统一冻结，不能追溯改动 V1–V3。此处不把建议值标成已经注册。

## 身份、执行合约与最小验证

完整 policy SHA 至少绑定：新 study /协议 /source register，原 V3 protocol、BANK 与 CONTROLLERS SHA，具体 selected head，helper 源码 SHA，14 索引及减法方向，fit origin 值、observed_initial 采集时点/角色/冻结规则，原 normalize/project/argmax 逻辑及 tie break。旧 base controller SHA 单独不足以区分原始和原点修正策略。

每个 decision 记录 raw30、mapped30、fit origin、observed initial、动作预测/动作、完整 policy SHA、scheduled microsteps、guard outcome、资源费用。记录/冻结 origin 的步骤不能以当前 endpoint 值回填。所有种子和方法都在同样时点测量；比较器得到同样基线信息。路径终点记录新 source identities；checkpoint 存在的 source roots 与 state 必须可回放。

已有 helper 6/6 合约测试通过；在启用科学任务前还需 runner 的无模型契约检查：拒绝旧 V3 phase 身份、拒绝未冻结/不匹配 register、108 路径完整性、方法配对、policy hash 绑定、初态一次固定、端点不反馈。只能在这些结构契约通过且新协议冻结后开始一次完整 qualification。不得为快速开跑把旧 DEVELOPMENT_SELECTION.json 的 passed 改成 true。

## 明确的反证与停止条件

- 若新源上任一主要任务比较或 clean NI 失败，**该一次资格试验失败**；停止原点干预的确认路线，保留完整负结果。
- 若原点校正使初始坐标回到 fit origin，但 H12 未通过相对普通策略/固定 richer 的预注册增益门槛，则该候选未获得资格支持，此次未证明“仅消除绝对面板偏移足以产生增量价值”。区间未过零不等于证明没有效应；只有明确负效应或精确排除预先要求的必要增益，才支持相应更强反证。不能用更漂亮的打分或回放动作替代终点。
- 若 raw H12 和 origin H12 在新完整路径上无实质差异，旧面板偏移对泛化失败的主要解释力受限；机制比较只作描述，无事后新增 p 值。
- 若 source identity、模型、冻结头、动作/预算/guard、原点或费用合约失配，记为执行无效并先修基础设施；不得把技术重启当作额外独立试验或隐藏已经消耗的评价信息。
- 不在同一资格面板换 ridge、Qref、原点索引、家族或 comparator 再试。不将日志重评分、oracle、数学合约或微步数量当作科学 pass。
- 通过也只证明此冻结小模型任务上的资格结果；大规模 LLM、通用参数场理论、Hepta runtime 以及两层组合仍需各自注册的独立实验证据。

## 独立 ordinary-only track：保留路线，不同时开放

ordinary-only 可独立问“强普通训练在新源上是否有可靠收益与 clean NI”，避免把参数场失败误报成普通训练无效。它当前是**非活动、未分配源**的独立研究选择；不因主资格失败而自动消费另一个面板。

若单独注册，它只运行已冻结 2/3/3 的普通策略：3 模型 ×4 新配对日程 = **12 路径、3,456 微步、331,776 梯度样本消费**。若沿用统一测量，另有 72 次状态测量；如移除测量须在方案与资源账中明确，而不能把成本和主试验直接等同。其收益和 clean NI 使用独立预注册的 family 与 alpha，或在主研究开数据前纳入同一联合检验家族。

本主方案一旦分配 6,352 张，未分配 train 只剩 2,648 张。之前任何假设可用 7,376 张 train 的 ordinary-only 构想不再成立。它需要不同的未用来源或显式、前瞻的角色再注册，且同一已消费资格 endpoint 不能再次作为独立确认。ordinary-only 的通过也不替代 final deployment 与 retention 的独立确认。
