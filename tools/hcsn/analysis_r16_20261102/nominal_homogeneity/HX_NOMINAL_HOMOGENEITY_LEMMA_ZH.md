# H–X 名义尺度齐次性与边界位置参数化：静态引理

**结论成立，但它是理想实数公式上的条件性恒等式。** 本文只读已冻结源码并作代数推导，没有执行金融核、神经网络、训练或新的数值采样；没有改变现有候选及准入门槛。

## 1. 正缩放引理

令 \(\psi=(r,\delta,\sigma,\alpha,\tau,\ell,m)\)，其中 \(\tau\) 是税率、\(\ell\) 是流动性折价率，\(C\) 是总票息、\(P\) 是总本金。固定同一货币单位。考虑原金融公式的同一个有效自由边界分支，要求 \(C,P>0\)、\(r,\delta,\sigma,m>0\)、\(r+\ell>0\)，各表达式有限、可去奇点按连续极限解释，且 \(b>0\)。这里不以源码的一项局部停止检验代替全局最优性证明。

对任意正数 \(u\)，设 \(\theta_u=(\psi,uC,uP)\)。则

\[
b_{\theta_u}=u b_\theta,\qquad
E_{\theta_u}(V)=u E_\theta(V/u),\qquad
d_{\theta_u}(V)=u d_\theta(V/u),
\]

\[
F_{\theta_u}(V)=F_\theta(V/u),\qquad
G_{\theta_u}(V)=G_\theta(V/u).
\]

因此，\((C,P,V)\) 共同乘以 \(u\) 时，\(b,E,d\) 乘以 \(u\)，\(F,G,Q=E/b,R=2F-F^2\) 及 \(x=\log(V/b)\) 保持不变。**G 是零次齐次，债券价值 d 是一次齐次，二者不能混写成同一种缩放。**

**证明。** 源公式中 \(c=C/m\)、\(p=P/m\)、\(q=p-c/(r+\ell)\) 及融资成本项均线性依赖 \(C,P\)。边界分子的每项是这些量的线性组合，分母、正态积分及特征根只依赖 \(\psi\)，故 \(b\) 一次齐次。\(F,G\) 只依赖 \(\psi\) 与 \(x=\log(V/b)\)；权益式和债券式的每个系数都是 \(b,C,P\) 的一次齐次量，因而得到上述关系。默认分支也保持：\(V\le ub\) 当且仅当 \(V/u\le b\)，该侧 \(E=0,F=G=1,d=\alpha b/m\)。价值匹配与 \(E_V(b)=0\) 的光滑粘贴条件亦在正缩放下保持。

## 2. 分离形状与边界位置

定义八维形状参数

\[
\phi=(\psi,\kappa),\qquad \kappa=C/P>0,\qquad
\beta(\phi)=b(\psi,\kappa,1).
\]

此处本金“1”是**理想公式的归一化定义**，不表示可以向当前实现提交该输入。只在 \(\beta\) 有限、严格为正且所选金融分支有效的形状域内，令

\[
B=e^\rho,\qquad P=\frac{B}{\beta(\phi)},\qquad
C=\frac{\kappa B}{\beta(\phi)}.
\]

则 \(b=P\beta=B\)。写 \(z=\log V\)，并定义

\[
\mathcal Q(x;\phi)=\frac{E_{\psi,\kappa,1}(\beta e^x)}{\beta},
\qquad
\mathcal R(x;\phi)=2F_{\psi,\kappa,1}(\beta e^x)
-F_{\psi,\kappa,1}(\beta e^x)^2.
\]

有

\[
Q(z;\phi,\rho)=\mathcal Q(z-\rho;\phi),\qquad
R(z;\phi,\rho)=\mathcal R(z-\rho;\phi),\qquad x=z-\rho.
\]

固定形状时，边界位置因此只平移归一化读出：在可微点

\[
\partial_\rho Q=-\partial_z Q,\qquad
\partial_\rho R=-\partial_z R,\qquad
\partial_\rho x=-1.
\]

这也可由欧拉齐次恒等式 \(VQ_V+CQ_C+PQ_P=0\) 及 \(C_\rho=C,P_\rho=P\) 直接得到。在理想联合 C1 条件下，\(\rho\) 之外的形状变化保持 \(b=e^\rho\) 不变。

**边界约定。** 当 \(z\le\rho\)，\(Q=0,R=1\)。若有效边界邻域内原权益满足联合光滑粘贴，且有限 \(m>0,\sigma>0\) 下续行侧 \(F\) 的一阶导局部有界，则 \(Q_x\to0\) 且 \(R_x=2(1-F)F_x\to0\)，上述 Q/R 导数关系跨边界成立。原 F/G 通常只有分支或单侧导数，本文不将它们声明为跨默认边界的 C1 输出；也不覆盖 \(m=0\)、\(\sigma=0\)、\(\beta=0\) 或退化金融分支。

**维数。** \(\phi\) 八维加 \(\rho\) 一维仍是原金融参数的九维，状态 z 另计。若 \(\beta\) 在该域 C1，则逆映射为 \(\kappa=C/P,\rho=\log b\)。固定 \(\psi\) 时

\[
\det\frac{\partial(C,P)}{\partial(\kappa,\rho)}=P^2>0,
\]

故这是有效域内的局部可逆重参数化，不是删去一个金融自由度。

## 3. 有效参考点与实现边界

\(\beta>0\) 及金融分支有效性是条件，不能由 \(B>0\) 自动推出。源码采用的严格局部停止符号条件在理想实数下等价于

\[
\delta\beta-(1-\tau)\kappa+\frac{\alpha\beta-1}{m}<0.
\]

它与名义尺度无关，但仍只是该源码检查的代数形式。

当前 C API 硬域是 \(0.5\le C\le10\)、\(20\le P\le100\)，所以直接调用 \(P=1\) 会被拒绝。可在一个有效形状邻域选择已有效的参考本金 \(P_*\)，令 \(C_*=\kappa P_*\)，并使用

\[
\beta(\phi)=\frac{b(\psi,C_*,P_*)}{P_*},\qquad
u=\frac{B}{b(\psi,C_*,P_*)},\qquad (C,P)=u(C_*,P_*).
\]

这是上述定义的等价实数表达，不需请求硬域外的归一化输入。参考本金必须满足
\([20,100]\cap[0.5/\kappa,10/\kappa]\ne\varnothing\)，并满足其余金融有效性条件；目标参数也仍受

\[
B\in[20\beta,100\beta]\cap[0.5\beta/\kappa,10\beta/\kappa]
\]

约束。选一个有效参考点并不能保证全部形状或任意边界位置均可由当前 API 接受。

**不作浮点恒等承诺。** C API 输入是 FP32 字值；参数构造、取指数、金融计算及导数传输都有舍入，核还使用积分近似、Taylor/混合稳定化和有限域拒绝。尤其停止检验中的 `max(1, scale)` 是绝对尺度门，整个拒绝逻辑不具有任意正缩放不变性。本文没有证明实现逐位齐次，也没有实现上述参考点/形状参数接口或完成其梯度工程验收。

当前已冻结的十八参数两层候选仍采用原来的逐坐标 tanh 参数化，**尚未采用本引理的形状／边界位置分离**。本引理不把既有训练收益归因于边界机制，不关闭因果任务优势、泛化、脉冲机制或新接口工程门。

## 源依据

- 冻结 `kernel.cpp`：`FullHX` 构造函数的成本与边界式、`first_hit`、`raw_equity`、`state` 默认／债券分支、`valid` 的硬域及局部停止拒绝条件；SHA256 `6c04009f4a782a2aaac5f0e6d8af7048d9bd9c26f1a3039f47c1c83491bb63cd`。
- 同协议封存的 `frozen_input/frozen_reference.py`：`fields` 中 literal A5/A7 公式，用于静态交叉核对；本次没有导入或调用其高精度求值与差分程序。
- 金融协议 SHA256 `76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0`；当前两层协议 SHA256 `da07c580e258f51517f124d6d7b902a8ae3c6700fb58cb96948c18447c740ad7`。
