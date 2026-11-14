"""Theory and fixed-diagnostic prose for the completed Hepta report."""


def dynamics_section(data, images, *, table, f, yes, fig):
    diagnostics = data["diagnostics"]
    phase = diagnostics["phase_dynamics001"]["results"]["rows"]
    reference_rows = [
        [
            r["case"],
            r["put_recovery_gain"],
            f(r["trace"]),
            f(r["determinant"]),
            str(r["eigenvalues"]),
            f(r["tail_margin_peak_to_peak"]),
            f(r["mean_peak_interval"]),
        ]
        for r in phase
        if "trace" in r
    ]
    mesh_rows = [
        [
            r["case"],
            f(r["internal_step"]),
            f(r["scaled_max_state_error"]),
            yes(r["reference_gate_passed"]),
        ]
        for r in phase
        if "internal_step" in r
    ]
    coupling = diagnostics["coupling_diagnostic001"]["results"]["rows"]
    coupling_rows = [
        [
            r["mode"],
            f(r["outer_step"]),
            f(r["inner_step"]),
            f(r["flow_scaled_max_error"]),
            f(r["memory_scaled_max_error"]),
            f(r["terminal_memory_l2_error"]),
            yes(r["reference_resolved"]),
        ]
        for r in coupling
        if "outer_step" in r
    ]
    return f"""<section id="dynamics"><h2>6. 能证明的动力学性质与外层耦合误差</h2>
<p>令 α=a′(x)≥0，s=−p′(x)&gt;0，固定 v 时 (q,z) 子系统雅可比为</p>
<div class="equation">J = [[(−1−g<sub>C</sub>α+g<sub>P</sub>s)/τ<sub>q</sub>, −1/τ<sub>q</sub>],
[g<sub>z</sub>s/τ<sub>z</sub>, −1/τ<sub>z</sub>]]。</div>
<p>Call 项提供恢复方向，Put 项可增强边界正反馈，慢恢复 z 对 q 为负反馈。
g<sub>z</sub>≥g<sub>P</sub>使固定输入下平衡唯一，并不自动保证平衡稳定。
在本轮参数与输入界内，可构造 |v|≤3、|q−q<sub>*</sub>|≤15、0≤z≤4 的不变矩形；
理想实数算术下 ETD2 也保留相应凸组合结构。该有界性不能排除周期运动或敏感梯度。[T]</p>
<h3>手选、未训练参数的相位诊断</h3>
<p>固定 κ=1、x<sub>*</sub>=0、g<sub>C</sub>=1、τ<sub>q</sub>=1、τ<sub>z</sub>=6、零输入与 v=0，
改变 g<sub>P</sub>=g<sub>z</sub>。在 v=0 不变平面的 q/z 子系统中，g=1.5 的局部平衡为稳定焦点，
g=3 为双特征值实部正的双曲源；完整三维系统另外具有 −1/τ<sub>v</sub> 这一稳定特征值。
该实验没有使用正式任务数据或已训练权重，仅展示结构可容纳衰减与自主周期运动。</p>
{fig(images, "phase_dynamics", "预定义未训练相位探针：参考轨迹、采样边界穿越与内步敏感性。不能代替训练模型的脉冲证据。")}
{table(["case", "gP=gz", "Jac trace", "Jac det", "特征值 [实,虚]", "尾段 margin峰峰", "平均峰间隔"], reference_rows)}
{table(["case", "h", "[0,180]全采样点最大scaled误差", "0.005门通过"], mesh_rows)}
<p>周期条件下 h=1/16 的最大 scaled q/z 误差约 0.013316，超过该独立探针预声明的 0.005 门；
h=1/32 约 0.003386。这里是<strong>整个 [0,180] 采样区间的最大误差</strong>，不是仅终点误差。
该长期失败被保留，没有据此修改正式训练步长，也不把有限状态当作长期精度保证。</p>
<p>理论文档以外矩形和内部排斥椭圆构造无平衡的紧致正不变环域，利用 C1 平面系统的 Poincaré–Bendixson 定理，
证明此手选条件下至少存在一条周期轨道。它没有证明周期轨道唯一、孤立或稳定，亦不是经典 Hopf 分岔证明。
matched C1 满足相同证明条件，因此周期轨道存在性不是 analytic 全局形状独有优势。[T][PB]</p>
<h3>条件精确 memory 与整体连续系统的区别</h3>
<div class="equation">Ṁ = −λM + γ(u−Mk)kᵀ，A = λI + γkkᵀ。</div>
<p>固定 k、u、λ、γ 的单个时间段里，M 的 rank-one 更新是精确解；齐次传播特征值为
exp(−λΔ)（k 的正交方向）与 exp(−(λ+γ‖k‖²)Δ)（k 方向）。因此在固定非负率、固定内容条件下是非扩张的。
完整网络的参数梯度还包含状态到率、内容投影和控制器敏感性，不能从该条件收缩推出全耦合 BPTT 收缩。</p>
<p>实际每个 token 先把 BoundaryFlow 推进 Δ，再用末端通道确定 λ、γ，并把这两个率冻结后推进 M。
若把它解释成联合连续 ODE，这是 Lie 型分裂/端点冻结的外层离散化。
例如 λ(t)=λ₀+ct+o(t) 时，纯遗忘连续解的对数系数为 −λ₀Δ−cΔ²/2+o(Δ²)，
端点冻结为 −λ₀Δ−cΔ²+o(Δ²)。所以内层 h→0 并不消除固定外层 Δ 的误差。
模型可被定义为确定的因果 tick map；该定义不能同时被宣传为全耦合连续真解或任意重采样不变。</p>
{fig(images, "coupling_error", "独立常数物理输入联合 ODE 参照：比较外层 Δ 与内层 h 的不同作用。矩阵误差含外层末端率冻结影响。")}
<p>耦合诊断固定 I<sub>v</sub>=1.2、I<sub>b</sub>=−0.5、k=(.6,.8,0)、u=(1,−.5,.2,0)、零初始矩阵，
采用另外明确声明的率头 λ=softplus(−3−1.2(a−a<sub>*</sub>))、γ=softplus(1.1(p−p<sub>*</sub>))。
它是三角耦合：flow 驱动 M，M 不反驱 flow；不是正式训练模型的任务分数。独立 NumPy 联合 RHS 与 DOP853 双容差参照，
没有调用生产 RHS 冒充独立验证。</p>
{table(["mode", "外层 Δ", "内层 h", "flow scaled误差", "M scaled误差", "末端M L2误差", "参照一致性"], coupling_rows)}
</section>"""
