# Hepta 任务价值边界、策略训练与原生接入：正式结果

本轮完成了两组预注册实验的 **29,440 次正式策略执行**、整段状态传播回放、五个训练模型的原生资格验证及独立原始记录审计。当前已定义范围内没有开放的数据一致性或实现审计 P0/P1。**主干准入仍未通过，全部科学与生产 blocker 并未闭合。**

三项实质结论是：普通轻量规划器已提供低教师遗憾，增加学习残差尚无稳定净收益；任务价值边界改善了八个预声明有限合同的指定效用；同一价值边界通过普通门控执行时产生完全相同的任务结果。新增提交同时提高了正确和错误答案数量，内容质量非劣尚未在价值边界任务上建立。所有主干／生产激活字段保持 `false`。[策略结果](../task_policy_v2_20261031/confirmation_publication/COMPACT_RESULTS.json) · [边界效用、质量与成本](../value_boundary_v2_20261031/publication/formal-confirmation01/QUALITY_AND_COST.json) · [独立审计总览](../progression_audit_20261031/CONFIRMATION_AUDIT.md)

## 1. 来源、冻结与统计单位

研究分支为 `research/hcsn-value-boundary-native-20261031`，审阅入口是 [PR #4461](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4461)。科学冻结提交为 [`a37c99a87a25fe8417ec29ddbebb1c035d356a53`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a37c99a87a25fe8417ec29ddbebb1c035d356a53)。**2026-10-31 02:42:31 UTC** 已核验 104 个远端不可变文件／blob 身份及准备归档成员；两组正式确认数据均在核验后生成。原实验 [PR #4440](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4440) 的冻结源、模型、数据和负结果保持不变。[冻结核验](FREEZE_VERIFIED.json)

发布核查时 PR 仍为 draft；远端 `blocking-ci`、`architecture` 为 pending，`v8-canary` 为 in_progress，不能称为远端 CI 已通过。代码可合并状态不代表科学准入或主干激活；最后交付 head 以 PR 实际版本与发布核验为准。

| 实验 | 状态与期限 | 策略与准备 | 正式样本及独立单位 |
| --- | --- | --- | --- |
| 原任务的策略改进 | 两个顺序任务、共享 READ 预算、公开固定期限与时间表；真实 READ、SKIP、FIRE、STOP | 精确拟合教师、OneRead、非零学习残差；5 个新训练 seed | 每 seed 128 IID + 128 压力分布会话，3 策略，共 3,840 runs；主要推断单位为 5 个配对训练 seed |
| 新的连续时间价值边界 | 实际证据状态、共享预算、单一隐藏指数期限；READ 等待、FIRE、复位与恢复 | 8 个公开合同；每合同 5 次固定 600 步拟合；固定、直接硬、直接软、QVI 解析、QVI 普通共 5 策略 | 每合同／fit 128 个不同会话，共 5,120 会话、25,600 runs；同时报告条件会话与五 fit 分组区间 |

两组实验的过程、期限和目标合同不同，结果不合并估计。第二组的 nominal／stress 是逐合同重新规划的公开参数情景，不能称为同一学习模型的 OOD 泛化。原生复核使用既有确认集的预指定子集，重复执行不增加独立效力样本。[策略协议](../task_policy_v2_20261031/evidence/formal_prepared/PROTOCOL.json) · [价值边界协议](../value_boundary_v2_20261031/publication/PROTOCOL.json)

## 2. 原任务：更强普通基线已建立，残差模型未通过收益准入

### 2.1 实际训练与执行

OneRead 是一个明确限制为每个剩余任务最多再看一次观测的规划器；在线反复规划可以在后续状态重新选择行动。它使用公开日程、拟合观测 law、后验、预算和成本，不调用完整 Bellman 教师。学习模型在其动作价值上增加非负残差，输入 65 个公开特征，具有 **4,484 个参数**。[规划器](../task_policy_v2_20261031/planner.py) · [训练代码](../task_policy_v2_20261031/training.py)

五个新 seed 各有 128 个实际校准 READ、1,024 个训练环境、256 个验证环境及 6,000 次更新。候选 100／300／1,000／6,000 步按共同 Q24 部署合同的验证教师遗憾选择；update 0、全部候选与固定 6,000 步模型均保留。五个最终非零候选都选中 6,000 步，均在验证集上优于 update 0。完整训练梯度范数为 **0.00459–0.00833**，均高于声明的 `1e-5` 平稳阈值，因此终止原因是固定预算，不能称为数学收敛。[准备汇总](../task_policy_v2_20261031/evidence/formal_prepared/PREPARE_SUMMARY.json) · [独立模型身份审计](../progression_audit_20261031/TEACHER_PREPARE_AUDIT.json)

实际执行包含文件读取、冻结的 6,217 参数内容模型、后验更新及后续提交；模型选择和确认都使用 `hepta.task.native-q24-residual.v1`。全部 3,840 runs 完成，未替换样本，失败 READ 为 0。[正式确认](../task_policy_v2_20261031/confirmation_publication/CONFIRMATION.json)

### 2.2 主要结果

下表为 **非零残差 − OneRead**。区间是五个配对训练 seed 均值的双侧 95% Student-t 区间；两项主要效用比较另作 Holm 校正。

| 指标 | IID | 压力分布 |
| --- | ---: | ---: |
| 任务效用差 | +0.006627 | +0.010216 |
| 95% 区间 | [−0.040090, +0.053344] | [−0.034287, +0.054719] |
| Holm 调整 p | 1.0 | 1.0 |
| 正确提交数／2 的差 | +0.002344 | +0.007031 |
| 正确提交数／2 的 95% 区间 | [−0.011202, +0.015890] | [−0.004029, +0.018092] |
| CPU 净效用差，κ = 1、H = 1,000 | −0.032421 | −0.028871 |
| 净效用差 95% 区间 | [−0.081174, +0.016333] | [−0.075149, +0.017408] |

正确提交数／2 把未提交任务计入分母，避免少提交制造表面质量改善。两百分点质量非劣门槛在两个分布均通过；正任务收益和完整成本后的正收益门槛均失败。负净效用点估计的区间也跨零，不能据此证明学习残差普遍更差。[全部指标与 12 个成本情景](../task_policy_v2_20261031/confirmation_publication/COMPACT_RESULTS.json) · [独立统计复算](../progression_audit_20261031/TEACHER_CONFIRMATION_AUDIT_01.json)

| 每会话平均值 | IID OneRead | IID 残差 | 压力 OneRead | 压力残差 |
| --- | ---: | ---: | ---: | ---: |
| 实际任务效用 | 1.194620 | 1.201248 | 0.911423 | 0.921638 |
| 累计拟合教师遗憾 | 0.004457 | 0.005443 | 0.003772 | 0.005229 |
| 完整执行 CPU | 11.781 ms | 14.111 ms | 19.625 ms | 21.994 ms |

验证遗憾下降没有转化成确认闭环中的更低教师遗憾或稳定净收益。当前 OneRead 的低遗憾是这组有限任务与拟合观测 law 下的结论。它是普通受限规划器，其收益不能归于解析 cell；有限样本的实际效用排序也不能替代模型内期望最优性证明。`task_level_learned_admission=false`。[策略均值与遗憾](../task_policy_v2_20261031/confirmation_publication/COMPACT_RESULTS.json)

## 3. 价值边界：同一过程贯穿求解、训练和实际后继

### 3.1 已实现的控制算子

新任务的充分状态为 `s = (job, shared_reads_remaining, signed_evidence)`。READ 完成后，真实内容模型给出二元观测，证据正负累积；首次进入 FIRE 区域会实际提交答案，随后证据归零并进入恢复，预算继续共享。一个隐藏指数 deadline 跨越全部 READ 和恢复累计竞争。指数期限的无记忆性支持该状态约简；它不能直接移用到已知固定期限或一般 hazard。[数学与事件合同](../value_boundary_v2_20261031/README.md) · [实际 owner](../value_boundary_v2_20261031/owner.py)

每次正确／错误提交分别得 +1／−1，READ、FIRE 和采样任务时间分别收费。所有五个策略都遵守 `posterior confidence ≥ 0.75` 的相同合法性约束。对于非最后任务，恢复算子为

\[
\mathcal R V(j,b)=\left(\frac{\gamma}{\gamma+\delta}\right)^kV(j+1,b,0)
-\frac{c_t}{\gamma+\delta}\sum_{\ell=0}^{k-1}\left(\frac{\gamma}{\gamma+\delta}\right)^\ell.
\]

价值方程比较 STOP、READ 和包含该后续价值的 FIRE。训练用当前策略的优势与占用权重优化同一初始任务价值；首 FIRE 分布用固定策略下的有限生成矩阵传播。该构造已经把边界与真实后续行动连在一起。[有限 QVI](../value_boundary_v2_20261031/model.py) · [直接价值优化](../value_boundary_v2_20261031/learn.py)

观测 law 在八个实际解码并按输出类别分组的有限输入支持上成立；每个实际 READ 都运行冻结内容模型，并计入额外的输入支持复核读取。这个合同检验不代表自然语言或开放域内容能力。[有限支持与执行证据](../value_boundary_v2_20261031/publication/formal-confirmation01/SUMMARY.json)

### 3.2 有限求解与训练结果

8 个合同 × 5 个 seed 的 **40 个硬策略**在初始状态、全部有限状态包络、合法可达状态及自身可达状态上的最优性差距／Bellman residual 均为 0，独立线性规划验证全部合同。直接拟合是已知有限模型上的 600 步 mirror 策略改进，使用当前策略价值；它没有建立 model-free DQN、跨合同摊销神经网络或高维自由边界网络的学习定理。[准备证书](../value_boundary_v2_20261031/publication/PREPARED_SUMMARY.json) · [独立准备审计](../progression_audit_20261031/VALUE_PREPARE_AUDIT.json)

软策略只有 **25／40** 达到 `1e-7` 梯度阈值，最大软梯度为 `0.0003229975`，最大硬软初始价值差为 `0.0007937448`。硬策略的有限最优性证书与软优化器收敛分别报告。首达 Frechet 导数保持策略区域固定，不包含硬边界切换或优化器对合同变化的总响应。[训练结果与适用范围](../value_boundary_v2_20261031/publication/PREPARED_SUMMARY.json) · [传播说明](../value_boundary_v2_20261031/README.md)

### 3.3 正式任务收益与范围

全部 5,120 会话／25,600 runs 完成，执行失败为 0。以下为八个**预声明有限合同**的等权平均；95% 区间按五 fit 分组并在合同间聚合，均为**未作多重性调整的描述性区间**。

| 比较 | 平均差 | 95% fit 分组聚合区间 |
| --- | ---: | ---: |
| 直接硬边界 − 固定边界：任务效用 | +0.140235 | [+0.119578, +0.160892] |
| QVI 边界 − 固定边界：任务效用 | +0.140235 | [+0.119578, +0.160892] |
| 直接硬边界 − 固定边界：κ = 1、H = 1,000 净效用 | +0.141861 | [+0.121215, +0.162508] |
| QVI 边界 − 固定边界：κ = 1、H = 1,000 净效用 | +0.142314 | [+0.121624, +0.163005] |

两种表示的相同策略没有给出不同任务结果：**QVI 普通／QVI 解析 5,120／5,120 路径相同；直接硬边界／QVI 也为 5,120／5,120 相同。** 解析执行额外计算首达分布，平均执行 CPU 为 11.734 ms，普通 QVI 为 10.802 ms。当前证据支持任务价值边界的作用；它没有建立解析表示本身的独立效用或成本优势，也不排除别的学习／传播设计可能有益。[效用、CPU 与归因](../value_boundary_v2_20261031/publication/formal-confirmation01/QUALITY_AND_COST.json) · [原始记录一致性](../value_boundary_v2_20261031/publication/formal-confirmation01/INTEGRITY_AUDIT.json)

| 合同 | 直接硬边界 − 固定边界效用 | 95% 五 fit 区间 |
| --- | ---: | ---: |
| nominal_1 | +0.212685 | [+0.077822, +0.347548] |
| nominal_2 | +0.031264 | [−0.003822, +0.066349] |
| nominal_3 | +0.269777 | [+0.143691, +0.395862] |
| nominal_4 | +0.034892 | [+0.002842, +0.066942] |
| stress_1，预声明 STOP 负控 | +0.164466 | [+0.125443, +0.203489] |
| stress_2 | +0.031619 | [+0.004349, +0.058890] |
| stress_3 | +0.342990 | [+0.265885, +0.420096] |
| stress_4 | +0.034185 | [+0.009991, +0.058379] |

`nominal_2` 的区间跨零。STOP 负控的直接／QVI 策略得到 0 效用，固定策略为 −0.164466；在该合同中，正确提交数／2 反而下降 0.035938。因此不能把总体效用增长解释为每个合同都完成更多正确任务。[逐合同原始汇总](../value_boundary_v2_20261031/publication/formal-confirmation01/SUMMARY.json)

### 3.4 质量取舍没有被效用掩盖

| 八合同合并描述指标 | 固定边界 | 直接硬边界／QVI | 变化 |
| --- | ---: | ---: | ---: |
| 正确提交／全部两任务机会 | 46.5820% | 54.1602% | +7.5781 个百分点 |
| 错误提交／全部两任务机会 | 4.4727% | 7.9395% | +3.4668 个百分点 |
| 完成率 | 51.0547% | 62.0996% | +11.0449 个百分点 |
| 条件于提交的准确率 | 91.2395% | 87.2150% | −4.0245 个百分点 |

共同的 0.75 posterior guard 通过，质量非劣没有自动成立。该实验的 `quality_noninferiority_claim=false`；“在同等内容质量要求下稳定提高净收益”的更强主干命题仍未建立。软硬部署也没有被默认等同：125 条会话路径不同；stress_4 的硬减软效用为 +0.019829，五 fit 区间 [−0.010348, +0.050007] 跨零。[质量与成本完整表](../value_boundary_v2_20261031/publication/formal-confirmation01/QUALITY_AND_COST.json) · [完整合同结果](../value_boundary_v2_20261031/publication/formal-confirmation01/SUMMARY.json)

## 4. 整段状态传播：增量实现消除了重复历史回放

普通门控、解析分布和解析采样模式现在分别持有自己的因果状态、序列与模型身份；查询不消耗 RNG，间隔按顺序消费，任务复位位于间隔末端。快照包含状态、时钟、事件计数和采样 RNG，PCG64 的 128 位字段以十进制字符串保存。改变动力学参数需要新 owner 并重放因果历史。并发重复消费、模型身份不匹配及损坏快照均有检查。[owner 合同](../recurrent_owner_v2_20261031/README.md)

对既有冻结证据的 **3,200 条轨迹、18,238 次决策**回放得到最大特征误差 `3.33e-16`、最大 critic 误差 `8.89e-16`、动作差异 0；640 条采样轨迹复现相同事件。2,048 间隔的不规则长流包含复位与恢复，最大质量守恒误差为 `2.00e-15`。这些是已公布数据上的实现回归，不是新效力样本。[回放报告](../recurrent_owner_v2_20261031/evidence/REPORT.json)

| cell 计算范围，每项 640 条轨迹 | 旧历史回放 CPU | 增量 owner CPU |
| --- | ---: | ---: |
| 普通／完整续行价值 | 0.209326 s | 0.144420 s |
| 解析分布／完整续行价值 | 2.312606 s | 1.244195 s |
| 解析采样／完整续行价值 | 1.530735 s | 1.631902 s |

两种表示都获得了增量状态优化。计时包含 owner 构造、查询与间隔消费，排除内容 IO 和 critic；增量分布实现还额外消费旧查询实现未推进的最终间隔。采样模式承担状态完整性与 RNG 复制工作，在本次测量中略慢。该结果没有把 CPU 下降换算成硬件能耗，也没有把有限矩阵传播冒称为连续多 cell 网络的全局解析解。[实现与计时范围](../recurrent_owner_v2_20261031/README.md)

## 5. 原生 Hepta 接入：真实模型与 owner 通过，物理传播仍在外部

本轮使用主干提交 `732e934ba496d90fbe042b8d41d479ef901643e5` 的真实 `NeuronRuntime`、`NeuronModelPort` 和 `FileAnchorWitnessStore`。57 个 Rust 源文件与 3 个 Cargo manifests 已按 Git blob 身份核验；隔离构建使用 Rust 1.96、实际 `just fmt`／`just test` 工作流，10 个原生测试通过、0 skipped。冻结非零 MLP 的归一化、tanh、残差和合法动作选择在 Rust 实际执行。[源码与构建身份](../native_task_bridge_20261031/SOURCE_IDENTITY.json) · [原生资格报告](../native_task_bridge_20261031/BUILD_Q24_PROFILE.json)

共同数值合同固定输入／先验的 Q24 规则、浮点权重计算、输出驱动量化及同分低索引规则，并把模型原始 SHA 与合同版本共同绑定为部署身份。五个正式模型的 **2,560 个固定验证状态**没有合同内动作差异，最大 Q 差为 `4.44e-16`。原 float64 argmax 仍有 6 个伪同分动作差异，不能声称原浮点模型的逐动作兼容性。某控制器自身 Q 的量化误差界，也不能被当作完整教师遗憾的误差界。[共享数值合同](../native_task_bridge_20261031/reference.py) · [五模型独立审计](../progression_audit_20261031/NATIVE_CONFIRMATION_AUDIT_02.json)

每个模型使用预先规定的 16 IID + 16 压力会话，共 **160 对实际任务、666 次 READ、320 次完成动作后的恢复**。Python／native 的任务动作、效用、成本、最终 cell 状态一致。内容解码、OneRead 与 cell 物理传播仍在外部；cell 快照用于生命周期绑定，其五个特征没有进入新的 65 特征 MLP。`native_physics_executed=false`。已确认动作后的恢复也不证明任意崩溃下的外部效果 exactly-once 结算。[原生完整结果](native_publication/SUMMARY.json)

| 原生工程复核 | 原始 attempt 01 | 末端报告修正 attempt 02 |
| --- | ---: | ---: |
| 固定模型／状态／任务数据资格 | 通过 | 通过 |
| 进程退出 | 1，末端 TypeError | 0 |
| Python 平均完整 CPU／任务 | 23.838 ms | 26.135 ms |
| Native 平均完整 CPU／任务 | 45.514 ms | 49.942 ms |
| 外层进程 CPU | 19.722267 s | 21.208040 s |

首轮在完整报告已写出后，把 `flush=True` 误传给 `json.dumps` 而退出失败。新增修正版仅移动这一参数，已在 [`a53aa04be8ffc4a9a656e5ce1fa5e8eba8206273`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/a53aa04be8ffc4a9a656e5ce1fa5e8eba8206273) 发布后复核原样本。原始源码、失败退出、结果及两轮成本均保留；修正后运行没有增加独立样本数，也没有挑选较快一轮。两轮 native 生命周期均更慢；其日志、见证与恢复责任较重，且为本次 debug／RAM 工作目录环境，不构成等持久化责任下的语言性能比较。[修复记录](NATIVE_REPORTING_REPAIR.json) · [两轮完整归档](native_publication/PUBLISH_ALLOWLIST.json)

## 6. 独立核查与资源会计

独立参照没有调用候选的统计聚合函数。冻结前以重新构建的有限递推、独立线性规划、Poisson 事件计数和有限差分核查价值、首达与梯度；确认后从实际原始记录重建全部后继与统计。[冻结前审计](../progression_audit_20261031/PRE_FREEZE_AUDIT_03.json) · [确认审计](../progression_audit_20261031/CONFIRMATION_AUDIT.md)

| 全量独立确认核查 | 范围与结果 |
| --- | --- |
| 原任务 | 3,840 runs、23,046 决策、7,792 READ、5,034,080 payload bytes；2,935 个唯一已访问 payload 重跑真实 decoder，logits 差 0 |
| 价值边界 | 25,600 runs、123,908 决策、81,836 READ、31,906,471 payload bytes；全部 clock、预算、恢复、guard、费用和评分吻合 |
| 首达概率 | 99,649 个 CDF 用独立 Poisson 参照重算，最大差 `3.00e-15` |
| 原生 | 两轮各 2,560 状态、160 pairs；两轮物理案例一致，并与原任务确认中的对应非零策略逐案一致 |

两组正式实验合计 89,628 次 READ／decoder 操作，以上 bytes 为其 payload 计量，不能称为全部文件系统读取。价值边界另有每次 READ 的输入支持复读及单独 bytes／成本收据；metadata、evaluator 和其他文件读取的成本也包含在相应外层 CPU 中。

审计实际发现并修复了 value 准备／加载成本遗漏：旧 attempt 完整保留，新版包含部署 artifact 的序列化、hash、加载、状态与 guard 验证，并补全准备尾部包装计时。审计自身也保留了两个修正：最初忽略 split 的同名 session 聚合，以及不属于合同的 10 μs 顺序计时差阈值。修正均有原始失败记录和独立重算，没有修改候选结果。[成本整改](../progression_audit_20261031/VALUE_PREPARE_AUDIT.json) · [原生审计修正](../progression_audit_20261031/NATIVE_AUDIT_FAILED_01.json)

CPU 净效用使用事前规定的研究会计：

\[
\Delta U_{\rm net}=\Delta U-\kappa\left(\Delta C_{\rm execution}+\Delta C_{\rm preparation}/H\right),\qquad
\kappa=1,\quad H=1000.
\]

敏感性包括 `κ ∈ {0, 0.1, 1, 10}`、`H ∈ {128, 1000, 10000}`。这不是生产货币价格或能耗测量；Bellman 内优化的是声明的任务时间和任务成本，host CPU 在执行后用于准入会计。共享生成／校准等工作单列，匹配政策差中抵消；嵌套 CDF、decoder、持久化和诊断时间不得再叠加到外层 CPU。[两组会计合同](../task_policy_v2_20261031/evidence/formal_prepared/PROTOCOL.json) · [价值边界会计](../value_boundary_v2_20261031/publication/PROTOCOL.json)

| 阶段 | 已记录 CPU | 口径 |
| --- | ---: | --- |
| 五 seed 策略准备 | 186.5268 s | 准备程序记录，含教师标签生成、优化、全部候选与 Q24 选模；不冒称含解释器生命周期 |
| 价值边界准备 | 17.840955 s | 完整准备 stage，含模型包装与 hash；排除末端小 receipt 自身写入及进程生命周期 |
| 原任务确认 | 92.195951 s | 外层 `wait4` 全进程；内部 90.021008 s 已包含于其中 |
| 价值边界确认 | 333.507513 s | 外层 `wait4` 全进程；内部完整 stage 332.743770 s 已包含于其中 |
| 原生两次工程复核 | 19.722267 s 与 21.208040 s | 两轮均保留；child CPU 不再加到已涵盖它的进程总数 |

开发尝试、独立审计、归档包装和发布是另行保留的研究开销；表中没有声称它们已经全部折算为某个生产部署总价。独立原任务审计与价值边界审计分别记录 30.156694 s 和 24.649336 s CPU；确认归档包装另计，不改变原策略准入。[独立资源复算](../progression_audit_20261031/CONFIRMATION_AUDIT.md) · [策略包装成本](../task_policy_v2_20261031/confirmation_publication/PACKAGING_COST.json)

## 7. Blocker 处置与主干决定

详细机器账本见 [BLOCKER_LEDGER.json](BLOCKER_LEDGER.json)。通过的工程资格均限定在当前有限模型、输入支持、数值合同与恢复边界内。

| 项目 | 本轮处置 |
| --- | --- |
| 同一过程的价值、边界、实际事件后继 | 有限 CTMDP 内已闭合，包含实际 READ／FIRE、共享期限与恢复 |
| 整段状态、采样恢复、数值传播与梯度 | 已声明有限范围内通过；不外推连续或高维网络 |
| 真实训练模型的原生接口与数值身份 | 五模型 Q24 合同通过；原始浮点逐动作兼容性不作承诺 |
| 包装、加载、失败及生命周期资源漏计 | 已发现问题闭合，旧 attempt 与审计修正保留 |
| 学习残差稳定净收益 | 正式准入未通过；验证改善未转化为稳定任务收益 |
| 解析 cell 的独立净收益 | 未建立；当前同边界普通执行效果相同且更便宜 |
| 保持内容质量的价值边界准入 | 未建立；错误提交增加、条件准确率下降，不能用共同 guard 替代非劣证明 |
| 原生解析物理、任意崩溃外部效果结算 | 未实现／未证明；当前只覆盖外部物理与已完成动作后的恢复 |
| 大规模自然内容、高维近似与硬件能耗 | 未由本轮有限支持、逐合同规划和 CPU 计量建立 |

**研究分支保留全部结果供审阅，`main_activation=false`。** 本轮支持保留可训练的任务价值边界、强普通规划基线、增量状态 owner 与受明确数值合同约束的原生策略接口；不将这些资格改写为新脉冲架构独立优势、全场景质量保证或生产完成证明。[独立结论边界](../progression_audit_20261031/CONFIRMATION_AUDIT.md)
