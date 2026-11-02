# R19：真实延迟复位任务的连续值函数与比较证明

本交付给出实际 R18 连续任务的定理证明草案：严格的时间 slab 递归、反射／Neumann 停止问题的比较、准入时刻左右极限，以及理想 jump-aware 隐式差分方法的定性值收敛。这里没有把网格通过当作 continuum proof，也没有另换成永续 put 问题。

主体见 [PROBLEM_AND_THEOREMS.md](PROBLEM_AND_THEOREMS.md)，收敛条件与证明见 [CONVERGENCE_DRAFT.md](CONVERGENCE_DRAFT.md)。[独立审阅](INDEPENDENT_PROOF_REVIEW.md)逐项记录 exact task 参数、DPP 上界和仍未证明的命题。

## 理论上新建立的范围

以 `G_k` 表示 `kρ` 的右值，`W_k(s)` 表示该 slab 内从初始右值到下一准入左值的连续演化。复位后继由前一 slab 提供，下一右值为

`G_(k+1)=max(W_k(ρ), −κ+M G_k(x_reset))`。

正延迟使其严格因果，不需要假设同时非局部 fixed point 收敛。每个 slab 的 reflected heat／stopping recursion 经精确 fold 映射到长度 16 的圆周，得到比较和唯一值函数；不要求 sigmoid 的 STOP payoff 在域端点有虚假的经典零导数。值在每个 trace slab 连续，整体为右值的 càdlàg 函数；准入时刻允许真实 jump。

理想隐式差分图具有 M-matrix 比较、显式收缩构造和稳定性。证明进一步核对了圆周一致性、半松弛上下极限、初值 barriers、旧 obstacle 的左末端处理及对齐 jump 的有限归纳。结论要求 **ρ 精确对齐、trace-aware 插值、精确代数求解或 scaled residual 趋零**。固定 FP 容差及有限 residual 表不自动满足整条渐近序列的要求。没有推出误差率、梯度或边界位置收敛。

## 三个不依赖网格的 exact task 结论

| 结论 | 证明依据 |
| --- | --- |
| mode1、x=−1.5、σ≤1.3 在 ρ=.2 的值 jump 大于 `.11175714` | Taylor 有理界给新 RESET 值 `>.421`；fold 的 Lipschitz 性和 Doob 界给无复位左值 `<.309242857` |
| mode1 在剩余时间 `t≥.6` 时全空间立即 RESET 最优，任意 σ>0 | 至多三次复位的可行策略有精确下界 `12720913317/25306336000 > 1/2`；STOP 回报始终 ≤1/2，延后 RESET 不能增加当前后继值 |
| 首准入 `t=.2`、mode1、`σ≤1.3` 的 RESET 右边界在 `(-.25,1.25)` | 下点 no-reset 值 `<.4201<B`；上点 STOP 回报 `>13/30>B`，结合 RESET 下区间结构 |

上述三个证书使用登记的基线奖励、转移矩阵与费用，不自动覆盖修改这些参数后的训练模型。第二项证明没有 continuation band 的情形确实存在；不能为每个 mode／时刻都强加两条边界。第三项只是首准入的粗解析括号，不是任意时间的窄误差界。

[纯有理算术证书](ARITHMETIC_CERTIFICATE.json)用 Fraction 逐项核对 Taylor 下界、尾项上界和分数比较；没有调用扩散求解器、抽样世界或读取新的边界位置结果。

## 只声明已经支持的自由边界结构

RESET 接触集若非空，是闭的下区间；它可以为空或整个空间。满足相应回报条件时可证明上端点 STOP 或全空间 RESET。

**尚未证明一般 STOP 单上阈值、全局 smooth fit、移动边界正则性或一般时刻／模式的精确认证位置夹逼。** 局部生成元 `Dg''−carry` 的正负不能代替全局最优停止论证。尤其下反射端点因为 payoff 正斜率，有短时 `O(√δ)` 的 WAIT 收益压过 `O(δ)` carry，不能直接将其判成 STOP。

对基线，σ=.7 时两模式的内部局部 WAIT 增益均为负；σ=1／1.3 时出现负 x 的正增益带。此差异及反射边界层不支持预设统一的单阈值形状。

完整金融／神经任务、真实未知内容／跨模态学习、连续事件原生执行、生产所有权及 GPU／能耗采用仍未闭合。该交付未开展新的数值收敛或边界定位验收；如追加可执行验收，将先冻结并发布源码／协议。
