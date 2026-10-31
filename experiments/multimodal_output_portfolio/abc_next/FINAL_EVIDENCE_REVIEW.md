# ABC next 最终证据审查

**最终结论：本轮注册的实际实验、完整评价、串行计时与产物审计已完成，主要报告与紧凑证据的数值、统计单位和状态一致。图文两项主要 CE 门槛通过，真实语音的共享语义门槛通过；语音反馈增量、实际成本补偿和原生生产接纳仍未成立。工程执行完成不等同于全部 blocker 闭合。**

本审查以用户的完整目标为准：在 Hepta neuron 框架下研究全模态生成训练与动态输出 portfolio 控制，并按本轮优先级推进可观测状态、条件价值、新来源训练/反馈识别、真实文字/语音延迟语义以及真实原生执行链。小型受控原型的完成不等同于该完整目标完成。

审查只读取冻结协议、代码、已完成主要报告及对应紧凑结果；没有修改被冻结的代码、模型、来源、阈值或评价程序，没有运行测试、实验或格式化，也没有读取尚在运行的评价质量。各评价完成后，核对了主要数字、统计单位、实际成本、结构化门槛、报告身份及原有结果是否被改写。本审查只编辑本文；其他作者根据反馈补充的报告范围说明与测量注释分别保留身份。本审查是另一工作方向 agent 的证据复核，不是外部数据 owner、生产 trust authority 或独立组织认证。

## 1. 状态的含义

| 状态 | 在本审查中的含义 |
| --- | --- |
| 局部工程闭合 | 所声明的实际执行、信息边界、来源或恢复链已有对应完整证据；限于明确的实现/profile |
| 科学收益通过 | 预先指定对比、测量对象和统计门槛获得支持；不扩展到未测任务、训练因素或模型族 |
| 收益未建立 | 证据未使主要门槛通过，或尚不能识别所要求的贡献；不等于证明真实效应恰好为零 |
| 已观察到负结果 | 原样保留实际不利结果及其测量范围，不用改标签或较弱对照替代 |
| 实际接纳拒绝 | 原有接纳路径真实执行并拒绝；明确首先触发的位置，不虚构后续检查已执行 |
| 待新研究/真实资源 | 原始目标仍有未实施或未证明部分，需要新协议、模型、任务、资源或真实资格；不能因本轮范围有限而删除 |
| 用户已取消的交付项 | 大原始文件不归档是明确用户要求，不列为科学或工程 blocker |

原始资料只在当前运行目录保留，GitHub 保存主要详细报告、源码、协议、紧凑结果、身份与复现入口。这满足当前交付指令，但不代表原始大数据已经获得长期保存。[范围依据](SCOPE.md)

## 2. 可核查的冻结身份

以下 SHA-256 已在本次审查中从实际文件重新计算，均与报告声明一致。

| 证据 | 文件 | SHA-256 |
| --- | --- | --- |
| 共同历史协议 | [COMMON_HISTORY_PROTOCOL.json](design/COMMON_HISTORY_PROTOCOL.json) | `e61349ad3297bbd3992b9923712a7ce50dc93382ca9ccde6c2eaafe4d29b1cee` |
| 共同历史完整紧凑结果 | [COMMON_HISTORY_RESULTS.json](design/COMMON_HISTORY_RESULTS.json) | `92c4b96cd21294cf4123fcc7c7da74e2747d01902f8e560a6f5552f36cbbb128` |
| Main 正式协议 | [PROTOCOL.json](results/main-001/PROTOCOL.json) | `e552230547779d3f92527d62272b115e7d940ff1b56400f5e9347dabfa16a834` |
| Temporal 正式协议 | [evaluation_protocol.json](temporal/freeze-v1/evaluation_protocol.json) | `9d74cc54fec42e9828b1b5bc110e861456d1d3bec1d0634507dd207cee038c2b` |
| Native 协议 | [PROTOCOL.json](native/PROTOCOL.json) | `1ccf9287e4246569678a1ff65b8d28dbb7d9307a0869cfc7b7a81421ad8626b3` |
| Native 紧凑结果 | [RESULTS.json](native/RESULTS.json) | `1cbcec7b0080afed244fc6f31bb9dd8fe343f875c18cfcb591f2cd95d5643515` |

基线为 `9595221c21f1fe0775295a9c8756a1ba4d69ea49`。Main 协议在正式新来源评价开始前发布于 GitHub commit `595d6ea7d728c0d293077bdf19dde31095ab5373`，tree `f01e0b0f3884fcdc2221664f5855102758ce23ea`。Native 实际运行所用预格式化源码发布于 commit `9d48cb518fcd457f58eb23d068e6b1bf934b2dc2`，执行字节身份由九文件 pins 与后续格式化回执分开保留。审查不把后续格式化文件冒充原运行字节，也不因已如实保留的格式化事件新增虚假的来源 blocker。[Native 身份说明](native/REPRODUCE.md)

Main [发布顺序回执](results/main-001/PUBLICATION_CHRONOLOGY.json) SHA-256 `f709f61958ae79858f431037a6eb6cb5fd9274139e2e7ba24132924e4df2ab10` 已重算一致。其 GitHub commit metadata 为 `06:43:19Z`，实际 process registration 为 Unix ns `1792910609579532504`，相差 **10.579532504 s**；本审查同时重算该原 registration SHA `fa7d579a3051279bc508511ace7756075f0cc3441f330954f0881db53be1dbbe`，与回执相同。这与协调 agent 已观察 branch CAS 完成后才启动 main 的顺序一致。Git metadata 与本地 launch receipt 不是外部密码学时间戳认证。

Native 原结果 SHA 为 `59cce0bb2204ed2350e5bfc10390da4d6ac9d245b3131cb106109bc454fe71c9`；后来仅追加 `measurement_scope_notes`，说明 after-only cumulative child RSS 的测量范围。本审查将 Git 中原文件与现文件逐对象比较：无删除 key、无任何共有字段值变化，仅该说明 key 新增；模型、校准、tick、proposal 与资源数值均未改。[EVIDENCE_INDEX.json](native/EVIDENCE_INDEX.json) 同步 SHA 为 `664643036b0ebf0b7d5fbe89b5a147b7f7effecd684b9212cb6c17b1c20755de`，已重算一致。

Temporal 的协议与模型有实际运行前 local freeze；其代码与协议的 GitHub commit `e04569d18504a4274d2df7ba98872f0240293d55` 发布在 C 执行启动之后。因此可以确认本地预冻结身份，不能宣称该 Git 发布是 C 的公开预 test 登记。[Temporal 发布顺序](temporal/PUBLICATION_CHRONOLOGY.json) SHA-256 `90883322e90fd4695a6a0b8522660cbf9eee91ea31491a7491b9e58ceb4084b9` 已重算一致；其中本地文件 mtime 同样不构成外部时间戳认证。

### 2.1 前一轮已有的消融与成本证据继续有效

本审查补读了基线 [A/B 独立审阅](../abc_recovery/results/ab-001/REVIEW.md)、[完整成本审阅](../abc_recovery/results/cost-001/REVIEW.md) 和 [主要结果](../abc_recovery/RESULTS.md)。本轮没有重新实施某个对比，不表示此前没有实际做过；同时，旧实现、旧来源上的结果不能直接赋给新控制器或全模态目标。

| 已有实验 | 既有实际证据 | 仍然保留的边界 |
| --- | --- | --- |
| Generator 持续 encoder 条件 vs initial-only 推理干预 | 128 来源 Primary 净 CE 差 `+0.00262590`，描述性 95% `[+0.00051672,+0.00483565]`；两个观察者任务成功率均改善 | 当前已训练生成器的依赖性证据；Secondary CE 区间仍跨零；不是重新训练两种架构的比较 |
| 实际在线 MPC vs 快速 feedback | 完整计费的 8 来源匹配队列：MPC mean wall `46.78514 ms`，feedback `9.39033 ms`；增量 `+37.39482 ms [36.22553,39.21893]` | 成本增加明确；Primary raw CE 增量 `+0.01646922 [-0.02626105,+0.05222800]`，质量补偿未建立；不是新控制器的成本结果 |
| Allocation-only / risk-neutral / modality-local | 原 128 来源对比已执行，两个观察者的净 CE 差值区间均跨零 | 是收益未识别，不是“没有实施”；modality-local 仍使用联合指数风险，不是完全独立模态风险模型 |
| Shared-state clamp | 旧 `semantic→couple` 路径联合评分收益已有支持 | Clamp 同时影响路径中共享更新，未单独分离首步 semantic，也未证明所有模态一起改善；本轮 temporal 的受控延迟机制进一步补充这一问题 |

这些历史描述性结果不替代本轮预声明主要对比；也不能为追求“全闭合”将它们重新标成未执行、把跨零变成严格等效，或把小来源时延分布当成一般部署保证。

## 3. 共同公开历史：诊断完成，正收益和最优性仍未建立

### 3.1 可以确认的进展

有限实验明确固定 8 条完整公开历史、32 个私有目标的均匀构造 prior、5 个 H1 动作，以及每个历史/动作的 32 个 fit future 和 64 个独立 evaluation future。先封存全部 fit 选择，再生成评价未来。私有目标被完整积分，在线旧 Q1 不接收私有目标或未来结果。该设计可以分辨同一有限条件律中的公开可实现选择与额外隐藏信息优势。[详细报告](design/COMMON_HISTORY_REVIEW.md)

H1 `refine_semantic` 只改变 latent，保留已输出图文，却支付 0.002 成本。因此，在没有后续发射机会的 H1，它对每个目标/未来分支都被 stop 严格支配。四个新候选及对应 one-shot 统一消除了这一动作；H2 首步 semantic 保留。这个结构性错误的闭合不依赖统计显著性，也不能归因于新增 90 维特征。

### 3.2 不能提升为成功声明的数值

| Primary 平均条件 CE 对比 | 点估计 | 冻结的同时差值区间 | 判断 |
| --- | ---: | --- | --- |
| 公开 lookup − 旧 Q1 | +0.014177 | [-0.231720, +0.214964] | 正期望收益未建立 |
| 公开 lookup − stop | +0.050794 | [-0.065404, +0.274837] | 正期望收益未建立 |
| 公开 lookup − couple | +0.033684 | [-0.349433, +0.314357] | 正期望收益未建立 |

上述“先按历史计算条件 CE 再取平均”与“先混合历史再计算 CE”是不同统计量。报告同时保留两者，没有选择较有利者替代主要结果。Stop 在固定有限目标下没有未来输出随机性，因此可有零宽条件区间；这不是新任务总体的零不确定性。

经验混合 CE 中，私有目标与全部未来潜在结果均可见的 oracle 相对表内公开最优高 **0.141001**。它是隐藏信息与表内选择的诊断差值，不能写成在线控制器应当获得的收益。目标/未来交互项为 **0.065867**，不能唯一拆成两项可加的信息价值。

Primary 真实有限条件最优平均 CE 的同时界仍为 `[-0.586786, -0.040438]`，lookup regret 上界为 `0.611752`、下界为零。没有得到全状态条件值误差证书或 H2/全模态最优性证明。旧 Q1 的条件矩误差还混合了有限 prior/task-law 变化，不能全部归因为旧表示差。

### 3.3 样本与成本

实际新生成 **2,312** 个样本，terminal 表 **3,840** 行，两评分器×目标交叉评分 **245,760** 行。后两者不是独立生成样本数或独立来源 N。运行 wall **48.126874 s**、CPU **94.385290 s**，为两线程批量诊断的完整成本，不是单请求延迟。0.002 的动作代理成本不能证明全部现实计算费用已获补偿。

## 4. Main 新来源研究：冻结设计的可解释范围

**正式质量评价、冻结分析和串行 timing 均完整完成并核对；两个主要 net joint CE 门槛通过。实际资源成本增加明确，同一计时队列的质量补偿未建立。**

### 4.1 主要对比与统计单位

正式范围为 **512 个新来源对、8 个视图、4 个生成场景、5 个历史训练 seed、3 个已有生成器训练臂、5 个实际策略**。完整策略行数为 **1,228,800**，但独立来源单位仍是 512 个来源对。每个 seed/训练臂/实际策略或引用的 plan-count 合计均为 16,384；`selected_nonfeedback` 只是五个实际策略之一的冻结引用，不是第六个新执行策略。视图、场景、策略副本以及两个观察者不增加独立来源数。未知原始 writer cluster 不可得，报告必须保留这一限制。[正式协议](results/main-001/PROTOCOL.json)

两项主要门槛为：

1. 同一 fixed 推理下，`output_ndu − output_mean` 的净效用 joint CE。
2. `output_ndu` 下，新 feedback − 开发阶段选定非反馈策略的净效用 joint CE。

比较对象由开发阶段从 fixed、21-plan 最佳常量路线、匹配的 one-shot 中选定；只能称这三个注册候选中的开发选定对照，不能称全部可能策略的最强非反馈方案。不能看到 test 后改选较弱参考。

主要区间为 4,000 次配对来源×seed bootstrap、nominal 97.5%；另报固定五个已训练模型的来源区间。五 seed、四场景的 percentile 区间仍为近似证据。每模型内先计算 CE、再跨训练 seed 平均，不能把训练 seed 当作同一模型的生成风险。各实验的两主对比处理也不是整个项目全部声明的联合 95% 保证。[统计实现](analysis.py)

### 4.2 所识别的训练处理

本轮使用已有生成器，没有重新训练 generator 或增加新的训练 seed。实际风险臂目标为

\[
F_\gamma(\theta) = \frac{M_\gamma(\theta)-1}{\gamma}+0.05A_\theta,
\qquad M_\gamma=E[e^{-\gamma U}],\quad \gamma=2.
\]

相对 CE 梯度，其有效辅助项权重为 `0.05/Mγ`，并有整体尺度和优化路径变化。因此，即使主要对比通过，也只能支持该操作性训练处理在新来源上的效果；不能称已经分别识别 pure risk、辅助项、旧 v6 gate 或 surrogate 的独立贡献。[推导与设计](design/DESIGN.md)

四个 matched 开发候选共享新 fit 数据、来源 OOF、每个 head 的更新步数等训练配置和 H1 支配约束；输入维度/hidden 宽度不同的实际计算并不相同。选中 enriched/32 或正式新反馈优于 legacy，不能单独证明 90 维新特征造成了全部收益。独立 sensor 误差、条件值拟合误差与策略收益是相关但不同的测量。

One-shot 的“匹配”同样需精确限定：它与 feedback 匹配输入特征、sensor、hidden 宽度、来源与单 head 拟合配置，不是严格同总参数或总训练 FLOPs。源码 `MomentHead` 的 enriched/32 五输出 Q head 为 24,613 个参数，Q1+Q2 合计 49,226；21 输出 route head 为 25,141，均不计共享 sensor。Q1 另有 OOF/refit 阶段。因此主要反馈增量是所声明整个控制器方案相对注册非反馈方案的效果，不单独分离持续观察、额外 head 容量或拟合计算的贡献。

### 4.3 执行与成本边界

实际二值像素与原 token 被 lossless 保存、关闭、重读和比对后才离线赋分。控制决策在对应未来子节点生成前关闭写入；这些 main JSON 未 fsync，因此不继承 native journal 的 crash-durability 声明。公共 reader 不使用两个 outcome observer 作为在线特征。[协议说明](PROTOCOL.md)

Main timing 的设计与源码已包含在 main 预 test 协议 `e5522305…` 和 commit `595d6ea7…` 中；实际 timing 运行安排在 main formal 完成之后。`timing.py` 运行时 registration 写出的 `test_outcomes_materialized_before_registration=False` 是字面常量，没有检查全局其他 test 的读取状态。它至多对应该次 timing 自身输出尚未生成的执行顺序，不是“所有 test 尚未开启”的观测证明。应以预先冻结的 timing profile 说明前瞻性，而不能把后来这份运行收据时间写成早于 main outcomes。

Main 的 0.002/continuation 是预声明代理成本。最终报告已分别保留原始与净 CE、真实生成/特征/critic/序列化/评分成本以及串行请求延迟。随机动作成本下不能将 `CE(U−c)` 简写为 `CE(U)−E[c]`。实际秒数没有预先映射到效用时，不能声称“质量收益已经覆盖全部现实成本”。

原 `process.py` 的 wall 与 children CPU before/after 差值保留完整有效范围；其 `child_maximum_rss_bytes` 读取的是 `RUSAGE_CHILDREN.ru_maxrss` 的 after high-water，未保存 before peak。若启动环境已继承更早 child 的 high-water，该字段是本次 child 峰值的上界，而非已隔离的 exact-PID peak；也不是并发进程树 RSS 之和。这是峰值字段的口径限制，不据此否定独立计时的 wall/CPU 差值。

### 4.4 完整正式结果与报告核对

完成 execution 的 SHA-256 为 `0f2271ff4024427e98de4d34e596e965c91ba6ac800f210ef7dae4ef73e50d0b`，冻结 analysis 为 `91bc59e20e071148601c8f9a6a5c905c615b8c3d86af9d799f511d711fe1d4f0`，均在本次复核重算。Execution 为 `completed`、phase=`test`、15 个模型齐全，protocol 为 `e5522305…`，没有重新拟合或选择策略。已核对主要报告数值；[SUMMARY.json](results/main-001/SUMMARY.json) 中 `official_frozen_analysis` 与完成的原 analysis JSON 完全相等。

| 主要对比 | Primary 净 CE 增量 | Nominal 97.5% 配对来源×seed 区间 | Secondary 净 CE 增量及同形式区间 |
| --- | ---: | --- | --- |
| Risk fixed − mean fixed | +0.005025977 | [+0.000899144, +0.008687139] | +0.004182867 [+0.001119052,+0.007096200] |
| Risk feedback − 开发冻结非反馈对照 | +0.017135170 | [+0.008992846, +0.025572848] | +0.015811121 [+0.005883188,+0.025376924] |

Primary 两门槛通过，Secondary 同向。固定五个模型时的来源区间分别为 `[+0.003513001,+0.006572116]` 与 `[+0.013525780,+0.020666148]`，是另一个有明确条件的推断，不能与主区间混为同一 estimand。[主要报告](results/main-001/REPORT.md)

核心四格（Primary net joint CE）为：

| 训练处理 | Fixed | 新 feedback |
| --- | ---: | ---: |
| Mean+aux | 0.149402556 | 0.168040004 |
| Risk-moment+aux | 0.154428532 | 0.175656531 |

训练×反馈交互为 **+0.002590550**，描述性 95% 区间 **[−0.002927434,+0.007976197]**。两个主增量通过不构成正交互或正协同证据。SFT 的 fixed/feedback CE 分别为 `0.128199985/0.148841438`，该背景对照也不改变主要比较对象。

**CE 收益不等于所有任务指标改善。** Risk fixed 相对 mean fixed 的 Primary exact success 差为 **−0.627441 个百分点**，描述性 95% **[−0.897217,−0.369843]**；Secondary 为 **−0.418701 个百分点 [−0.646973,−0.183105]**。Mean loss 也从 `0.229412103` 到 `0.230503776` 略增；逐输出 P95/CVaR90 的点估计则下降，分别由 `0.842259366/0.825946260` 到 `0.825182692/0.820592005`。这些尾部点估计并未在本审查追加新的区间。

相对冻结非反馈对照，新 feedback 的 Primary success 提升 **+0.668945 个百分点 [0.371063,0.961914]**，Secondary 提升 **+0.718994 个百分点 [0.439453,0.994873]**，均为描述性 95% 区间。完整 raw CE 点差为 `+0.015681783`，net CE 点差为 `+0.017135170`；可变成本下不能将 net 主区间直接移给 raw 差值。

新 NDU feedback 的 complete 为 100%，但 clean success 为 **89.003906%**，missing-untrusted **4.619141%**、missing-unknown **2.548828%**、both-missing **0.068359%**。这些完整保留的失败表明它没有建立一般缺失模态鲁棒性。正式 NDU feedback 仍有 **4.747314%** 的 `semantic_then_stop` 路径；H1 semantic mask 关闭了特定末步支配错误，没有使整体近似 Q2/Q1 策略成为最优证书。

完整 formal process wall **1,755.522621915 s**、child CPU **3,340.412877 s**；entry-scope wall **1,753.965716037 s**、CPU **3,338.306442578 s**。后者包含在前者中，不能相加。独立冻结分析另有 wall **14.072438443 s**、CPU **14.893955 s**。主报告已将包括最终 timing 的八份 whole-process receipts 与 entry-scope 阶段分表，保留模型/数据生成、训练、选择、离线评分及冷启动边界。

### 4.5 串行计时完整，但未建立实际成本补偿

[TIMING_SUMMARY.json](results/main-001/TIMING_SUMMARY.json) SHA-256 `0c84458bb9744d6f5c065af0032ac0debc24c48ac6e38413e7a08b2e4f11b070` 已重算；主 SUMMARY 中的 `timing` 对象与之完全相同。实际 **19,200 次请求**涵盖预注册的 16 来源对×8 视图×2 场景×5 seed×3 训练臂×5 策略。失败或未评分 **0**，各条件完成率 100%，完整 attempt census 通过，没有删除慢请求。

这些时延是 resident 请求，包含 owner RNG、initialize/encoder、实际生成、公共 reader/特征、控制器、无损内存 NPZ 序列化及 SHA。磁盘 append、最终 archive close/fsync、读回/离线评分、模型加载、来源构造和聚合另有测量。主时延表不含磁盘持久化或终端评分，不能与直接计入 durable WAV/text 的语音时延当作同一终点来比较。

| NDU 策略 | Wall mean ms | Wall P50 ms | Wall P95 ms |
| --- | ---: | ---: | ---: |
| 原 fixed | 6.499063 | 6.343424 | 7.405130 |
| 开发选定非反馈引用 | 7.218253 | 6.743047 | 9.673387 |
| 新 feedback | 8.646325 | 9.148075 | 11.762076 |

新 feedback 相对开发选定非反馈的 mean wall 增量为 **+1.428072 ms**，配对来源×seed 描述性 95% 区间 **[+0.652012,+2.129240] ms**；P95 增量 **+2.088689 ms [+1.262314,+4.386506]**；mean CPU 增量 **+2.915987 ms [+1.260948,+4.431488]**。P95 的差是两策略时延分布的 P95 相减，不是逐请求差值的 P95。[计时详报](results/main-001/TIMING_REPORT.md)

必须同时保留该计时队列**自己实际产物**的质量：Primary raw CE 差 **−0.009984508 [−0.039803527,+0.020097003]**、步数代理 net CE 差 **−0.008458027 [−0.038169082,+0.021684090]**、success 差 **−0.234375 个百分点 [−2.421875,+1.484375]**；均为描述性 95% 区间并跨零。Secondary raw/net CE 区间同样跨零，点差分别为 `+0.004815598/+0.006319260`。

因此，本队列支持“已测到额外资源成本，质量补偿未建立”。16 来源的结果不替代 512 来源主要质量结论；也不能将后者正增量与前者时延拼成一个新的、显著的经济收益。实际时间价格尚未外部标定，.002/action 也不是其换算。

计时完整 child receipt SHA-256 为 `8c45ef1971eb2194592450459e92e5e2773221ef1622b131c32a5818fd45ab8b`，exit 0、wall **199.262528107 s**、child CPU **382.201685 s**；内部 timing wall **197.768445778 s**、CPU **379.884492693 s**，与外层重叠。八个已记录 main 进程合计 wall **3,458.595252 s**、child+wrapper CPU **6,627.703930 s**，仅是这些进程的累计成本，不是并行跨分支项目的关键路径 wall，也不覆盖报告渲染、其他实验或未记录的历史尝试。

## 5. Temporal：真实语音机制与完整目标的边界

**完整 64 fact groups 的 formal 质量结果，以及 256 次串行 timing 和其产物 audit 均已完成并核对。Timing 没有改变主要质量结论、模型、阈值或统计 N。**

生成链为固定模板文本、真实新 Piper 神经语音、真实 Vosk 草稿观察、共享语义/语速动作和离线冻结 Whisper。控制器不用 Whisper 终端结果拟合、选择或决策。Vosk/Whisper 的角色和参数分离成立，但预训练语料与误差的统计独立性未知，不能替代人工感知评价。[README](temporal/README.md) [独立静态审阅](temporal/INDEPENDENT_REVIEW.md)

64 个 evaluation 组是同一模板族、同一 voice 中不同 number/color/direction 事实组合。5 个 seed 是 critic 拟合 seed，不是五个声学模型或五个自然来源。四场景、五候选路径、策略重放、seed 复制及 timing 重复均留在事实组内；它们不扩大独立 N。

共享语义 clamp 是同 prefix、同 normal 语速、同未来两块真实合成、同 0.02 fuse 代理成本的机制干预。它能测当前任务中共享状态的延迟传播价值；正结果本身不能证明反馈 gate 必要。Fixed/initial-only 选中 fuse 后，仍使用同一合法公开融合算子与后来释放的 cue，未被剥夺动作执行信息。

Owner 在 episode 初始阶段预采样 initial/fresh 两组 cue；initial-only adapter 忽略 later 字段，executor 在 prefix/draft 后释放它们。这是受控延迟释放，不是从外界实时采集新信号。实际 neutral prefix 已 fsync，后续两块语音新合成，但整个任务只有一个在线 action gate，未建立多轮长时域反馈控制。

### 5.1 完整正式质量结果

完成的 `analysis-before-timing-001.json` SHA-256 为 `c55bb93805d93c4434dfb3a4afabde5832edd815b2b87f011160d801d6825bb2`，本次审查重算一致。已将最终 [SUMMARY.json](temporal/SUMMARY.json) 与该文件逐字段核对：除新增的 timing 对象外，原有质量、对比、分组、成本及其他字段全部相等，没有重估或更换主要结果。[RESULTS.md](temporal/RESULTS.md) 的主对比、计数与时延数值也与紧凑证据一致。

实际执行 64 事实组×4 场景×5 候选，共 **1,280 路径、3,072 次 TTS API 请求、220 个不同最终 WAV hash**。相同语义和确定性声学生成产生重复波形，不代表跳过真实生成，也不产生新的独立来源。API 请求数不是内部 sentence-level acoustic forward 次数。

完整 census、冻结公共策略重算、不可改 prefix/spans 及独立 ASR 实际输入身份检查均通过。质量主结果如下；CE 越高越好。

| 外部 Whisper 对比 | 净 CE 增量 | Nominal 97.5% 区间 | 门槛结论 |
| --- | ---: | --- | --- |
| `fuse_normal` − 同成本 shared-state clamp | +0.120281404 | [+0.078878701, +0.162827663] | 当前受控任务的共享语义延迟机制收益通过 |
| Learned feedback − fit 选定 `fuse_slow` | +0.003574786 | [-0.027771731, +0.033416140] | 学得反馈相对强固定策略的收益未建立 |

反馈对 initial-only、probe-masked feedback、声明 prior 参考的 CE 差值分别为 `+0.003806898`、`+0.002852855`、`+0.015271621`，三项描述性 95% 区间也都跨零。不能用共享机制的显著正值或其他观察者的某个有利比较替代失败的反馈主要门槛。

反馈 exact task success 为 **59.84375%**，fit 选定固定策略为 **62.890625%**，差 **−3.046875 个百分点**，描述性 95% 区间 **[−7.5, +1.171875] 个百分点**。这是不利点估计，不是显著下降结论。反馈 required semantic completion 为 **88.90625%**，固定策略为 **86.71875%**；完成率的不同方向不取消任务成功率和主要 CE 的各自判断。Whisper/Vosk 在 **269/1,280 路径（21.015625%）**的事实识别上不同，也不构成两个独立自然任务样本。

已完成成本：evaluation parent 全局 wall **1,501.4500741 s**、parent-plus-child CPU **2,968.627484392 s**；各 case wall 总和 **2,969.714346815 s** 是两 worker occupancy。Fit 数据真实生成 wall **855.314342625 s**、CPU **850.916938887 s**。

最终 active critic 构建 wall 为 **1.893659428 s**、CPU **1.893600648 s**；此前还有一次 wall **2.071523821 s**、CPU **2.067833171 s** 的构建。前一 bundle SHA 为 `0338e2bc7d31968729968e423c362c11f5e3003948594c7f587d045429c52bed`，active bundle 为 `bdd0e423b67d4618fd639df427beb18e4964544ddfad7f1cbf1d737bc19ad1cb`。本审查确认二者 `models` 与选定 fixed action 完全相等；公共解析参考改为显式风险敏感后，两次实际 fitting 成本均应保留，合计 wall **3.965183249 s**、CPU **3.961433819 s**。SUMMARY 的 `value_fit_cost` 是 active 一次，主要报告另如实计入两次。这些阶段成本不能直接当作单请求时延，也不能把重复 seed 展开的 `sum` 追加成新总执行成本。

### 5.2 完整 timing 与三项收尾核对

原 timing report SHA-256 `d1be5a1bd7512861152a41a167ebdb839216450390f1efbaadd93cf15801d5d7` 与 [TIMING_AUDIT.json](temporal/TIMING_AUDIT.json) SHA-256 `bd9e422c4d523ceb88b72c12799edd816e951bc155fe8d863e9d04b4585d5fd8` 均已重算一致。三个收尾问题得到以下明确状态：

1. **Timing 产物身份已核对。** 16 事实组×4 场景×2 回合×2 策略，共 **256 次**，每策略 128 次。Stored false flag **0**；实际 WAV/text 不一致均 **0**；全部 committed spans 与冻结 action 一致。无须重新评分，新增独立质量 N=0。可按精确身份使用这些选定路径原有的终端测量，不把 16 来源 timing 扩展成 64 来源时延资格或新质量复现。
2. **总成本口径已区分。** 五 seed 展开后的 `component_cost_ms.sum` 不是 unique physical executions 的总 wall/CPU。总成本使用 evaluation parent global wall 与 parent-plus-child CPU；per-case wall 总和是 worker occupancy。Timing 另外完整串行执行，未将上述副本和 component sums 重复加入其完整进程成本。
3. **顺序保证范围保持准确。** Analysis 核查 prefix/fresh/decision 顺序、digest 与冻结策略重算；未来 candidate 之前完成决策的保证来自冻结调用顺序及 decision fsync。没有将其提升为另已实施的 candidate 绝对创建时间独立审计。

| 实际串行策略 | Wall mean ms | Wall P50 ms | Wall P95 ms | CPU mean ms |
| --- | ---: | ---: | ---: | ---: |
| Fit-selected `fuse_slow` | 1521.509599 | 1510.288934 | 1652.327065 | 1514.724075 |
| Feedback / critic seed 17 | 1510.039615 | 1501.738806 | 1632.885650 | 1502.867974 |

这是共享容器内当前 16 组任务的点汇总；本 timing receipt 没有给这些成本差值提供配对置信区间。Feedback 平均时延点估计较低不能被写成已证明统计或经济支配，尤其 64 事实正式评价中的反馈主要 CE 门槛仍未通过。

[完整 child 回执](temporal/TIMING_PROCESS_RECEIPT.json) SHA-256 `3130f79f6f1ff1cb208479e0cfd3381aeef5e6646a6186b39a8ab56e800c1fb3` 已核对：launch `07:15:26.328707 UTC`、exit `07:21:58.394412 UTC`，wall **392.065686181 s**、CPU **390.146426 s**、exact-PID child peak RSS **469,916 KiB**，正常 exit 0。它包括 launch、imports、加载、256 请求、最终报告序列化和 child exit；内部 run timer 的 `390.173369053 s` 与之重叠，不重复相加。独立产物 audit 另花 wall **0.294372769 s**、CPU **0.2943055 s**，没有加载新的终端 scorer 或更换主要结果。

首版完整进程 wrapper 因发现已存在 cumulative `RUSAGE_CHILDREN` counters，在 Popen 前退出；没有启动 timing child，没有产生或丢弃任何 timing 观测，来源也未重抽。修正后的外层 wrapper 用 `os.wait4` 对新 child 精确 PID 取资源，执行与质量代码仍使用原冻结身份。[预启动失败记录](temporal/TIMING_WRAPPER_PREFLIGHT_FAILURE.json) 保留了原错误与修正，未将测量工具修正冒充重新生成更有利的评价。

该分支仍未训练 acoustic generator，未实现开放式 neural text generation、自然多 voice 泛化、audio/video 输入 encoder、video synthesis 或 AV 时间对齐。0.02 fuse/0.01 slow 是代理效用罚项，durable WAV/text 是计时终点，均不是实际经济价格、网络交付或声音播放结束的时间。注册 timing 的 fixed 和 feedback 都支付公共 draft/probe；优化后的 fixed 可以省掉未使用的 probe，但本轮没有实际测量该部署优化，不能将 matched pipeline 的成本对比当作对所有部署实现的支配结论。

## 6. Native：研究执行链闭合，生产接纳与未来预测未闭合

### 6.1 校准结论必须保留的限定

新模型为 **resident observed-output correctness head**，用实际已生成图文训练，并在专用来源上一次校准、一次验证。原 runtime 接收到 `drive=[1, features]`、`prediction=[p(correct), same features]`，第一维常量 1 是 success reference；误差为 `1−p`，原 confidence 计算得到约 `p`。这是显式 confidence 编码，未修复旧 future-latent dynamics predictor。[主要报告](native/REPORT.md)

| 指标 | 实际结果 | 可以支持的结论 |
| --- | --- | --- |
| Verification 独立来源 | 800 ID + 800 不重叠 complete-absence OOD | 单 generator/observer/profile 的一次验证 |
| ID ECE | 0.024466055；写入 gate 24,467 ppm | 原点估计 ECE≤30,000 ppm gate 通过 |
| ID ECE 描述性 95% 区间 | [0.0119708164, 0.0506751291] | 不支持人口 ECE 以 95% 置信度≤0.03 |
| ID 接受/正确 | 800/800 接受，674/800 正确 | 非空洞 acceptance；仍有 126 个已接受错误 |
| OOD false acceptance | 0/800；单侧 95% 上界 0.003737662826 | 当前 complete-absence FAR gate 通过；不是一般未知 OOD 资格 |

Complete absence 可由公开 mask/hint 识别，具有预声明独立 calibration bin。它不能被宣传为通用未知异常检测。Calibration 的拟合后 ECE、native replay、成本复现和候选 development 计算增加的独立资格 N 均为零。原有旧 predictor 失败保留。

### 6.2 Tick、journal 与资源

实际分别创建 **1,600 个单 tick 上下文**，复用已观察 verification，不增加独立资格 N；800 ID 非 abstaining、0 OOD 非 abstaining，1,600/1,600 durable acknowledgement/checkpoint/eligibility recovery 匹配。OOD abstention 仍写 journal/witness。每上下文 logical sequence=1、profile 有效序列 1–2；这不是一个连续运行 1,600 tick 的 daemon。

外侧 `runtime.tick` 含 durable witness 的 P95/P99 为 **676/1,425 μs**，transient peak **11,870 B**，checkpoint **1,528 B**，符合所声明 resident profile。Resident heap **132,477 B** 和约 24 MB process RSS 分账，没有将 512 KiB transient 门槛冒充全进程内存。完整 Rust 进程 wall **5.982949 s**，不等同逐 tick 分位数。

上游实际 generator+公共特征的串行 P50/P95/P99 为 **6.6772/8.8469/13.3409 ms**，还未包括 head/journal/raw media serialization。因此完整生成不能继承 resident 的 3ms/8ms envelope。新两个进程 train-only 成本复现 wall **19.515262584 s**、CPU **21.038287 s**，weights/cuts 与原冻结果逐字节一致；它是后置成本复现，不是原历史 wall，未重开 reserved 来源。

Native `training_cost.py` 的 `child_peak_rss_bytes=370,286,592` 同样来自 after-only cumulative `RUSAGE_CHILDREN.ru_maxrss`；若包含更早 child high-water，只能作为这次训练 child 峰值上界。该口径不影响 before/after CPU 差或 wall，也不影响 Rust 自身直接测得的 transient allocation/RSS 与 resident tick 资源判定。

### 6.3 Same-context proposal 的真实边界

真实 acknowledged checkpoint 后完成 35 次原 dynamic resolver 调用、32 参数映射、两个各修改 4 个 `w2` 参数的非零候选，以及原 `propose_v2`/durable registry/witness/reopen。原先“缺 acknowledged neuron anchor 无法构造这条链”的局部缺口已解决。

候选为局部 utility×eligibility perturbation，没有证明 eligibility 是 correctness loss 或 generator loss 的梯度。已观察 development 的 raw Brier 为：no-change **0.058366352931054**、half **0.058366371187071**、full **0.058366389446792**。两个都略差，且 development 已用于 head 选择，所以不能用作独立候选 acceptance。

Product `resolve_agentd_plasticity_admission_v1` 实际返回 **`ArtifactBinding`**。实际 learning ledger 为 **0 条记录、零 head**；原代码在 owner-evidence dispatch 前即拒绝该零 frontier。**DatasetSnapshot owner、签名验证和独立 candidate acceptance 均未到达**，不能写成这三类检查已经各自执行并拒绝。研究 proposal 保持 **`RequiresIndependentAcceptance`、`DENY_ALL`、无已应用更新**。[结构化拒绝依据](native/RESULTS.json)

真实 DatasetSnapshot、有效 learning-ledger frontier、独立候选评价与合法 trust authority 是实际未满足条件。不能用本地自签、常量 frontier 或重命名 development 来闭合。Agentd/fleet daemon、长期 drift/expiry、生产主机资格、native 在线条件价值反馈及原生文字/语音/视频均未运行。

## 7. 最终门槛表与结果核对

已逐值核对 [GATES.json](GATES.json) 的 21 个状态记录与完成结果：两项 main、两项 temporal 主 CE 对比、对应 success 的概率单位、native 首次实际拒绝对象、同队列时延/质量数据均一致。总体状态 `registered_round_execution_complete=true`、`all_blockers_closed=false` 与 [README](README.md) 及各主要报告相符。

| 问题/门槛 | 最终状态 | 可支持的范围或仍欠缺的证据 |
| --- | --- | --- |
| 共同公开历史的信息诊断 | 局部工程闭合 | 有限 prior/H1 的实际生成、fit/evaluation 隔离及隐藏目标/未来信息分解 |
| 公开 lookup 正期望收益 | 未建立 | 主要同时区间跨零；不能借 oracle 高值改写 |
| H1 semantic 严格支配错误 | 特定错误已闭合 | 四候选统一 mask；H2→stop 仍可能，非整体最优证书 |
| 新来源操作性 risk-vs-mean CE | 注册主要门槛通过 | 当前 gamma/aux、五已有生成器 seed、512 来源与指定 CE |
| 新来源 feedback package CE | 注册主要门槛通过 | 对三个注册非反馈候选的开发选定引用；整个方案的增量 |
| 风险训练全面提高任务成功 | 当前 profile 反例明确 | Fixed exact success 的描述性区间为负，不能宣称全面支配 |
| 训练×反馈正协同 | 未建立 | 四格交互的描述性区间跨零 |
| Sensor/持续观察/head 容量独立贡献 | 本比较未分离 | 不否定整套控制器合法主比较；更强单因素归因另需证据 |
| 真实文字/新语音共同 continuation | 局部执行闭合 | 实际新合成、已提交 prefix、两块后续内容与独立终端观察 |
| 延迟共享语义机制收益 | 注册主要门槛通过 | 固定模板/单 voice/64 事实组，同成本 clamp 对比 |
| 语音 learned-feedback 增量 | 未建立 | 对 Vosk-fit-selected `fuse_slow` 的主要区间跨零 |
| 实际串行成本与媒体 census | 已完成 | Main 19,200、temporal 256，失败/未评分或媒体错配均为零 |
| 质量覆盖全部现实成本 | 未建立 | Main matched 队列成本增加、质量区间跨零；C 只有点时延；价格未校准 |
| Native 观察输出 correctness profile | 注册点校准/限定 FAR gate 通过 | 不等于未来 latent predictor、一般 OOD 或 95% 人口 ECE≤.03 |
| Native tick/ack/journal/same-context proposal | 研究 profile 执行闭合 | 分别创建单 tick 上下文、真实恢复与低层研究提案持久化 |
| Native product admission | 实际拒绝 | 零 learning frontier 的 ArtifactBinding；需真实部署资格，后续 checks 未到达 |
| 独立且有益的 native 参数更新 | 未建立 | 两个候选在已用 development 上略差，未独立验收，DENY_ALL，无更新 |
| 旧未来 latent-dynamics predictor | 未修复 | 新 correctness head 不替代旧对象 |
| 全生成满足 resident 3ms/8ms envelope | 当前上游实测未满足 | 上游 generation/features 的 P95/P99 已超过该 resident 边界 |
| 端到端全模态训练与全局 portfolio 最优 | 未建立 | 缺少对应全部模态、长时域、真实 native 生产与最优性证据 |
| 大型 raw 长期归档 | 用户明确不要求 | 不能再作为本轮交付 blocker |

两类已知不利结果应按其证据强度保留：risk fixed 的 success 下降获得描述性区间支持；native 候选 Brier 略差只是已用 development 上的实际观察。C feedback 与 main timing 质量的区间跨零属于未建立收益，不宣称严格零效应、等效或显著劣化。

原有 bounded encoder conditioning 推理干预、allocation/risk-neutral/modality-local 消融和实际 MPC 成本研究按 §2.1 保留。没有把更强的重训架构或普遍最优声明设成这些既有有界结果的新增必选条件。外部产品资格、科学效应未识别和原始全模态目标未完成也没有被“研究实现完成”替代。

## 8. 必须避免的易误导结论

| 不应使用的表述 | 与证据一致的表述 |
| --- | --- |
| Oracle 高 0.141，因而在线控制有 0.141 可利用收益 | 共同历史经验表中隐藏目标与未来信息提供 0.141 的诊断优势 |
| 新特征/条件值已经被证明是全部增益来源 | 新方案同时使用新 fit 数据、OOF、支配约束与特征；单因素作用需匹配独立消融 |
| Qualification 正值就是 formal test 通过 | Qualification 是独立的 104 来源开发资格；formal 512 来源结果单独判断 |
| 风险训练 pure NDU 因果贡献已分离 | 检验已有风险矩+aux 与 mean+aux 的操作性处理，且本轮未新训练 generator |
| 大量重放行使 N 达百万 | Main N=512 来源对，temporal N=64 有限事实组；seed/视图/场景/重放相关性保留 |
| 本轮 controller 的 initial-only 对比证明了持续 encoder conditioning 的生成贡献 | 本轮对比限制的是 controller gate 可观察信息，不是独立的 generator conditioning 消融；历史已有生成器条件访问干预按 §2.1 保留 |
| 当前离线候选矩阵证明实时 MPC 优于快速策略 | 当前矩阵是诊断；旧真实 MPC 成本/未识别质量结果保留，新模型/任务的 planner 结论须有对应实际执行 |
| 输出状态共享收益证明 learned feedback 必不可少 | 共享状态干预与 feedback 对强基线是不同对比，必须各自判断 |
| 实际语音就等于端到端图文声视频共同训练 | 当前为固定模板、固定 Piper 与小型语义/动作 critic 的受控真实输出 |
| 新 native predictor 已解决未来 dynamics | 新 head 预测当前已观察输出正确性，以 confidence adapter 接入 |
| Native ECE gate 通过意味着 95% 总体 ECE≤0.03 | 通过的是注册点估计 gate；描述性 95% 上界仍高于 0.03 |
| Resident 亚毫秒意味着全生成符合 3ms/8ms | 上游 generator+特征已超过该 resident envelope，成本边界须分开 |
| Durable proposal 成功就是产品更新已接纳 | Product admission 实际 ArtifactBinding；研究 proposal DENY_ALL，未应用 |
| 零 frontier 后 DatasetSnapshot/签名检查也均已失败 | 这些后续检查未到达；应区分实际首错与推断缺项 |
| 每步代理罚项已证明现实算力成本被收益覆盖 | 代理价格与实际 wall/CPU/经济价格不同；需预声明完整成本目标 |
| 本轮主要模块完成，所以全模态全局最优和所有 blocker 均闭合 | 只关闭有完整证据的具体问题，原始全模态与全局控制目标仍单独列示 |
| 未上传大型 raw 是交付 blocker | 用户明确取消大型原始归档；保留主要报告与紧凑可核查身份即可 |

## 9. 原始完整目标仍需的证据

即使本轮 formal 主要对比通过，原始全模态目标与更强的归因声明仍有各自的证据范围。以下同时区分实际剩余目标与仅在扩展声明时才需要的额外研究，不能把后者增设为已完成有界实验的必选 blocker：

1. **训练识别。** 本轮合法识别的是已声明 mean+0.05aux 与 risk-moment+0.05aux 的操作性训练处理；pure CE 下相同有效辅助权重、旧 surrogate×内容 gate 因素分离属于不同且尚未回答的问题。若要作这些更强归因，须有相应独立训练；这不否定合法的主要操作性比较。跨训练 seed/任务族的更广泛结论仍需对应复验。
2. **生成条件机制。** 已有 fixed generator 推理干预回答了其对持续 encoder 条件的依赖，当前有界问题不重新列为未实施。只有要扩展到“重新训练的 initial-only 架构普遍优于/劣于 persistent 架构”等新声明时，才需要匹配的架构训练比较。新 controller one-shot/feedback 不能回答这个更强问题，也不能抹去已有推理干预证据。
3. **真实时序范围。** 多 gate、长时域、外界实时不确定性、自然文本/多 voice/多语言与独立感知质量，随后 video 与音画同步。
4. **全模态训练/推理。** Audio/video 输入编码、实际各模态生成器的端到端训练、共享表示/内容更新和必需模态约束，及可用训练算力和总训练成本。
5. **完整风险与成本目标。** 明确任务效用、动态约束、允许策略类和真实资源价格。旧在线 MPC 的完整成本与未识别质量结果已经存在；新状态、新策略及多模态任务中的质量/实际成本仍需对应的匹配执行，不能迁移旧数值或由当前离线矩阵推定。
6. **Native 产品能力。** 真正未来状态预测/条件值模型、匹配的目标 host/profile、连续 lifecycle、有效原生模态 backend 和合法 product qualification/update。
7. **最优性。** 当前 bounded 动作/有限历史上的经验诊断不构成全神经状态、开放任务或全模态 portfolio 的统一误差界、Bellman 证书或全局最优性证明。

这些项并非要求将有用的研究结果一概判无效；它们约束能对用户原始目标作出的完成声明。后续研究必须使用新冻结任务/未来分支及适当的序贯规则，不能把本轮已读取评价资料重新命名为未见 test，或通过改阈值、删失败、缩小声明对象来制造全闭合。

## 10. 最终报告身份与审查结束状态

以下为本次完成复核时的主要文件身份，均由实际本地文件重新计算。报告与矩阵对象的相等比较只是数据/文档核对，没有重新拟合模型、运行评价或重算 bootstrap。

| 文件 | SHA-256 |
| --- | --- |
| [Main REPORT](results/main-001/REPORT.md) | `e3322321eba750520a3f543601ccea4662e4c14b2c19a01b730f9a41406b4520` |
| [Main SUMMARY](results/main-001/SUMMARY.json) | `b3c7500e751dd839caa167c656995f045824681c8a43674962c076612c8fedd5` |
| [Main TIMING_SUMMARY](results/main-001/TIMING_SUMMARY.json) | `0c84458bb9744d6f5c065af0032ac0debc24c48ac6e38413e7a08b2e4f11b070` |
| [Temporal RESULTS](temporal/RESULTS.md) | `84f148a9341000b09d1ce501ee7a9b572b4c1e3ceae4cbedbd9d6be0de8e7afa` |
| [Temporal SUMMARY](temporal/SUMMARY.json) | `f057d83ba0d373782bf530a8781822906a695217be479e3b0f92d0fa4c1b7633` |
| [GATES](GATES.json) | `2253d43aa41acf807477887ddadb798bad6c75384a968fd4dda9992c1feff1e4` |
| [总览 README](README.md) | `e8a1c978aa88ff04e57da384f2639441139396b49e45e17e74ce2b91da7713b1` |

协调 agent 在全部源码编辑结束后实际执行了要求的最终 `just fmt`，退出 0；[FINAL_FORMAT_RECEIPT.json](FINAL_FORMAT_RECEIPT.json) SHA-256 为 `b5ed61029173ebb81fdab3a29bcd0c4f7f9534ef6288f659eba3b8b0b73ca146`，记录 62 个当前 Python/Rust 文件前后字节一致，未重跑测试或实验。它不改写 native 早期实际执行使用预格式化字节的既有身份区分。

**最终审查未发现仍待修正的主要数值、统计单位、成本边界或跨报告门槛矛盾。** 本轮证据可按上述限定发布供其他 agent 继续工作。发布完成、科学收益通过、真实生产接纳与全模态全局最优是不同状态；本审查仅确认所列报告忠实反映已完成执行与仍未闭合的问题。
