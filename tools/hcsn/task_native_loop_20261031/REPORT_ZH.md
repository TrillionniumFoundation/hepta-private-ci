# R10：读取前价值决策、原生任务闭环与同信息四组实验

## 结论

**闭环实现和正式对照已完成；当前模型的架构收益验收未通过。**

这轮把同一证据读取任务的 belief、公共机会、内容调用、预算、时钟、提交与恢复状态交给 Rust owner。Rust 在真正打开 packet 之前自行计算动作，只有 READ 分支运行 FullHX；实际结果参与观测法则校准、cell 训练、独立 TD 更新及最终评分。

冻结的五个独立训练拟合完成了 **1,200 次原生任务执行和 240 次精确 DP 参照执行，零失败**。但是解析 cell 相对普通 cell 的效用差未显著为正，两种 learned-Q 都落后于固定规则和精确 posterior＋DP。不能据此升级生产架构、宣称连续模型已经原生落地，或者把更少的读取解释为质量相同下的计算节省。

原始失败、全部模型、真实执行 receipt、协议、完整成本和负结果均保留。主要入口为 [交付清单](DELIVERY_MANIFEST.json)、[源码组合](SOURCE_COMBINATION.json)、[正式执行完成记录](evidence/confirmation_execution/COMPLETE.json) 和 [压缩统计结果](evidence/confirmation_execution/STATISTICS.json.gz)。

## 一、同一任务与合法后继

沿用 `task_value_factorial_20261030` 的两个二元任务，每次 READ 真实读取一个本地 packet，并运行已有 frozen FullHX。oracle 所用观测法则由公开 reliability 与 TRAIN 校准的 confusion law 构造；标签仅供终止后的外部评分。所有组的公共信息、动作空间、预算、数据和内容解码器相同。

| 状态 | 训练／oracle／Rust 中的对应含义 |
|---|---|
| 当前证据 | 当前 job 的 posterior，及已经完成的 READ 结果 |
| 内容状态 | FullHX 模型身份、成功调用数、最近输出与内容摘要；packet 内部执行记忆模型 |
| 待到达信息 | 两个 job 的未来公开时段、reliability、price、duration、packet 身份；未读内容不进入特征 |
| 时钟与期限 | tick、task elapsed、整数微秒时钟、deadline |
| 预算 | 剩余 READ 次数与累计 query／latency 费用 |
| 恢复状态 | 原生 journal／witness、cell 状态、任务历史、外部 acknowledgement；显式 in-flight 字段 |

该任务是同步的原子动作合同：已确认边界没有进行中的 READ；FIRE 一次消耗两个时段。因此 checkpoint 的 `pending_observation` 和 `in_flight` 为 null、`recovery_ticks_remaining` 为 0。未来机会由公开 schedule 与 tick 确定。这不是任意异步到达队列或任意动作中途恢复的实现。

| 动作 | 真实效果 | 时钟、预算与收费 |
|---|---|---|
| STOP | 终止，不补交答案 | 不耗时，不读内容 |
| SKIP | 放弃当前信息机会 | 推进一槽，计实际存在的任务时长 |
| READ | 打开当前 packet，运行 FullHX，成功后更新 posterior | 成功时推进一槽、预算减一；尝试计 query 与 latency。失败时 tick／预算不变、elapsed 仍增加，保留费用并终止 |
| FIRE | 提交当前 job 的答案，进入后续 job | 推进两槽、posterior 重置为 .5、cell 任务复位、预算保留 |

READ／SKIP 在最后一槽不合法，FIRE 仍可合法；FIRE 的 tick 可以越过 deadline，但 elapsed 只加总存在的时段。cell 使用动作前的 driver 推进，不能把刚取得的观测倒填到过去。**任务 FIRE 与 cell 的潜在首达／重复事件是不同对象。**

主机只传公共文件、模型、owner 路径、继续步数以及可选 acknowledgement，不传动作、posterior、driver、observation 或预先选好的内容。真实 `NeuronModelPort` 完成决策并产生原生 receipt，随后 READ 分支才调用内容模型。[原生实现](native/owner.rs) 与 [独立审计](AUDIT_NOTES.md) 给出完整执行顺序。

## 二、训练与真正的四组比较

| | 固定 posterior 阈值 .8 | 同构任务价值控制器 |
|---|---|---|
| 普通 elapsed-time recurrent cell | A：ordinary_fixed | B：ordinary_value |
| 解析有限首达／复位 cell | C：analytic_fixed | D：analytic_value |

两个价值控制器具有同一 67→24→4 结构、相同初始化、minibatch 索引、更新预算和动作合同；各自随 cell 联合拟合，因此最终权重并不强制相同。前 62 维编码完整公共任务状态，后 5 维来自相应 cell。全部标准化统计只使用 TRAIN，不裁剪 OOD 特征。

另保留两个参照：`direct_fixed` 跳过 cell 推进，给出普通 posterior 阈值规则在同一原生接口内的成本；它仍加载共同的 policy artifact，不代表已经优化到最小的规则执行器。`fitted_dp` 使用同一 posterior 与完整公开 schedule 进行精确有限 Bellman 规划。普通参照没有被禁止使用解析风险公式，也没有被剥夺已知信息。

固定列只消费 posterior，不消费 cell 特征。因此 **C−A 的任务动作与效用相同是结构性结果**；它可衡量额外状态推进的成本，不能衡量解析信号对固定控制决策的收益。固定控制不执行无用的 critic 或 forecast query。

每个 fit 使用 32 个 TRAIN、16 个 validation、24 个 IID test 和 24 个 OOD session；五个独立 seeds 为 71031、71037、71043、71049、71057。IID packet 长度为 24，OOD 为 48，并改变 reliability、价格和时段长度。确认数据在模型 freeze 后生成，未用 heldout 调参。[协议](PROTOCOL.json) 在训练前固定了所有这些选择。

每个 family 共有 1,743 个可训练参数：11 个 cell 参数和 67→24→4 critic。先进行 4 次真实 next-observation 预训练更新，再做 600 次 critic 更新；每 100 次更新，以全部因果历史的中央差分对 11 个 cell 参数做一次 task-Q 更新，共 6 次。validation 在 100／200／400／600 四个检查点中选择整套 cell＋critic。没有声称固定预算优化已经收敛。

Q 标签来自 TRAIN 校准观测律下的完整任务 Bellman 递归，包含 FIRE 后第二个任务的机会。它不是知道未读 packet 的 clairvoyant oracle，也不自动等于实际环境的真值函数。真实回报与拟合法则的误差另行记录。

扣除 L2 梯度后，60 次联合更新的前 6 个动力学参数任务梯度范数为 **0.00021949–0.00814964**，后 5 个读出参数为 **0.00013356–0.01192753**，全部非零。任务信号确实到达 cell；参数改变本身不等于任务收益改善。[梯度验收记录](evidence/TRAINING_SIGNAL_AUDIT.json)

## 三、正式结果：没有取得架构优势

效用定义为“正确提交数减错误提交数，再减 READ query 费用与任务 latency 费用”。以下是五个 fit、每个 split 共 120 个配对 session 的平均每 session 效用。

| 策略 | IID test | OOD |
|---|---:|---:|
| A：普通 cell＋固定控制 | 0.825750 | 0.401483 |
| B：普通 cell＋learned-Q | 0.244358 | 0.155829 |
| C：解析 cell＋固定控制 | 0.825750 | 0.401483 |
| D：解析 cell＋learned-Q | 0.231150 | 0.073033 |
| 无 cell 推进的 direct_fixed | 0.825750 | 0.401483 |
| 精确 posterior＋fitted-law DP | 1.131729 | 0.902617 |

| 配对效用对比 | IID 差值与同时置信区间 | OOD 差值与同时置信区间 |
|---|---|---|
| B−A：价值控制替换固定控制 | −0.581392 [−1.131288, −0.031495] | −0.245654 [−0.552860, 0.061552] |
| C−A：固定控制下 cell 替换 | 0 [0, 0] | 0 [0, 0] |
| D−B：解析 cell 的额外效应 | −0.013208 [−0.158327, 0.131911] | −0.082796 [−0.413894, 0.248303] |
| D−C：解析 cell 下价值控制效应 | −0.594600 [−1.052524, −0.136676] | −0.328450 [−0.777540, 0.120640] |
| 交互项 | −0.013208 [−0.158327, 0.131911] | −0.082796 [−0.413894, 0.248303] |

区间按预先声明的五个独立训练 fit 的配对均值计算，使用 Student-t 与五项对比 Bonferroni 校正，每个 split 的 familywise alpha=.05。240 个测试 session 不被当作 240 个独立训练重复。五个 fit 仍使区间较宽；未通过非劣门不等于已经证明劣于对照达到某一幅度。

读次数下降伴随明显的任务完成量下降：

| 指标 | A，IID | B，IID | D，IID | 精确 DP，IID | A，OOD | D，OOD | 精确 DP，OOD |
|---|---:|---:|---:|---:|---:|---:|---:|
| 每 session READ | 2.733 | 1.417 | 1.467 | 2.108 | 2.742 | 1.217 | 1.975 |
| 可用任务完成率 | 98.75% | 63.75% | 62.50% | 98.33% | 99.17% | 58.33% | 97.08% |
| 正确完成／全部可用任务 | 77.50% | 43.33% | 42.50% | 83.33% | 69.17% | 36.25% | 78.33% |
| 每 session fitted-law regret | 0.3763 | 0.9290 | 0.9474 | 0 | 0.4258 | 0.8078 | 0 |

这批结果定位到控制器校准与选动作问题，而非主机替 Rust 选择动作、未读内容泄漏或执行后继不一致。D 在 IID 的 120 个 session 中有 426 次 SKIP，贡献每 session regret 0.4414；OOD 有 396 次 SKIP，贡献 0.3703。它选中 STOP 时的平均预测 Q 为 0.2156／0.1473，但合同中 STOP 的真实 Q 恒为 0。这是事后诊断，没有据此重训主模型或重做同一 heldout。

## 四、完整成本与恢复

计量包括模型／元数据加载、传播、forecast query、critic、决策、真实内容执行、原生日志、snapshot、进程启动、失败与恢复。协议的任务费用与硬件 CPU 是不同单位，分别记录；硬件成本另做预先声明的价格与训练摊销敏感性分析。没有能耗仪器读数，energy 为 null。

主对比的每 session 原生进程与宿主启动／解析 CPU：B／D 在 IID 为 **12.860／12.843 ms**，OOD 为 **13.711／13.999 ms**。这些数字不是显著硬件优越性证明。内容调用少了，更多 SKIP、持久化与进程成本也必须计入。

在每 CPU 秒价格 0.01 效用、训练摊销 1,000 个 session 的预声明点，D−B 的完整成本调整差为：

| Split | 调整差 | 同时置信区间 |
|---|---:|---:|
| IID | −0.013240 | [−0.158361, 0.131882] |
| OOD | −0.082830 | [−0.413920, 0.248260] |

两个 split 的效用门、质量非劣门、完整成本门均未通过。整个训练准备消耗 **26.122 CPU 秒**；主确认的 parent CPU 为 **36.912 秒**、native child CPU 为 **16.520 秒**，wall 为 **61.912 秒**。parent 含数据生成、独立评分、oracle、重放与压缩；这些与逐项耗时是嵌套归因，不能重复相加。

独立恢复审计发现并修复一个真实缺陷：首次 `--steps 0` 初始化后，新进程会报 `BootstrapRequiresEmptyJournal`。现在 bootstrap 延后到首个真实 step；genesis 阶段、没有 witness anchor 的非空日志仍明确拒绝且不擦除。已有 anchor 的底层 SparseJournal 可在核验后裁剪未完成尾帧。原始失败保存在 [失败记录](evidence/causal_audit/FAILURE.json) 与 [完整原始归档索引](evidence/AUDIT_ARCHIVE_INDEX.json)。

修复后的 50 次真实新进程审计全部通过：四动作后继、独立特征与 critic、有限 CTMC、未读包／标签移除、失败计费、身份变更拒绝，以及两种 cell 的每个已确认动作边界恢复均得到核对。全程与逐边界恢复的 task、cell、content 快照位级一致。[审计报告](evidence/causal_audit_attempt02/REPORT.json)

一个开发样本的 ordinary 连续／六次恢复 CPU 为 0.016966／0.046958 秒，distribution 为 0.018965／0.046844 秒。失败 READ 保留 query 0.0225＋latency 0.006，失败执行 CPU 0.007202 秒，随后恢复 CPU 0.012526 秒。这是明确样本上的计量，不是性能置信区间。任意动作中途 crash 的自动原子重试尚未实现；任务 checkpoint 与原生 frontier 不一致时会拒绝继续。

## 五、训练后的边界是否真的影响内容执行

为区别“潜在事件计数改变”与“实际动作改变”，在主确认之外，对五个已冻结 analytic_value 模型的全部 80 个原 validation session 做了额外开发诊断。保持 critic、norm 和其他参数不变，只把原始边界参数 theta[3] 置为 −3 或＋3；三个版本均以新的 owner 执行，不给已有 checkpoint 偷换模型。

全部 **240 次原生运行完成，零失败**。每个方向均有 80／80 个案例的潜在特征改变，但行为变化只发生在部分案例：

| 干预 | 动作轨迹变化 | READ 数变化 | READ 时序变化 | 平均效用差 |
|---|---:|---:|---:|---:|
| theta[3]=−3，相对冻结模型 | 11／80 | 5／80 | 6／80 | −0.051594 |
| theta[3]=＋3，相对冻结模型 | 8／80 | 3／80 | 5／80 | −0.002738 |

两个方向合并并按 seed／session 去重后，19／80 个不同 session 改变动作、11／80 改变真实读取时序、8／80 改变读取次数。这证明已经训练的解析状态能通过同一个冻结 critic 改变实际内容执行，且没有把 latent-only 响应算作内容门通过。它是 **DEV 次级因果诊断**，不用于选边界、不回流主模型，也不证明收益改善。[干预计划与结果](evidence/trained_boundary_intervention/SUMMARY.json)

## 六、实际结果回流训练与校准

主确认保存了每一步实际 reward／费用、realized suffix return、oracle-bootstrap TD residual 与 critic 校准记录。heldout 的这些记录没有反馈给训练。

另一个独立开发更新只读取已归档且已终止的 TRAIN 轨迹，用实际 FIRE reward、READ charge、latency charge 和冻结的后继 critic 构造 TD 目标。五 fit×两 family 各做一次预设 lr=.001 的 critic 更新，不更新 cell，不做候选筛选，随后执行全部 validation 前后对照。

**10／10 候选的 TRAIN TD 残差下降，10／10 权重改变，但 10／10 的 validation 效用和动作 regret 均未变化。** 实际 reward 与期望 reward 产生的梯度差范数为 0.518–0.610，说明结果确实进入目标与梯度。这次小更新证明了真实结果回流机制，没有证明它已经改善决策，也没有把开发候选替换为主模型。[回流报告](evidence/outcome_feedback/REPORT.json)

## 七、连续参照、有限 QVI 与本次真实训练参数

源码组合固定为：R9 父提交 `e7eaa5e0be835269636216c8fe8b1ae2f1a22361`；独立标量 QVI 原样导入 `979dc20082f30c88b17e7b9c92ec81108574e5ee` 的两个文件；原生 60 个 Hepta 源文件逐个核对与 R9 父树一致。新的训练模型、原生 binary 和每个参考源文件均以 SHA 绑定。

原生解析 cell 当前仍是 **三个活动格点＋两个 Erlang 恢复相位的有限 CTMC**。为使用相同空间边界条件，本轮新增独立的反射下边界／吸收上边界连续 Laplace 边值解，配合 Erlang renewal 逆变换，再将全部五个真实训练参数放入 3／6／12／48／192 格点分辨率检查。数值逆变换使用两档精度；它不是区间算术证明。

| 检查 | 结果 |
|---|---|
| 固定参考点，原生 3 格点首达误差 | 0.143312 |
| 同点，192 格点首达误差 | 0.004017 |
| 五个真实训练 cell，3 格点首达误差 | 0.127420–0.161888 |
| 五个真实训练 cell，192 格点首达误差 | 0.003495–0.004542 |
| 低噪声例，3 格点首达误差 | 0.422307 |
| 尾概率例，连续首达概率 | 8.956×10⁻⁹ |
| 同尾例，3 格点绝对误差 | 0.015642 |
| 有限模型 Fréchet 与独立差分最大误差 | 小于 5×10⁻¹⁰ |

同一报告同时保存首次事件、重复计数和折现事件数随分辨率的变化。训练 cell 在 3 格点上的 upwind 额外局部方差比例约为 2.26–2.56，即额外方差超过目标扩散方差两倍。**有限模型内部的梯度准确，不能消除连续事件律的离散偏差。** [数值报告](evidence/NUMERICS.json)

独立标量有限 QVI 对实际训练参数的 value、边界与 drift-gradient 也在 301／601／1201 点检查；1201 点 value 误差约 3.12×10⁻⁵–5.61×10⁻⁵，但边界与梯度仍有可见网格误差。此 QVI 的奖励为 x−K，与 packet 任务奖励不同；其 Erlang 恢复仅在固定折现率的 Laplace 因子上转换成等价 delay，不能据此声称事件时间分布相同。

原 R9 的移动／分段边界、低噪声、短恢复、重复事件及梯度独立参照也在本次源码组合重新运行：4 项 R9 测试与 7 项独立 QVI 测试通过，7 项连续参考门通过。这些有明确模型域的参考结果，与“连续核已替代 Rust 的有限核”是两回事。后一个门仍未通过。[参考执行记录](evidence/REFERENCE_TESTS.json) [连续参考](evidence/CONTINUOUS_REFERENCE.json)

## 八、源码、构建与可复现性

本轮通过 Cargo 从源码构建，不调用历史预编译 owner。Rust 1.95.0、just 1.59.0、nextest 0.9.150；7 项原生测试通过，4 项独立 Python audit 测试通过。最终本地 binary SHA256 为：

`f53e90a388a6f97dfe5283535ed2b5877cf197a726a9842debc5f9ed097b5330`

本地网络代理不可用，24 个 Cargo 包中 17 个发布 archive 通过锁定 checksum；另 7 个通过显式缓存源码 patch 构建。为补足来源核验，读取这 7 个包声明的精确 GitHub commit/tree，267／267 个可映射上游文件、其中 133 个 `src/` 或 `build.rs` 文件全部匹配，295／295 个实际缓存与编译副本文件 SHA 一致，7 个 normalized manifest 的依赖／feature／构建入口语义一致。133 是文件路径分类，包含条件测试源与非 Rust 资源，不是实际编译输入计数。**缺失的 .crate 压缩字节未被验证，archive_checksum_verified=false 保持不变。** [构建记录](evidence/BUILD_ATTEMPT03.json) [依赖来源核验](evidence/CACHED_DEPENDENCY_PROVENANCE.json)

新增 `ci.py` 和限定路径的 GitHub workflow，从空 cache 下载公开依赖、核验所有 archive，再构建、执行 `just test` 与 50 次机制审计。这个入口不重训或重跑 1,200 次正式确认。工作流源码已经验证，远端执行状态须以 GitHub 实际运行记录为准，不能把“已提交 workflow”称为 CI green。

完整复现命令与证据读取方法见 [README](README.md)。原始大文件按成员 SHA 验证后分块，所有交付 blob 小于 512,000 bytes，不扩大现有大小 allowlist。仅二进制压缩证据加入精确 codespell 路径，科学文本继续检查。

## 架构判断

目前可以关闭的是：**同一任务的状态、动作与费用对齐；Rust 自主读取前决策；任务信号进入 cell；已训练边界能改变真实读取；真实结果能回流更新；已确认动作边界恢复一致。**

目前不能关闭的是：**解析 cell 优于同信息普通状态、learned-Q 优于简单控制、质量与完整成本同时改善，以及原生有限核等同连续首达／复位模型。** FullHX 内容权重保持冻结，也没有建立硬件能耗或生产异步恢复结论。

这轮最直接的研究优先级已经清楚：先让同信息普通价值控制器可靠逼近强 DP，校准 STOP／SKIP 与后续任务价值；同时处理连续律的分辨率误差。已有证据不支持靠增加 cell 复杂度或扩大现有粗格点网络来跳过这两个问题。
