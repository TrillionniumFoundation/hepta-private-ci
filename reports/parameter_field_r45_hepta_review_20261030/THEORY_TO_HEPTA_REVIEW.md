# R45 论文与 Hepta 五优先级：恢复来源后的独立理论评论

审阅日期：2026-10-29（America/New_York；执行凭据仍使用 UTC）。本文只依据恢复的论文源、已登记研究设计和实现源码；没有读取 execution04 的 RAW、端点数组或结果，没有运行科学实验。

## 1. 版本与证据状态

论文仓库为 TrillionniumFoundation/ICLR-2027。通过已授权 GitHub connector 实际读取，paper-llm-theory 分支当前 HEAD 仍为 **f8df0a6075f58f3ab9431a889b773cdf8d6e771d**，提交时间 2026-09-26T11:21:37Z，正是历史 R45。默认 main 当前为更早的 39e8a4f5c0db9b5fd3c7ab5320f019120d33004f（2026-09-19），不能把默认分支当作最新论文。这个核对只说明已查 canonical paper 分支未变，没有声称查尽所有其他未发布草稿。

原始入口：[R45 main.tex](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/main.tex)。正文：[sections/r45_main.tex](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex)。

本地恢复 20 个 TeX 文件，187,480 bytes；逐文件重新计算 Git blob SHA-1，全部与 connector 返回的原 blob 身份相同。SOURCE_MANIFEST.json 保存精确路径、Git blob、SHA-256 和固定提交 URL，VERSION_CHECK.json 保存版本核对。仓库当前为 private，公开 web open 返回 DisabledError，未取得可供公开 web citation 的正文 ref；以下为真实授权来源的固定 GitHub URL，不伪造公共网页引用。

## 2. 总判断

**关系已经是“可执行控制研究框架与一个具体神经系统之间的实例化”，但还不是“论文证明 Hepta 神经元正确或优越”。**

R45 最可迁移的贡献是把四个容易混淆的问题分开：被压缩掉的动力学、被隐藏掉的决策信息、动作空间本身的限制、以及估计系数误差。论文明确说它不提供任意 LLM 的普适二维充分统计量，也不把新的 Riccati 代数作为贡献。Hepta 五项优先级分别在工程可执行性、标签语义、信息可用性、独立收益和架构交互上落实这个区分。

当前 Hepta ridge heads 没有解论文的 Riccati、HJB 或全耦合 FBSDE。论文的训练时间参数过程与神经元在推理序列上的内部递推不是同一个时间轴；PyTorch 反向传播也不是 backward stochastic value equation。两边可以通过明确的状态、控制、价值及信息接口连接，不能只因都出现“forward/backward”“field”“noise”就直接认同。

## 3. 论文到底证明什么：核心命题与前提

### 3.1 完整 optimizer state 先于 field

R45 §2 的状态 X 包括参数与 optimizer 辅助变量；momentum 要含动量，AdamW 要含一阶和二阶矩。均值参考、Jacobian 与噪声 covariance 来自完整有限更新映射 Ψ，而不是先平均梯度再代入非线性 optimizer：

\[
\bar x_{k+1}=E_\xi\Psi_k(\bar x_k,\xi),\quad
A_k=D_xE_\xi\Psi_k(\bar x_k,\xi),\quad
Q_k=h^{-1}\operatorname{Cov}_\xi\Psi_k(\bar x_k,\xi).
\]

这支持 Hepta 保存完整 parent、momentum、guard/clock 与实际 RNG/replay 状态的工程要求；但 replay 可用的未来 tape 不因此成为 policy 可观察信息。论文的 finite linearized array 与原 nonlinear optimizer 仍是不同对象。对应 eq:r45-array、eq:r45-optimizer。

来源：[§2](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex#L14-L31)，[完整 momentum array](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r45_exact_group.tex#L66-L82)。

### 3.2 Closure residual 与 reachable forcing 不相同

对于线性化 field Y_k=C_k Z_k：

\[
F_k=C_{k+1}A_kC_k^+,\quad
R_k=C_{k+1}A_k-F_kC_k,\quad
Y_{k+1}=F_kY_k+D_ku_k+c_k+R_kZ_k+C_{k+1}w_{k+1}.
\]

这是所声明线性 array 内的恒等式。强 all-fiber closure 需要 R_k=0；特定策略下实际受到的 omitted forcing 则是

\[
q_k^2=\|R_km_k\|^2+\operatorname{tr}(R_kS_kR_k^\top),
\]

其中矩来自被评估策略的可达分布。一个未被访问方向上的大 residual 与常被访问方向上的同样 residual，决策后果不同。

Proposition prop:r45-transfer 比较同一 affine feedback 在 full/projected 两个模型上分别读自身 field 的表现，使用同一初始 field、同一创新耦合和有限二阶矩。它不是 hidden-state oracle comparison，也不是 nonlinear deployment certificate。连续版本的 all-fiber 等价定理还要求 C_t 常满行秩、最小奇异值有正下界，以及所述光滑/有限时域条件。只有误差预算对共同候选策略类统一成立，才能给出 2ε+η 型优化迁移 regret。

来源：[§2 projection/transfer](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex#L32-L63)，[R40 closure theorem](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r40_control_bridge.tex)，[R41 reachable proof](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r41_reachable_proofs.tex)。

### 3.3 Bellman 信息恒等式属于明确的 LQ oracle 问题

在同一个 affine dynamics、相同初始律、动作空间和二次目标下，连续 unrestricted action 的 curvature 为 W_k=hλI+E_kᵀP_{k+1}E_k≻0。Completing the square 得到

\[
J(\pi)-J_*=\frac12\sum_kE_{\pi}
\|u_k-u_k^*(Z_k)\|_{W_k}^2.
\]

条件正交性把它分成“可见信息下对 oracle action 的不可预测部分”与“相对条件预测动作的 policy mismatch”。期望必须取被评估策略的 occupancy，不能拿 oracle 自己的状态分布代替。条件 oracle-action 均值一般也不是 POMDP 最优 policy，因为改当前 policy 会改变以后的 occupancy 和信息。

另一个可计算的 Schur complement
S−SCᵀ(CSCᵀ)^+CS
是最佳仿射预测残差；一般不等于条件 covariance。条件均值本身为 affine 时才消去额外的非线性可预测部分；joint Gaussian 只是一个充分条件。离散 minibatch 噪声不允许默认 Gaussian。

来源：[§3 advantage/information](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex#L67-L84)，[R42 information proofs](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r42_information_proofs.tex)，[R44 Bellman/information proofs](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r44_proofs.tex#L17-L44)。

### 3.4 Actuation penalty 不能和架构交互混为一谈

论文 nested-action ordering 要求 B₀=B₁S、SᵀS=I、同一物理计价、同一 dynamics/初始律/目标。它分开同动作空间内的信息与策略差，以及扩大动作空间可能减少的最优成本。它不意味着换成 Hepta architecture 后收益必定增加，因为换架构已改变系统的 transition law。

论文 complete-module action 只覆盖声明的 adapter，不覆盖 frozen backbone；Hepta 四个倍率也只是一个很窄的控制族。即使在四动作内 field 接近最优，也不能推出更广更新方向、结构调节、资源分配或自然 free boundary 不再有价值。

更新规则也需重新识别：R45 预训练实验的 momentum 定义是 m⁺=ρm+(1−ρ)g，再给参数加 h√hBu 的加性干预。Hepta 使用其冻结 SGD 实现、学习率倍率、clipping 与 guard/rollback。R40 fluctuation theorem 特别要求 h√h 控制尺度；一般有限幅度 learning-rate change 会改变均值参考，并不自动执行该渐近尺度。因此可以迁移“对完整更新求均值/Jacobian/covariance”的方法，不能直接复制论文的 A、E、Q 或 effort 系数当作 Hepta 的真实动力学。

来源：[eq:r45-actuation](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex#L85-L93)，[R44 nested actions](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r44_proofs.tex#L41-L44)。

### 3.5 Coefficient-error budget 与经验 head 校准不是同一种保证

R45 的 Bellman residual 对固定 policy 比较真实与估计 affine coefficients，明确收费 transition/reference bias/covariance/moment errors。Covariance-level identity 不依赖任意选定的噪声平方根旋转。单一 policy 的误差预算不能推出整个策略类的 regret；两个 policy 排序稳定需要 nominal separation 超过各自误差预算之和。

这不自动覆盖 Hepta ridge head。后者是有限 parent 上真实非线性 paired-tail label 的监督拟合，并没有提供 R45 所需的 uniform coefficient、moment 或 nonlinear expected-cost remainder。校准残差小、训练 R² 高或某次 margin 为正，都不能代替上述条件。

来源：[§3 coefficients](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex#L95-L117)，[R44 residual/transfer proof](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r44_proofs.tex#L55-L162)。

### 3.6 参数场的几何定义不等于充分性

历史场是声明角色上的 L² observable field；三 role energies 的正交变换只保留这三个系数的信息，不能恢复原参数、函数或全部场通道。Raw Frobenius/spectral channels 对协调 permutation 不变，但对一般非正交 Transformer gauge 不不变。W_QW_Kᵀ、W_VW_O 一类 operator channels 可在声明 gauge 范围内保持不变，但 gauge invariance 仍不等于 Markov closure。

因此 Hepta H12 可以是有效的 training-coordinate observable，无须声称 intrinsic functional quotient。当前研究不是论文原三角色 Galerkin 系数的直接复现。动量范数、参数位移和 gradient projections 的实用意义必须在实际 optimizer 坐标与行动规则中解释。

来源：[parameter-field definition 与 finite-field proposition](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/technical/m_parameter_field.tex)，[gauge-aware appendix](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/technical/at_gauge_aware_field.tex)。

## 4. 与五优先级的逐项对应

| 优先级 | 论文支撑的研究原则 | 现有研究确实能检验什么 | 不可越界的解释 |
|---|---|---|---|
| P1：合法行动与真实后继 | 完整 optimizer update；实际 actuation 才决定 controlled transition | 同 parent、同 tape 的 guard 后物理后继、parameter/momentum 差异、有效动作等价类；R 补全 terminal 证据 | 请求倍率不同不代表物理后继不同；first.dynamics 相同不代表 controller history、完整 augmented state 或任何未来 policy 相同 |
| P2：baseline-aligned labels | 固定 terminal 与 continuation policy 定义价值；Bellman telescoping | 一次候选 guard transaction 后固定 baseline tail，相对 baseline-first 的 paired realized contrast；strict deployed choose 与 ungated predict 的差别 | 单 tape 标签不是 expected Q；baseline-tail 不是部署重选 policy 的 Q；12 dependent calibration states 没有 uniform deployment certificate |
| P3：field/full-state/history 与 W | 区分全 fiber closure、reachable forcing、决策信息、仿射解码误差 | 同 bank 上三种已冻结 predictor 的 residual/ranking/regret，加上闭环 B；三个预先选定反射状态的近场和共同动作代价 | full-state ridge 不是 oracle；未赢 field 不证 sufficiency；W 非 reachable、近似相等而非严格同 field，不是普适不可表示定理 |
| P4：独立任务、retention、成本 | 目标收益、泛化与成本分别计量；不把预测区间当均值置信界 | 新 endpoint pairs 和 schedule 上实际 task/clean outcomes、双 observer、普通基线及 fixed taper、观测/训练/评分成本 | 三个固定模型不是 LLM population；history 仍支付 H12 probe；全部 jobs 完成不代表 Pareto 改善；历史总成本无可恢复上界 |
| P5：architecture × controller | 区分系统 dynamics 与控制政策的效应 | 8 paired seeds 下 ordinary/dual event law × baseline/field 的 interaction 和两个 simple effects | 不证明 FBSDE、Call-Put neuron、自然 free boundary 或全生成器替换；正 interaction 不必意味着 dual 内 field increment 为正 |

本表对应研究 README 的 “Research question” 五行，具体实现说明见 [固定研究源码 README](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/README.md)。该完整提交由本地 Git 只读历史确认；实际科学执行身份仍须使用各 SOURCE_FREEZE 的完整提交与文件 SHA，不能用会移动的 branch tip 替代。本地完整源码和冻结元数据由主代理管理，本文不重新定义它们。

### P1 的精确等价语义

first.dynamics 刻意排除 controller history、path-kind 等非物理标签。若 guard 全部 rollback，参数、optimizer 等可能完全相同，但请求动作和历史记录仍不同。对于固定 baseline continuation，如果相同后继拥有相同后续物理更新所需状态、相同 tape、相同 terminal clock，且 reward/charge 相同，可以验证同尾输出与价值相同；这只是该 continuation 语义下的等价。

未来 history-policy 会读取不同的请求动作、guard/work 记录，因此可能选择不同后续动作。不能从 first.dynamics equality 推出 augmented history state equality，更不能推出对所有策略的控制双模拟。若把真实执行成本纳入 Q，即使物理后继相同，只要已发生成本不同，Q 也可不同。

### P2 的关键修正：baseline continuation 本身并不妨碍策略改进

对有限时域、同一合法 transition kernel、加性期望回报，定义真实 expected baseline value：

\[
Q_t^b(s,a)=E[r_t(s,a,S')+V_{t+1}^b(S')\mid s,a],\quad
A_t^b(s,a)=Q_t^b(s,a)-V_t^b(s).
\]

则任何合法 policy π 满足

\[
V_0^\pi-V_0^b=
E_{\pi}\sum_t A_t^b(S_t,\pi_t(S_t)).
\]

所以，若沿实际部署 occupancy 的真实优势均非负，反复应用基于 Q^b 的改进动作仍可保证不劣于 b。**不能仅以“标签用 baseline-tail、部署会重选”就否定这种策略改进。**

当前缺少的是：单条 paired tape 对比如何变成 conditional expected advantage，以及拟合/校准误差如何在部署新状态分布上得到适当控制。原设计正当地把 certificate 设为 false。此恒等式是加性 expected-return 的离散推论；不能直接当作一般 nonlinear recursive-utility/FBSDE generator 的同一公式。

论文 technical/u_continuation_target_semantics.tex 还说明固定 rolling window 的移动右端点项不能删掉。当前 Hepta bank 采用共同 terminal clock，避免那一种移动窗口语义错误，但它仍保持 baseline reference continuation，未自动升级成 learned replanning policy 的自洽 Bellman value。

来源：[rolling vs terminal recursion](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/technical/u_continuation_target_semantics.tex)，[Bellman telescoping proof](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r42_information_proofs.tex#L25-L41)。

### P3 应把“知道更多”与“拟合得更好”分开

对于固定状态分布 ρ 和四动作真实 Q，reward convention 下可定义一个有限动作信息差：

\[
E_\rho\max_a Q(S,a)
-E_\rho\max_a E[Q(S,a)\mid\mathcal I]\ge0.
\]

这是该 Q 和该分布下的单次决策信息价值，不等于整个闭环的 regret。若 history sigma-field 包含 current field，理论上最优条件决策的信息不减少；但固定 ridge、有限样本和独立测试误差并不保证 history head 的经验表现单调改善。Full-current-state 包含更多变量但有限样本更难拟合，不能把其预测器当作全状态最优控制。

W 更适合回答“在预定的 field 数值分辨率下，两个构造状态是否需要不同动作”。排序变化本身不够：若仍有共同最优动作，压缩未必有决策代价。补充诊断的共同最优集合、共同确定动作 minimax regret 与等权 mean regret因此有意义。但这些是三个固定构造对与固定 baseline tail 的局部诊断；反射 state 没有 reachable 保证，H12 近似相等也不排除一个极敏感的 field policy 分辨细微差异。不得把它写成所有 field policy 的不可实现性证明。

### P5 的 simple-effect 解释

若 J 是越高越好的 observer utility，interaction
(J_dual,field−J_dual,baseline)−(J_ordinary,field−J_ordinary,baseline)
为正，只表示 field 的增量在 dual 下更大。例如两边增量分别 −0.01 与 −0.02，interaction 仍为 +0.01。故正交互不能独自支持“field 改善了 dual”。还必须同时读两个架构内 simple effects、dual-field 对 ordinary-field、retention 与成本。若 J 采用成本约定，则全部符号应统一反向解释。

C 的实际 temporal module 只替换 text encoder/decoder，普通模式使用 sigmoid event，dual 使用 FPT CDF 与 interval-end mean reset；boundary 来自 softplus(raw_boundary)+1e−4，是可训练参数，未由任务 Bellman stopping 方程求得。该 inference-time deterministic mean recurrence 不意味着 training-time minibatch innovation 为零，也不证明 forward/backward 共享同一 Brownian 驱动。对应 [固定 architecture.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/architecture.py#L94-L136)。

## 5. 从参数场到一般 NDU：尚未跨越的理论条件

technical/p_optimizer_bridge.tex 的 multidriver theorem 要求 conditional Lindeberg、统一 2+δ 矩、Taylor/漂移 residual 消失、backward terminal consistency、integrand strong L² tightness，以及 causal control convergence。它先得到多维 Brownian noise；再以 forward/backward martingale integrands 对同一 predictable unit direction 的正交能量缺陷趋零，才能压成共同标量驱动。低 covariance rank 或两个 observed losses 相关不等于已经满足这些条件；forward loading 为零而 backward noise 不零的异常集合也须单独处理。

更进一步，scalar common family 的 FBSDE、DPP/HJB 要求声明的 Markov/global Lipschitz/growth 条件、G-monotonicity、terminal sign 条件，以及 coefficient identification。其 affine closure
z=p η(v)σ_u/(1+κp)
依赖 p≥0、κ>0 及 diffusion 对 z 的具体 affine 形式，不是任意 neural module 的通用式。z 是 backward martingale integrand，在适当光滑 Markov 条件下才可写成价值梯度乘 noise loading；它不能直接叫 parameter gradient。

当前五项研究没有测量独立 continuation slope p，也没有在新状态检验 Γ_UV=pΓ_UU 与 Γ_UU=[η(v)σ_u/(1+κp)]²。论文 §7 本身承认这些 neural identification tests 尚未执行。成功 LQ tracking、ridge 策略收益或 FPT event law 的训练收益均不能代替这一步。

来源：[multidriver/common-driver theorem](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/technical/p_optimizer_bridge.tex)，[Markov/G-monotonicity/DPP assumptions](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/technical/core_02_model.tex#L64-L101)，[affine-Z/HJB](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/technical/core_04_hjb.tex)，[依赖图与零-loading边界](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/technical/au_theorem_dependency.tex)，[§7明确未识别项](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex#L237-L268)。

一个可严谨表述的后续桥梁是：先对实际 guard/reset 后的有限时域核证明受控状态聚合——所有同 field 的 states 对每个 action 有相同 projected successor law、相同 immediate expected reward/cost，且 terminal reward 因子化到 field。对有限 action 的普通加性 Bellman 问题，这足以使 value 因子化并允许 field policy。它是比“covariance 低秩”更直接的可检验目标，也是比“full-state 预测器没赢”更强的理论条件。

**这仍不是一般 NDU/FBSDE 的完整定理。** 对 nonlinear recursive aggregator，还需要 aggregator/terminal 与观察 sigma-field 的相容因子化、martingale/交叉变差相容性，以及其比较/适定性条件。对于带 guard、spike/reset 或 topology jump 的系统，transition kernel 必须包括这些跳变；不能在跨越不光滑界面时直接套用平滑 Jacobian expansion。本文提出的是解释桥梁，不修改现有 preregistration，也不宣称当前已验证。

## 6. R45 预训练实验可以支持与不能支持的评论

最明确的新增可执行结果是 exact full-vocabulary aggregation：固定 pretrained logits、features 和全部词表的 partition，在每组加相同 nonlinear offset，按组 log-sum-exp 保留原全部分母，所以 likelihood、存在的参数导数与同 marks 的完整 optimizer path 在 exact arithmetic 下相同。限制也精确：组内 token ratios 不变；backbone、feature map 或 grouping 改变即需重算 cache。这个代数等价验证了受限模块的忠实计算，不是 unrestricted LLM updates 的等价定理。

R45 使用两个 checkpoint（GPT-2、Pythia-70M）、三文本、每组合两个 adapter seeds；116 个 changing parameters、232 维 momentum state。48 cells 不是 48 个独立预训练模型。正文报告的 complete-module stress objective gains 40.76–61.32% 指 tracking-plus-quadratic-effort 的改进，不是 token loss 提高同等百分比；myopic 在这些 stress cells 的 terminal observed loss 实际略低，unseen loss 变化有正有负。effort 是干预向量平方范数，不是 CPU、GPU 时间或能耗。

其 63 calibration / 128 validation 路径的 61st-order-statistic prediction interval，针对 exchangeable 一个未来完整路径、概率同时积分 calibration 与未来路径。它不是 expected advantage 的置信区间，更不是挑选正区间后的条件保证。正文披露 primary/family positive counts 为 37/48 与 13/48，并披露 24 个跨模型 calibration/validation RNG stream reuse；该复用不等于 cell 内 calibration/validation相同，但排除了把所有 cell 当独立 replication 的做法。

这些限制多数已经由论文主动写明。强评论应针对是否在 Hepta 应用中继续保留这些限制，而不是把论文已修正的过强表述重新强加给作者。论文的负面记录、窄 action-space 局限、nonlinear oracle reversals 和未识别 scalar hypotheses，对 Hepta 的科学设计比单一正收益数字更有用。

来源：[exact theorem 与 expressivity](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r45_exact_group.tex#L1-L47)，[§5 outcome semantics](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex#L156-L198)，[protocol、RNG、区间](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r45_protocol.tex)，[摘要的 all-cell numbers](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/main.tex)。

## 7. 可直接用于最终 comments 的表述

1. **最强正面评价**：论文提供了可执行而可反驳的分解框架，把 omitted dynamics、information、actuation 与 coefficient error 分开；Hepta 已把其中关键问题落实到真实 guard kernel、完整 branch state、baseline-aligned tails、同信息比较与架构 factorial。这比只报告 loss correlation 更接近控制研究需要的证据。

2. **最重要保留意见**：当前候选是有限动作的经验策略，不是论文完整 FBSDE/HJB 的求解器。应以真实 guarded successor、baseline-advantage prediction 与独立 task/retention/cost 来判断它，不能把“参数场”命名或 neuron 的 FPT 公式当作理论识别已经完成。

3. **最关键结果解释**：若 field 无 override 且同 guard 下 terminal dynamics 与 ordinary 相同，应报告本候选没有显示决策增量，并保留它的观察成本；这不推翻一切 parameter-field model。若收益为正，也只支持固定任务、模型、action set、head 与已冻结比较，不推成全 LLM sufficiency 或自由边界定理。

4. **执行与证据闭合必须单独结案**：全部注册 jobs、seals、literal restoration、独立分析和补充诊断完成，只意味着这次预定比较获得了诚实的 disposition。效益、retention、interaction 或 sufficiency 的结论可以为阴性、无效或未识别；旧 exact-regression FAIL 与原资源合同未通过不能因此改写。历史已观察工作可给分层下界，旧不可见执行的后续工作及整个历史成本上界仍未知。此处不预告 execution04 的结果。

## 8. 恢复范围及独立复核

主审阅读取 R45 正文、exact-group、R40 closure、R41 reachable、R44 coefficient、参数场几何、optimizer bridge、continuation semantics、scalar assumptions/HJB 与依赖图。另一独立只读 reviewer 复核 R42/R44 的 Bellman information/actuation 部分，确认最需要保留的是 occupancy、conditional-vs-affine residual 和 finite guarded actions 不能套用 continuous LQ 平方 gap 的边界。

本次没有重做论文全部 proofs 或全部 empirical audit，没有把论文作者报告的数值变成本轮独立复算结果。20 个精确源文件和 manifest 为最终评论提供可复核依据。

## 9. A/B 实现成本口径补充（2026-10-30 静态核对）

本节只核对已登记源代码，不修改算法、阈值、补充计划或统计检验，也不读取实际运行结果。以下是 A/B 的具体实现口径；不能未经单独核对将同一成本拆解套到 C。

**三种 learned policy 都支付当前测量实现的共同工作。** bank.measure 调用 training_features.measure_state，后者完整计算 H7、五个 directional channels、额外 loss/module displacement channels 和六个 margins，形成 30 维向量之后，前者才取 field[:12]。这包括 hard-panel 生成与 observer、一次当前训练方向的 forward/backward、三个 probe loss 的反向导数，以及额外 margin generator/observer。bank.measure 还同时构造 full_current_state 和 history6 特征。run.evaluate_paths 对 field12、full_current_state、history6 都调用这一共同 measure；ordinary 与 fixed_taper 分支不调用它。

因此实测的是**当前完整实现的实际成本**，不是仅计算必要 H12 的理论最小成本。相同的前置工作有利于比较已实现 head 的输入效果，但不代表所有方法都已做了各自最省算力的部署实现。若当前实现没有净收益，可据此否定该实现的已测成本/收益组合；不能据此推出删去未使用 richer channels、margins 或不必要特征构造后的 H12 实现也必然没有净收益。反过来，也不能假定尚未实现和测量的优化会得到多少收益。

计时边界同样须明确：feature_measurement_wall_ns/cpu_ns 只包住 measure_state；前后 seal 的 capture/serialization 单列计时；随后 full-current/history 的 NumPy 特征组装位于该内部计时器之外，会进入整体 path/phase 的实际 CPU/wall，但没有因此自动成为 feature_measurement 的分项。作净成本判断应使用相容的完整核算范围，不把某一个分项称作全部 controller overhead。

来源：[bank.measure](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/bank.py#L32-L43)，[各 method 的实际调用](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/run.py#L62-L91)，[完整 richer30 测量](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/multimodal_output_portfolio/field_bridge_v3_20261027/training_features.py#L74-L146)，[计时器](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/branching.py#L18-L24)。

**训练控制标签没有计入训练 CPU 或论文 quadratic effort。** bank 的 value 取 terminal hard_panel 的 means.reward，分支的 costs 另存。严格地说，它不完全等于未扣款的 observer utility：hard_panel 先扣固定 generator refinement_charge × (1 + 1{context.action≠0})。context.action 是每个原模型固定的生成动作，不是四个训练学习率倍率；同一 parent 的四倍率比较中，该固定项共同抵消。它既不是实测 CPU/能耗，也不是论文 λ‖u‖² 的训练干预成本。因此不能写成“Q 已优化包含全部执行成本的论文目标”，当前是 task utility label 与实际资源成本分别报告。

来源：[terminal value 与分支 ledger 分开](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/bank.py#L75-L88)，[hard_panel 的实际收费](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/multimodal_output_portfolio/field_bridge_v3_20261027/learning.py#L143-L170)，[固定生成动作 context](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/multimodal_output_portfolio/field_bridge_v3_20261027/learning.py#L225-L250)。

**零学习率动作仍有真实梯度和 guard 工作。** learning.update 无论 multiplier 是否为零，都会执行 objective、zero_grad、loss.backward、gradient clipping 和有限性检查。只有设置学习率、optimizer.step 以及 optimizer_steps 计数被 multiplier≠0 条件包围。正常训练调用仍计 scheduled_gradient_microsteps；用于 field direction 测量的零倍率调用则计 directional_gradient_measurements。一次零倍率 guarded block 仍执行所排定的 48 个 microsteps、candidate guard 和相关 snapshot/restore 工作，clock 继续前进。Guard 拒绝也不退还已发生的计算。

这解释了为何“参数/动量没变化”不能解读为“零训练成本”，也为何 scheduled microsteps、实际 optimizer updates、direction measurements 与有效 accepted update 必须分开报告。对于 current A/B kernel，零倍率不推进 optimizer momentum，因为整个 optimizer.step 被跳过，而非只把参数学习率设为零后照常调用 optimizer。

来源：[update 的真实分支](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/multimodal_output_portfolio/field_bridge_v3_20261027/learning.py#L207-L223)，[guarded_block 的 48 步与拒绝收费](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/multimodal_output_portfolio/field_bridge_v3_20261027/learning.py#L261-L298)。


