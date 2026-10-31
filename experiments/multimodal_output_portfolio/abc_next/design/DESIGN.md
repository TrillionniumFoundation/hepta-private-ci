# 下一轮：公开信息、条件价值和独立来源的可证伪设计

本轮先解决一个明确的问题：旧反馈策略没有获得的收益，究竟是公开历史下可实现而没有学到的收益，还是事后 oracle 使用私有目标与未来结果才有的收益？随后在新的冻结来源上复验风险训练与反馈控制的独立增量。此设计不修改 `abc_recovery/protocol.json`，不把已经看过的开发来源重新称作独立 test。

## 1. 来源边界和执行次序

所有区间都是 v7 manifest 内的**来源对**，左闭右开；一个来源对的所有视图、策略重放、生成随机数和训练 seed 保持相关。

| 用途 | 角色与区间 | 决策权限 |
|---|---|---|
| 共同公开历史有限分布诊断 | `forecast_fit[448,480)`，32 对 | 只用于本文 H1 诊断；不进入主 critic 拟合 |
| 新条件价值拟合 | `forecast_fit[480,736)`，256 对 | 拟合与来源二折交叉拟合 |
| 架构和静态对照选择 | `forecast_calibration[448,576)`，128 对 | 明确属于开发集；允许预先列出的候选选择 |
| 一次开发资格检查 | `development[896,1000)`，104 对 | 选择冻结后只执行一次；不据此再选架构 |
| 最终独立评价 | 新冻结 `test` 角色内 512 对 | 全部模型、策略、主对比和统计程序冻结后才能读取 outcome |
| Public sensor 训练 | `train` 角色 | 第三个独立 reader；不使用 Primary / Secondary 评分器作在线输入 |

已有 `development[0,896)` 与 `forecast_fit`、`forecast_calibration` 的 `[0,448)` 不作为本轮新的独立评价。未触及的 audit/test/retention 也不因“以前没用过”而自动变成训练数据。neuron calibration/verification 继续按原生接入的专门协议使用。

最先执行的诊断协议为 `COMMON_HISTORY_PROTOCOL.json`。冻结工具只读来源 manifest 元数据、文件校验和和代码，不运行生成器或读取新诊断 outcome。主最终评价应有自己的后续冻结协议；本文不代替其精确来源 ID、模型文件 SHA 和运行时校验。

## 2. H1 共同公开历史实验

固定旧 `seed-17/output_ndu` 生成器。公开输入完全缺失：图像与 mask 为零，文字只含已知 swap 指令和无数字提示标记。对 swap=0 和 1 各生成四个独立初始草稿；每个草稿、公开 latent、输入和剩余预算构成一条固定公开历史。

私有目标是上述 32 个来源对的均匀有限分布。目标只在离线评分侧出现。由于输入和初始草稿的生成程序没有目标参数，对每个固定公开历史，条件目标分布仍是同一个已知均匀分布。这是本实验主动构造的条件生成律；它不声称恢复了自然任务的真实后验。

初始生成沿旧公共前缀 `refine_semantic, couple`；随后将剩余预算显式设为 H1。动作顺序固定为 `stop, refine_semantic, refine_image, refine_text, couple`。每条历史、每个动作执行 32 个拟合未来分支及 64 个独立评价未来分支，每个实际输出都对全部 32 个目标评分。私有目标被完整积分，32 个目标不是 32 个蒙特卡洛置信样本。

动作之间使用独立注册随机流；同一动作的批量 decoder 行按声明的生成律视为独立未来样本。fit 与 evaluation 的流身份不重合。每条分支从同一个不可变公开父状态出发，动作提交在未来采样前写入 ledger。PNG 和 UTF-8 先实际写盘、关闭 archive、独立读回校验，才进入两个离线评分器。

策略包括：H1 固定 stop、H1 固定 couple、旧 public-only Q1 critic，以及从 Primary fit 分支选出的单动作 lookup。该 lookup 只对这八条固定历史定义，是有限诊断参考，不是一个已经能泛化的新神经控制器。八条历史的所有 fit 选择统一落盘封存后，才允许发出任何 evaluation 分支；Secondary 评价相同已冻结动作，不重新替 Primary 选动作。

stop 与 semantic 在 H1 保留实际草稿，因此其输出效用在给定目标下是确定的。semantic 仍更新 latent 并支付 0.002 成本；没有后续输出步骤时，该动作不能体现延迟语义收益。这个结构事实是确定性区间的依据，不是看到样本恒定后才声明确定性。此诊断不能据此否定 H2 或真实时序任务里的语义修正价值。

## 3. 信息层级：可实现动作和 oracle 的区别

记净效用为 \(u_{kra}=U_{kra}-c_a\)，\(k\) 是私有目标，\(r\) 是未来潜在结果表，\(a\) 是动作。风险参数 \(\gamma=2\)，目标权重 \(w_k=1/32\)。先在指数矩空间计算：

\[
Z_0=\min_a E_{k,r}[e^{-\gamma u_{kra}}],\qquad
Z_T=E_k\min_a E_r[e^{-\gamma u_{kra}}],
\]

\[
Z_F=E_r\min_a E_k[e^{-\gamma u_{kra}}],\qquad
Z_{TF}=E_{k,r}\min_a e^{-\gamma u_{kra}}.
\]

再统一转换 \(C=-\log Z/\gamma\)。\(C_0\) 是公开历史只能选择一个动作的条件最优值；\(C_T\) 额外给出私有目标；\(C_F\) 额外给出**所有动作的未来潜在结果表**；\(C_{TF}\) 同时给出两种信息。\(F\) 不是在线策略已经观察到的当前草稿，也不是只看所选动作之后的下一次随机数。

对同一完整经验表，必有

\[
C_0\le C_T\le C_{TF},\qquad C_0\le C_F\le C_{TF}.
\]

这两种信息优势通常不能唯一地加法分摊；报告 \(C_{TF}-C_T-C_F+C_0\) 的交互项。直接用 evaluation 表选最优动作的 \(\widehat C_0\) 也包含有限样本取最大值的乐观性。报告将它明确标作经验诊断，不把它称作总体因果最优值，也不将它的动作灌入在线策略。

有限模型中，随机混合动作不能优于某个确定性动作：混合策略的指数矩是各动作矩的凸组合，其最小值至少为最小动作矩。因此 H1 的完整动作表已经包含该已声明动作集内的所有公开信息策略。这个结论只适用于固定历史、动作集、条件分布和剩余 H1。

## 4. 条件值区间和三种失败机制

对每个动作和每条评价未来分支，先精确平均所有私有目标，得到

\[
Y_{ra}=\sum_k w_k e^{-\gamma u_{kra}}.
\]

净效用界 \([-1.002,1]\) 在冻结前给出，因此 \(Y\in[b_-,b_+]\)，其中 \(b_-=e^{-2}\)，\(b_+=e^{2.004}\)。对 \(n=64\) 个未来分支，用双侧有界 Hoeffding 不等式并对五动作、八历史、两评分器做 union bound：

\[
r=(b_+-b_-)\sqrt{\frac{\log(2\cdot5\cdot16/\alpha)}{2n}},\qquad\alpha=0.05.
\]

区间截在已知矩界内，再用单调递减变换 \(-\log Z/\gamma\) 变为 CE 区间。确定动作的目标积分是精确值，其未来采样误差为零。这个区间不要求动作间独立；它要求每个动作内的未来分支按声明条件律独立。32 个目标、五动作和重放行数不扩增置信样本量。

若动作区间为 \([L_a,U_a]\)，则条件最优 CE 在 \([\max_aL_a,\max_aU_a]\)。已冻结策略选 \(\pi\) 的 regret 区间为

\[
\left[\max(0,\max_aL_a-U_\pi),\ \max(0,\max_aU_a-L_\pi)\right].
\]

这将三类问题分开：

1. **公开信息不足。** 同历史的目标平均动作值可能接近，而私有目标 / 未来 oracle 上界很大。公开输入完全缺失时，新 sensor 也不能创造目标信息；草稿只影响修复或停止的价值。
2. **条件矩估计不足。** 将旧 \(\widehat Z(h,a)\) 与独立评价得到的 \(E[Y_a\mid h]\) 比较，报告逐动作误差、MSE、最大误差估计和本有限历史集合的同时误差上界。
3. **选择或策略不足。** 比较冻结 lookup、旧 critic 与上述条件最优区间。若条件值已足够准而动作仍差，才有证据归因于策略规则；区间过宽时必须保留未识别状态。

有界区间在 64 分支下可能很宽，这是预先接受的限制；不能通过事后改窄区间、增加伪独立行数或挑选有利历史来“闭合”统计问题。可追加样本的下一轮需另行注册独立分支与序贯规则。

旧 Q1 没有在这个 32 对有限 prior 上训练，其条件值误差也可能反映 prior / task-law shift。不能将误差全部归因于 673 维表示或优化失败；主任务的新增来源评价才检验通用新 critic 的泛化。lookup 依据完整已声明 prior 的 fit 分支选择，不知道某次私有目标的实际取值，因此仍属于该有限过程的因果参考。

Hoeffding 原始来源：W. Hoeffding, “Probability Inequalities for Sums of Bounded Random Variables”, *JASA* 58(301), 13–30 (1963), [DOI](https://doi.org/10.1080/01621459.1963.10500830)。这里的固定有限目标积分、union bound 和 CE 反变换是本文显式推导。

## 5. Q 的最大化、Z 的最小化和近似误差

旧 `DYNAMIC_RISK.md` 的 greedy 链在 Q 表示 CE 效用、greedy 表示 argmax 时是正确的；旧执行和旧证明不需改写。为消除与代码中正指数矩 Z 的符号混淆，本轮明确写成：

\[
Q_t^*(h,a)=\mathrm{CE}_\gamma[V_{t+1}^*(H')-c_t\mid h,a],
\quad \widehat a=\arg\max_a\widehat Q_t(h,a).
\]

若 \(\sup_{h,a}|\widehat Q_t-Q_t^*|\le\delta_t\)，则

\[
Q_t^*(a^*)\le\widehat Q_t(a^*)+\delta_t
\le\widehat Q_t(\widehat a)+\delta_t
\le Q_t^*(\widehat a)+2\delta_t.
\]

条件 CE 单调、平移不变，因此对随机未来值的 sup 范数是 1-Lipschitz。把后续策略损失递推代入，得到 \(V_0^*-V_0^\pi\le2\sum_t\delta_t\)。这里的 \(\delta\) 是 **CE 单位的 Q 均匀误差**；若 head 只拟合近似 continuation 的 Bellman backup，还必须将 continuation 误差计入 \(\delta\)，不能忽略。

代码训练的是 \(Z\) 并取 argmin。若 \(Z,\widehat Z\ge m>0\) 且绝对误差 \(\le\epsilon\)，由 log 的 Lipschitz 界，\(\delta\le\epsilon/(\gamma m)\)。若相对误差 \(|\widehat Z/Z-1|\le\rho<1\)，则 \(\delta\le-\log(1-\rho)/\gamma\)。\(\gamma=0\) 单独回到期望净效用，不使用除以零的变换。

训练 MSE 或有限 holdout 的平均平方误差不能推出上述均匀误差证书。本文工具只对预先固定的有限历史/动作集合提供蒙特卡洛区间，不给全部神经状态、H2 或开放世界任务提供最优性证书。

## 6. 主实验的可观测状态与条件价值

新增 public sensor 在 train role 独立训练；读取原公开输入、mask、可靠性标记和实际当前草稿，输出语义预测概率、熵、跨通道分歧与缺失标记。未做后验校准前，称其为“预测语义概率”，不直接称作真实 Bayesian posterior。Primary / Secondary evaluator 不进入在线控制。

明确携带公开原始 Observation 的缓存摘要；不能用闭包从包含 Target 的 batch 偷取数据。初始命令、提示的可靠性和 mask 应保留，否则“图像全零”与“观测缺失”可能被误混。生成后的草稿特征只可在实际动作执行后读取，未选分支的未来草稿不能提前成为特征。

主开发只比较四个候选：原 673 维 / hidden 32、原 673 维 / hidden 128、追加 sensor / hidden 32、追加 sensor / hidden 128。四者使用同一批新 fit rows、训练步数、来源二折和控制预算 schema；较宽 head 和 sensor 的实际计算成本分别报告。

二折以**来源对**分组，所有视图、生成随机数、重放节点一起进同一折。Q1 在另一折训练，为本折真实 child public state 预测 continuation 产生 Q2 target；最后 Q1 用全 fit 集重拟合部署。交叉拟合减少同样本 bootstrap 的乐观性，但不会自动消除 model bias，也不会令 OOF Q1 和最终 full-refit Q1 完全相同；这个部署分布变化明确属于近似误差。

候选选择仅用 seed17 NDU 的开发数据，随后将选定配置应用到全部 15 个冻结生成器。旧 legacy feedback 作为历史复验；新 673/32 matched-data baseline 控制更多新数据与 cross-fitting 的作用，不能把其共有收益全归于 sensor。

新 one-shot 使用同一 sensor、同来源、同训练目标。在初始公开历史一次选定完整路线；不使用后续实际草稿调整。静态路线在开发集调优。这些对照检验反馈是否超过强的无反馈方案，而非只超过任意固定路径。

共同历史诊断后、四个候选拟合及正式评价冻结之前，主线统一加入已知运行语义约束：Q1 选择和 continuation backup 排除被 stop 严格支配的 H1 semantic，one-shot 排除末步 semantic 路线；H2 首步 semantic 继续可用。这一约束对四个候选一致实施，旧 legacy 保留原状。新增特征的独立收益必须在这些共有约束下比较，不能把支配约束修正归为 sensor 增益。

## 7. 训练处理、主要比较与统计依赖

本轮先复验已有 15 个生成器，不临时加入 lambda=0 新训练臂。已有实际输出 NDU 处理为

\[
F_\gamma(\theta)=\frac{M_\gamma(\theta)-1}{\gamma}+0.05A_\theta,
\qquad M_\gamma=E[e^{-\gamma U}],\quad\gamma=2.
\]

mean 臂取 \(\gamma\to0\)，即 \(-E[U]+0.05A\)；SFT continuation 的监督系数为 1。应记录实际 gamma、aux 系数和 fixed generator SHA。

即使 aux 账面系数相同，该风险比较也不是“纯 CE 加相同有效 aux 权重”。因为

\[
\nabla F_\gamma=M_\gamma\left[\nabla\left(\frac{\log M_\gamma}{\gamma}\right)+\frac{0.05}{M_\gamma}\nabla A\right],
\]

相对 CE 梯度的有效辅助权重为 \(0.05/M_\gamma\)，还存在整体梯度尺度与优化器路径变化。本轮识别的是已声明操作性训练处理的独立来源表现；纯风险目标、aux 权重和旧 v6 gate/surrogate 的进一步分解属于独立开发及另一份未开启 test 的研究。

主最终评价使用 512 个新冻结来源对、五个训练 seed、四个生成随机分支、八个视图，报告全部 SFT/mean/NDU 与 fixed、legacy feedback、enhanced feedback、tuned static、new one-shot 的结果。两个预先指定主要比较为：

1. **风险训练增量：NDU − mean，在同一 fixed 推理下。**
2. **反馈增量：NDU enhanced feedback − 开发阶段选定的最强非反馈对照。** 非反馈候选是 fixed、tuned static、new one-shot；最终 test 不再选择比较对象。

这两项名义 97.5% 区间对应两主对比的保守家族处理。采用 4000 次来源 × seed 交叉重采样；每次对比必须使用同一来源/seed 重采样权重，保留所有视图、生成分支和策略配对。另报固定这五个已训练 seed 条件下的来源聚类区间，区分对任务分布的推断与对训练随机性的推断。只有五个 seed，交叉 bootstrap 对 seed 母体的外推仍是近似证据。

核心 2×2、相对于原 fixed 的反馈增量及训练 × 推理交互全部报告，但不能替换强非反馈主要门槛。Secondary 是同一任务的稳健性评分，不是第二组独立任务；所有非主要消融与观察者分歧明示为次要/诊断证据。

同时报告独立任务成功、必需模态完成、事实一致性、均值及尾部损失、动作开销、真实计算和 P50/P95 延迟。训练、sensor、critic、规划、所有丢弃分支、特征提取与评分开销分账并计总成本。预定效用中的每步 0.002 只是代理价格，实际墙钟成本不能自动与之等同；若质量与成本分别报告，不能声称净收益已经抵偿全部现实成本。

## 8. 交付和闭合标准

Git 保存主要详细报告、冻结协议、代码、测试与校验摘要。原始 PNG/TXT、数组和大 ledger 保留本地运行目录，不再以长期大文件归档作为完成 blocker。

完成的工程诊断应提供：真实生成输出、同公开历史的可核查构造、全目标积分、fit/eval 选择屏障、独立未来评价、所有观测与成本的完整 census、有限声明范围，以及未识别结论的具体原因。科学门槛若区间跨零或有限条件最优区间过宽，应保持“未建立”，不能用“工程完成”将其改写成“已证实”。
