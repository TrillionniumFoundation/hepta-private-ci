# 条件解析编辑的公式、可行域与保持限制

## 符号与原模型

活跃时绝对对数状态满足 `dY=mu dt+sigma dW`。流收益为 `gain*Y-maintenance`，贴现率为`rho>0`。状态到达下边界`b`时支付成本`K>0`，经过确定不应期`d>0`（其间无流收益），回到固定绝对位置`a>b`。

源码八参数顺序为：`mu,sigma,discount,log_reset,refractory,gain,maintenance,spike_cost`，分别对应`mu,sigma,rho,a,d,g,m,K`。`log_reset`是绝对对数位置a，不是到边界距离；真实reset距离是a−b。

定义：

\[
\kappa=\frac{\mu+\sqrt{\mu^2+2\rho\sigma^2}}{\sigma^2}
=\frac{2\rho}{\sqrt{\mu^2+2\rho\sigma^2}-\mu},\quad
s=\frac g\rho,\quad t=\frac{g\mu}{\rho^2}-\frac m\rho,\quad
\eta=e^{-\rho d}.
\]

稳定实现使用第二个kappa表达式，与源码一致。活跃区域的价值方程是

\[
\tfrac12\sigma^2 V''(y)+\mu V'(y)-\rho V(y)+gy-m=0.
\]

舍弃在无穷远爆炸的解，令`V(y)=s*y+t+A*exp(-kappa*(y-b))`。平滑贴合`V'(b)=0`给出`A=s/kappa`。值匹配`V(b)=-K+eta*V(a)`给出原源码残量

\[
F(b;\theta)=sb+t+\frac{s}{\kappa}+K
-\eta\left(sa+t+\frac{s}{\kappa}e^{-\kappa(a-b)}\right)=0.
\]

在b<a下：

\[
\partial_b F=s\left(1-\eta e^{-\kappa(a-b)}\right)>0,
\qquad \partial_K F=1.
\]

所以合法内点根唯一。给定目标`b_*`，只改K的精确逆是

\[
K'=K-F(b_*;\theta).
\]

这一步无需任何梯度更新，也无需神经网络学习去猜K。仍必须检查新K正且有限、目标在原合法内点范围，并用原正向根/传播程序验证。原实现要求reset距离严格在`(1e-4,8)`内、sigma/rho/g正、maintenance非负、`0<d<=2`，其余原物理校验照常适用。

## 为什么两个坐标能保持一个锚点

A发往B的输入为

\[
y_B(x)=c+\alpha b_A+\beta w^\top M_A(x;\theta_A),
\]

其中本实验`alpha=.31,beta=.48,w=(.63,-.41)`，`M_A`为有限期限内累计有符号触及量，x为A绝对初态。先改变K使边界到达目标，再选择

\[
c'=c+\alpha(b-b')+\beta w^\top\{M_A(x_0;\theta)-M_A(x_0;\theta')\}
\]

就使锚点`x_0=.72`的B输入完全相同。B的其他参数、自己的内生边界和演化期限都固定，因此其所有49个连续输出在同一浮点误差线内保持。

## 多锚点和全域为何不自动保持

同一个c'能同时保持所有x，当且仅当

\[
\alpha(b'-b)+\beta w^\top\{M_A(x;\theta')-M_A(x;\theta)\}
\]

在要求保持的x集合上为一个常数。一般的首次触及概率和有符号续生信号不满足此条件。固定目标b'已经通过严格单调残量唯一确定K'，此后只剩一个常数偏置自由度；多个独立锚点通常过定约束。

更明确地，在固定有限期限下让x趋于无穷，所有触及概率趋于零，故

\[
\lim_{x\to\infty}(y'_B(x)-y_B(x))=(c'-c)+\alpha(b'-b).
\]

本轮直接编辑的这个极限是`0.006095251723316795`，非零；锚点输入差约−2.22e−16。函数差不可能在全域为零。21个固定初态的49项原传播输出也直接观测到最大差`0.007229360858953426`。该反例是保持条件的范围，不否定原给定锚点目标的精确成功。

## 对更一般读出编辑的含义

若冻结特征矩阵H，并要求保护样本所有连续输出完全不变，线性读出增量必须满足`H*deltaW=0`。可用方向属于H的零空间；H列满秩时唯一精确保留编辑就是零。近似保持、只保持argmax、加入新特征或改变可编辑参数域是不同数学契约，须分别说明和验收。

以上解析编辑证明给定内部目标可直接实现。选择哪个目标能提高真实任务收益，是另一层需要独立任务数据、成本定义和NDU目标的决策问题；不能将给定目标命中率当成端到端能力改善。
