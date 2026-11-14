"""Assemble the research deliverable from the verified reference calculation."""
from pathlib import Path
import base64
import json
import zipfile

root=Path(__file__).resolve().parent
result=json.loads((root/'results/validation_results.json').read_text())
cells=[]
def md(text, attachments=None):
    cell={'cell_type':'markdown','metadata':{},'source':text.strip().splitlines(keepends=True)}
    # Ensure source line boundaries survive JSON notebook concatenation.
    cell['source']=text.strip()+'\n'
    if attachments:
        cell['attachments']=attachments
    cells.append(cell)
def code(text):
    cells.append({'cell_type':'code','metadata':{},'execution_count':None,
                  'outputs':[],'source':text})

md(r"""
# 续约、自由边界与解析脉冲神经元
## 从 He–Xiong 的建模技术到可检验的神经算子

**日期：2026-10-29。性质：研究设计与标量数学验证。**

结论：可以把首达概率、存活传播、有限期限价值函数和内生干预边界组成神经算子；也存在包含反复发放、固定重置和不应期的可解析特例。完整的资源期限网络尚属待验证提案。本笔记没有训练 SNN，没有测生物数据，也没有证明任何 Hepta、性能或能耗收益。

这份笔记包含完整公式、一个可证明的 Lambert W 阈值特例、资源期限扩展、训练与反事实实验设计、数值结果和自包含 Python 代码。代码只需要 NumPy、SciPy、Matplotlib。保存结果由同一脚本在本轮实际运行生成；Notebook 的代码单元保留未执行状态，便于重新运行。

### 证据层级

| 层级 | 已有内容 | 不能由此推出 |
|---|---|---|
| 原论文 | 固定参数金融模型中的价值函数与内生边界闭式 | 神经元或神经网络已被该论文建模 |
| 本轮数学推导 | 首达算子重写；特定标量重复干预问题的解析阈值 | 一般时变、多维模型全局解析 |
| 本轮计算 | 有限差分 PDE、数值积分、首达分布采样、阈值数值优化一致性 | 已训练 SNN 优效或生物真实性 |
| 研究提案 | 期限义务、续约决策、物理资源约束与事件网络组合 | 首创、通用更优或已经实现 |
""")

md(r"""
## 1. 原论文中可以迁移的结构

He 与 Xiong（2012）采用风险中性几何布朗状态、固定期限且到期日均匀错开的债务。流动性冲击的 Poisson 强度是 $\xi$，比例折损是 $k$；债券有效贴现为 $q=r+\xi k$，状态漂移仍是 $r-\delta$。原文式(5)、(11)可压缩为

$$\partial_\tau d=\mathcal Ld-qd+c,$$
$$rE=\mathcal LE+\delta V-(1-\pi)C+d(V,m)-p.$$

平稳设定下边界满足 $E(V_B)=E'(V_B)=0$，命题1式(12)确有显式边界；它不是一般时变阈值。作者用对数变换、Laplace 变换和边界条件得到解。[1]

需要迁移的思想是：**继续维持状态的价值受未来续约代价影响，触发边界由同一个价值问题导出。**金融中的风险中性测度、股债利益冲突和“违约即终止”没有自动的神经对应物。

以下均为我们重新设定的数学模型或设计，不是原文的神经网络结论。
""")

md(r"""
## 2. 从价值函数提取三个解析基本算子

定义距边界的无量纲状态 $X_0=x>0$：

$$dX_t=\mu\,dt+\sigma\,dW_t,\qquad \tau_0=\inf\{t\ge0:X_t\le0\},\quad \sigma>0.$$

若它来自 GBM 的对数变换，则 $X=\log(V/V_B)$，漂移要包含 Ito 修正；在神经模型里则直接定义 $X=h-Y$，其中 $Y$ 是证据，$h$ 是输出边界。因此兴奋输入使 $X$ 减小。

### 2.1 首达时间

对 $t>0$，令 $\Phi$ 为标准正态 CDF：

$$F(x,t)=P_x(\tau_0\le t)
=\Phi\!\left(\frac{-x-\mu t}{\sigma\sqrt t}\right)
+e^{-2\mu x/\sigma^2}\Phi\!\left(\frac{-x+\mu t}{\sigma\sqrt t}\right).$$

$$S(x,t)=1-F(x,t),\qquad
f(x,t)=\frac{x}{\sigma\sqrt{2\pi t^3}}
\exp\!\left[-\frac{(x+\mu t)^2}{2\sigma^2t}\right].$$

这是“整个区间内至少触边一次”的概率，不是 $P(X_t\le0)$。后者漏掉先越界再返回的路径。

若 $\mu>0$，$F(x,\infty)=e^{-2\mu x/\sigma^2}<1$；若 $\mu\le0$，最终首达概率为1。$\mu<0$ 时首达时间服从逆高斯分布，其均值为 $x/(-\mu)$、形状参数为 $x^2/\sigma^2$。不能把任意漂移都按必然发放的逆高斯采样。

### 2.2 折现首达算子

$$H_\rho(x,t)=E_x[e^{-\rho\tau_0}\mathbf 1_{\tau_0\le t}],\quad \rho\ge0.$$

令 $\nu=\sqrt{\mu^2+2\rho\sigma^2}$。由 $e^{-\rho t}f(x,t)$ 配方并积分得到

$$H_\rho=
e^{(-\mu+\nu)x/\sigma^2}\Phi\!\left(\frac{-x-\nu t}{\sigma\sqrt t}\right)
+e^{(-\mu-\nu)x/\sigma^2}\Phi\!\left(\frac{-x+\nu t}{\sigma\sqrt t}\right).$$

$$H_\rho(x,\infty)=\exp\!\left[-\frac{\mu+\sqrt{\mu^2+2\rho\sigma^2}}{\sigma^2}x\right].$$

$H_0=F$。当 $\rho>0$ 时，$H_\rho$ 是价值权重，不能作为真实脉冲 CDF。

### 2.3 有限期限价值算子

设存活期间的效用流是 $u$，到期仍存活得到 $p$，触边时得到 $R$：

$$Q(x,m)=E_x\left[\int_0^{m\wedge\tau_0}e^{-\rho s}u\,ds
+p e^{-\rho m}\mathbf1_{\tau_0>m}
+R e^{-\rho\tau_0}\mathbf1_{\tau_0\le m}\right].$$

因为

$$A_\rho(x,m)=\int_0^m e^{-\rho s}S(x,s)ds
=\frac{1-e^{-\rho m}S(x,m)-H_\rho(x,m)}\rho,$$

所以

$$\boxed{Q=\frac u\rho+\left(p-\frac u\rho\right)e^{-\rho m}S
+\left(R-\frac u\rho\right)H_\rho.}$$

这给出具有明确时间意义的可微特征映射 $(x,m,\mu,\sigma,\rho,u,p,R)\mapsto Q$。一般 $Q$ 不是 $[0,1]$ 中的概率；$u,p,R$ 都必须采用一致的效用单位。$\rho=0$ 用积分式或连续极限，不直接除零。

### 2.4 存活传播算子

对 $z>0$：

$$K_t(z\mid x)=\frac{e^{-(z-x-\mu t)^2/(2\sigma^2t)}}{\sigma\sqrt{2\pi t}}
\left[1-e^{-2xz/(\sigma^2t)}\right].$$

$$\int_0^\infty K_t(z\mid x)dz=S(x,t),\qquad
p(X_t=z\mid\tau_0>t)=K_t(z\mid x)/S(x,t).$$

这定义了真正的状态传播半群 $\mathcal K_t\phi(x)=\int K_t(z\mid x)\phi(z)dz$。单个 CDF 值不是状态转移分布，也不能直接承担任意时间拼接。

实现时若先按 $F$ 判定“没有发放”，就不能再用无条件高斯更新状态；必须使用存活条件分布。靠边界的差值用 `expm1`，大指数乘小尾概率用 `log_ndtr`。
""")

md(r"""
## 3. 含重复发放的解析自由边界：一个可验证特例

这一节重新设定一个简单的神经计算问题，用于证明“重置后仍可解析”在受限条件下可行。**它不是 He–Xiong 的公式，也不主张是新的数学定理。**

### 模型和目标

活跃状态积累证据：

$$dY_t=a\,dt+\sigma\,dW_t.$$

每次脉冲产生净效用 $Y_{T_n^-}-c$。随后经历固定不应期 $r_f\ge0$，再从 $y_r$ 开始下一轮。此期间无新证据、无额外效用或成本。可永久等待，价值为零。

$$J(y)=\sup_{\{T_n\}}E_y\sum_n e^{-\rho T_n}(Y_{T_n^-}-c),$$

其中 $\rho>0,\ \sigma>0,\ c>y_r$。这里 $c$ 是输出成本或效用偏置；它不是金融流动性参数。

令

$$\gamma=\frac{\sqrt{a^2+2\rho\sigma^2}-a}{\sigma^2}>0,\quad
\eta=e^{-\rho r_f},\quad D=1+\gamma(c-y_r).$$

等待区的方程是 $(a\partial_y+\sigma^2\partial_{yy}/2-\rho)J=0$。
值匹配和光滑拼接为

$$J(h)=h-c+\eta J(y_r),\qquad J'(h)=1.$$

得到

$$\boxed{h=c+\frac{1+W_0(-e^{-\rho r_f-D})}{\gamma}},$$

其中 $W_0$ 是 Lambert W 主实支。它给出 $h>c>y_r$；另一个实支不满足重置后进入等待区。

$$J(y)=\begin{cases}e^{\gamma(y-h)}/\gamma,&y<h,\\
y-h+1/\gamma,&y\ge h.\end{cases}$$

### 最优性核验

干预算子 $\mathcal MJ=y-c+\eta J(y_r)$；应验证的是

$$\max\{(\mathcal L-\rho)J,\mathcal MJ-J\}=0.$$

在等待区，第一项为0，第二项为

$$\frac{1+\gamma(y-h)-e^{\gamma(y-h)}}\gamma\le0.$$

在输出区，第二项为0，第一项为

$$-\frac12\sigma^2\gamma-\rho(y-h)\le0.$$

边界处值函数为 $C^1$；配合折现可积性，构成该标量问题的验证。也可最大化固定阈值策略的更新值

$$J_h(y_r)=\frac{e^{-\gamma(h-y_r)}(h-c)}{1-\eta e^{-\gamma(h-y_r)}}$$

独立核对同一个最优阈值。

若 $w=W_0(-e^{-\rho r_f-D})$，则

$$\frac{\partial h}{\partial c}=\frac1{1+w}>0.$$

因此更高输出成本提高阈值，避免把“资源不足”机械地当作兴奋发放。$a>0$ 时，稳定平均发放率为

$$\bar\nu=\left[r_f+\frac{h-y_r}{a}\right]^{-1}.$$

$a=0$ 时平均首达时间无穷；$a<0$ 时存在永不再发放的概率。训练时应保留 $c-y_r\ge\varepsilon$，避免 $c\to y_r,r_f\to0$ 的 W 分支点病态。

### 与首达核组合

取距离 $X=h-Y$，则 $x=h-y,\ \mu=-a$。本节给出 $h$，上一节给出发放时间分布、存活传播及期限读出。于是已有一个包含状态、边界、脉冲、重置、不应期和价值目标的完整标量神经原语。
""")

md(r"""
## 4. 真正的 rollover 扩展：期限义务必须成为状态

建议称候选体系为“续约首达脉冲网络”，简称 RR-SNN，仅作研究代号。

$$z_i=(y_i,e_i,b_i(a),r_i).$$

- $y_i$：尚未输出的任务证据。
- $e_i$：可用于计算、通信、状态维护的真实预算。
- $b_i(a)$：剩余时间为 $a$ 的待维护记忆／工作义务分布。
- $r_i$：不应期状态。

确定期限的义务随时间前移，连续表示满足

$$\partial_t b_i(t,a)-\partial_a b_i(t,a)=u_i(t,a),\quad a>0.$$

期限到零时选择更新、输出、释放或丢弃；更新会支付成本并把义务重新放到未来期限。离散实现可先用4–8个期限桶，但桶近似误差必须量化；单个指数衰减变量不等于固定到期队列。

在期限 $m_k$ 上，上一节的 $Q_{ik}(x,m_k)$ 可预测“保留这份状态的期望任务效用”。对到期的义务，比较

$$Q_{ik}^{\rm renew}-Q_{ik}^{\rm drop}\quad\text{与}\quad
\lambda(e_i)C_{ik}^{\rm renew}.$$

其中 $C^{\rm renew}$ 必须来自实际或独立校准的资源成本；$\lambda$ 将资源单位转为效用单位。$Q$ 的折现损失不能直接当成 GPU 能量或 FLOPs。

若每类总义务为 $B_k$ 且剩余期限均匀分布在 $[0,m_k]$，稳态到期流才是 $B_k/m_k$。一般动态队列应按实际到期通量计算，不能随意把所有状态乘 $1/m_k$。

### 资源动力学与发放可行性

$$de_i=(R_i-C_{i,\rm hold}-C_{i,\rm renew})dt-E_{i,\rm spike}\,dN_i.$$

这只是预算记账框架；离散到期成本也可以作为跳跃。必须规定 $e_i\ge E_{i,\rm spike}$ 才允许发放。不足时可以进入休眠、释放状态或请求外层重新分配。人工计算模型无需假定真实生物能量的单调响应。

### 一般自由边界

令 $\ell(z)$ 为等待期间净效用流；输出、刷新、休眠各有干预算子。完整问题为

$$\max\{(\mathcal L-\rho)J+\ell,
\mathcal M_{\rm spike}J-J,
\mathcal M_{\rm renew}J-J,
\mathcal M_{\rm sleep}J-J\}=0.$$

发放后的继续价值必须出现在 $\mathcal M_{\rm spike}$ 内；不应期若有资源恢复，其转移也必须计算。一般多维问题需要数值自由边界、近似动态规划或受约束的策略学习。

**上一节 Lambert W 解仅适用于冻结参数、无线性以外的输出奖励、无维护成本的特例。**把 $c$ 在控制时刻依据预算更新，再套公式，是一个可解释近似控制器；尚不是完整动态资源模型的全局最优解。

### 有辨识力的创新检验

构造两组神经元，使当前 $y,e$、总义务质量、平均期限相同，但期限分布不同。例如将全部义务均匀到期与集中到期比较。若新模型能在未来突发预算收缩前保留更有价值的状态，而同规模 ALIF、资源 LIF、无期限首达模型做不到，期限结构才提供了可辨识的贡献。必须同时给基线同样的期限观测，避免额外信息造成不公平优势。
""")

md(r"""
## 5. 如何组成网络而保持解析性口径

最小网络采用稀疏脉冲耦合。事件间参数固定：

$$dY_i=a_i^{(k)}dt+\sigma_i dW_i.$$

上游脉冲在传输延迟后造成跳跃：

$$Y_i(t^+)=Y_i(t^-)+w_{ij}s_j.$$

每个神经元保存状态、预算、少量期限桶和不应期计时。正负权重提供兴奋与抑制；一次输入跳跃直接越过阈值时应立即处理脉冲。正的最小不应期／传输延迟使事件顺序明确。

下一事件取输入、首达、期限到期、预算更新、不应期结束的最早者。事件发生后重算受影响神经元的局部参数、状态和等待时间。

固定系数的单区间算子可以精确，但网络仍需要事件队列、条件传播和重新调度。若输入连续变化、边界移动、加入泄漏形成 OU、或者噪声在神经元间相关，就不能直接继续使用独立标量的两项 CDF 公式。状态分布的均值替代完整传播也属于近似。

### 多次发放

在同一 $\mu,\sigma$、初始距离 $x_0$、每次重置距离 $x_r$、固定不应期 $r_f$ 下：

$$P[N(t)\ge n]=F\big(x_0+(n-1)x_r,\ t-(n-1)r_f\big),$$

时间参数不正时右端定义为零。这由独立再生首达区间和强 Markov 性得到。于是 $E[N(t)]=\sum_{n\ge1}P[N(t)\ge n]$。一般时变输入需要逐段再生，不能把任意长区间压为一次 Bernoulli。
""")

md(r"""
## 6. 训练、可辨识性与数值边界

**第一阶段训练概率和期限价值。**对有删失的首达样本，负对数似然为

$$\mathcal L_{\rm time}=-\sum_{\rm hit}\log f_\theta(t_i)
-\sum_{\rm censored}\log S_\theta(T_i).$$

通过稳定的 CDF、指数和 W 函数计算导数，先学习漂移、阈值尺度和时间尺度。若只把 $F$ 或 $Q$ 当连续激活，得到的是概率动态网络，需要另外实现硬事件才能叫实际 SNN。

**第二阶段训练真实脉冲。**可以研究首达时间的隐式重参数化、score-function 梯度或事件反传。对不发放的质量和参数变化导致的脉冲出现／消失必须显式处理。EventProp 的已有结果针对特定硬阈值动力学，不能直接宣布适用于这个扩散过程。[8]

**第三阶段训练期限策略。**以独立任务结果和真实消耗训练续约／释放策略。对于 Hepta，可保留共享 Encoder 与轻量 Head：Encoder 提供证据初值，RR-SNN 候选层处理时序记忆、稀疏通信、计算触发；NDU 负责外层预算与多模态输出组合。局部脉冲只产生认知事件或候选，不自行取得 authority、generation fence、生命周期或部署权。

建议目标：

$$\mathcal L=\mathcal L_{\rm task}+\lambda_E C_{\rm measured}
+\lambda_D C_{\rm deadline}+\lambda_U C_{\rm calibration}.$$

同一成本不要在局部 $Q$、输出成本和全局目标中重复扣除。效用头不能自行给自己评估；训练、选择和验证分离。

数值与统计限制：

1. $(x,\mu,\sigma)$ 同比例缩放不改变首达分布，要固定一个尺度。
2. $\xi,k$ 在原价值结构中只通过乘积出现；神经实现不应无证据地把两者独立识别。
3. $\sigma\to0$、$t\to0$、$x\to0$ 需要专门分支；参考代码仅接受正值内域。
4. 极小存活概率用稳定 `log-survival`，不能假设简单 `1-F` 在所有浮点尾部都可靠。
5. $c-y_r\to0,r_f\to0$ 附近的 W 导数病态，训练要有间隔约束。
6. 正态 CDF、特殊函数、随机采样、条件传播、队列和期限存储都计入成本。解析不自动等于更快。
7. 现有有界或定点 Cell 状态若加反射／裁剪，会改变过程及其核；需要独立误差证明或新边界解。
""")

md(r"""
## 7. 已有工作与新意边界

| 方向 | 已有原始研究 | 本方案必须增加的证据 |
|---|---|---|
| 随机游走趋向吸收边界 | Gerstein–Mandelbrot 1964 [2] | 不能把首达核本身称新神经元 |
| 突触消耗与恢复 | Tsodyks–Markram 1997 [3] | 期限义务应超越传统短期抑制 |
| 年龄／更新与适应 | Naud–Gerstner 2012 [4] | 多期限状态与多指数适应区分 |
| 适应阈值与长时间记忆 | Bellec 等 LSNN 2018 [5] | 同状态和参数预算的 ALIF/LSNN 基线 |
| 能量与发放联合约束 | Fardet–Levina 2020 [6] | 实际续约反馈的额外贡献 |
| 成本收益导出决策边界 | Tajima 等 2016 [7] | 重复输出和期限承诺的价值 |
| 事件精确梯度 | EventProp 2021 [8] | 扩散、删失、重置后的梯度验证 |
| 闭式连续时间网络 | Hasani 等 CfC 2022 [9] | 局部精确与全网络近似分别说明 |
| 解析时间与延迟学习 | DelGrad 2025 [10] | 特殊函数和“解析”本身不是首创 |

有限检索没有提供足以宣布“从未有人提出这一组合”的证据。更合适的候选贡献是：**显式期限义务、续约成本驱动的循环干预边界、可组合首达核、以及在匹配资源预算下的可验证效果。**
""")

md(r"""
## 8. 本轮实际数值结果

参数均为无量纲：$x=1,\mu=-0.7,\sigma=0.8,t=1,\rho=0.4$。

| 检查 | 结果 |
|---|---:|
| 首达概率解析值 | 0.5035073444 |
| 有限差分后向 PDE，较细网格 | 0.5035006157 |
| PDE 绝对误差 | 0.0000067288 |
| PDE 较粗网格误差 | 0.0000269090 |
| 5个种子、共500,000个首达样本 | 0.502648 |
| 合并采样标准误 | 0.00070709 |
| 只检查末端越界 | 0.3538302333 |
| 末端检查遗漏的概率质量 | 0.1496771111 |
| 折现首达解析值 | 0.4009843679 |
| 与密度数值积分的绝对差 | 1.67e-16 |

采样直接使用已知的逆高斯首达分布，属于分布实现检查，不是独立积分 SDE。独立数值交叉验证来自后向 PDE；$\Delta x=0.02\to0.01$，时间步数 $1000\to2000$，误差约缩小四倍。

重复发放检查使用 $x_0=1,x_r=0.8,r_f=0.15,t=2$：

| 数量 | 解析 | 抽样 |
|---|---:|---:|
| 平均脉冲数 | 1.3704078811 | 1.368134 |
| 至少2次脉冲的概率 | 0.4354085932 | 0.434122 |

Lambert W 特例取 $a=0.7,\sigma=0.8,\rho=0.4,y_r=0,r_f=0.15$：

| 输出成本 $c$ | 解析阈值 $h$ | 直接数值最大化所得阈值 |
|---:|---:|---:|
| 0.2 | 1.1727468618 | 1.1727468779 |
| 0.5 | 1.7448792018 | 1.7448792152 |
| 1.0 | 2.5117487247 | 2.5117486998 |
| 2.0 | 3.7892880066 | 3.7892880071 |

这组检查证明的是代码与所述标量数学问题相符。50万采样和5个种子均用于核验证，不能当作5个训练种子的 SNN 性能实验。
""")
png=(root/'results/analytic_neuron_validation.png').read_bytes()
md('![Scalar validation](attachment:analytic_neuron_validation.png)',
   {'analytic_neuron_validation.png':{'image/png':base64.b64encode(png).decode()}})

md(r"""
## 9. 下一步可否证的实验设计

优先顺序：标量原语 → 带输入事件的真实重置网络 → 多期限反馈 → 公平任务比较 → Hepta 小规模候选。

| 阶段 | 交付 | 验收条件 |
|---|---|---|
| R0 | 解析核与固定重置阈值 | 本轮已做常系数标量推导及数值核对；极限和生产数值实现待补 |
| R1 | 真正脉冲与输入事件调度 | 条件存活状态、多个脉冲、不应期、参数切换都正确 |
| R2 | 期限队列和资源约束 | 同状态不同期限反事实；有限预算不可凭空透支 |
| R3 | 可训练候选网络 | 硬事件梯度检查；删失校准；独立训练／验证／测试 |
| R4 | 比较与消融 | LIF、ALIF/LSNN、资源LIF、无期限首达、固定边界多期限、CfC |
| R5 | Hepta候选评估 | 共享Encoder不变、独立未来窗口、真实资源与负迁移指标 |

关键任务：不规则采样、延迟回报、突发输入、动态预算、期限分布变化。再用公开时序脉冲任务或实际工作负载检验可迁移性，避免只在为模型定制的模拟任务上获胜。

控制变量包括总参数、状态字节、输入信息、训练算力、超参数搜索预算、时延目标。主要消融：去期限、打乱期限、去续约、固定阈值、冻结资源，以及同一模型用数值求解替代解析核。

最终主表至少报告：任务质量与校准、未来窗口效用、负迁移、峰值 RSS、p95/p99、吞吐、总事件数、特殊函数／队列开销，以及可用时实测能量。Hepta规模可依次取64/256/1024/4096 Cell，但这里的 Cell 不等于单个生物神经元。

如果它只打败固定小步长 Euler，却打不过已有精确事件 LIF/ALIF；或者加入相同期限观测的基线即可获得同样收益，应降低其创新和效率主张。
""")

md(r"""
## 10. 原始资料

1. He, Z. & Xiong, W. (2012). *Rollover Risk and Credit Risk*. Journal of Finance 67(2), 391–430. https://www.princeton.edu/~wxiong/papers/rollover.pdf
2. Gerstein, G. L. & Mandelbrot, B. (1964). *Random Walk Models for the Spike Activity of a Single Neuron*. https://pmc.ncbi.nlm.nih.gov/articles/PMC1367440/
3. Tsodyks, M. V. & Markram, H. (1997). *The neural code between neocortical pyramidal neurons depends on neurotransmitter release probability*. https://www.cns.nyu.edu/csh/csh04/Articles/Tsodyks-Markram-97.pdf
4. Naud, R. & Gerstner, W. (2012). *Coding and Decoding with Adapting Neurons: A Population Approach to the Peri-Stimulus Time Histogram*. https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1002711
5. Bellec et al. (2018). *Long short-term memory and learning-to-learn in networks of spiking neurons*. https://papers.nips.cc/paper_files/paper/2018/file/c203d8a151612acf12457e4d67635a95-Paper.pdf
6. Fardet, T. & Levina, A. (2020). *Simple models including energy and spike constraints reproduce complex activity patterns and metabolic disruptions*. https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1008503
7. Tajima, S., Drugowitsch, J. & Pouget, A. (2016). *Optimal policy for value-based decision-making*. https://pmc.ncbi.nlm.nih.gov/articles/PMC4992126/
8. Wunderlich, T. C. & Pehle, C. (2021). *Event-Based Backpropagation can compute Exact Gradients for Spiking Neural Networks*. https://arxiv.org/pdf/2009.08378
9. Hasani et al. (2022). *Closed-form continuous-time neural networks*. https://cap.csail.mit.edu/sites/default/files/research-pdfs/Closed-form%20continuous-time%20neural%20networks.pdf
10. Göltz et al. (2025). *DelGrad: exact event-based gradients for training delays and weights on spiking neuromorphic hardware*. https://pmc.ncbi.nlm.nih.gov/articles/PMC12420821/

## 11. 自包含参考代码

下面包含完整实现，可重新生成 JSON 和图像。其定义域、假设和限制在函数说明中列出。代码单元没有预填执行计数；上文记录的是2026-10-29实际脚本运行结果。
""")
source=(root/'analytic_neuron.py').read_text()
code(source.split("if __name__=='__main__':")[0])
code("results = validate(Path('rollover_snn_results'))\n")
code("from IPython.display import Image, display\ndisplay(Image(filename='rollover_snn_results/analytic_neuron_validation.png'))\n")
md("## 完整本轮结果 JSON\n\n```json\n"+json.dumps(result,ensure_ascii=False,indent=2)+"\n```\n")

notebook={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
             'language_info':{'name':'python','version':result['environment']['python']},
             'research_status':'Scalar analytical verification; network proposal untrained'},
          'nbformat':4,'nbformat_minor':5}
for i,cell in enumerate(cells):
    cell['id']=f'rrsnn-{i:03d}'
nbpath=root/'rollover_snn_research.ipynb'
nbpath.write_text(json.dumps(notebook,ensure_ascii=False,indent=1)+'\n')
(root/'requirements.txt').write_text('numpy>=1.24\nscipy>=1.10\nmatplotlib>=3.7\n')
(root/'README.txt').write_text('''续约首达脉冲网络研究 / 2026-10-29

主要文档：rollover_snn_research.ipynb（完整中文推导、已有文献、研究提案和自包含代码）。
运行方式：
  python -m pip install -r requirements.txt
  python analytic_neuron.py --output results

本轮已验证：常系数首达概率、折现首达、吸收核质量、固定重置重复脉冲计数、
固定成本最优阈值的 Lambert W 公式。独立数值交叉验证使用有限差分后向 PDE；
Monte Carlo 是已知逆高斯首达时间分布的采样，不是独立 SDE 积分。

本轮尚未完成：带时变输入的网络、期限资源反馈训练、SNN任务性能、实际能耗、
Hepta集成、生物拟合、首创性证明。所有演示参数与时间单位均无量纲。

运行环境版本、完整结果、限制见 results/validation_results.json。
图像见 results/analytic_neuron_validation.png。
''')
files=['rollover_snn_research.ipynb','analytic_neuron.py','requirements.txt','README.txt',
       'results/validation_results.json','results/analytic_neuron_validation.png']
with zipfile.ZipFile(root/'rollover_snn_research.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
    for name in files:
        z.write(root/name,arcname='rollover_snn_research/'+name)
print(json.dumps({'notebook':str(nbpath),'cells':len(cells),
                  'files':[{'name':name,'bytes':(root/name).stat().st_size} for name in files],
                  'zip_bytes':(root/'rollover_snn_research.zip').stat().st_size},ensure_ascii=False,indent=2))
