# 首达算子的稳定计算与学习保证边界

本说明对应本目录的 `kernels.py`、`oracle.py`、`validation.py` 和
`kernel_tests.py`。它说明本轮实际修复了哪些数值问题、哪些下降结论可以从
明确假设推出，以及这些结论不能延伸到哪些训练或系统场景。

本轮独立验收为 **67 个参数案例、946 项检查通过，12 个行为回归测试通过**。
完整结果保存在 `NUMERICAL_VALIDATION.json.gz`；修复前的七项失败保存在
`INITIAL_NUMERICAL_FAILURES.json.gz`。压缩是无损的，原始与压缩摘要见
`EVIDENCE_MANIFEST.json`。这些结果是声明域内的数值与事件合同证据，
不是所有浮点输入、任意神经网络或全局优化问题的证明。

## 1. 模型与四种不同的观察

在单个活动区间内，系数和障碍固定：

\[
X_t=x+\mu t+\sigma W_t,\qquad d=b-x>0,\qquad \sigma>0,
\]

\[
\tau=\inf\{t\geq0:X_t\geq b\},\qquad
R\sim\operatorname{Exp}(\lambda),\qquad R\perp W.
\]

这里的 `cancel_rate` 是独立终止率。一次终止结束当前合同；它本身不意味着
复位、再次排队或发出脉冲。后续动作属于单独的状态机。

未取消过程的首达密度与存活函数为

\[
f(t)=\frac{d}{\sigma\sqrt{2\pi t^3}}
\exp\!\left[-\frac{(d-\mu t)^2}{2\sigma^2t}\right],
\qquad S(t)=\Pr(\tau>t).
\]

在期限 \(T\) 内先触发的质量是

\[
H_\lambda(T)=\mathbb E[e^{-\lambda\tau}\mathbf1_{\{\tau\leq T\}}].
\]

本包区分以下观察：

| 观察 | 似然或质量 | 含义 |
|---|---|---|
| `hit`，事件时间 \(t>0\) | \(e^{-\lambda t}f(t)\) | 在这个时间先触发的密度 |
| `cancel`，事件时间 \(t\geq0\) | \(\lambda e^{-\lambda t}S(t)\) | 在这个时间先终止的密度 |
| `survive`，期限 \(T\) | \(e^{-\lambda T}S(T)\) | 两类事件均未发生 |
| `no_hit`，期限 \(T\) | \(1-H_\lambda(T)\) | 未观察到触发；取消可能发生且未被报告 |

事件密度具有时间单位，数值可以超过一；不能把其对数强制限制为非正。
`outcome_law` 返回的则是三个无量纲质量，次序为 `[hit, survive, cancel]`。

`distance == 0` 单独表示时刻零已经触界：`hit` 在时刻零有质量一的原子。
该原子不能使用普通 \(t>0\) 密度替代。`time == 0, distance > 0` 时，
合同尚未发生事件。取消密度在零时刻可有有限右极限，但在那里没有额外的概率原子。
零取消率下 `cancel` 不可能发生，似然为负无穷，其 score 明确拒绝。

## 2. 贴现首达量：有理化根与必须保留的微小漂移

令

\[
\kappa=\sqrt{\mu^2+2\lambda\sigma^2},\qquad
\beta=\frac{\kappa-\mu}{\sigma^2}.
\]

直接比较首达密度中的指数可得

\[
e^{-\lambda t}f_\mu(t)=e^{-\beta d}f_\kappa(t).
\]

因此

\[
H_\lambda(T)=e^{-\beta d}F_\kappa(T),\qquad
\log H_\lambda(T)=-\beta d+\log F_\kappa(T).
\]

当 \(\mu\geq0\) 时，直接计算 \(\kappa-\mu\) 会在小噪声或小取消率下
丢失有效位。代码改用

\[
\boxed{\beta=\frac{2\lambda}{\kappa+\mu}}.
\]

当 \(\mu<0\) 时，\(\kappa-\mu=\kappa+|\mu|\)，不存在同一种相减消去。
\(\mu=\lambda=0\) 的重根情形使用单独的有限时间极限。

### 2.1 只修复 \(\beta\) 仍然不够

浮点 \(\kappa\) 可能已经舍入成 \(|\mu|\)，但其差值在除以扩散尺度后
仍然会影响有限期限的触界概率。令

\[
\delta\kappa=\kappa-|\mu|
=\frac{2\lambda\sigma^2}{\kappa+|\mu|},
\]

\[
s=\frac{\delta\kappa\sqrt T}{\sigma}
=\frac{2\lambda\sigma\sqrt T}{\kappa+|\mu|}.
\]

`_tilted_arguments` 保留这个标准化位移，直接计算

\[
u_\kappa=\frac{d-|\mu|T}{\sigma\sqrt T}-s,
\qquad
v_\kappa=\frac{d+|\mu|T}{\sigma\sqrt T}+s.
\]

它不先用舍入后的 \(\kappa\) 去构造 \(d-\kappa T\)。概率和参数导数共用
这些保留位移的变量，避免前向与梯度采用两个不同的数值合同。

实际反例为 \(d=T=\mu=1,\sigma=10^{-8},\lambda=1\)。
此时 \(\delta\kappa\) 约为 \(10^{-16}\)，但标准化位移约为 \(10^{-8}\)。
忽略它得到的 \(\partial_\sigma H\) 约为 \(0.36690666\)，高精度参考则为
\(0.22014399660000702\)。修复同时关闭了概率、`no_hit` 似然和相应 score 的错误。

## 3. Mills 比率、补量与有限梯度

对 \(z\geq0\)，定义

\[
M(z)=\frac{\Phi(-z)}{\phi(z)}
=\int_0^\infty e^{-zu-u^2/2}\,du,
\]

\[
A(z)=1-zM(z)
=\int_0^\infty u e^{-zu-u^2/2}\,du>0.
\]

`_mills` 用缩放互补误差函数计算 \(M\)。`_mills_complement` 在大参数区间
直接计算 \(A\)，避免从两个接近一的数相减。其展开为

\[
M(z)\sim z^{-1}-z^{-3}+3z^{-5}-15z^{-7}+\cdots,
\]

\[
A(z)\sim z^{-2}-3z^{-4}+15z^{-6}-105z^{-8}+\cdots.
\]

这些是渐近级数，不能无限累加。将 \(e^{-u^2/2}\) 的有限 Taylor 展开代入
上述正积分，可为每个有限截断得到由首个遗漏项控制的余项界。代码在项开始
增大或小于当前和的舍入尺度时停止。这个解析余项事实不等同于全部浮点操作的
全域误差证书；舍入行为仍由声明案例和独立参考检验。

令

\[
h=\sigma\sqrt T,\qquad u=\frac{d-\mu T}{h},\qquad
v=\frac{d+\mu T}{h}.
\]

当 \(v\geq0\) 时，CDF 导数可稳定写为

\[
\partial_dF=-\frac{2\phi(u)}h
\left[A(v)+\frac d hM(v)\right],
\]

\[
\partial_\mu F=\frac{2d\phi(u)M(v)}{\sigma^2},
\]

\[
\boxed{\partial_\sigma F=
\frac{2d\phi(u)}{\sigma h}\left[A(v)+uM(v)\right]},
\qquad \partial_TF=f(T).
\]

在 \(d=\mu T\) 处，\(u=0\)。当 \(\sigma\to0\) 时，上式趋于有限值

\[
\partial_\sigma F\longrightarrow\frac{\phi(0)}{2\mu\sqrt T}.
\]

原始相减表达式的两个项却各为 \(O(\sigma^{-2})\)。对于 \(d=\mu=T=1\)，
正确极限是 \(0.1994711402007163\)；旧附件在 \(\sigma=10^{-8}\) 时曾返回
约 \(7.976\times10^{15}\)。本轮保留这个原始反例，未通过提高验收的噪声下界来回避它。

## 4. 存活尾部与隐藏取消的日志计算

### 4.1 存活概率不能普遍用浮点 \(1-F\) 获得

当 \(\mu\geq0,u<0\) 时，

\[
S(T)=\phi(u)\left[M(-u)-M\!\left(-u+\frac{2d}{h}\right)\right].
\]

差值可以通过正积分表示为

\[
M(z)-M(z+\delta)
=\int_0^\infty e^{-zu-u^2/2}(1-e^{-\delta u})\,du.
\]

实现保留 \(\delta\)，在小差值处用 `expm1`、尺度变换和正积分，在大 \(z\)
处使用逐项差值展开。这样不会先把两个接近的 Mills 比率各自舍入后再相减。

当 \(u\geq0,\mu\geq0\) 时，还可使用两个非负项：

\[
S(T)=\operatorname{erf}(u/\sqrt2)+\phi(u)[M(u)-M(v)].
\]

负漂移通过首达密度的漂移反转关系处理。`log_survival` 保留日志尾部，
而不是要求普通概率变量表示所有极小正数。

例如 \(d=T=\sigma=1,\mu=10\) 时，真实 \(S\) 约为
\(2.01602880130604\times10^{-20}\)，直接 `1 - F` 已变成零。
\(\mu=100\) 的对应案例中，\(\log S=-4909.936331684632\)，即使普通概率
下溢，日志结果仍有意义。

### 4.2 `no_hit` 不等于 `survive`

记 \(N=1-H_\lambda(T)\)。利用倾斜后的正漂移过程，可写成

\[
\boxed{N=(1-e^{-\beta d})+e^{-\beta d}S_\kappa(T)}.
\]

`log_no_hit` 对这两个非负项作 `logaddexp`，并用 `log1mexp` 处理第一项。
这两个代数分量不能分别解释成有限期限的实际取消质量和实际存活质量；
该恒等式的用途是稳定计算整个 \(N\)。

在 \(\lambda=0\) 时，代码直接返回原漂移下的 `log_survival`。这避免了先把
\(H\) 舍入为一，再从 `log1mexp(-0.0)` 错误得到负无穷。
实际观察到“两类事件均未发生”的日志似然仍然是
\(-\lambda T+\log S_\mu(T)\)，不能替换成 `log_no_hit`。

## 5. 稀有取消质量及有界小率近似

严格取消质量为

\[
C=\lambda\int_0^T e^{-\lambda t}S(t)\,dt.
\]

通常分支使用两个日志质量的稳定差：

\[
C=N\left[1-\exp(\log(e^{-\lambda T}S(T))-\log N)\right],
\]

其中括号由 `-expm1` 计算。不会无条件把两个接近一的普通概率相减，也不会
对一个很小的积分仅给宽松绝对误差，然后将其声称为高相对精度结果。

在 \(\lambda T<10^{-8}\) 的分支，代码使用有明确误差界的一阶量

\[
C_0=\lambda\mathbb E[\min(\tau,T)]
=\lambda\left(M_1+TS(T)\right),
\]

\[
M_1=\mathbb E[\tau\mathbf1_{\{\tau\leq T\}}]
=-\left.\partial_\lambda H_\lambda(T)\right|_{\lambda=0}.
\]

该分支是受控近似，不能写成另一个完全精确的闭式质量。误差证明如下。
因为 \(S(t)\) 非增，

\[
\int_0^T tS(t)\,dt\leq\frac T2\int_0^T S(t)\,dt.
\]

这一不等式可以将 \(t\) 与 \(T-t\) 配对直接证明。再由
\(0\leq1-e^{-\lambda t}\leq\lambda t\)，得到

\[
0\leq C_0-C
\leq\lambda^2\int_0^T tS(t)\,dt
\leq aC_0,\qquad a=\frac{\lambda T}{2}.
\]

只要 \(a<1\)，相对真实质量的严格界就是

\[
\boxed{\frac{C_0-C}{C}\leq\frac{a}{1-a}}.
\]

当前切换门限给出不超过约 \(5.000000025\times10^{-9}\) 的相对界。
相对真实 \(C\) 的严格界不能简写成 \(a\)。三个质量的和也不会被任意
归一化来掩盖误差；该近似带来的质量增加有上述独立界。

在 \(\mu=\lambda=0\) 的重根处，有限时间矩仍然有限。令
\(z=d/(\sigma\sqrt T)\)，则

\[
M_1=\frac{2d\sqrt T}{\sigma}\phi(z)A(z).
\]

这是实现单独的重根分支的原因。不能把无限期限解析式的根退化，当作有限期限
概率或导数必然发散的理由。

## 6. 参数学习的真实 score 与光滑域

对于已知距离、已知物理时间和正确事件类型，`score_event` 返回对
\((\mu,\sigma,\lambda)\) 的日志似然导数。以触发观察为例，令
\(r=d-\mu t\)，

\[
\nabla\log p_{\rm hit}(t)=
\left(\frac r{\sigma^2},
-\frac1\sigma+\frac{r^2}{\sigma^3t},-t\right).
\]

存活与取消观察满足

\[
\nabla\log p_{\rm survive}
=(\partial_\mu\log S,\partial_\sigma\log S,-t),
\]

\[
\nabla\log p_{\rm cancel}
=(\partial_\mu\log S,\partial_\sigma\log S,\lambda^{-1}-t).
\]

隐藏取消的 `no_hit` 则有

\[
\nabla\log N=-\frac{\nabla H_\lambda}{1-H_\lambda}.
\]

这些 score 属于这里明确定义的观察似然。它们不是把一个稳态电位密度插入
硬阶跃 backward 所得到的替代场。数据与可辨识性的完整讨论由本轮另一份
研究文档承担；本节不把“可计算 score”直接当作“数据足以辨识参数”。

### 6.1 可用的紧致光滑域

取凸紧参数域

\[
\Theta=[-M,M]\times[\sigma_{\min},\sigma_{\max}]
\times[\lambda_{\min},\lambda_{\max}],\qquad \sigma_{\min}>0.
\]

对普通活动观察另要求距离和正事件时间位于
\([d_{\min},d_{\max}]\)、\([t_{\min},T_{\max}]\)，其中下界为正。
即时触界和零期限合同由专门的离散分支处理，不放入内部光滑性论证。

如果数据中有取消事件，需令 \(\lambda_{\min}>0\)，或把 \(\lambda=0\)
作为无限损失边界处理；\(\log\lambda\) 在零点没有有限梯度。
对于不含取消观察且似然仍有定义的目标，可以保留零率边界，并使用有限时间极限。

在上述条件下，有限数据集的负日志似然及其有限阶导数连续，在紧集上有界；
因此存在有限的梯度 Lipschitz 常数 \(L\)。这是存在性结论，不代表本包已经
估计出一个对所有数据都实用的数值 \(L\)。极小的似然仍可能令这个常数很大。

对取消率，有限时间积分还给出直接的界：

\[
\partial_\lambda^kH_\lambda(T)
=(-1)^k\int_0^Tt^ke^{-\lambda t}f(t)\,dt,
\qquad |\partial_\lambda^kH_\lambda(T)|\leq T^k.
\]

概率导数有界不意味着日志 score 有统一的温和大小：它还要除以观察概率。
极罕见 `no_hit` 的取消率 score 可以真实超过浮点范围。数值验收保留其日志
概率，但明确排除了无法在 float 中表示的完整 score；没有把它改成零或伪造有限值。

### 6.2 投影梯度下降：可证的是驻点界

令 \(J\) 是该参数域上的一个可微、下界有限、\(L\)-smooth 的真实标量目标，
使用确定性精确梯度更新

\[
\theta_{k+1}=\Pi_\Theta(\theta_k-\eta\nabla J(\theta_k)),
\qquad
G_\eta(\theta_k)=\frac{\theta_k-\theta_{k+1}}\eta.
\]

投影最优性给出

\[
\nabla J(\theta_k)^T(\theta_{k+1}-\theta_k)
\leq-\frac1\eta\|\theta_{k+1}-\theta_k\|^2.
\]

与下降引理结合，

\[
J(\theta_{k+1})\leq J(\theta_k)
-\eta\left(1-\frac{L\eta}{2}\right)\|G_\eta(\theta_k)\|^2.
\]

因此，对于 \(0<\eta\leq1/L\)，

\[
\boxed{\min_{0\leq k<K}\|G_\eta(\theta_k)\|^2
\leq\frac{2[J(\theta_0)-\inf_\Theta J]}{\eta K}}.
\]

\(G_\eta=0\) 是约束一阶驻点条件。这个结论不要求目标凸，但也不保证
全局最优、参数唯一、每个迭代点收敛或模型在新任务上更好。

### 6.3 条件 SGD 结论

随机梯度必须满足明确的条件，例如

\[
\mathbb E[g_k\mid\theta_k]=\nabla J(\theta_k),\qquad
\mathbb E[\|g_k-\nabla J(\theta_k)\|^2\mid\theta_k]\leq v^2/B_k.
\]

这里 \(B_k\) 表示有效独立批量；相关事件不能未经检验就按独立样本除以批量。
对投影随机更新，同样取 \(\eta\leq1/L\)，利用投影的非扩张性可以得到一个
保守而充分的界：

\[
\frac1K\sum_{k<K}\mathbb E\|G_\eta(\theta_k)\|^2
\leq\frac{4[J(\theta_0)-\inf J]}{\eta K}
+\frac{8v^2}{K}\sum_{k<K}B_k^{-1}.
\]

证明要点是：随机梯度映射与精确梯度映射的距离不超过梯度噪声；条件期望下
噪声与精确映射的内积为零，剩余内积由噪声二阶矩控制。固定有限批量时，
这个界保留噪声项；若批量逐渐增加使平均 \(B_k^{-1}\) 趋于零，则给出
期望驻点意义的收敛。不能从这个界宣称固定批量下每个样本路径必然收敛。

若投影不活跃，普通无约束 SGD 的下降引理还给出常见的更精细式子：

\[
\frac1K\sum_{k<K}\mathbb E\|\nabla J(\theta_k)\|^2
\leq\frac{2[J(\theta_0)-\inf J]}{\eta K}+L\eta v^2/B.
\]

该式不能在不作额外论证时直接改名为任意投影、任意代理梯度或任意在线自适应
算法的保证。当前实验运行本身也不提供上述所有理论假设的自动验证。

### 6.4 这些结论不覆盖的训练

硬阶跃前向配人工 SG 的更新场不一定是某个标量目标的梯度，因此上述下降证明
不能直接应用。把参数仅放入 custom backward，也不会自动获得正确的参数学习。
真正元学习还需要对训练过程求外层导数；局部三参数似然的光滑性没有证明该
展开过程稳定。多层循环网络的 Jacobian、信用分配、状态分布漂移和非凸结构，
同样不由本包的局部核验证自动解决。

## 7. 终止率、复位率、资源价格与稳态形状

在本模型中

\[
\partial_\lambda H_\lambda(T)
=-\int_0^Tt e^{-\lambda t}f(t)\,dt\leq0.
\]

这只证明提高独立终止率会降低本次合同在期限内先触发的概率。
它没有证明提高 Poisson **复位**率会降低长期发放频率。

如果改成复位后不断重新尝试，令复位率为 \(r\)，同一起点的平均触发时间为

\[
m_r=\frac{\exp\{d(\sqrt{\mu^2+2r\sigma^2}-\mu)/\sigma^2\}-1}{r}.
\]

对于 \(\mu>0\)，

\[
m'_0=\frac{d^2\mu-d\sigma^2}{2\mu^3}.
\]

当 \(\sigma^2>d\mu\) 时，小量复位会提高频率。例子
\(d=\mu=1,\sigma=2\) 中，\(m_0=1\)，而 \(m_1=e^{1/2}-1\approx0.648721\)。
因此 `cancel_rate`、复位规则、触发后的不应期和资源约束的对偶价格必须分别建模。
资源价格乘以实际计量成本进入动作价值；它不是独立终止率的同义词。

同样，特征根

\[
\gamma_\pm=\frac{\mu\pm\sqrt{\mu^2+2r\sigma^2}}{\sigma^2}
\]

可以构成带源项、吸收边界和复位匹配条件的稳态占据密度。该密度描述状态上的
停留质量，通常在吸收障碍处为零。它没有起点和传播时长两个必要变量，不能
直接当作有限时间状态转移核，也不自动等于 \(\partial_xF\)。
readiness 必须说明用的是首达质量、存活条件下的风险率、还是某个价值量。

## 8. 独立参考、失败映射与实际验收范围

`oracle.py` 不导入主内核，包含三个参照层次：

1. Decimal 100 位加 40 位保护位的 Gaussian 中心积分级数和尾部连分数；
   参数导数用高精度五点差分，步长解析扩散宽度，包括 \(\sigma=10^{-8}\)。
2. 原始首达密度与吸收密度的正积分，独立核验三个事件质量。
3. 正、零、负漂移的精确 inverse-Gaussian/Levy 事件抽样，再与独立指数终止
   竞争；没有 Euler 时间网格或漏检触界误差。

第一层是对同一数学恒等式的独立高精度算术实现，不冒称另一个数学定理的证明。
第二、三层提供分布层面的独立参照。正积分使用明确的中等参数域和绝对误差；
它不替代尾部日志的相对精度检验。

首次对新内核的全面验证有 65 个案例、920 项检查，保存了七项失败：

| 失败记录 | 共同根因 | 最终修复 |
|---|---|---|
| `log_discounted_hit`，到达边界、\(\sigma=10^{-8}\) | \(\kappa-|\mu|\) 舍入丢失 | 保留标准化倾斜位移 |
| 同例 `outcome_law` | 上述 H 误差传入三质量 | 同一倾斜变量用于概率 |
| 同例 `discounted_derivatives` | 导数也使用了舍入后的漂移 | 前向与导数共用保留位移 |
| 同例 `likelihood_no_hit` | H 误差进入隐藏取消似然 | 正分量日志表示 |
| 同例 `score_no_hit` | H 与 H 导数共同传播误差 | 修复值与梯度两条路径 |
| `rare_mass_cancel`，\(\sigma=10^{-4},\lambda=10^{-12}\) | 求积漏掉期限附近窄层 | 有界小率近似 |
| `rare_mass_cancel`，\(d=10^{-8},\mu=50\) | 小质量的绝对求积误差过大 | 日志质量差与 `expm1` |

随后增加两个零取消率案例，覆盖极小 `no_hit` 日志，以及仍可表示但很大的取消率
score。最终 **67 案例、946 检查通过**；12 个行为测试也通过。验收包含
12 个正积分案例，以及三组各 120,000 次的精确事件抽样。

精确参数、绝对与相对容差、每条实际值及参考值都在 `NUMERICAL_VALIDATION.json`。
训练实验可以使用更窄的科学参数域；它不能据此抹掉这里保留的小噪声回归。
该证据没有扩展到移动障碍、一般状态依赖漂移、任意浮点输入、硬 SG 的无偏性、
全网络收敛、硬件净节能或生产激活资格。
