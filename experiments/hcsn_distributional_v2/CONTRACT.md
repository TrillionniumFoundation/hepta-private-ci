# HCSN v2：金融启发、内部值、最优控制与任务价值的统一合同

本文件统一术语与接口，不新增模型、不修改已登记运行，也不宣布尚未完成的内容实验胜负。正文中的“最优”“未来收益”“发放”“复位”和“不应期”必须带上所属问题，不能只凭相同字母相互替换。

对应实现为 [model.py](model.py)、[distribution_kernel.py](distribution_kernel.py)、独立 [grid_control_reference.py](grid_control_reference.py) 与 [task_value.py](task_value.py)。数学细节和已完成证据分别见 [MATH.md](MATH.md)、[有限控制参考报告](results/grid_control_validation001/REPORT.md)、[TASK_VALUE.md](TASK_VALUE.md)。

## 1. 四层语义总表

| 层次 | 状态与输出 | 收益单位 | “最优”的有效范围 | 未来收益与发放语义 |
| --- | --- | --- | --- | --- |
| 原始 Call/Put 金融启发 | 用户设想将 equity/restoring 与 debt/run 两个通道用于神经动力学；原论文实际对象是资产价值 \(V\)、股权 \(E(V)\)、债券 \(d(V,\tau;V_B)\) 与违约边界 \(V_B\) | 金融现金流现值；不能直接解释成力或分类奖励 | 原论文的内生违约问题及其假设 | 原金融违约含清算；神经复位和不应期是本项目另外定义的过程 |
| 内容模型的内部 finite-distribution \(J^\pi,G^\pi\) | 每个物理通道有 \(n+m=10\) 个概率状态；值向量为 \([10]\)，概率投影后每通道一个实数 | 内部归一化发放收益 \(x-K\) 的贴现现值 | 精确评估所声明有限生成器及其自然上边界发放策略 \(\pi\)，不声称该策略在更大动作类中最优 | \(J^\pi\) 包含反复发放；\(G^\pi\) 的合法即时发放包含随后 Erlang 阶段和再次释放后的 \(J^\pi\)。输出发放量是期望次数 |
| 独立有限网格 QVI 最优 \(V^\star\) | 单个标量物理问题，值 \([n+m]\)、active FIRE mask \([n]\)；同时返回匹配的受控生成器 | 与内部物理奖励相同的单位 | 固定网格、外边界、复位分布和 Erlang 规律下，允许各活动格点立即 FIRE 的有限动作类 | 合法 FIRE 后进入 phase zero，未来按同一最优策略；Boolean mask 是策略选择，传播输出仍可为多次发放的期望 |
| 任务层 \(C^{task},G^{task},J^{task}\) | 当前前缀 \(k\)、观测状态 \(z\)、期限 \(h\)、剩余任务数 \(m_q\)、READ 价格 \(c_{\rm read}\)；每个动作值为标量 | 真实分类正确性减实际 READ 价格的期望效用 | 二元充分统计量模型可精确；MNIST 四置信度状态仅为 TRAIN 拟合的粗化 Markov 模型 | FIRE 对真实标签评分并实际 STOP；两次 quiet tick 后重新开始后续任务。\(G^{task}\) 包含这些后续任务的价值 |

为避免重名，本文使用 \(J^\pi,G^\pi\) 指内部策略值，\(V^\star\) 指有限控制最优值，带上标 \(task\) 的量指分类任务值。代码保留其原有字段名；不能仅凭字段名 `continuation` 或字母 \(G\) 推断所属语义。

## 2. He–Xiong 原模型与 Call/Put 标签

依据 He–Xiong, *Rollover Risk and Credit Risk* 的[作者官方 PDF](https://www.princeton.edu/~wxiong/papers/rollover.pdf)，模型联合确定债务、股权价值和内生违约：展期损失进入股权现金流，违约时债权人取得清算回收。债券不是直接命名为 Put 的对象，违约也未定义自动神经再生。原文 Section II 的条件包括

\[
E(V_B)=0,\qquad E'(V_B)=0,\qquad
d(V_B,\tau;V_B)=\frac{\alpha V_B}{m_{\rm debt}}.
\]

前两项分别是股权的价值匹配与平滑粘贴；最后一项是债券的违约回收边界条件，见原文式 (6)、(11) 及其后边界讨论。同一来源的这组金融条件不等于本项目的神经复位合同。

因此，“Call 通道”“Put 通道”“恢复力”“恐慌力”在原始提案中是设计启发。本实现的正式输出名是策略值、干预值、分布质量、内容状态和任务动作值。把一个价值映射成状态更新，还需要明确参数化的动力学；当前代码使用这些值作为门控输入，并未实现“股权价值直接等于恢复力”或“债务价格直接等于再生力”的等式。

方向也须区分：金融 \(V_B\) 是资产下降触发违约的边界；内部 \(b\) 是压力向上到达的发放边界。二者没有自动的数值同一性。用户提出的 \(V-V_b\) 也不等于代码中的 `margin`；后者是活动概率加权的 \(b-x\)，定义见下文。

## 3. 内部有限分布过程：实际发放、复位与奖励

### 3.1 状态、时间与单位

对每个物理通道，活动区间 \([L,b)\) 划分为 \(n=8\) 格，\(L=-2\)；另有 \(m_\phi=2\) 个 Erlang 不应期阶段。令

\[
p=(p_0,\ldots,p_{n-1},z_0,\ldots,z_{m_\phi-1}),\qquad
p\geq0,\quad \sum p=1.
\]

活动质量按各格内均匀密度解释；阶段质量记录已经进入不应期的分布。完整概率向量跨观察保留，均值只是可输出的特征。默认模型不会把所有质量闭合成一个压力均值；`active_mean_collapse_free_dual` 是另外声明的信息丢失消融，并仍保留每个不应期阶段。

代码采用归一化内部状态与时间单位。若给它们标上量纲，\(x,b,L,x_r,K\) 使用状态/单次发放效用单位，漂移 \(\mu\) 是状态/物理时间，噪声 \(\sigma\) 是状态/物理时间平方根，贴现 \(\rho\) 是物理时间的倒数，\(\tau_\phi\) 是物理时间。单次奖励系数为一，故 \(x-K\) 与相应值函数共用内部效用单位；它们不是美元或分类正确率。代码键 `r` 在这里表示复位位置 \(x_r\)，不要与金融无风险利率混淆。

输入观察间隔为 `dt`；物理推进使用 \(\Delta t_{\rm phys}=0.1\,dt\)。外层 `elapsed` 累加原始输入间隔，内容递推也使用原始 `dt`。这两个时间尺度均不同于任务 owner 的 READ/quiet 整数时钟。

### 3.2 发放和重复再生

自然上边界退出进入 phase zero。每个阶段速率为

\[
\nu=\frac{m_\phi}{\tau_\phi};
\qquad
E[T_{\rm refractory}]=\tau_\phi,\quad
\operatorname{Var}(T_{\rm refractory})=\frac{\tau_\phi^2}{m_\phi}.
\]

最后一个阶段按中心线性插值权重 \(w_i(x_r)\) 释放到活动网格。\(m_\phi=2\) 是声明的随机 Erlang 时长，不是确定延迟。新观察不会把已有阶段质量重启到 phase zero。复位位置和阶段平均时长在一个 episode 内固定，训练更新它们后影响下一次完整 rollout。

令 \(Q\) 为列概率的前向生成器，\(A=Q^T\) 为后向生成器；列概率满足 \(\dot p_{\rm col}=Qp_{\rm col}\)，本文的行概率满足

\[
p(t)=p(0)e^{At},\qquad
E[N_{[0,t]}]=\int_0^t p(s)\lambda\,ds .
\]

\(\lambda\) 为自然发放强度向量。有限区间内可经历多次发放、阶段推进和释放，所以 `events/activity` 是实数期望次数，可超过一；它不是 Boolean spike，也不是“至少发放一次”的概率。

内部每次发放奖励为实际发放位置的 \(x-K\)。固定边界自然退出时是 \(b-K\)。边界突然下降覆盖旧活动质量时，该质量立即发放，奖励按旧物理位置积分，不能一律改成新边界 \(b_{\rm new}-K\)。零时长会禁止后续正时间传播，但不会抹掉初始越界或边界下降的即时事件。扩大边界不会拉伸旧压力坐标；它增加空的物理空间。

这些变化都作用于物理概率状态。内部发放**不自动清零 32 维内容状态**。即使部分或全部物理质量处于不应期，内容递推仍按其门控公式更新；“阶段内禁止再次物理发放”不等于“整个内容网络停止计算”。

## 4. 主内容模型的 \(J^\pi,G^\pi\)：同一策略的值

### 4.1 定义与未来项

当前内容层的策略 \(\pi\) 是按已选外边界自然发放、进入 Erlang 阶段并按 \(x_r\) 释放。局部值计算冻结当前物理系数；它不预测未来输入将如何改变这些系数。

自然发放奖励率为 \(g=(b-K)\lambda\)，内部策略值满足

\[
(\rho I-A)J^\pi=g.
\]

等价地，设活动链折现首次退出变换为 \(H_i\)，复位处变换为 \(H_r=\sum_i w_i(x_r)H_i\)，阶段剩余贴现为

\[
D_j=\left(\frac{\nu}{\nu+\rho}\right)^{m_\phi-j},\qquad D=D_0 .
\]

则

\[
J_i^\pi=H_i\,\frac{b-K}{1-DH_r},\qquad
J_r^\pi=H_r\,\frac{b-K}{1-DH_r},\qquad
J^\pi_{\phi,j}=D_jJ_r^\pi.
\]

合法即时干预的值为

\[
G_i^\pi=x_i-K+DJ_r^\pi
\quad\text{（活动格点）},\qquad
G^\pi_{\phi,j}=J^\pi_{\phi,j}
\quad\text{（强制阶段续存）}.
\]

活动格点的 \(G_i^\pi\) 表示“现在额外 FIRE 一次，然后继续执行原策略 \(\pi\)”的反事实值。阶段状态没有合法 FIRE 动作，所以其对应槽位使用强制续存值，不会凭空增加一次奖励。

主模型实际投影为

\[
J_{\rm total}^\pi=p\cdot J^\pi,\qquad
G_{\rm total}^\pi=p\cdot G^\pi
=G_{\rm eligible}^\pi+J_{\rm phase}^\pi .
\]

这些是全概率质量加权的期望，不是除以活动概率后的条件均值。值可以超出 \([0,1]\)，不能当概率解释。源实现：[distribution_kernel.py](distribution_kernel.py) 的 `policy_value_vectors` 与 `finite_generator_values`。

### 4.2 解析边界的适用范围

`distribution_free_dual` 等 free arms 用连续无限域 Brownian 再生问题的解析/隐式自由边界作为 \(b\)。为匹配 Erlang 贴现，传入

\[
\tau_{\rm eff}
=\frac{m_\phi}{\rho}
\log\left(1+\frac{\rho\tau_\phi}{m_\phi}\right),
\qquad e^{-\rho\tau_{\rm eff}}=D .
\]

这只匹配阶段等待的 Laplace 贴现因子，不把 Erlang 分布变成确定时长。解析边界在对应连续理想模型下的最优性，不等于它在有下壁、只有八格、带插值和移动重映射的有限网格上最优。`distribution_conditional_dual` 则显式学习条件边界参数。两者的内部 \(J^\pi,G^\pi\) 都按实际有限生成器评估所选策略。

当前主 `model.py` **没有调用 QVI 最优控制求解器**，也没有根据 \(G^\pi>J^\pi\) 自动改变物理发放策略。这两个值经缩放后进入内容门控。它们包含内部反复发放的未来收益，却不包含未来分类标签收益、任务层复位的内容损失、剩余任务期限、真实 CPU 或 owner 恢复费用。

### 4.3 输出字段映射

下表列“单 token 逻辑形状”。`forward` 的逐时输出另有时间轴，故 \([B,8]\) 在 `aux` 中实际为 \([B,T,8]\)；`step` 的 `aux` 仍保留 \(T=1\)。返回的 recurrent `state` 不带这个时间轴。

| 代码输出 | 单 token 逻辑形状 | 精确定义与单位 |
| --- | --- | --- |
| `continuation` | \([B,8]\) | \(p\cdot J^\pi\)，内部贴现策略值；字段名不表示任务的 READ 动作值 |
| `intervention` | \([B,8]\) | \(p\cdot G^\pi\)，活动可干预值加阶段强制续存值 |
| `eligible_intervention` | \([B,8]\) | \(\sum_{i<n}p_iG_i^\pi\)，不除以活动质量 |
| `refractory_continuation` | \([B,8]\) | \(\sum_j z_jJ^\pi_{\phi,j}\)；与上一项之和为 `intervention` |
| `margin` | \([B,8]\) | \(\sum_{i<n}p_i(b-x_i)\)，活动质量加权的安全距离；单位为内部状态 |
| `activity` | \([B,8]\) | 当前观察区间内含即时重映射事件的期望重复发放次数 |
| `cost` | \([B,8]\) | \(K\times activity\)，内部建模发放成本；不是实际 CPU 或任务 READ 费 |
| `modeled_reward` | \([B,8]\) | 当前区间的未贴现内部 \(x-K\) 发放奖励期望；不同于无限期贴现 \(J^\pi\) |
| `probability` | \([B,8,10]\) | 八个通道各自的八活动格加两阶段概率 |
| `flow_mass` | \([B,8]\) | 每通道全质量，合法递推约为一；不是传给下一层的“内容量” |
| `active_mass`、`refractory_mass` | 各 \([B,8]\) | 活动与阶段总概率，两者相加为 `flow_mass` |
| `active_center_variance` | \([B,8]\) | \(\sum_{i<n}p_i(x_i-\bar x_{\rm active})^2\)，活动质量加权的中心方差；不是格内均匀密度的全部二阶矩 |
| `boundary` | \([B,8]\) | 本 token 的八通道边界 \(b\)，单位为内部状态 |
| `content` | \([B,32]\) | 更新后的可学习内容向量，潜在特征单位 |
| `total_activity`、`total_cost` | 各标量 | 对 batch、时间、通道和层求和的诊断量；相应单位不变 |

`distribution_free_ordinary` 不计算上述双值特征；其门控特征使用安全距离、活动条件均值和中心方差。它仍接收完整概率与相同七项局部系数。当前内容训练的目标是任务交叉熵；`modeled_reward` 和 `total_cost` 的诊断记录不意味着训练直接最大化内部发放收益。见 [content_training.py](content_training.py)。

## 5. 实际内容与状态接口

以已登记的 width32、八物理通道、八格、两阶段配置为准：

| 数据/状态 | 形状 | 去向或保留方式 |
| --- | --- | --- |
| 原始输入 `x` | \([B,T,I]\)，MNIST 中 \(I=64\) | 与当前 `dt/32`、累计 `elapsed/32` 拼接，经 frontend 映射到 32 维 |
| 层间内容路径 | \([B,T,32]\) | 每层输出 \(x_\ell+W_{\rm out}h_\ell'\)，作为下一层的输入 |
| 每层 `state["content"]` | \([B,32]\) | 跨 token 保留的内容状态 \(h_\ell\) |
| 每层 `state["probability"]` | \([B,8,10]\) | 跨 token 保留全部活动和阶段质量；首次观察前为 `None` |
| 每层 `state["boundary"]` | \([B,8]\) | 保留上次边界，供下一次物理重映射；首次观察前为 `None` |
| 全局 `state["elapsed"]` | \([B]\) | 累计输入间隔，用于 frontend 时间特征 |
| readout logits | \([B,O]\) 或 \([B,T,O]\) | 类别分数；MNIST 中 \(O=10\)，不能解释成内部物理值 |

**信息传递不是只靠一个标量 \(V_b\)。** 层间主路径携带 32 维内容；各层跨时间同时携带 32 维内容、\(8\times10\) 概率与八维边界。概率和边界是每层自己的 recurrent state，不是全部直接拼接成下一层输入的一个大向量。

门控额外读取每通道的完整十维概率和七个局部系数 \((\mu,\sigma,\rho,K,x_r,\tau_\phi,b)\)，合计 \(8(10+7)=136\) 维；双值 arm 再读取每通道三个缩放特征，共 24 维。内容与物理概率具有实际耦合，而非只保存一个未使用的边界标签。

令两个宽度为32的 sigmoid 门为 \(u,v\)，正内容写入速率为 \(a\)，正衰减速率为 \(d\)，则递推为

\[
w=1-e^{-a\,dt\,u},\qquad
R=e^{-d\,dt\,v},\qquad
\widetilde h=\tanh(W_x\,signal+W_hh),
\]
\[
h'=R\odot\big((1-w)\odot h+w\odot\widetilde h\big).
\]

双值通过学习的门控权重影响该递推，不直接充当力。`step(x,dt,state)` 返回 `(logits,new_state,aux)`；复原一个活动序列必须恢复 `elapsed` 与每层全部三项状态，不能只恢复内容均值或边界。

## 6. 独立 QVI：最优值必须与受控流一起改变

[grid_control_reference.py](grid_control_reference.py) 在同一固定有限物理模型上扩大动作类：每个活动格点可 CONTINUE 或立即 FIRE；阶段状态仍强制续存。它固定外边界/网格，并不继续优化 \(b\)、下壁或复位规律。

令 \(R_i=x_i-K\)，即时干预值为

\[
\mathcal I_i(V)=R_i+V_{\phi,0}.
\]

续存残差与其按时间归一的动作候选为

\[
\mathcal R_i(V)=g_i+(AV)_i-\rho V_i,\qquad
\mathcal C_i(V)=
\frac{g_i+\sum_{j\ne i}A_{ij}V_j}{\rho-A_{ii}}.
\]

\(\mathcal R_i\) 的单位是内部效用/物理时间，\(\mathcal C_i,\mathcal I_i,V_i\) 的单位都是内部效用。实际策略改进比较归一后的 \(\mathcal C_i\) 与 \(\mathcal I_i\)，避免把单位不同的数值当作动作价值直接比较。活动 QVI 可等价写为

\[
\max\{\mathcal C_i(V)-V_i,\ \mathcal I_i(V)-V_i\}=0,
\]

实现同时检查 \(\mathcal R_i(V)\le0\)、\(\mathcal I_i(V)-V_i\le0\) 和互补条件；阶段要求 \(\mathcal R_i(V)=0\)。该 \(V^\star\) 是固定有限状态/动作类的最优值；它不等于无限域连续问题、原金融问题或分类任务的最优值。

源输出的关键对应为：

| 接口 | 形状/对象 | 语义 |
| --- | --- | --- |
| `howard(... )["value"]` | \([n+m_\phi]\) | 通过 QVI 残差检查的所选最优控制值 |
| `["fire"]` | Boolean \([n]\) | 活动格的即时干预集合；阶段无此动作 |
| `controlled_generator` | 受控生成器、奖励率、发放率与初始映射 | 消除瞬时 FIRE 状态、把进入该状态的质量和奖励转接到 phase zero |
| `propagate_controlled` | 概率、次数、奖励、贴现奖励和末端值 | 按所选 mask 推进匹配过程；包含零时间初始干预和重复发放 |

设 \(F\) 为 FIRE 集，\(C\) 为保留的活动格与全部阶段，\(u_0\) 指 phase zero。受控生成器包含

\[
\widetilde Q=Q_{CC}+u_0{\bf1}_F^TQ_{FC},\qquad
\widetilde g=g_C+Q_{FC}^TR_F,\qquad
\widetilde\lambda=\lambda_C+Q_{FC}^T{\bf1}_F.
\]

初始质量若在 \(F\)，还要先记录一次即时奖励/次数并映射到 phase zero。即使某条概率自返回项在矩阵中抵消，其事件与奖励也不能被删掉。匹配过程需要满足

\[
pV^\star
=E_p\!\left[\text{到 }t\text{ 的贴现奖励}
+e^{-\rho t}V^\star(X_t)\right].
\]

**不能把主模型的 \(J^\pi\) 替换成 \(V^\star\)，却继续使用旧的自然边界 flow。** 那样值属于一个策略，状态/奖励/计数属于另一个策略。当前 QVI 是独立参考，没有接入冻结的内容模型。若将来接入，必须同时更改状态推进与奖励/计数，并重新登记和验证。

## 7. 任务层 Bellman 与真实 owner 动作

### 7.1 价值、单位与可行动作

任务状态为 \((m_q,h,k,z)\)。当前分类立即正确的期望为 \(r_k(z)\)，读取费为 \(c_{\rm read}\)，任务 quiet 长度为 \(\tau_q=2\)。任务贴现使用 \(\gamma\)，当前登记取一：

\[
G^{task}_{m_q}(h,k,z)
=r_k(z)+{\bf1}_{\{m_q>1,\ h\ge\tau_q\}}
\gamma^{\tau_q}F_{m_q-1}(h-\tau_q),
\]
\[
C^{task}_{m_q}(h,k,z)
=-c_{\rm read}
+\gamma\sum_{z'}P_k(z,z')J^{task}_{m_q}(h-1,k+1,z'),
\]
\[
J^{task}_{m_q}(h,k,z)=\max\{G^{task},C^{task}\}.
\]

READ 不合法时只允许 FIRE。新任务价值为

\[
F_{m_q}(h)
=\max\!\left\{0,-c_{\rm read}
+\gamma\sum_z\pi_1(z)J^{task}_{m_q}(h-1,1,z)\right\},
\quad F_{m_q}(0)=F_0(h)=0.
\]

这里 \(G^{task}\) 是当前正确性加未来任务净收益，\(C^{task}\) 是支付下一条实际 READ 后的动作值，\(J^{task}\) 是两者最大值。它们都使用分类效用单位。内部 `K`、\(\rho\)、\(x-K\) 不出现在这个分类账本中，不能拿内部 `modeled_reward` 代替后续实际任务收益。

MNIST 表数组 \([m_q,h,k,z]\) 的尺寸为 \([4,49,33,4]\)；包含未使用索引和不可达槽位，不能把所有槽位都当成合法状态。\(F\) 与 `future_after_reset` 为 \([4,49]\)。每个已观察任务状态取出的 \(C^{task},G^{task},J^{task}\) 都是标量；两个学习头输出 \([B,2]\)，其中值回归头的目标顺序为 \([G^{task},C^{task}]\)。普通动作蒸馏头的两个输出是动作 logits，不是两项校准价值。

精确二元观测模型有充分统计量和独立参考。真实神经内容采用 TRAIN 拟合的四置信度状态，它通常不是充分 belief state；teacher 最优性只对这个近似状态模型成立，压缩学习头还增加拟合误差。未来值结构中包含实际任务，不能证明其预测已校准；逐流事后检验另见 [未来价值校准报告](results/task_future_calibration001/REPORT.md)。

### 7.2 FIRE、quiet、RESET 与输出账本

| 任务接口/动作 | 实际语义 |
| --- | --- |
| READ | 调用一次真实 `backbone.step`，消耗一个任务时钟并收取价格；首次 READ 也收费 |
| `teacher_fire_value` | 当前模型的 \(G^{task}\)，不是已经获得的收益 |
| `teacher_read_value` | 当前模型的 \(C^{task}\)；READ 不合法时该值不可用 |
| `teacher_future_after_reset` / `first_fire_predicted_future` | 首次 FIRE 时对随后任务净收益的预测 |
| FIRE / owner STOP | 使用当前预测对真实标签评分 0/1，实际终止当前 owner 和当前输入 iterator |
| 两个 quiet tick | 消耗共享期限；不调用模型、不读取观察、不推进 owner，也不是 wall-clock sleep |
| RESET | 将整个 `state=None`，包括全部内容、概率、边界及 elapsed；下一任务使用新 owner 和另一张图像 |
| `later_task_net_reward` | 同一策略后来实际获得的正确性减全部后来 READ 费用；它独立于预测值记账 |
| 实际 CPU / recovery 费用 | 另按执行收据计量；不混入内部发放 `cost`，费用场景转换另行声明 |

共享期限为48个任务 tick，单任务最多32 READ，队列最多三个任务。第一次观察前不允许凭空 FIRE 赚取分类奖励。真实登记价格下先核对所有可用正期限的拟合新任务价值为正，随后统一执行必须读取第一条观察的合同。不存在后续任务或剩余期限不足时，未来收益为零，不能垫一个常数。

实际 owner 读取实数 gap 的归一化/量化结果。对表格策略，gap 为 \(C^{task}-G^{task}\)；动作蒸馏头使用动作 logit 差。`tanh(gap)` 经 Q24 后，量化分数大于零才 KEEP，否则 STOP，零值选择 STOP。任务合法性另外强制期限末端或第32次读取 FIRE。连续控制分数没有消除最终离散动作，置信度到四状态的映射也不是处处连续。

## 8. 三种“复位/不应期”不能互换

| 项目 | 内部自然边界策略 | 独立 QVI 控制 | 任务层 owner |
| --- | --- | --- | --- |
| 触发 | 自然上边界退出或边界下降覆盖质量 | 自然退出，加上所选格点即时 FIRE | 当前任务的实际 KEEP/STOP 决策 |
| 触发次数输出 | 可大于一的期望次数 | 控制 mask 为 Boolean；执行次数仍可重复、期望可大于一 | 每任务最多一次最终 FIRE；任务队列离散 |
| 复位对象 | 物理概率进入 phase zero，最后按 \(x_r\) 释放 | 受控概率映射、相应奖励与次数同步改变 | 全神经状态清空，任务输入切换，owner 更换 |
| 内容是否自动清零 | 否 | 参考未定义神经内容状态 | 是，任务 RESET 显式传 `None` |
| 不应期 | 两阶段 Erlang，均值可学习 | 同一固定正 Erlang 律，阶段强制续存 | 两次确定的整数 quiet tick |
| 是否允许期间再次该类发放 | 阶段内不允许；完成释放后可再次自然发放 | 阶段内不允许；释放到 FIRE 格可立即再次干预 | quiet 中没有 model/owner step |
| 未来收益 | 同局部物理策略的后续 \(x-K\) | 同所选控制策略的后续 \(x-K\) | 同任务策略在剩余期限内的后续真实分类净收益 |

金融违约不在此表中充当第四种自动复位；它只提供前述估值/内生边界启发。

## 9. 可微性与数值合同

“有连续值/边界”或“满足 smooth-pasting”不能推出整个网络及执行系统处处可微。实际合同如下：

| 环节 | 已声明的可微范围与限制 |
| --- | --- |
| 连续理想自由边界 | 特定值函数在边界的匹配/一阶条件；不是任意模块的全局光滑性定理 |
| 隐式 `free_boundary` | 自定义 backward 支持已检查的一阶局部导数；更高阶导数没有实现/认证 |
| 上风跳率 | 含 \(\max(\mu,0)\)、\(\max(-\mu,0)\)，漂移换号处是分支 |
| 活动网格与复位插值 | 中心选择、插值结点和有限体积近似有分段结构 |
| 移动边界 remap | 物理区间相交用 min/max 和截断；重叠集合改变处不保证光滑，往返重映射有投影误差 |
| 固定阶 uniformization | 内容模型固定 rate8.1、21项，物理子步上限0.36；数值传播误差与空间/舍入误差分开 |
| 每 token 数值分块 | \(n_i=\max(1,\lceil\Delta t_{{phys},i}/0.36\rceil)\)，必要时按表示舍入局部加一；整数分支/资源拒绝边界不宣称可微 |
| QVI active set | Howard 先选 Boolean 集合，再在固定集合的线性方程上求导；不对策略切换本身求导 |
| 任务 Bellman | \(\max\) 与最优动作切换是分段结构；四状态量化和实际 Q24/KEEP/STOP 为离散环节 |

每 token 分块由该 token 自己的时长决定，不能从未来 suffix 或其他样本的最大时长为当前 token 选择数值算子。整数块数固定的局部导数不等于跨整数边界的全局导数。固定有限生成器的时间传播精度，也不等于八格过程已经精确还原连续 Brownian 动力学。

独立 QVI 在固定 active set 上使用

\[
A_\pi V=h_\pi,\qquad
dV=A_\pi^{-1}(dh_\pi-dA_\pi\,V).
\]

这里的局部分支梯度、内部概率守恒、任务值结构、真实 owner 动作和内容能力是不同证据。通过其中一项不能代替另一项。

## 10. 交付边界与可审计来源

本合同可以支持的精确陈述是：主模型保留并推进有限活动/阶段分布，计算与所选物理策略一致的 \(J^\pi,G^\pi\)，让它们影响有内容状态的门控网络；另有与其匹配的有限 QVI 最优控制参考；任务执行器另用真实分类/读取账本定义 \(C^{task},G^{task},J^{task}\)，并实际执行 STOP、任务复位和恢复。

它不把四个层次合并为一个“Call/Put 最优神经元”，不把有限控制改进解释成分类能力提升，也不把边界标量解释成唯一内容载体。全模态内容能力、训练规模和完整部署收益应使用各自登记实验的结果，不由本合同预先宣布。

| 核对对象 | 源文件/证据 |
| --- | --- |
| 金融模型及其边界含义 | [He–Xiong 官方 PDF，Sections I–II](https://www.princeton.edu/~wxiong/papers/rollover.pdf) |
| 内部概率、发放、奖励、值与重映射 | [MATH.md](MATH.md)、[distribution_kernel.py](distribution_kernel.py) |
| 内容递推、输出字段及持久状态 | [model.py](model.py)、[content_training.py](content_training.py) |
| 连续理想边界的一阶接口 | [v1/oracle_torch.py](../hcsn_free_boundary_v1/oracle_torch.py) |
| 固定有限动作类的最优值和匹配受控流 | [grid_control_reference.py](grid_control_reference.py)、[grid_control_validation001/REPORT.md](results/grid_control_validation001/REPORT.md) |
| 真实任务价值和运行合同 | [TASK_VALUE.md](TASK_VALUE.md)、[task_value.py](task_value.py)、[task_value_native.py](task_value_native.py) |
| 已训练 v2 分布状态的实际 owner/恢复工程证据 | [distributional_native001/REPORT.md](results/distributional_native001/REPORT.md) |
| 发放未来值预测与实际后续净收益的区别 | [task_future_calibration001/REPORT.md](results/task_future_calibration001/REPORT.md) |

本文件核对的核心源身份：`model.py` SHA256 `3eb5f6b8797475abf84b09ae5b588f3d0a253e0584578586cb081f15142a355f`；`distribution_kernel.py` SHA256 `07195028877b4eb24f1bb1b53f1337019daf7bdabbdecbcd059f89079ba23de6`；`grid_control_reference.py` SHA256 `1aea0f50b1a8328394a2c2260dd89fc8203d416e73e1db8c3d38baf2e7ce2d84`。本合同新增时没有修改这些源或既有运行。
