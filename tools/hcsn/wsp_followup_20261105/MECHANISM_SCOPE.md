# 从解析算子到可验收的权重修改

本文件区分已核对的模型语义、由数学结构推导的可编辑子问题，以及仍缺少实际证据的修复。它不是本轮实验结果表；执行结果由各冻结协议及其收据决定。

## 一、先绑定事件、状态和实际参数

本轮沿用的公开五模型源是
[joint 研究的固定提交](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/5b69a046d886cf4c2a73c50e58197360ea15d8f5)。
执行语义来自后续冻结包中的
[joint_deploy.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2d0120e208ed81515837a7530c9f6943af03e87f/tools/hcsn/wsp_20261104/joint/joint_deploy.py)、
[joint_task.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2d0120e208ed81515837a7530c9f6943af03e87f/tools/hcsn/wsp_20261104/joint/joint_task.py) 和
[joint_law.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/2d0120e208ed81515837a7530c9f6943af03e87f/tools/hcsn/wsp_20261104/joint/joint_law.py)。

| 部位 | 已核对的实际含义 | 本轮可定位或可修改的范围 | 不能据此认定的结论 |
| --- | --- | --- | --- |
| 状态表示 | 43 维公共状态、33 维条件质量、9 维预测 bank，经过 48 维 tanh 隐层 | 冻结完整表示，枚举合法状态，检查同一 Markov 状态的不同沉没费用表示 | 未证明 48 维特征足够表示任意最优策略，也未证明原始状态缺失了信息 |
| First-Passage / Reset | 该任务目标是固定第 6 时点的正负号；renewal CTMC 有边界恢复与重置分布；REPAIR 动作只修复传感器 | 使用 checkpoint 已存储的转移表，保留其重置语义；不重新生成名义 law | 没有把第 6 时点事件当成首次越界；没有把传感器 REPAIR 当成潜变量 Reset 权重修复 |
| Call / Put 双通道 | 当前 decoder 是互斥且穷尽的二分类终止收益；没有独立金融 Call/Put 参数块 | 检查 STOP 与两个 SUBMIT 分数由同一个 Belief 决定的结构一致性 | 不能用二分类互补约束替代首次越界的存活质量，也不能据此宣布金融期权通道已修复 |
| Belief | 第四输出是 logit；已有 bank[7] 是该模型自身的 deadline-six 正号概率 | 修改 49 个头参数，或单列解析 posterior 结构对照 | 更准确复制自身 posterior 不等于更接近真实环境 posterior |
| Continuation Q | 前三输出是 WAIT / READ / REPAIR 的未来净价值 | 用自身完整 Bellman 目标拟合 147 个头参数，单独检验排序、边际和任务轨迹 | Q-MSE 更低不保证选到更有价值的动作 |
| NDU 价值控制 | 有限期限内的期望终止收益减去读数、延迟和修复费用 | 以完整策略轨迹评价结构策略及编译头；按真实 incumbent 决定接受或恢复 | 未给实际 CPU 赋货币价格，未证明总经济净值、能耗或真实交易收益改善 |

上述研究模型与 pocket4 的 encoder / RowLoRA / value-readout 是不同产物。没有逐张量映射证据时，不向实际 Trader 权重强行赋予同名语义。

## 二、哪些约束可以成为编译器的硬条件

下面是从声明模型推导的设计条件，不是已经在所有 Hepta 模型上执行的证明。

### 1. 状态、时间与观测完成顺序

行向量条件质量的预测与更新可以写为

\[
\tilde m_{t+1}=m_tP_t,\qquad
m_{t+1}=\frac{\tilde m_{t+1}\odot e_{t+1}(y)}
{\tilde m_{t+1}e_{t+1}(y)}.
\]

矩阵的状态顺序、行列约定、时长单位、公开 drive、观测完成时点和 emission 必须一并绑定。更新分母为零表示该 law 下不可能的观测；不应由编辑器偷偷改成均匀分布。当前研究只允许已存储的 `(duration, drive)` 转移表，未知键应拒绝。

`mass33` 不是通用的完整决策状态。剩余期限、读数预算、设备故障、未完成请求、日程和动作合法性也影响 continuation value。另一方面，纯加性的历史沉没费用不影响未来最优动作，但进入神经特征时仍可能改变头输出。因此本轮训练状态枚举保留完整费用状态；Bellman 的未来价值缓存可以在已证明费用只作差的前提下合并这些状态。两种键不能互换。

### 2. 首次越界、存活与重置不是同一个事件

对于只有上下两个吸收边界的有限期限 first-exit 模型，正确的质量守恒关系是

\[
F_+(t)+F_-(t)+S(t)=1,
\]

其中 `S` 是尚未吸收的存活概率。一般不能强制 `F_+ + F_- = 1`。若改为固定时点的穷尽二分类，则相应两个概率之和才是 1。

若边界还会恢复并重置到内部状态，时点边界占据概率、首次到达概率和累计到达次数又是三个不同量。当前 renewal law 的边界行包含恢复率与重置分布，所以其完整转移矩阵的时点质量不能直接当作首次到达 CDF。重置算子或辅助首次通过状态需要在事件 schema 内显式表示；一个通用的“Call/Put 互补”补丁无法纠正这种语义错误。

### 3. 终止一致性已经由执行图保证

当前公开任务的 decoder 已经执行

\[
p=\sigma(o_3),\quad
Q_{\mathrm{STOP}}=0,\quad
Q_{\mathrm{SUBMIT0}}=1-2p,\quad
Q_{\mathrm{SUBMIT1}}=2p-1.
\]

因此本轮不能把重新检查这三条恒等式当成新修复。真实缺口可能是 `p` 本身、future-value 目标，或现有隐藏特征无法保持决策边际。Rust guard 的 terminal constraint 是可执行断言；它在供应行上的通过不证明其他状态上的概率校准。

### 4. Bellman 目标必须带完整未来路径和费用

对声明的有限模型，目标为

\[
Q(s,a)=\sum_{s'}P(s'\mid s,a)
\left[V(s')-\bigl(c(s')-c(s)\bigr)\right],
\quad V(s)=\max_{a\in\mathcal A(s)}Q(s,a),
\]

终止动作使用前述 reward。失败分支、完成观测的两个分支、不可行动作、剩余预算、修复和延迟都必须进入递归。不能仅在一次前向上改变 argmax，就声称改善了整个任务。

原公开任务已经有这个递归。新研究增量是把它的 law 绑定到实际 checkpoint 自己的表，再把完整策略与同一固定神经头的编译进行对照；不是新发明 Bellman 算法。真环境 law 只用于评价，不进入候选策略和训练目标。

## 三、为什么选择受约束的直接头编译

在固定特征 `H`、目标 `Y` 和非负样本权重下，每组头参数的编辑可以写为

\[
\min_{\Delta}\;\sum_j\|D_j^{1/2}(H(\theta_{0j}+\Delta_j)-Y_j)\|_2^2
+\lambda\|\Delta\|_F^2,
\qquad \|\Delta\|_F\le r.
\]

该子问题是凸的。输出有不同样本权重时，各 Hessian block 不同，但同一组半径对应同一个拉格朗日乘子。直接求解与 projected gradient 应使用同一起点、目标、半径和独立的数值停止门；不能用直接解作梯度停止 oracle，然后宣称公平。

这里的直接求解没有梯度迭代，但仍使用目标、数据、特征构造和线性代数。将解析 teacher 编译到网络属于程序监督的蒸馏。它不是零数据学习，也不是从任意权重中直接读出完整电路。

对 Rust 的实际 F32 写入，F64 求解器的可行性不够。参数量化可能穿过边界。本轮原生实现因而将“F64 凸解的数值诊断”和“实际 F32 改变量的精确范数判定”分开；后者的整数算术契约见 [NUMERIC_CONTRACT.md](native/NUMERIC_CONTRACT.md)。写入后的行为仍需真正执行 forward 并验收。

## 四、能减少哪些无效计算

合理的停止条件应先于下一轮训练：

1. 若事件 schema、状态顺序或观测时点不匹配，先修正表示和执行契约；额外训练不能使两个不同事件成为同一个目标。
2. 若某个失败排序的两个动作都由冻结 Belief 决定，continuation-only 编辑对该排序没有控制权，应拒绝无关参数搜索。
3. 若固定特征和预算类已有严格容量下界，不再把同类 SGD 轮次增加当成突破该界的办法。改变特征、预算或模型类必须是新协议。
4. 若完整自身 Bellman 策略有效而神经编译无效，应分别检查表示误差、目标缩放、动作边际和量化；不能把 teacher 的价值增益记到学生权重上。
5. 若二者均无效，应保留未知环境 law、decoder 偏差和任务定义的可能性。局部算子正确不是全局真实目标正确的证据。

这些是依据当前数学结构制定的诊断路径。是否节省端到端成本，仍需连同 Agent、数据获取、目标生成、失败编辑、验收和恢复一起计量。当前工作不提供完整能源或货币成本结论。
