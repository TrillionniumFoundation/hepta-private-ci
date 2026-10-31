# Hepta Continuous Spiking Network：数学合同、解析算子与实现边界

本文规定当前研究模型中价值、事件、复位、状态与梯度的含义，并给出可独立复核的标量推导。核心对象是**具有内生触发边界、发放后延续价值与完整再生状态的连续数值网络**。He–Xiong 提供自由边界建模的方法启发；当前模型的随机过程、收益、复位和训练目标均需重新定义。

必须区分三个数学层次：无界 Brownian 标量控制问题有解析最优解；内容网络中的有限网格算子评估所选策略；新增有限状态 Bellman/QVI oracle 对自身声明的任务求最优解。三个层次之间不存在自动继承的最优性。本文是模型规范和推导，不证明所有任务的最优停止、架构优势或全球首次创新。

## 1. 从 He–Xiong 可以迁移什么

He、Xiong 的 *Rollover Risk and Credit Risk*, *The Journal of Finance* 67(2), 2012，以风险中性几何 Brownian 资产过程为状态。其式 (11) 可将金融利率另记为 \(r_f\)，写成

$$
r_f E=(r_f-\delta)V E_V+\tfrac12\sigma^2V^2E_{VV}
       +\delta V-(1-\pi_{\rm tax})C_{\rm debt}+d(V,m)-p_{\rm debt}.
$$

股权在违约时吸收终止，因此值匹配为 \(E(V_B)=0\)，最优违约边界满足 \(E_V(V_B)=0\)。原文 Proposition 1 指向股权解 (A7) 与违约边界式 (12)；附录使用对数状态和 Laplace 变换。[原文 PDF，式 (11)、Proposition 1 与附录 A](https://www.princeton.edu/~wxiong/papers/rollover.pdf)

可迁移的方法是：用生成元建立价值方程，将触发边界与价值共同求解，利用首达/Laplace 结构，并在适用条件下用值匹配、光滑贴合确定边界。神经元发放后继续运行，必须另写复位与不应期的延续算子。金融股权或债权的解析式不能只改变量名就成为新神经元的解析解。

本文以下 \(r\) 专指**复位状态**，\(\rho\) 是模型时间的折现率；\(C,P\) 专指事件统计。它们均不同于上式的金融利率、票息和债务本金。有限模型中的 \(J,G\) 分别是策略价值与干预价值，不是字面意义的金融 Call/Put，也不是已定义的机械恢复力或恐慌力。若要引入“力”，还需另外声明它如何进入状态方程、符号与单位；仅给一个价值函数并没有完成这一步。

## 2. 条件信息、时间与六符号合同

所有量均以已经接收的信息 \(\mathcal I_k\) 和完整当前状态为条件。一次网络读入可以使用当前输入、已知时长、既往内容状态及既往物理状态，不使用未来观测或隐藏标签。内容实现根据当前读入确定局部系数，并在声明的传播区间内冻结它们；这是模型定义，不代表真实数据在该区间恰好服从同一扩散。

区分三种时间：输入的序列时长 \(\Delta t\)，物理过程的模型时间 \(h=0.1\Delta t\)，以及程序运行的 CPU/wall 秒。native owner 的 READ/tick 又是执行计数。它们不互相替代；所有概率视窗与折现都必须注明采用哪个时间。[内容模型](content/models.py)、[物理时标与保留状态](../hcsn_distributional_v2/model.py)

令 \(S_j\) 为从当前起算的第 \(j\) 次发放时刻，

$$
N(h)=\sum_{j\ge1}\mathbf1\{S_j\le h\},\qquad T_1=S_1.
$$

若初态已经应当立即发放，\(S_1=0\)，该原子计入 \(N(0)\)。普通阈下活动初态则没有零时刻原子。

| 符号 | 固定含义 | 范围与单位 |
|---|---|---|
| \(C(h)\) | \(\mathbb E[N(h)\mid\mathcal I_k]\) | 期望次数，可大于 1 |
| \(P(h)\) | \(\Pr[N(h)\ge1\mid\mathcal I_k]\) | \([0,1]\) |
| \(F(h)\) | 指定初态、冻结系数与边界下首达时间的 CDF | \([0,1]\)，初态与事件必须明确 |
| \(f(t)\) | 首达分布的绝对连续密度部分 | 模型时间的倒数；原子另计 |
| \(H_\rho(h)\) | \(\mathbb E[e^{-\rho T_1}\mathbf1\{T_1\le h\}\mid\mathcal I_k]\) | 无量纲折现权重，\(0\le H_\rho\le P\) |
| \(K\) | 单次发放收益 \(x-K\) 中的即时成本 | 与收益相同单位；不是概率或转移核 |

\(P=F\) 只在两者使用同一初态、同一首次事件、不应期与边界原子约定时成立。一般有 \(C\ge P\)，但不能以 \(C\) 代替概率。存活条件下的瞬时风险率是 \(f(t)/(1-F(t))\)，也不同于 \(f\) 或 \(H\)。在实际内容网络中，物理概率质量并未被证明是任务标签后验；后文另建的带标签任务才明确赋予状态后验含义。

## 3. 标量再生模型：先定义发放后的世界

活动态服从算术 Brownian 过程

$$
dX_t=\mu\,dt+\sigma\,dW_t,
\qquad \mathcal L=\mu\partial_x+\tfrac12\sigma^2\partial_{xx},
$$

其中 \(\sigma>0,\rho>0,r<K\)。发放时取得 \(X_{S_j}-K\)，随后状态置为 \(r\)，经历独立同分布的不应期 \(T_{\rm ref}\ge0\)，再从 \(r\) 开始新的活动周期。不应期内没有新发放、活动扩散、观测或收益。若改成“不应期内继续扩散”，下面的 \(D J(r)\) 就必须替换，现有公式不能直接使用。

定义

$$
D=D(\rho)=\mathbb E[e^{-\rho T_{\rm ref}}]\in(0,1],
\qquad
J_*(x)=\sup_{\pi}\mathbb E_x\left[
\sum_{j\ge1}e^{-\rho S_j}(X_{S_j}-K)\right].
$$

策略依赖可获得信息，且排除有限时间内无限干预等不容许策略。当前标量合同没有活动期运行收益。其干预算子为

$$
(\mathcal M J)(x)=x-K+D J(r),
$$

相应 QVI 为

$$
\max\{\mathcal LJ-\rho J,\ \mathcal MJ-J\}=0.
\tag{R1}
$$

这里第二项保留全部未来复位周期。删掉 \(D J(r)\) 会得到另一种单次停止问题。代码中 `oracle.py` 的原标量接口使用确定不应期；内容模型以等效折现时长接入 Erlang 不应期，具体区别见第 5 节。[标量 oracle](../hcsn_free_boundary_v1/oracle.py)

## 4. 从首达变换推导自由边界与双价值算子

### 4.1 固定阈值策略的价值

先固定一个上触发边界 \(b>\max(K,r)\)，而不先宣称它最优。令

$$
\omega=\sqrt{\mu^2+2\rho\sigma^2},\qquad
\beta=\frac{-\mu+\omega}{\sigma^2}>0.
$$

\(\beta\) 是 \(\tfrac12\sigma^2\beta^2+\mu\beta-\rho=0\) 的正根。若 \(\mu\ge0\)，数值上宜用等价式 \(\beta=2\rho/(\omega+\mu)\)，避免相近数相减。对 \(x<b\)，固定边界首达时刻 \(T_b\) 满足

$$
\mathbb E_x[e^{-\rho T_b}\mathbf1\{T_b<\infty\}]
=e^{\beta(x-b)}.
$$

于是固定阈值策略 \(\pi_b\) 的价值满足

$$
J^{\pi_b}(x)=e^{\beta(x-b)}\{b-K+D J^{\pi_b}(r)\}.
$$

记 \(q=D e^{\beta(r-b)}<1\)，解得

$$
J^{\pi_b}(b)=\frac{b-K}{1-q},\qquad
J^{\pi_b}(x)=\frac{b-K}{1-q}e^{\beta(x-b)},\quad x<b.
\tag{R2}
$$

同一策略的即时干预价值定义为

$$
G^{\pi_b}(x)=x-K+D J^{\pi_b}(r).
\tag{R3}
$$

\(J^{\pi_b}\) 包含按该策略等待和之后的全部发放；\(G^{\pi_b}\) 表示现在发放、之后继续该策略。\(J^{\pi_b}\) 不是“继续一次”的动作 Q 值。对任意次优策略，也不能预设 \(J^{\pi_b}-G^{\pi_b}\ge0\)。

### 4.2 再生边界条件

最优候选满足

$$
J(b^-)=G(b)=b-K+D J(r),\qquad J_x(b^-)=G_x(b)=1.
\tag{R4}
$$

第二式的 1 来自即时收益 \(x-K\) 的斜率；复位点固定，所以延续项不依赖当前 \(x\)。这解释了它与金融吸收违约的零斜率边界为何不同。

将 (R2) 代入 (R4)，得到

$$
\boxed{\Psi(b)=\beta(b-K)-1+D e^{\beta(r-b)}=0.}
\tag{R5}
$$

因为

$$
\Psi(K)<0,\quad \Psi(K+1/\beta)>0,\quad
\Psi_b=\beta(1-q)>0\quad(b>K),
$$

容许根唯一，并且 \(K<b<K+1/\beta\)。令

$$
a=D e^{\beta(r-K)}\in(0,1),\qquad y=\beta(b-K),
$$

则 \((y-1)e^{y-1}=-a/e\)，因此具有闭式

$$
\boxed{
b=K+\frac{1+W_0\!\left(-D e^{\beta(r-K)-1}\right)}{\beta}.
}
\tag{R6}
$$

必须取 Lambert \(W\) 的实主支 \(W_0\)。它给出 \(0<y<1\)；另一实支 \(W_{-1}\) 不给出 \(b>K\) 的容许解。实现不必直接求 Lambert 函数：在 \(y\in(0,1)\) 上求

$$
y+\operatorname{expm1}\{\log D+\beta(r-K)-y\}=0
$$

可避免接近退化参数时的 \(1-\exp(\cdot)\) 消减误差。现有实现采用有界求根与隐式反传。[数值根与 backward](../hcsn_free_boundary_v1/oracle_torch.py)

### 4.3 最优值与验证范围

在上述根处 \(J(b)=1/\beta\)，从而

$$
J_*(x)=
\begin{cases}
\beta^{-1}e^{\beta(x-b)},&x<b,\\
x-b+\beta^{-1},&x\ge b,
\end{cases}
\qquad
G_*(x)=x-b+\beta^{-1}.
\tag{R7}
$$

仅求出值匹配与光滑贴合还不足以证明最优。这里可以继续检验：对 \(z=\beta(x-b)<0\)，

$$
J_*(x)-G_*(x)=\frac{e^z-1-z}{\beta}\ge0,
\qquad (\mathcal L-\rho)J_*(x)=0.
$$

在 \(x\ge b\) 区域，\(J_*=G_*\)，且

$$
(\mathcal L-\rho)J_*=
-\tfrac12\sigma^2\beta-\rho(x-b)\le0.
$$

候选值非负且至多线性增长；固定复位不能把状态推到任意高处，\(\rho>0\) 时 Brownian 增长对应的折现尾项消失。在所声明的非爆炸容许策略类上，对候选值作局部化 Itô 验证，QVI 不等式给出所有策略的上界，阈值策略处取得等号，从而得到这个无限时域、固定参数、固定复位问题的验证。该值函数为 \(C^1\)、分段 \(C^2\)，在边界通常不是 \(C^2\)。上述结论不适用于任意分类损失，也不自动适用于输入持续改变系数、有限下边界或不同复位规则的模型。

### 4.4 双价值通道不等于两份独立信息

固定同一组参数并令安全距离 \(m=b-x>0\)，由 (R7) 直接得到

$$
G_*(x)=\beta^{-1}-m,\qquad
J_*(x)=\beta^{-1}e^{-\beta m}
       =\beta^{-1}\exp\{\beta G_*(x)-1\}.
$$

因此，在这个固定参数的阈下标量问题中，给定 \(\beta\) 后，\(J\) 和 \(G\) 是同一个安全距离的确定变换；两个通道没有产生两份独立输入信息。阈上区域则有 \(J=G\)。这不排除某种特征变换更利于优化或近似，但这种收益需要相对于同信息、同容量的普通非线性特征检验。单凭两个解析表达式，不能推导更大的有效记忆容量或更强的内容寻址能力。

价值也不会自动规定反馈力的方向。在阈下区域，\(J_x=e^{\beta(x-b)}>0\)、\(G_x=1>0\)；将它们的梯度以正号或负号接入状态方程，会定义不同的动力学。恢复或再生的符号、稳定性及作用单位都需要另行规定，不能由 Call/Put 名称决定。当前内容实现将价值特征接入有界门控，并没有把上述两条导数声明为生物膜电位的两种力。

若状态是分布，则通常 \(\mathbb E[J(X)]\ne J(\mathbb E[X])\)，非线性价值期望可能包含均值不能表示的分布信息。不过，当前内容对照的普通物理门控同样收到完整活动／不应期质量与物理参数，因此比较的是特征表示的贡献，不是某一 arm 独占隐藏信息。第 8 节有限网格、反射下界及不应期值向量定义了另一组策略价值；不能直接把本小节的标量恒等式套在那些期望特征上。

### 4.5 光滑贴合使价值差在边界处二阶消失

同一标量最优问题中，记等待相对立即发放的价值差为 \(A(x)=J_*(x)-G_*(x)\)。在 \(x<b\)、\(m=b-x\) 时，

$$
A(x)=\frac{e^{-\beta m}-1+\beta m}{\beta}
=\frac{\beta m^2}{2}+O(m^3),\qquad
A_x(x)=e^{-\beta m}-1=-\beta m+O(m^2).
$$

因此 \(A\) 在阈下为正、到边界时趋于零，阈上干预区内恒为零；它不是一个会自动穿过正负号的有符号脉冲信号。光滑贴合同时令 \(A_x(b)=0\)。若直接以这个价值差作为触发强度，边界附近的状态梯度会衰减，不能仅凭“消除了阶跃函数”就断言梯度更强或训练更容易。

这一推论仅涉及固定参数下的标量最优价值差。内容网络中的有限网格策略价值、输入驱动边界、分布期望，以及阈值化后的实际 KEEP/STOP 都需要分别分析；它们不自动继承上述符号与局部展开。当前原生绑定采用单独登记的工程停止目标，也没有声称 \(J-G\) 已经等于内容任务的分类停止优势。

## 5. 不应期分布与可训练边界

### 5.1 确定等待与 Erlang 等待

确定不应期 \(T_{\rm ref}=\tau\) 给出

$$
D_{\rm det}=e^{-\rho\tau}.
$$

若有 \(m\) 个连续 Erlang 阶段，每阶段速率 \(m/\tau\)，则 \(\tau>0\) 是**均值**，

$$
D_m=(1+\rho\tau/m)^{-m},\qquad
\tau_{\rm eff}=-\frac{\log D_m}{\rho}
=\frac m\rho\log(1+\rho\tau/m).
\tag{R8}
$$

把 \(\tau_{\rm eff}\) 送入确定延迟边界函数，能够精确匹配这里的无限时域折现因子。它不把随机等待变成确定等待，也不匹配有限时域事件时间分布。有限 \(m\) 时 \(D_m>e^{-\rho\tau}\)，且 \(m\to\infty\) 时趋向确定等待。实际内容实现固定 \(m=2\)，有限 QVI 同样显式登记阶段数。[内容参数化](content/models.py)、[有限 QVI 合同](oracle/finite_qvi.py)

### 5.2 隐式梯度

令

$$
B=(b-K)+q(r-b),\qquad q=D e^{\beta(r-b)}.
$$

对独立参数 \(\theta\)，在固定 \(b\) 下求偏导后，边界总导数为

$$
\boxed{
b_\theta=-\frac{
B\beta_\theta-\beta\mathbf1_{\theta=K}
 +\beta q\mathbf1_{\theta=r}+q(\log D)_\theta
}{\beta(1-q)}.
}
\tag{R9}
$$

其中

$$
\beta_\mu=-\beta/\omega,\qquad
\beta_\sigma=-\sigma\beta^2/\omega,\qquad
\beta_\rho=1/\omega.
$$

确定等待时 \((\log D)_\rho=-\tau\)、\((\log D)_\tau=-\rho\)；Erlang 等待时

$$
(\log D_m)_\rho=-\frac{\tau}{1+\rho\tau/m},\qquad
(\log D_m)_\tau=-\frac{\rho}{1+\rho\tau/m}.
$$

例如，独立固定其余物理参数时，\(b_K=1/(1-q)\)、\(b_r=-q/(1-q)\)；确定等待的 \(b_\tau=\rho q/[\beta(1-q)]\)。若神经网络通过共享参数同时改变多个物理量，必须把这些项全部接入链式法则。使用 \(\tau_{\rm eff}(\rho,\tau)\) 时，也不能遗漏其对 \(\rho\) 的依赖。

\(r<K\) 与 \(\rho,\sigma>0\) 保证当前非退化根的隐式导数存在；但 \(q\to1\) 时分母趋小，数值条件变差。现有自定义根 backward 只实现一阶导数，没有认证高阶微分。固定整数阶段数 \(m\) 也不是一个连续可微训练参数。

## 6. 有限时域首达解析式：\(f,F,H\) 各自解决什么

现在固定活动初态 \(x<b\)、系数与边界。记距离 \(d=b-x>0\)、视窗 \(h>0\)，\(\Phi\) 为标准正态 CDF。首达连续密度为

$$
f_d(t)=\frac{d}{\sigma\sqrt{2\pi t^3}}
\exp\!\left[-\frac{(d-\mu t)^2}{2\sigma^2t}\right],\quad t>0,
\tag{E1}
$$

CDF 为

$$
F_d(h)=\Phi\!\left(\frac{\mu h-d}{\sigma\sqrt h}\right)
 +e^{2\mu d/\sigma^2}
  \Phi\!\left(\frac{-\mu h-d}{\sigma\sqrt h}\right).
\tag{E2}
$$

折现首次事件权重为

$$
H_{\rho,d}(h)=\int_0^h e^{-\rho t}f_d(t)\,dt
=e^{-\beta d}F_d(h;\mu\leftarrow\omega),
\tag{E3}
$$

即

$$
H_{\rho,d}(h)=
e^{(\mu-\omega)d/\sigma^2}\Phi\!\left(\frac{\omega h-d}{\sigma\sqrt h}\right)
+e^{(\mu+\omega)d/\sigma^2}\Phi\!\left(\frac{-\omega h-d}{\sigma\sqrt h}\right).
$$

这可由指数倾斜直接验证：\(e^{-\rho t}f_d(t;\mu)=e^{-\beta d}f_d(t;\omega)\)。因此 \(H\le F\)，并有 \(H_{\rho,d}(\infty)=e^{-\beta d}\)。若 \(\mu<0\)，首达可能永不发生，\(F_d(\infty)=e^{2\mu d/\sigma^2}<1\)；\(\mu\ge0\) 时该极限为 1。实现使用 log-CDF 与 `expm1` 处理尾部，不应把极小概率裁掉后再冒称解析精确。[首达源码](../hcsn_free_boundary_v1/oracle.py)

**终点事件不同。** 未复位自由扩散的

$$
\Pr(X_h\ge b)=\Phi\!\left(\frac{\mu h-d}{\sigma\sqrt h}\right)
$$

只包含 (E2) 的第一项。路径可能先越界再返回，故终点越界不能代替区间首达；存在复位后，终点状态还要按再生模型重新计算。

**原子不能丢失。** 若 \(x\ge b\)，约定立即发放，\(T_1=0\)，所以任意 \(h\ge0\) 都有 \(F=H=1\)，但连续密度 (E1) 不表示这一 Dirac 原子。若 \(x<b,h=0\)，两者为 0。\(\sigma=0\) 的确定首达属于另一个退化合同，不能直接把零代入这些含 \(\sigma\) 的分母。

初态若正在不应期，不能使用活动初态的 (E2)。令剩余不应期为 \(R\)，应有

$$
F_{\rm ref}(h)=\mathbb E[\mathbf1_{R\le h}F_{b-r}(h-R)],
\quad
H_{\rm ref}(h)=\mathbb E[e^{-\rho R}\mathbf1_{R\le h}H_{\rho,b-r}(h-R)].
$$

混合初态还需对活动与各不应期状态分别加权。输入更新导致边界突然下降时，被新边界覆盖的原活动质量构成即时事件质量；这是另一类边界原子，不能仅靠区间内的连续密度补出。

## 7. 重复发放是 renewal 问题，不是一次 CDF

对固定边界、活动初态 \(x<b\)，令初次首达密度为 \(f_{b-x}\)，之后每个完整周期的等待分布为

$$
g=\operatorname{Law}(T_{\rm ref})*\operatorname{Law}(T_{b-r}),
$$

其中星号表示时间卷积。总事件强度密度的 renewal 展开为

$$
u_x(t)=f_{b-x}(t)+(f_{b-x}*g)(t)
 +(f_{b-x}*g*g)(t)+\cdots,
\quad C_x(h)=\int_0^h u_x(t)\,dt.
\tag{E4}
$$

而同一初态的至少一次概率始终是 \(P_x(h)=F_{b-x}(h)\)。因此高频再生时可以有 \(C_x(h)>1\)，并不违反概率约束。

确定不应期 \(\tau\) 下，各次 Brownian 首达时间的 Laplace 变换相乘，相当于相加首达距离，得到

$$
C_x(h)=\sum_{n\ge1}
F_{d_n}\bigl(h-(n-1)\tau\bigr),
\quad d_n=(b-x)+(n-1)(b-r),
\tag{E5}
$$

其中负视窗项取 0；活动初态的零视窗项也为 0。该固定策略在有限视窗内的折现发放收益为

$$
V^{\pi_b}_h(x)=(b-K)\sum_{n\ge1}
e^{-\rho(n-1)\tau}
H_{\rho,d_n}\bigl(h-(n-1)\tau\bigr).
\tag{E6}
$$

(E6) 不是重新优化有限终止时域后得到的价值，也没有在终点额外附加剩余价值。随机不应期则须对相应随机延迟卷积，不能直接把 \(\tau\) 的均值塞入 (E5)。当前首达和 renewal 参考实现分别保留这些合同；其级数截断界也不等于区间浮点证明。[有限时域固定策略参考](../hcsn_free_boundary_v1/oracle.py)

## 8. 内容神经元实际保留的状态与算子

### 8.1 完整状态

当前一层的持久状态包含

$$
s_k=(e_k,\ h_k,\ \boldsymbol p_k,\ b_k),
$$

其中 \(e_k\) 是 elapsed，\(h_k\) 是内容向量；每个物理通道的 \(\boldsymbol p_k\) 包含全部活动网格质量和不应期阶段质量，\(b_k\) 是上一步边界。实际配置有 8 个活动单元和 2 个 Erlang 阶段。只保存均值、一次发放概率或一个 cooldown 标量，不能恢复同一个分布过程；只传边界或安全距离，也不足以区分具有相同边界的不同内容与概率状态。[分布状态实现](../hcsn_distributional_v2/model.py)、[精确字段序列化](execution_binding/state_io.py)

这里的不应期限制物理通道的发放，不会使整个内容网络停止接收输入。内容向量仍按神经递推更新，各物理通道也可能同时包含活动与不应期的概率质量。第 3 节标量控制问题的“等待期间无观测”不能被误读成当前内容网络执行层面的全局冻结。

输入经内容前端产生局部漂移及门控信息；扩散、折现、成本、复位和不应期具有受约束的可训练参数。边界从这些参数计算。活动区间为 \([-2,b)\)，下端反射；边界变化使用声明的网格质量重映射。被降低边界扫过的质量立即发放，之后仍可在剩余区间内经历不应期、复位和再次发放。

对冻结生成元 \(Q_{\rm full}\)，完整再生传播在数学上为

$$
\boldsymbol p(h)=\boldsymbol p(0)e^{hQ_{\rm full}},
\quad
C(h)=\boldsymbol p(0)\int_0^h e^{tQ_{\rm full}}\lambda\,dt,
$$

其中 \(\lambda\) 是发放事件率向量；有边界重映射时还要加入其即时事件质量。当前代码用有界 uniformization 多项式与分块计算，并声明截断和舍入处理，因此不把实际浮点结果称为无误差矩阵指数。单位质量舍入修正只适用于再生分布，不能用于下一小节的被杀死过程。[网格与再生算子](../hcsn_distributional_v2/distribution_kernel.py)、[加速实现](../hcsn_conservative_acceleration_v1/kernel.py)

### 8.2 网格上的 \(J/G\) 是自身策略评估

记网格首次出口的无限时域折现变换为 \(h_i\)，复位插值权重为 \(w\)，\(h_r=w^\top h\)。给定边界策略的活动态价值是

$$
J_i^{\pi_b}=h_i\frac{b-K}{1-D_m h_r},\qquad
J_r^{\pi_b}=w^\top J^{\pi_b},\qquad
G_i^{\pi_b}=x_i-K+D_mJ_r^{\pi_b}.
\tag{N1}
$$

剩余 \(j\) 个不应期阶段的价值为

$$
J_{{\rm ref},j}=\left(\frac{m/\tau}{m/\tau+\rho}\right)^jJ_r^{\pi_b}.
$$

不应期内禁止干预，代码把该域的 \(G\) 设为同一个强制延续值 \(J\)。网络使用完整 \(\boldsymbol p\) 对两组值向量求期望，得到 `policy_J` 与 `policy_G`，再参与内容门控。[`policy_value_vectors`](../hcsn_distributional_v2/distribution_kernel.py)、[内容通道](content/models.py)

这里的有限网格有反射下边界、离散空间、复位插值和随机不应期。即使输入 \(b\) 来自 (R6)，(N1) 也只是此网格上的固定策略价值；它没有执行对所有可行动作的 Bellman 最大化。有效延迟匹配仅匹配 \(D\)，不消除这些差别。

### 8.3 下一次事件的有限状态 \(F/H\)

要计算“首次以后发放”，从完整生成元中移除发放后进入第一个不应期阶段的那条边，同时保留相应对角退出损失，构造被杀死生成元 \(Q_{\rm kill}\)。已有不应期质量仍按原阶段链完成，然后重新活动；但此后第一次发放即被杀死，不再复位。

若初始分布已排除即时原子，\(\lambda=-Q_{\rm kill}\mathbf1\)，则

$$
F(h)=1-\boldsymbol p e^{hQ_{\rm kill}}\mathbf1
=\boldsymbol p\int_0^h e^{tQ_{\rm kill}}\lambda\,dt,
\quad
H_\rho(h)=\boldsymbol p\int_0^h e^{t(Q_{\rm kill}-\rho I)}\lambda\,dt.
\tag{N2}
$$

禁止将残余存活质量重新归一化，否则会抹去已发生事件的概率。`value_fh` 对当前读入后的状态，使用同一读入所声明的物理时长作为预测窗，并冻结当前系数计算下一事件预测；它不是在不知道未来输入时精确预测未来所有系数变化。[`first_event_vectors`](content/models.py)、[独立密集矩阵与梯度核验](audits/first_event_independent.py)

## 9. 与标签收益一致的有限最优 Bellman/QVI

为了得到真正任务一致的控制值，新增 oracle 固定可观测节点 \(i\)、生成元 \(Q\)、活动期收益率 \(\ell_i\)、发放收益 \(g_{a,i}\)、复位分布 \(w\) 及 Erlang 折现 \(D\)。最优值 \(U\) 满足

$$
\max\left\{\ell_i+(QU)_i-\rho U_i,
\ \max_a[g_{a,i}+Dw^\top U-U_i]\right\}=0.
\tag{Q1}
$$

选择 \(\Lambda\ge\max_i(-Q_{ii})\)、\(R=I+Q/\Lambda\)，其 Bellman 动作值为

$$
Q_{{\rm KEEP},i}(U)=\frac{\ell_i+\Lambda(RU)_i}{\rho+\Lambda},
\qquad G_{a,i}(U)=g_{a,i}+Dw^\top U.
$$

\(TU=\max(Q_{\rm KEEP},G_1,\ldots)\)。对该实现要求的 \(\rho>0,\tau>0\)，

$$
\gamma=\max\{\Lambda/(\rho+\Lambda),D\}<1,\qquad
\|v-U_*\|_\infty\le\frac{\|Tv-v\|_\infty}{1-\gamma}.
\tag{Q2}
$$

主求解器用策略迭代；独立参考使用全部动作不等式的线性规划和 Bellman 值迭代。这里的边界是动作集合或动作价值差的零集合，不能额外强加连续扩散的 smooth-pasting。[有限最优求解器](oracle/finite_qvi.py)、[独立参考](oracle/reference_solvers.py)

具体标签任务令节点 \(p_i=\Pr(Y=1\mid\mathcal I_t)\)。在均匀网格上定义

$$
Q_{i,i+1}=Q_{i,i-1}=\frac{2a^2p_i^2(1-p_i)^2}{\Delta p^2},
\quad Qp=0,
$$

端点吸收；继续的收益率为 \(-c\)，预测 0/1 的即时收益分别是 \(1-p_i-K\)、\(p_i-K\)。它们正是实际正确分类奖励 \(\mathbf1\{\widehat Y=Y\}-K\) 的条件期望。发放后经过不应期，从复位先验开始独立的新标签任务。

标签条件生成元由 Doob 变换给出：\(h_1(p)=p,h_0(p)=1-p\)，对有正条件概率的状态，\(Q^y_{ij}=Q_{ij}h_y(p_j)/h_y(p_i)\)。另外建立隐藏标签 × 活动节点 + 不应期的展开 CTMC，以实际正确/错误奖励独立评估策略，检查它与后验值一致。[任务生成模型](oracle/task_model.py)

该最优性只覆盖这个明确有限任务。selective copy、MQAR、真实音视频或其他内容任务需要自己的充分状态、收益与控制合同；不能把仿射 \(x-K\) 或这里的后验值直接改名为那些任务的正确分类价值。节点外插值在当前 oracle 中表示随机选中相邻**可观测**节点后的价值期望，不等价于重新求解一个节点身份未观测的混合状态决策问题。

## 10. BP 可以穿过哪些部分，哪些地方仍然分段

连续期望和有限状态概率传播允许内容损失对内容、动力学、成本/边界、复位和不应期参数求梯度，无需对每一次抽样 0/1 脉冲直接求普通导数。但这不意味着“没有 step 输出”就使整个系统处处光滑。

| 部件 | 可用梯度 | 限制 |
|---|---|---|
| 非退化标量根 | (R9) 的隐式梯度 | \(q\to1\) 条件变差；当前仅一阶 |
| 冻结生成元的传播与价值线性求解 | 矩阵/多项式计算与线性系统微分 | 只对声明数值模型成立；不消除截断误差 |
| 复位插值、移动网格重映射 | 固定插值单元内的分段导数 | 网格节点和覆盖集合切换可能无唯一双侧导数 |
| 有限最优策略 | 严格固定活动集合内的隐式导数 | 不跨 `argmax` 切换面声称全局光滑 |
| native KEEP/STOP | 已训练连续消息的执行接口 | 硬动作本身不自动成为可普通反传的分类最优控制器 |

固定策略集合 \(\pi\) 时，线性方程 \(A_\pi(\theta)U=b_\pi(\theta)\) 给出

$$
U_\theta=A_\pi^{-1}\{(b_\pi)_\theta-(A_\pi)_\theta U\}.
\tag{Q3}
$$

数值梯度核验必须在每个扰动后重新求最优策略，并检查活动集合是否稳定。现有 Torch bridge 输出 \([J,Q_{\rm KEEP},G_0,G_1]\)，实现一阶隐式反传；切换面、插值节点及高阶导数均有明确限制。[Torch bridge](oracle/torch_bridge.py)

已有有限任务在 \(p=.375\)、不应期均值约 \(.6497384304\) 附近发生策略切换，两侧复位价值对不应期的导数约为 \(-5.03510\) 与 \(-4.76375\)。这项保留结果直接否定全局光滑推断；光滑贴合只约束适用连续问题的特定状态边界。[数学状态与原始结果入口](oracle/MATH_AND_STATUS_ZH.md)

## 11. 已有反例、普通阈值对照与证据范围

**解析边界不能自动继承网格最优性。** 旧审查在 5 组参数、8/32/128 活动单元上，找到使有限网格价值相对解析阈值提高最多 **4.6050991%** 的可行阈值。比率定义为

$$
\frac{J_{\rm sampled}-J_{\rm analytic}}{|J_{\rm analytic}|}.
$$

这给出解析阈值次优程度的一个下界；它不是分类准确率损失，也不是全局最优价值差的精确测量。新增固定网格 QVI 求解了另一个有明确合同的问题，不会消除旧反例。[固定提交上的旧数学说明](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1d959d8d82091e6014b13c2191f62bf74e778561/experiments/hcsn_conservative_acceleration_v1/reports/MATHEMATICAL_STATUS_ZH.md)

**任务最优不等于架构独占。** 新增后验任务的全部 20 个任务/网格组合中，普通双阈值规则精确表达了最优动作集合与价值。在标准 33 节点问题中，最优再生值与该普通规则同为约 \(4.9404162131\)；优化时遗漏后续周期的单次停止策略，在相同真实再生任务内只有约 \(3.0704411247\)。这说明延续项会影响决策，却没有证明双价值通道或价值边界优于充分表达同一策略的普通阈值。[新 oracle 结果](oracle/MATH_AND_STATUS_ZH.md)、[最终本地数学记录](oracle/results/local003/RESULTS.json)

**当前内容模型传播的是期望事件与概率质量。** 它没有因此自动生成生物神经元的抽样脉冲，也没有从数学上获得事件稀疏执行收益。固定宽度和固定网格能够保持持久推理状态不随序列长度增长；实际延迟、训练内存、矩阵算子成本、输入输出缓存、native 日志和能耗仍须完整测量。内容状态的离散更新也不因其内部有 CTMC 就变成任意细分时间下不变的精确连续半群。

**训练和执行的证据必须分别标注。** 联合可微路径需要梯度与参数更新证据；机制收益需要冻结、边界和双通道对照；内容收益需要预先固定任务与强基线；执行收益需要真实 checkpoint、持久恢复、实际消息动作及完整成本。当前执行绑定为指定 checkpoint 预先固定了这些工程检查，但其消息阈值实验不声称分类最优停止。[内容设计](content/DESIGN.json)、[执行绑定设计](execution_binding/PROTOCOL.json)、[硬件计量设计](hardware/HARDWARE_DESIGN.json)

本文没有加入尚未完成或尚未审核的内容、AV、GPU 或能耗结果。是否优于 Transformer、传统 SNN 或其他连续状态模型，应由相同信息、参数容量和完整预算下的已封存比较决定；解析可解性本身不能替代这些比较。

## 12. 复现与文件导航

本文公式直接从第 3 节合同推导；Lambert 主支由唯一容许区间确定，未另起大型数值试验。已有实现和证据按以下入口分别复核，避免把不同问题的“通过”混为一项结论。

| 要核对的对象 | 实现或合同 | 证据入口 |
|---|---|---|
| 标量最优根、首达、有限时域固定策略 | [oracle.py](../hcsn_free_boundary_v1/oracle.py)、[oracle_torch.py](../hcsn_free_boundary_v1/oracle_torch.py) | [本轮数学说明](oracle/MATH_AND_STATUS_ZH.md) |
| 完整再生网格、策略 \(J/G\) | [distribution_kernel.py](../hcsn_distributional_v2/distribution_kernel.py)、[content/models.py](content/models.py) | [内容源码审查](audits/CONTENT_SOURCE_REVIEW.json) |
| 下一事件被杀死生成元及梯度 | [first_event_vectors](content/models.py) | [独立核验脚本](audits/first_event_independent.py) |
| 有限最优 QVI 与独立解 | [finite_qvi.py](oracle/finite_qvi.py)、[reference_solvers.py](oracle/reference_solvers.py) | [oracle 协议](oracle/ORACLE_PROTOCOL.json)、[local003](oracle/results/local003/RESULTS.json) |
| 标签任务与复位延续 | [task_model.py](oracle/task_model.py) | [任务说明](oracle/MATH_AND_STATUS_ZH.md) |
| 一阶 BP 桥接 | [torch_bridge.py](oracle/torch_bridge.py) | [Torch 验证](oracle/results/torch001/RESULTS.json) |
| 真实训练权重的恢复与消息绑定 | [execution_binding/README.md](execution_binding/README.md) | [准备状态](execution_binding/PREPARED.json)、[源码审查](audits/EXECUTION_BINDING_SOURCE_REVIEW.json) |
| CUDA/CPU 与实际能量计数器合同 | [hardware/README.md](hardware/README.md) | [硬件源码审查](audits/HARDWARE_SOURCE_REVIEW.json) |

所有已有数值记录应以它们各自绑定的源码、参数、初态、时标和计时范围解释。固定策略评估、有限问题最优性、内容学习、原生执行和硬件收益各有独立验收；不能用其中一项替代其余项目。
