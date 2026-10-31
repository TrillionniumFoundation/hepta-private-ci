# R10：公开状态下的付费证据读取与解析门价值头

## 结论与证据版本

本轮建立了有真实任务收益、读取成本、失败成本、预算、deadline 和恢复期的有限证据任务，并完成精确 Bayes–Bellman teacher、独立条件世界求和，以及三种等容量价值头的完整训练。**解析门没有在预先记录的主要比较中优于 ordinary：ID 与 OOD 的 utility 差均为负，95% 区间均包含零。** OOD 上解析门优于选定的固定阈值规则，但其平均 utility 仍低于初态直接 STOP；因此不能据此宣称稳健的解析算子优势。[主要协议](evidence/confirmation/PROTOCOL.json) · [完整结果](evidence/confirmation/RESULTS.json)

`main` 是原始运行；`confirmation` 是加强 `State` 校验、对齐原生合同后的相同配置与相同种子重放。两次运行的配置、配对 utility 文件和九个 checkpoint 逐字节相同，数值检查及结果相同，时间测量不同。**confirmation 不是新增独立测试集，也不能把三次初始化算成六次。** 两版源码哈希分别保留在 [main/SOURCES](evidence/main/SOURCES.json) 与 [confirmation/SOURCES](evidence/confirmation/SOURCES.json)。本报告以 confirmation 的数值和时间为主，原始证据未被修改。

## 1. 任务、信息与目标

一个任务有私有二元真值 (Y\in\{0,1\})，先验为 (p_0)。第 (i) 个 packet 的公开元数据包含 arrival、可靠性 (q_i>1/2) 与失败概率 (f_i)。给定 (Y)，各 packet 的 vote 条件独立，且 (P(Z_i=Y\mid Y)=q_i)；失败独立于真值和 vote。失败读得到 `x`，成功读得到 `0` 或 `1`。这些可靠性和失败率是**声明的合成任务模型**，并非从未来测试内容估计的 decoder 校准结果。[任务实现](task.py)

策略只能看公开配置与状态：clock、剩余预算、recovery、已消费 packet 数、已揭示历史及其后验。未来 vote、失败实现和 truth 不进入策略特征。对已揭示的成功读，后验为

\[
\ell(s)=\log\frac{p_0}{1-p_0}
+\sum_{i:\,h_i\ne x}(2h_i-1)\log\frac{q_i}{1-q_i},
\qquad p(s)=\frac{1}{1+e^{-\ell(s)}}.
\]

| 动作 | 合法性及状态变化 | 任务费用 |
| --- | --- | --- |
| READ | 只能读首个未消费且已到达 packet；clock 小于 deadline、有预算且不在恢复期。消耗一个 tick、一个预算单位和该 packet；设 recovery 为新 clock 加 refractory ticks。失败也消耗资源。 | `read_cost`；失败另加 `failure_cost` |
| WAIT | clock 小于 deadline；推进一个 tick，不揭示内容。 | `latency_cost` |
| STOP | 所有非终态都合法，包括初态；按当前后验 argmax 作答，平局选 1；不推进 clock。 | `stop_cost` |
| 非法 READ/WAIT | 在读取前变为 STOP，提交当前答案，不访问内容。 | `invalid_cost + stop_cost` |

READ/WAIT 可以恰好完成于 deadline；下一次只有 STOP 合法。外部评价端持有 truth，终止收益为

\[
U=\mathbf 1\{\widehat Y=Y\}-\sum_t c_t.
\]

从中间状态评估时，只扣除后续费用，已支付费用是 sunk cost。STOP 享有相同正确性奖励，并非被人为设为零收益的退出动作。合同、合法性和费用语义与 [原生合同](../native/task_contract.json) 一致。

## 2. 精确 Bellman teacher 与独立核验

令 (V^*(s)=\max_{a\in\mathcal A(s)}Q^*(s,a))。对合法动作：

\[
\begin{aligned}
Q^*(s,\mathrm{STOP})&=\max(p(s),1-p(s))-c_S,\\
Q^*(s,\mathrm{WAIT})&=-c_W+V^*(s_W),\\
Q^*(s,\mathrm{READ})&=-c_R-f_i c_F
+\sum_{o\in\{0,1,x\}}P(o\mid s)V^*(s_o).
\end{aligned}
\]

这里 (m=p(s)q_i+[1-p(s)](1-q_i))，因此 (P(1\mid s)=(1-f_i)m)、(P(0\mid s)=(1-f_i)(1-m))、(P(x\mid s)=f_i)。每次继续动作都会推进有限 clock，因此可精确递推；teacher 不查看实际未来 world。非法动作在部署端按合同结算，teacher 的最优化仅对合法动作进行。平局使用 `STOP > WAIT > READ`，容差为最大合法 Q 减 `1e-12`。[teacher 与策略评价](oracle.py)

核验分三类，不能混为一个样本量：

- **初态独立求和：** 前四个 validation 配置分别强制三个合法动作，再枚举私有真值、所有 votes 和失败组合，比较 teacher 的动作值；共 12 个动作值，最大绝对误差 `7.77e-16`。[RESULTS.checks](evidence/confirmation/RESULTS.json)
- **条件状态审计：** 另用固定 seed 5001 生成 12 个配置；每个确定性抽取 12 个公开状态，按已揭示历史筛选并重新归一化私有世界概率。144 个状态产生 **280 个合法条件动作值：144 STOP、93 WAIT、43 READ**；每项求和涉及 2–512 个相容世界，最大误差 `1.44e-15`。求和不复用 Bellman 价值递推，但 rollout 继续采用 teacher 策略和同一任务转移，因此是独立求和检查，不是完全独立重写整个环境。另有 36 个禁止私有访问的 guard 检查。[审计源码](audit.py) · [全部条件证据](evidence/conditional_audit.json)
- **配对实际 world：** `COUNTERFACTUALS.json` 保存前八个 ID 配置各 12 个 world，共 96 个 world 的初态动作分支。这是 Python 任务执行，不是 native 执行，也不同于上面的 280 个条件期望值。[原始分支](evidence/confirmation/COUNTERFACTUALS.json)

条件审计另外记录了一个配置的 61 点 read-cost 扫描。网格上，cost `0.135` 时 READ 优势为 `+0.004004`，`0.140` 时为 `−0.005996`，最优动作切换为 STOP。这是任务动作值的切换边界，不是 He–Xiong 金融 free boundary 的 smooth-pasting 证明。该扫描和条件审计属于补充诊断，不参与 head 选择。

## 3. 三种价值头：相同信息、容量和更新预算

三种 head 都接收同样的 **29 个公开特征**：后验、先验、clock、deadline、预算、recovery、已读位置、恢复时长、五种费用，以及四个 packet 槽位的 arrival、reliability、failure probability、是否未消费。额外门参数 (H=0.25+(D-t)/8) 完全由同样公开的 deadline 和 clock 决定；它不提供未来内容。所有特征归一化均使用训练行统计，标准差下限为 `0.03`。[特征与训练代码](heads.py)

每个 head 有 24 个隐藏单元、两个输出，训练参数总数均为 **770**。两个输出拟合 `Q_READ − Q_STOP` 与 `Q_WAIT − Q_STOP`；STOP 值由精确后验公式共同提供给全部 head。非法动作不进入 MSE。三者只有隐藏门不同：

| 家族 | 隐藏门 |
| --- | --- |
| Ordinary | (g(z)=\sigma(z)) |
| Analytic | (g(z,H)=\operatorname{erfc}[\operatorname{softplus}(-z)/\sqrt{2H}])，采用零漂移、单位扩散 Brownian 首达概率的函数形式 |
| Matched C1 | logistic 门，随 (H) 调整斜率和截距，使其在 (z=0) 的值及对 (z) 的一阶导数与 analytic 相同 |

Matched C1 的局部匹配是控制实验设计，不能当作金融模型的 value-matching/smooth-pasting 已被迁移到任务 Q 函数。解析门也不是完整 He–Xiong equity/default 解或连续随机路径求解器。

| 训练项 | 记录值 |
| --- | --- |
| 配置划分 | train 128，validation 32，ID test 48，OOD test 48 |
| 配置 seed | 3101、3102、3103、3104 |
| teacher 训练/验证行 | 18,628 / 5,442 |
| 初始化 seed | 17、29、43；3 家族 × 3 seed = 9 fits |
| 更新 | 每 fit 1,800 次，batch 256，按 seed 配对相同 minibatch 索引 |
| 优化器 | Adam，β=(0.9,0.999)，ε=`1e-8`；学习率从约 0.008 线性降至 0.0016 |
| 正则 | L2=`1e-5` |
| 选择 | 每 100 updates 计算 validation masked advantage MSE，共 18 次；取最低值，平局保留较早 checkpoint |
| 数值 | NumPy float64，手写解析梯度，无 surrogate spike 梯度 |

相同 seed 的三个家族有相同初始参数和 batch 顺序。它们匹配的是信息、参数量和更新次数，**没有匹配 CPU 预算**。训练直接反传连续 head；运行时动作仍通过合法性 mask 和离散 argmax 选取，未对实际 I/O 或离散决策路径进行端到端反传。

三个家族各在小模型的全部 34 个坐标上做中央差分；最大绝对梯度误差分别为 `1.17e-10`、`1.45e-10`、`1.68e-10`。匹配控制的值误差 `1.11e-16`、斜率误差 `5.55e-17`。这验证实现中的梯度和局部匹配，不证明训练会找到全局最优或存在架构优势。[梯度证据](evidence/confirmation/RESULTS.json)

测试 teacher 在训练前已经生成；训练更新和 checkpoint 选择仅消费 train/validation 行。源码没有用 test 分数选择 checkpoint，但这里不能声称“直到 checkpoint 封存才首次打开 test”。协议和源码快照在运行开始写入；这是本次运行内的事先记录，不是外部注册平台上的独立预注册。[执行顺序](run.py)

## 4. 分布与对照

各配置有 2–4 个 packets，arrival 在 0–4 tick，首个在 0；deadline 为 4–8，预算 1–packet 数，先验从 `{0.3,0.5,0.7}` 选取，reliability 在 `[0.60,0.93)`，refractory 为 0–2 ticks。latency cost 在 `[0.002,0.018)`，stop/failure/invalid cost 分别为 `0.002/0.025/0.03`。[配置全集](evidence/confirmation/CONFIGURATIONS.json)

| 项 | Train / validation / ID | OOD |
| --- | --- | --- |
| read cost | `[0.012,0.09)` | `[0.10,0.20)` |
| failure probability | `{0,0.08,0.16}` | `{0.20,0.35}` |

OOD 同时提高读取成本和失败率。固定规则从 `{0.5,0.6,0.7,0.8,0.9,0.98,1.0}` 七个 confidence 阈值中按 validation 的精确期望 utility 选择，选中 **0.8**。另保留无需读取的强初态 STOP 对照，以及相同可见信息下的精确最优 teacher。固定阈值失败不能替代与 STOP/ordinary 的比较。

## 5. Held-out 期望 utility

每个配置的策略 utility 按完整条件分支概率求和，不是少量采样 rollout 的估计。下表在 48 个配置上取平均，learned head 另外对三个 fit seeds 取平均；regret 是相对于同配置精确最优值的差。[配对原始数值](evidence/confirmation/PAIRED_UTILITIES.json)

| 策略 | ID utility | ID regret | OOD utility | OOD regret |
| --- | ---: | ---: | ---: | ---: |
| Bellman optimum | 0.745645 | 0 | 0.662506 | 0 |
| Fixed threshold 0.8 | 0.732220 | 0.013425 | 0.544544 | 0.117962 |
| Initial STOP | 0.635500 | 0.110145 | 0.643833 | 0.018673 |
| Ordinary | 0.723205 | 0.022440 | 0.636497 | 0.026008 |
| Matched C1 | 0.719771 | 0.025874 | 0.624624 | 0.037882 |
| Analytic | 0.720984 | 0.024661 | 0.632137 | 0.030369 |

协议记录的主要比较为 analytic−ordinary；analytic−matched/fixed 为辅助比较。以下为按配置和 fit seed 配对重抽的 2,000 次 bootstrap、双侧名义 95% 区间，**没有多重比较校正**；源码的 `positive_gate` 仅表示区间下界大于零。只有三个初始化，区间需按该有限设计理解，不能把 48×3 个值都当作独立任务样本。

| 比较 | ID 差值 [95% CI] | OOD 差值 [95% CI] |
| --- | --- | --- |
| Analytic − Ordinary，主要比较 | −0.002221 [−0.009857, +0.004648] | −0.004360 [−0.016061, +0.008428] |
| Analytic − Matched C1，辅助 | +0.001213 [−0.006504, +0.008062] | +0.007513 [−0.002393, +0.016552] |
| Analytic − Fixed，辅助 | −0.011236 [−0.022703, −0.000007] | +0.087593 [+0.056821, +0.117174] |
| Optimum − Initial STOP，任务价值诊断 | +0.110145 [+0.083893, +0.138097] | +0.018673 [+0.007523, +0.032642] |

为避免只强调 OOD 的弱对照，报告另外从已保存配对值派生 **analytic−initial STOP 的事后探索性区间**：ID 为 `+0.085484 [0.056667, 0.116441]`，OOD 为 `−0.011696 [−0.028177, +0.007099]`。派生使用相同 2,000 次配对 bootstrap 与 seed 51，没有重训、重新选择或改写原始 RESULTS。它不是新注册主要终点。

由此可以说：该任务存在可获益的信息读取策略；解析 head 在 ID 上优于无读取的初态策略。但本轮未显示解析 head 优于等信息普通门，OOD 的正向 fixed-rule 比较也没有超过强 STOP 的平均 utility。OOD 解析 head 低于 STOP 是均值观察，探索性区间含零，不能写成已显著劣于 STOP。

## 6. 测量成本与计时范围

| 家族 | main 平均 fit CPU / s | confirmation 平均 fit CPU / s | confirmation Python 决策微基准 / µs |
| --- | ---: | ---: | ---: |
| Ordinary | 0.325426 | 0.395611 | 19.614 |
| Matched C1 | 0.402347 | 0.466193 | 31.794 |
| Analytic | 0.890395 | 0.969879 | 28.804 |

confirmation 九个 fit 合计 CPU 为 `5.495051 s`，teacher preparation 为 `1.128159 s`，`RESULTS` 记录的运行区间 CPU/wall 为 `7.504360/7.505075 s`；main 对应为 `4.854504 s`、`0.851922 s`、`6.603825/6.604404 s`。[两次完整计时](evidence/main/RESULTS.json) · [confirmation](evidence/confirmation/RESULTS.json)

fit 计时覆盖训练循环和其中 18 次 validation 计算，不含其前面的归一化和模型初始化。teacher preparation 覆盖四个 split 的 teacher/数据准备。名为 `end_to_end_*` 的计时从写完 PROTOCOL 后开始，到构造最终 summary 为止：包含主要准备、训练、评价、Q 导出和微基准，但**不含 Python 启动/import、最终 RESULTS/PAIRED_UTILITIES/COUNTERFACTUALS 文件写出和其后的打印**，不能称为整个进程或完整原生流水线成本。

决策微基准仅在第一个 ID 配置的初态，使用 seed 17 的已加载 head，warm-up 20 次后测量 2,000 次 Python policy 调用。它不包含 payload decode、原生 checkpoint、IPC 或文件 I/O。以上 CPU 数值不是能耗，没有 GPU/功率测量；特殊函数成本也不能由神经事件数替代。解析 fit 在本次等更新预算下耗时更多，不能据此宣称训练速度优势。

## 7. 原生桥接的意义与限制

八个 `native_case_*.json` 导出前八个 ID 配置中所有 teacher 可达公开状态的 Q table。每个 learned 家族使用第一预定 seed **17** 的已选 checkpoint；不是三 seed ensemble，也不是按 native world 的结果选择最佳 seed。表只依赖公开 metadata/state，不携带未来 vote。[导出实现](run.py) · [示例导出](evidence/confirmation/native_case_0.json)

Rust owner 部署时执行的是 Q-table lookup、合法性 guard 和真实读取后的状态更新，**不是在原生端执行上述 Python MLP 的矩阵乘法，也不是原生 head 训练**。未枚举状态没有自动神经泛化；若实际失败落在导出任务声明支持之外，缺失 table row 会拒绝决策。Python expected-utility 实验自身标记 `native_executed=false`；真实 FullHX/native 执行由独立的 [native qualification](../native/evidence/qualification/REPORT.json) 与 [独立派生审计](../native/evidence/INDEPENDENT_AUDIT.json) 证明。

原生有限 CTMC 在 READ/WAIT 上推进，任务的 refractory 是另行声明的控制约束；latent physical firing 不直接触发 READ。本轮不能据此认定：完整金融 free-boundary 解已经成为新的神经元动力学；平滑门消除了实际离散行动；解析物理状态导致任务收益提升；或者 HCSN 已经优于传统 SNN、Transformer、全模态 encoder 或 foundation model。可以复核的是有限任务合同、有效的连续 head 梯度、完整等容量训练，以及上述清楚保留的负结果。

## 证据入口

- [协议及预先记录的比较](evidence/confirmation/PROTOCOL.json)
- [Main 原始结果](evidence/main/RESULTS.json)；[同种子重放结果](evidence/confirmation/RESULTS.json)
- [全部配置](evidence/confirmation/CONFIGURATIONS.json)；[逐配置、逐 seed utility](evidence/confirmation/PAIRED_UTILITIES.json)
- [96 个 Python 配对 world](evidence/confirmation/COUNTERFACTUALS.json)；[280 个条件动作值、36 个 guard 与成本扫描](evidence/conditional_audit.json)
- [任务](task.py)、[Bellman 与独立世界枚举](oracle.py)、[head 与梯度](heads.py)、[训练/选择/导出](run.py)、[补充条件审计](audit.py)

复现实验入口为 `python run.py --output <新的空目录>`；`python audit.py` 会写入其指定的条件审计文件。既有 evidence 应保留，本报告的编写没有执行新的训练或覆盖这些文件。
