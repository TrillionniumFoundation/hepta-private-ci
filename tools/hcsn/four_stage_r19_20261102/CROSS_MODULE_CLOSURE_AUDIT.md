# R19 跨模块闭合审计

独立审计日期：2026-11-02。本文件按原验收门汇总；实验正常退出、记录复核通过和科学门通过是三个不同结论。当前 `all_blockers_closed=false`、`production_activation=false`。后续 learned-owner 结果只补充同一训练模型的执行/恢复范围，不改变下列增益、泛化或成本失败。

## 原门与本轮实际结论

| 范围 | 本轮新增的可复核证据 | 原门状态与边界 |
| --- | --- | --- |
| 算子/梯度 | Rust 40状态传播、killed/event-reward 算子56例；8个稀有READ用独立110位90项直接Q-Taylor复核。有限jump-map15个原始训练坐标、独立全时间稀疏Jacobian与临界锥方向导数。 | 有限已声明范围通过。主梯度run01仍9/10；两个较大差分跨活动分支。独立冻结的全部90例更小邻域followup通过，未撤销原失败。15坐标含softmax gauge，不能称15个独立物理参数；完整HX参数到Q/连续边界梯度未完成。 |
| 连续任务 | 精确定义的公开质量x/两模式/固定恢复延迟synthetic任务；正延迟slab构造、folded-circle粘性comparison、唯一性与càdlàg值；理想implicit-FD值收敛论证经独立细审。另有真实准入跳、mode1全状态RESET、首次准入RESET边界粗括号。 | 这些是该精确synthetic值问题的数学结果。理想收敛要求精确LCP或scaled residual→0、ρ对齐且不跨跳插值。不是完整HX模型、一般STOP图/smooth fit/窄边界误差/连续参数导数证明；固定浮点容差不自动满足渐近条件。实际owner仍在决策网格执行。 |
| 真正内容学习/核心贡献 | 实际Torch训练80个独立fit/control/core任务，共享训练资料；40维已声明latent state进入训练head。240原始轨迹/491520个查询决策复核；48组analytic/HMM全轨迹完全相同。 | **原核心增益门失败**。16个强普通模型选择均为SSM；D−B utility：IID −.0184608，OOD −.0212497，long −.0440589，原主两域CI上界均负。不能用训练完成或native实现成功替代正增益。该latent state不是精确物理owner后验。 |
| 未知生成器/缺测可靠性 | 原R19校准因IID fractional风险失败并在未开未知族前停止。新R19b用全公开masked proper loss重拟合；768公开world/3043条件view的NLL独立重建。24576个独立generator校准world、196608策略记录、48CP门均核对。 | R19b三训练族校准τ=.95通过，**五族确认原门失败**。5120确认world按256generator×4world/族重抽，20个主单侧边界全部复核。switching-rotor fractional错误18/47=38.30%，upper .57847；不能用全部accepted的18/854=2.11%替代。IID fractional upper .11765；rotor/switching净收益区间负。 |
| 冷恢复/实际数值owner | 物理有限模型Rust实际计算/filter/planner，私有provider只暴露公开OPEN及合法完成ACT。80例、480查询、782 durable effects、16真实SIGKILL恢复、5负例、237进程均复核；独立公共状态Bellman重算782次选择一致。 | 通过已声明trusted-host/有限FP64/持久mailbox范围。该旧物理模型与Torch learned模型不同，不能把其冷恢复贴到学习模型上。FNV是意外损坏/context检测，不是恶意写入认证；非网络/重启掉电资格。anchored实际数组4×40，不借用296B packed资格。 |
| 同一训练模型的Rust forward | 原16个训练checkpoint逐字段导出，raw W与显式FP32常量折叠均与checkpoint精确匹配；48 saved pairs、20 fresh worlds、3072 model-query comparisons，动作/答案精确，最大状态差1.11e−14。 | 这条链真正覆盖原学习模型的γQ、WRITE/READ channel和neural head。forward tape包含所有潜在token；单独forward parity不证明私有owner隔离/恢复。新的causal learned-owner结果待独立审计后只追加自身范围。 |
| 原成本/采用门 | 实际1000 uses/fit/domain，共16000world/96000exec；1008 lossless raw档案、48000 exact pairs、576000费用核对，四个fit单位NI下界均>−.01；缓存/workspace数组有界。 | **原成本门失败**。anchored/full在线CPU比IID1.2253、OOD1.2898；严格I+1000比1.00817/1.01110。新实现相对共享R18优化器也慢约2.4%–9.5%。不能用内存上界或先前较小批量速度结果覆盖真实N1000失败。 |
| 全模态/生产采用 | 原生产crate SparseJournal/anchor API桥有实际源码身份和失败拒绝证据；本机CPU有限证据可复现。 | 同条件质量/时延/吞吐/能耗全套采用门仍未完成。只观察到本机无可用GPU/能耗接口，不能推测外部硬件；未用CPU替代GPU或推算joules。实际ModelPort/完整kernel/认证与release authority未接通；生产桥仍DENY_ALL、requires_calibration=true。 |

## 可以接起来的证据链

1. **物理有限模型链**：R15/R16冻结Q/prior/emissions与公开WRITE语义 → 实际Rust算子/filter/原三slot控制 → 因果私有provider → 同模型持久状态、费用、租约和16次真实冷恢复。独立审计同时重建状态与控制选择。
2. **学习模型链**：原80-job训练中16个analytic checkpoint → 同checkpoint的γQ、raw W、FP32 folded intervention/emission、实际head → 独立Rust forward。该链保留48组普通same-family HMM等价证据和对SSM的负增益。causal learned-owner若通过，将延长这条链，不改变学习结论。
3. **连续synthetic链**：同一个公开状态/成本/恢复任务的精确DPP → 左/右准入值 → 修正jump solver → 对该有限map的解析坐标导数。理想值收敛证明只在其假设下联结网格值和连续值，不自动联结导数或边界。

不能相互拼接的部分：物理Q的确定WRITE/固定emission/边际argmax与learned γQ/column-W/row-W/neural head；packed4×8状态与native展开4×40状态；公开Brownian质量任务与隐藏40状态内容任务；静态六WRITE全prefix推断与真实长距离跨模态绑定；研究checkpoint/file-mailbox与实际生产dispatch/authentication。它们即使各自通过，也不构成一条未经测试的完整生产模型链。

同Q、prior、emission、intervention、reward/cost、horizon和相同controller/固定tie规则的普通HMM与HX参数化给出相同过滤、值和动作。当前same-family训练也实际产生完全相同轨迹。只有不同假设类/有限样本约束/拟合或优化预算的差异，才可能另有经验问题；不允许删去强same-family comparator来制造排他增益。

## 成本账与失败保留

| 账项 | 已记录CPU秒/逻辑费 | 不允许的合并方式 |
| --- | --- | --- |
| planner历史已知投资 | 642.903506秒下界，含原训练与R17/R18/R19已记录尝试/失败 | `complete_history_reconciled=false`；未知人工/审计/未计时搜索及其他模块研究成本不是0。 |
| planner真实N1000本轮 | 1202.451002秒下界，其中worker1200.583782，额外1.867220 | inclusive pipeline已含worker；不得再加worker。实际一次服务分摊与“qualification投资+未来复用”是两个明确账视角。 |
| native物理模型run02 | outer46.080450，已含237children的34.534088 | 两者不相加。未按source-before-world执行的run01排除正式资格，已记录children22.981258仍保留；被中断outer成本未知。 |
| 梯度main+followup | 52.701903秒 | 两次实验和原失败均保留，不把后续通过改写成首次全通过。 |
| Torch训练+确认 | 158.574751秒；共同离线3072 READ逻辑费419.66625 | 观察费不等于CPU、货币价格或joules；完整80候选/阈值/ablation已计入此模块进程范围。 |
| trained-native forward | 8.673383秒完整worker | 包含编译、所有Rust子进程、Torch reference和输出；不能当作纯native推理时延。导出与失败开发另列。 |
| 原R19失败prepare/calibration | 102.956330秒完整stage | IID校准失败仍保留全部候选/阈值开销；未知五族确认未开，不能把失败stage成本删除。 |
| R19b fit/cal/confirm | 11.052758 /166.146381 /24.238712秒，合计201.437851 | 包含强static与所有预注册阈值策略。196608策略记录及READ fee不能当成196608独立generator样本；与原R19失败stage分列。 |
| root事后结果传输 | V2包装31.406742秒、exact-byte恢复23.063303秒 | 均为独立post-result transport，不混入科学训练/确认。首V1包装CPU未知，不能记0；运输结果不证明模型质量。 |

这些是不同作用域的账，不在此宣称完整项目生命周期总成本。未计时开发、工具链安装、传输、审计、旧中断和真实硬件/服务费用仍有未知项；任何正的完整采用结论必须先解决相应账项。有限CPU样本不支持能耗结论。

原R17/R18失败、R19较大差分跨branch、planner早期bit/tie失败与真实N1000成本回退、native未先发布的run01、R19 IID校准失败、R19b五族失败、Torch强普通参照获胜、raw-softmax native开发精度失败均保留。数学证明新增的是精确任务结论；不修饰旧实验门。

## 条件不可辨识结论的用途

同一完整可见history/已完成READ transcript存在不同target合法完成，且未知律类允许分别集中到这些完成时，正概率回答的点态风险 `Pr(error | answer,H=h)` 的最坏值至少1/2；m个target时至少1−1/m。独立检查的witness仅证明这个条件前提。该命题不禁止无歧义history回答，不限制受约束生成器中的有用校准，也不对跨随机history平均风险给全局下界；另一READ可区分该witness。它不能解释为R19b实测错误不可避免，更不能替代有限族失败。

各项数值、源码/模型身份与可重跑审计程序见同目录 `independent_*.py/json`；连续证明的逐项独立复核见 `../continuum_task_r19_20261102/INDEPENDENT_PROOF_REVIEW.md`。真实learned-owner结果到齐后仅增其独立条目及证据链接，所有原门状态保持不受无关模块成功覆盖。
