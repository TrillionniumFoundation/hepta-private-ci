# 从多模态初值到动态 output portfolio

这里给出本轮实现使用的工程形式，不把金融 Merton 模型的解析结论直接移植到
生成模型。问题可以建模；一般模型的可识别性、优化收敛和实际优势仍需分别证明。

## 状态与可行动作

Encoder 将公开输入转成生成过程的初态。完整控制状态必须比 latent 更丰富：

\[
S_t=(h_t^{text},h_t^{audio},h_t^{image},h_t^{video},b_t,r_t,o_t,d_t).
\]

其中 `b_t` 是关于联合目标与共享噪声原因的 belief，`r_t` 是预算/耗时/剩余
资源，`o_t` 是 owner/checkpoint/准入状态，`d_t` 记录已交付结果、不可逆成本
和已消费的事件身份。缺少这些状态时，一个只预测 token 质量的 value head
无法预测实际终局收益。

Portfolio action 指资源与生成行为的组合：哪些模态继续生成、每条路径多少
步、是否共享状态/重新观察/校验/修复、何时交付或停止。资源约束可以是非负
配额和总预算，但文字、音频、图片不是可以直接线性相加的金融资产。动作的
质量、成本和相关尾部由整个联合生成过程决定。

有限实现写成 `S_next = F_theta(S, action, event)`。连续时间版本可引入扩散
和交付/拒绝跳跃，但新增随机过程假设不能由离散试验自动证明。

## 联合 belief 与事件身份

目标 prior `p(Y | public task)` 与观察 likelihood `p(E | Y, shared cause)`
是两个对象。相同物理事件的两个视图不能再作为两个独立因子；只有实际不同
的事件才能在声明的条件独立结构下相乘。存在说话人、设备或共享噪声等共同
原因时，应显式边缘化其 joint likelihood，而不是仅给各模态分数再加权。

`evidence/` 实现同边际的联合 likelihood 与单独 target prior，并验证真实
音频 alias；`control/` 在 state transition 层实现已注册 event ID 的持久化
消费。两层身份处理作用不同。后者不能识别被外部重新赋予新合法 ID 的同一
物理事件，这个能力仍需要上游事件归属机制。

## 明确一个可执行的 NDU，而不是只有名称

本轮使用有限时域、固定风险参数的 entropic certainty equivalent。假设任务
最终质量为 `R_T`，每步实际成本为 `c_t`，则目标为

\[
\sup_{\pi\in\Pi_{admissible}}-
\frac1\gamma\log\mathbb E^\pi
\exp\left[-\gamma\left(R_T-\sum_t c_t\right)\right].
\]

只使用当前可得信息的 admissible policy 必须满足 owner 准入与资源约束。
在给定完整 Markov belief 状态、已知转移和固定 `gamma` 的有限模型中，等价
moment recursion 为

\[
M_T(s)=e^{-\gamma R_T(s)},\qquad
M_t(s)=\min_{a\in A_t(s)}
\mathbb E[e^{\gamma c_t(s,a,S')}M_{t+1}(S')\mid s,a].
\]

不能先平均终局损失，再对均值取指数。若研究选择一般非线性动态效用、随机
风险偏好或 BSDE driver，还必须声明其 filtration、可积性、时间一致性和
backward equation；本轮代码并未求解这种一般问题。

实际部署通常只能使用有限搜索或 learned critic。此时必须分别标注：完整
枚举最优、有限候选最优、固定 continuation policy 的预测、以及函数近似的
估计值。`control/` 证明的是已知有限法则下完整实际策略的预测一致性；
`joint/` 是四个部署计划的条件 moment 回归与贪心选择。

## 训练路径与本轮失败给出的修正

最初可把训练分成基础生成/保留能力、联合 observation 模型、终局 moment
critic、动作策略和生成器更新。正式比较时必须给两种算法相同信息和计算
预算，并保留实际 codec、交付、观察器、备份和校验成本。

本轮的 controller 学习真实 PNG/UTF-8 输出的 `exp(-gamma U)`，将训练选择
与部署 argmax 对齐。生成器仍以监督损失作 proxy，仅用实际风险权重重新
加权。实验表明这个 risk-weighted proxy 比 uniform proxy 差，因此不应
将它默认为正式训练目标。

下一步可以检验真实轨迹 score-function/policy gradient，或对可微部分使用
路径导数、对离散输出使用显式估计器；critic 的条件 moment 与实际交付校准
必须单独检验。使用 surrogate 或 straight-through 时要量化偏差。每次更新
会改变下一步的输出分布，controller、observation 模型和 generator 应有
版本绑定与冻结评估，避免拿过期 likelihood 评价已改变的输出过程。

这些是待验证的实现方向。现有数字结果不能证明某一种新梯度必然改善，也
不能通过在本轮测试集上改权重后再称其为新资格结果。

## 当前各模块是否已连接

| 接口 | 已有执行证据 | 尚未建立 |
| --- | --- | --- |
| 原始观察 → 联合 belief | 真实 WAV、共享边际、目标 prior、alias 单次更新 | 自然全模态共享原因的稳定泛化 |
| 状态 → 备份 → 真执行 | 原 owner/journal/witness、同 continuation、预算与拒绝 | 生产 daemon 与语义准入；未知法则校准 |
| 实际交付 → neuron → 后续动作 | 原 eligibility、零 drive hold、实际 repair、外部成本收益 | 对同信息 history 的优势；自然任务语义收益 |
| Encoder/transition/decoder 联合更新 | 原图文生成器真实参数变化、新输出收益、保留能力、旧 oracle 上界 | 风险 proxy 优势；原 owner 在该生成网络中的端到端作用 |
| 自然模态输出与调度 | 自然 ASR、文档回答和真实缺帧像素重建 | 自然语音/视频语义生成；稳定的质量成本优势 |

因此，合理的下一步是把已验证接口接到同一自然任务，并保留强固定策略、
同信息 history、uniform generator update 与零反馈等对照。直接扩大模型
规模无法替代这些接口和目标的因果、统计及成本检验。
