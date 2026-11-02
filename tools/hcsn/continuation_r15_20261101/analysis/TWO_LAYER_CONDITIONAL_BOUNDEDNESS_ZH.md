# 两层连续值场的条件有界性

本结论针对下述实数连续 ODE。它没有证明金融参数盒内的所有前提，
也不覆盖 FP32 exp 的溢出/下溢、Euler 数值稳定性、训练梯度的长期大小、
自主振荡、稀疏脉冲或任务效果。当前有限输入检查不能替代这些全域前提。

## 1. 前提与模型

对每层金融参数集合 K_i，假设它是紧集，且金融读出在所需状态—参数
闭包的一个开放邻域内良定义、联合 C1（局部 Lipschitz 已足够保证状态
解的唯一性）。在该域内：

- Q_i(z,theta) >= 0，0 <= R_i(z,theta) <= 1；
- 0 < b_min,i <= b_i(theta) <= b_max,i < infinity；
- z <= log b_i(theta) 时，Q_i=0、R_i=1；
- ell_i>0、k_R,i>0、tau_i>0，k_Q,i>=0；
- 物理初态、静息参考及参数有限；外部输入连续且有界。也可允许可测、
  局部有界输入，采用通常的 Caratheodory 解及相应局部一致 Lipschitz 条件。

每层状态为 (z_i,a_i)：

\[
\dot z_i=u_i(t)-\ell_i(z_i-z_{r,i})-k_{Q,i}Q_i-k_{R,i}R_i+a_i,
\qquad
\dot a_i=(k_{R,i}R_i-a_i)/\tau_i.
\]

两层之间只存在单向耦合。实数模型的连续消息为

\[
h_1=z_1-\log b_1(\theta_1),\quad
u_2=u_{2,\mathrm{ext}}+c_d h_1,\quad
\theta_2=\theta_{2,\mathrm{base}}\odot
[1+\epsilon\tanh(\xi_2+c_\theta h_1)],
\]

其中 c_d=0.2、c_theta=0.5、epsilon=0.03，xi_2 是一条 rollout 内固定的
raw 参数。tanh 只使 theta_2 落在一个紧参数盒内；它本身不能证明该参数
盒满足上述金融有效性和正则性前提。实际实现使用 FP32 exp、cast 和
数值 Euler；本节的 h_1 是相应实数模型的表达式。

## 2. 单层不变矩形

令

\[
a_i^- =\min(a_i(0),0),\qquad
 a_i^+=\max(a_i(0),k_{R,i}).
\]

在 a_i=a_i^- 处，dot a_i >= 0；在 a_i=a_i^+ 处，dot a_i <= 0。
因此恢复状态不会离开 [a_i^-,a_i^+]。

若 u_i^- <= u_i(t) <= u_i^+，定义

\[
z_i^+=\max\left\{z_i(0),\ z_{r,i}+\frac{u_i^++a_i^+}{\ell_i}\right\},
\]

\[
z_i^-=\min\left\{z_i(0),\ \log b_{\min,i},\
z_{r,i}+\frac{u_i^- -k_{R,i}+a_i^-}{\ell_i}\right\}.
\]

在上边界 z_i=z_i^+，利用 Q_i>=0、R_i>=0 和 k_Q,i>=0，得到

\[
\dot z_i\le u_i^+-\ell_i(z_i^+-z_{r,i})+a_i^+\le0.
\]

在下边界 z_i=z_i^-，由 z_i^-<=log b_min,i<=log b_i(theta)，该点
处在 default 分支，Q_i=0、R_i=1。因此

\[
\dot z_i\ge u_i^- -\ell_i(z_i^- -z_{r,i})-k_{R,i}+a_i^-\ge0.
\]

初态已经包含在矩形内，四个边界的向量场均朝内或相切，故
[z_i^-,z_i^+] × [a_i^-,a_i^+] 为前向不变集合。该推导不需要把实际
轨迹重新归一化、截断或裁剪。

## 3. 单向两层耦合

先对第1层应用上述结论。其有界状态及正边界给出

\[
h_1^- = z_1^- -\log b_{\max,1},\qquad
h_1^+ = z_1^+ -\log b_{\min,1}.
\]

因为 c_d>0，若外部第2层输入位于 [u_ext,2^-,u_ext,2^+]，则

\[
u_2^-=u_{\mathrm{ext},2}^-+c_dh_1^-,\qquad
u_2^+=u_{\mathrm{ext},2}^++c_dh_1^+.
\]

theta_2 的条件化映射仍位于假设的有效紧域 K_2，故可对第2层使用同样
的不变矩形论证。这里没有第2层到第1层的反馈，不能把这一归纳直接
当成任意反馈网络的有界性证明。

在包含这些矩形与参数域闭包的开放邻域内，局部存在唯一性加上不变
紧集给出任意有限时间的延拓。若输入在整个正时间轴上一致有界，以上
状态界也可取为时间无关。若只对每个有限区间输入有界，则相应状态界
可以依赖区间终点；同样排除了符合前提的有限时状态逃逸。

## 4. 结论的范围

这是一项带前提的连续系统结论。它没有关闭以下问题：

1. 所用完整金融参数盒是否满足 Q>=0、0<=R<=1、b 正且有界及联合
   正则性的全域证明；有限数值例不能证明整个参数盒。
2. FP32 表示、步长 0.05 的同步 Euler 与任意更大步长是否保持该矩形；
   连续系统有界不蕴含离散算法稳定。
3. 一阶 BPTT 的长程敏感性、梯度消失或爆炸；状态有界不能保证梯度良态。
4. 周期轨道、脉冲次数、精确首达事件时刻、跨模态或质量优势。

局部解延拓和连续系统的标准背景可参见
[Gerald Teschl, Ordinary Differential Equations and Dynamical Systems](https://www.mat.univie.ac.at/~gerald/ftp/book-ode/ode.pdf)。
这里的不变矩形和单向层间界由上述模型直接推导，没有复制该教材的证明。
