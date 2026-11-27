# 固定网格 QPR 的短时极限：源码与数学诊断

**范围：机制解释与后续验证设计；不修改实现，不授数值资格或 P5 收益。** 本次没有加载模型、概率状态或 E，没有运行当前审计、训练、转移矩阵或高精度 oracle。唯一标量计算是固定 32 点 Gauss 规则的节点几何。[完整来源索引](SOURCE-INDEX.json) 将下列 S1–S9 与实际字节绑定。

## 1. 已有契约与精确源积分的极限

已有 `MODEL.md` §2/4 与 `TRAINING_DOMAIN.md` 已说明：uniform active/remaining-time basis、returning exponential tail、QPR 非精确 semigroup，以及相位重投影可能早释放；现有测试也区分对齐相位运输与非对齐反复投影。它们尚未给出下面两种不同的短时渐近式。[S1–S3]

实际 v8 源胶囊 SHA `288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102` 中的 `operator.py`，与当前 canonical / v8-local 源逐字节相同：25,180 B，SHA `cb3eed1bcfbd3b10cc331a193a5d4b6a3d4309db899e0d8f821477f97b7dbdc1`。`_construct` 对每个 active cell 使用严格内点 `left + width*nodes`；缓存层调用同一算子，只缓存精确输入身份。[S4–S6]

记时间步为 $h>0$，固定格宽为 $Δ$，$σ>0$、有限漂移 $μ$。令 $T_h=QP_hR$ 表示**理想精确源积分**，先取远离吸收边界和 tail 的相邻等宽格。由源格均匀分布进入右邻格的质量，在 $μ=0$ 时是

\[
p_+(h)=\frac1\Delta\int_0^\Delta
\left[\bar\Phi\!\left(\frac r{s}\right)-\bar\Phi\!\left(\frac{r+\Delta}{s}\right)\right]dr,
\qquad s=\sigma\sqrt h.
\]

取 $A=Δ/s$、$B(u)=φ(u)-u\bar\Phi(u)$，直接用 $B'(u)=-\bar\Phi(u)$ 得

\[
p_+(h)=\frac{s}{\Delta}[\phi(0)-2B(A)+B(2A)].
\]

因此，对固定 $Δ$ 的内点格，加入有限漂移后

\[
p_\pm(h)=\frac{\sigma\sqrt h}{\Delta\sqrt{2\pi}}
\ \pm\frac{\mu h}{2\Delta}+O(h^{3/2})+O(e^{-c/h}),\qquad c>0.
\]

远跳及远处 killed-image 修正不改变此首项；贴近吸收边界的 hit 行不可直接套用内点系数。故至少相邻 off-diagonal 元素 $(T_h-I)/h\sim σ/(Δ\sqrt{2πh})$，**不存在有限固定网格矩阵生成元极限**。这不否认连续扩散生成元：问题在于每步重建的分段常密度有跳跃，质量跨界的首项为 $\sqrt h$。固定网格下只缩短步长不能据此推得收敛。[解析推导 D1；S1/S4]

## 2. 实际固定 Gauss 规则、年龄与 tail 是不同误差源

令 $T_{h,N}$ 是固定 $N$ 个源节点的规则；$r_k>0$ 为某节点到相邻格边的距离，$r_*=\min r_k$。Mills 尾渐近给出

\[
\bar\Phi\!\left(\frac{r_k-\mu h}{\sigma\sqrt h}\right)
\sim \frac{\sigma\sqrt h}{r_k\sqrt{2\pi}}
\exp\!\left[-\frac{r_k^2}{2\sigma^2h}+\frac{\mu r_k}{\sigma^2}\right].
\]

固定有限正权重求和后，邻格质量为 $O(\sqrt h\,e^{-r_*^2/(2σ^2h)})$。所以在理想实数算术中，固定规则的 **active 内点 probability 行**满足 $(T_{h,N}-I)/h\to0$，与精确源积分的发散首项不同；这不包括整个 reward/phase 算子，折现矩阵还会有 $-ρI$。FP64 舍入、下溢和检查失败是另一个层次。[D2；S4]

准确说法是**缩放后的极限不交换**：先精确积分再取 $h\downarrow0$，$p_+(h)/\sqrt h\toσ/(Δ\sqrt{2π})$；固定节点先取极限则为零。未缩放的 $T_h$ 本身都可趋 $I$，不能笼统称两重矩阵极限不交换。

名义 v8 几何 $Δ=4.8/256$、$N=32$、$σ=.35$ 给出 $r_*=2.56513\times10^{-5}$，$h_*=r_*^2/σ^2=5.37134\times10^{-9}$。已有两个 tiny-gap 压力步长 $10^{-7}$、$8\times10^{-7}$ 分别约为 $18.6h_*$、$149h_*$，**不在 $h\ll h_*$ 的深冻结区**。这仅排除直接套用该极限解释的捷径，不证明 Gauss 积分已经准确。[S7/S8；SCALAR-GEOMETRY.json]

**剩余年龄。** 隔离纯相位运输，格宽 $ω=d/m$，在 $0<h<ω$ 时 `_construct` 的精确 overlap 给出 stay $1-h/ω$、下降一格 $h/ω$。反复投影再令 $h\to0$，从第 $j$ 格（1-based）到释放的等待趋于 Erlang$(j,1/ω)$，均值 $jω$、方差 $jω^2$；原 uniform law $[(j-1)ω,jω]$ 的均值却是 $(j-1/2)ω$。从最高格看，方差 $d^2/m$ 需随相位细化才消失。这是隔离相位链的**涌现极限**，不是代码显式采用 Erlang 模型，也不与对齐 $h=kω$ 的确定性运输测试冲突；不能直接推广到耦合 reset 的完整网络。[D3；S1/S3/S4]

**Tail。** 每步把 tail 质量重建为 $L+\mathrm{Exp}(λ)$，条件均值固定为 $L+1/λ$；保留质量不等于保留其真实形状或未来回返性质。两个 tail law 即使同为质量 1，若相差平移 $a>0$，其连续折现首达矩 $ℓ(x)=e^{-κ x}$ 相差因子 $e^{-κ a}$，Q 却给出同一个 tail 系数。固定源 quadrature 又叠加自己的误差。现有 returning-tail 测试只证明指定 fixture 可回返/触界，不证明任意 tail 精度或正漂移 escape 性质。[D4；S1/S3/S4]

## 3. 对已有失败能说什么，以及下一项有界验证

已冻结压力摘要记录 18 个无穷重复 gap 的**折现 value** 检查，其中六模型在 $8\times10^{-7}$、$10^{-7}$ 两类步长共 12 项失败。它们不是有限 horizon count/probability；实际 burst fixture 从 posterior47 出发，tiny-repeat 用 posterior48/49，初始 law 与时间域不同。[S8]

上面的四个机制没有给这些失败分配误差占比或符号。要作定量归因，还需固定同一初始 law，分别控制空间投影、quadrature、年龄、tail 与 perpetual resolvent 条件数；守恒、单点解析精度或有限 schedule 通过都不能替代这项区分。尤其不能把“exact-source 的过快跨格”和“极小步长下 fixed-node 的近冻结”混成同一个解释。

建议下一次**另行批准后**只做标准库 toy 验证：42 对自由扩散相邻格闭式积分/固定 Gauss 标量、4 个隔离相位几何例、2 个同质量不同位置的 tail Laplace 矩；不使用真实模型或 posterior。先冻结全部输入与顺序，最多 120 秒、1 worker/thread、RSS256 MiB、零重试；记录 FP64 不可分辨项，不据此给训练域通过。具体 roster、归一化观测与停止规则在 [FOLLOWUP-PLAN.json](FOLLOWUP-PLAN.json)，当前 `execution_authorized=false`。若它支持上述局部机制，再另立有界的真实 law 归因研究；本笔记不改变现有压力失败、数值 HOLD 或 P5 收益门。
