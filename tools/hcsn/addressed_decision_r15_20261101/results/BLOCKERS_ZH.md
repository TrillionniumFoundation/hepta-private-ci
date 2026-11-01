# R15 验收结论与尚未关闭的问题

## 验收结论

**本轮有限研究的代码、冻结执行、原始结果及独立审计已交付；主要 HX 质量增益和成本优势未获准入，生产准入仍为否。** 补充协议的完整执行不能改写成“未经修订的原协议通过”，也不能改写成“所有研究阻碍已清除”。机器可读结论和各项证据哈希见 [ACCEPTANCE.json](ACCEPTANCE.json)。

以下判断以 [SUMMARY.json](SUMMARY.json) 的原有门槛为准，没有新增检验、改变阈值、选择成功子集或重算一个更有利的结果。

| 验收项 | 结论 | 解释 |
| --- | --- | --- |
| 补充设计完整 | **通过** | 8 个注册 fit × 2 域 × 128 episodes；16 个 worker 全完成，12 个有效臂完整，mean 臂全尝试与失败留档。 |
| 主要质量增益 | **未通过** | 两域 D−B 均未达到预登记增益条件，Holm p 均为 1。 |
| 质量非劣 | **通过** | utility/reward × 两域共四项同时单侧 98.75% 下界均高于 −0.01。非劣不等于更优。 |
| 质量保护的成本优势 | **未通过** | 同时要求 online 与 1000 次使用的完整搜索成本 D/B ≤ 0.90；两域均未达到。 |
| 未修订的原协议 | **未通过** | 原运行被 mean 的支持失效打断；补充协议另行冻结，原失败和费用保留，原确认收益未并入补充估计。 |
| mean 对照有效性 | **无效** | 2048 次中 16 次 `invalid_support`，均在 OOD。两域 mean 性能与 D−mean 一律 null。 |
| D 与同矩阵 HMM | **完全相同** | 2048 对完整 episode/query trace 相等。 |
| HX 独有算子收益 | **未建立** | 相同有限算子可由普通 CTMC/HMM 实现；本轮不支持排他性优势。 |
| hepta neuron 生产准入 | **未通过／未实施** | 没有 native Q24 集成、完整 owner 恢复、部署能耗或网络成本证据。 |

### 主要结果的量级

统计独立单位是 **8 个 fit**，每个 fit 先平均其 128 个 episode，不能把数千个 query 当作独立训练重复。下列区间为原协议的描述性 t95 区间，显著性门另用 256 个符号翻转和两域 Holm 校正。

| D−B 与成本 | IID | OOD |
| --- | ---: | ---: |
| 平均效用差 | +0.0000471598 | −0.0001126139 |
| t95 区间 | [−0.0001215392, +0.0002158589] | [−0.0002883527, +0.0000631249] |
| 两域 Holm p | 1.0 | 1.0 |
| online CPU D/B | 0.992580 | 0.979844 |
| 完整搜索成本，1000 次使用 D/B | 0.994159 | 0.983960 |

这组结果允许保留“本轮精度未明显劣于已选普通核心”的结论，不能升级为“解析核心有稳定效用收益”或“已实现至少 10% 的质量保护成本下降”。[证据：主要统计](SUMMARY.json)、[独立复算](INDEPENDENT_STATISTICS_AUDIT.json)。

## 七类研究问题：已经完成的部分与开放部分

以下七类是本报告整理研究范围的验收分组；状态描述本轮实际证据，不表示用户已验收尚未完成的工作。

### 1. 内容记忆与寻址

已实现所有核心共用的 typed 地址接口、公开 WRITE、带类型的 DISTRACTOR、四个地址的全局时间推进及六次 query。静态内容合同覆盖 4096 episodes、24576 queries、全部 24 种地址排列与 8192 次 changed overwrite，全部答对；执行审计也核验了实际运行中的地址、写入与真值时序。

**尚未完成 learned addressing。** 地址由任务直接提供，不是网络从语义 key 中学出的检索路由。静态读写合同也没有证明动态内容保持、泛化的语义记忆或新 learned neuron 已形成。下一步应在共同内容接口下验证可学习写入/检索，并加入可用信息、训练搜索、状态容量与计算预算匹配的 gated recurrent/SSM。

证据：[静态内容合同](../dev/content_baseline.json)、[执行审计](INDEPENDENT_EXECUTION_AUDIT.json)、[原协议](../PROTOCOL.json)。

### 2. 联合分布、决策相关性与压缩

已执行 full、factorized、index-mean 固定参数敏感性。synthetic 探针找到 phase/content 边缘相同、joint 不同、最优动作严格不同的数学见证。另一个固定公开历史探针在 16 episodes、768 格点内未找到 full 与即时 factorized 投影的动作差；该阴性结果保留。补充确认中 full/factorized 在 IID/OOD 各有 11/32 次首动作不同，但各仅 1 次最终答案不同；动作计数是描述性证据，不是独立样本或效用增益证明。

**支持保持压缩尚未完成。** 本轮 index-mean 会删除 recovery 支持，导致世界合法 READ erasure 的模型概率变为零。其 16 次失败不是零分观测，更不能只在成功的 2032 次上计算性能。补充协议规定两域 mean 性能与 D−mean 全部为 null。这个失败仅适用于当前两邻 phase-index 压缩，不能推断所有点状态模型都失败。

后续必须先设计并独立验证 support-preserving closure，确保传播、WRITE 和 Bayes 更新后合法观察仍在支持内，再用新冻结、新确认比较成本与效用。可达的同边缘公开历史对照、完整 joint 的稳定净收益仍属开放问题。

证据：[决策探针](decision_probe.json)、[动作计数](MECHANISM_ACTION_COUNTS.json)、[失效定位](FAILURE_DIAGNOSIS.json)、[主要统计](SUMMARY.json)。

### 3. 固定、学习与自由边界控制

当前共同控制器枚举本 query 三个时间槽的 READ、WAIT、REFRESH、STOP；固定模式按验证任务效用选定。本轮八个 fit 的固定模式均为 STOP。因此，本轮完成了 **固定 STOP 与有限 value 控制** 的比较。

**固定阈值、学习阈值、He–Xiong 自由边界的三对照未完成。** 有限动作价值最大化不等于连续 QVI 的求解，不构成 value matching 或 smooth pasting 的最优性证明，也不全局优化未来六个 query 的信息价值。四个 ridge 策略仅选一次 READ/REFRESH 后 STOP，不能作为一个已经训练充分、规划深度相同的学习边界对照。

任务自适应边界、完整隐式边界导数、训练梯度的正确性与稳定性，以及端到端 neuron 学习，仍需另行实现与确认。已有金融边界数值或局部导数代码不能替代这一研究。

证据：[控制范围与学习策略声明](../PROTOCOL.json)、[实际冻结模式审计](INDEPENDENT_EXECUTION_AUDIT.json)。

### 4. value/risk 双通道

本轮实际执行 state/confidence、STOP-value、value+risk、ordinary-dual 四种特征策略。value+risk 相对 STOP-value 在 IID/OOD 各改变 24/93 次首动作，相对 ordinary-dual 改变 38/84 次。动作与答案差已有完整计数，所有变体都承担共同 eager 特征计算成本。

**这些结果没有建立双通道稳定净收益。** 本轮的 value 是终点正确率预测，不是原金融股权价值或最优 continuation；risk 是自然首达概率，不是自动产生再生运动的力。有限策略的动作分歧也不能代表完整控制器中的独立特征收益。下一轮应在相同公开 prefix、规划范围、真实后继与预算下同时检验决策发生频率、答案变化、实际效用和完整计算费用，不能以动作翻转本身作为成功标准。

证据：[特征范围](../PROTOCOL.json)、[机制解释与全部动作对比](MECHANISM_INTERPRETATION_ZH.md)、[主要统计](SUMMARY.json)。

### 5. 自然再生、reset 与 recovery

已经区分至少一次自然首达概率与可含多次的事件数，恢复后继续传播剩余时间。也执行了固定拟合参数下两阶段 Erlang 与同均值 exponential recovery 的敏感性比较；二者均值相同不代表条件剩余寿命或后继分布相同。

**这不是所有 reset 学习研究已完成。** 本轮未学习 reset 核、reset 时机、年龄记忆或全部 recovery 家族。memoryless 对照仅改变恢复分布，不能单独证明这些机制必要或无用。

REFRESH 的真实含义是有费用、有耗时的新观测；它没有修复世界。内部无新信息 reset 不得偷偷改变 owner 真值或提供隐藏信息。若后续研究外部 repair，必须把其物理作用、成本、耗时和观测范围写入新协议，再比较实际后果。

证据：[恢复分布与事件诊断](numerics.json)、[协议](../PROTOCOL.json)、[执行审计](INDEPENDENT_EXECUTION_AUDIT.json)。

### 6. 同信息 2×2 与强普通对照

本轮正式补充确认完成 A/B/C/D 四格、同矩阵 HMM 和其他有效次要臂；五个主要效用对比、256 次符号翻转、Holm、多重非劣界和双成本门均被独立重算。普通核心依据验证任务效用选择；六个 fit 选同矩阵 HMM，两个 fit 选自由率 CTMC。

这项程序已经完成，主要增益结果为阴性。D 与同矩阵 HMM 的 2048 对完整 trace 相同，是有限算子的可实现等价证据；不能将控制器相对固定 STOP 的收益记成解析核心的独有收益。

**强对照范围仍不完整。** R15 未实现充分训练且训练/搜索预算匹配的 gated recurrent/SSM，免费或少训练的弱基线不能补这个缺口。当前 OOD 只改变 query/观察时间间隔；动力学、观察核和价格族保持相同。跨动力学族、真实内容任务或实际 hepta neuron 部署的泛化尚未确证。

证据：[模型范围](../MODEL_SPEC.md)、[主要统计](SUMMARY.json)、[独立统计审计](INDEPENDENT_STATISTICS_AUDIT.json)。

### 7. 数值求解、成本与生产交付

已经核验同一 40-state 有限 Q 的 expm 与独立正 uniformization、semigroup、首达和事件计数等数值性质。记录了全训练搜索、冷启动、候选规划分支、在线执行、本地 belief checkpoint 及两轮确认费用，原失败 worker 没有从账本删除。

**这不是连续 PDE 与闭式解的完整比较。** 同 Q 的两种数值方法回答有限算子实现是否一致，不能回答 continuum 离散化误差、移动边界收敛或控制任务闭式求解优势。相关 PDE/闭式比较仍开放。

**生产相关门也仍开放。** 当前 checkpoint 仅含 belief/model/clock 并进行本地 fsync/read/restore，未覆盖 owner 的 RNG、query/action receipts、in-flight 操作及网络重放。没有 native Q24/Rust 集成、生产吞吐与尾延迟、能耗或网络费用测量。确认和审计是有限 Python/NumPy/SciPy 研究证据，不能据此激活生产路径。

研究账本记录的非重叠 CPU 合计约 547.075 秒，其中正式训练与两轮确认完整 worker 合计 495.065 秒。账本明确列出未完整计量的早期开发、报告生成、上传/存储与其他范围；这些数值不是全部项目的能耗或货币账单，部署摊销曲线也不把研究确认账单假装成每次在线成本。

证据：[数值结果](numerics.json)、[数值范围](../NUMERICS_SCOPE.md)、[成本账本](RESEARCH_COST_LEDGER.json)、[执行审计](INDEPENDENT_EXECUTION_AUDIT.json)。

## 独立审计与来源固定

两份独立审计均通过。统计审计没有调用项目 `summarize`，从原始世界、query/action、episode 到 fit 重新计算；检验了 159648 个完整 query 记录、1379725 次数值比较，与 SUMMARY 的最大绝对误差为 5.684341886080802e−14。执行审计独立核验 token、截止时刻左极限真值、公开 WRITE、无观察 WAIT、全部 key 的时间、checkpoint、失败费用与发布先后，报告 0 处不一致。

核心源码 18 个文件及补充源码 3 个文件的冻结哈希均保持不变。源码冻结范围是 manifest 明列的文件，新增报告文件不改变实验定义。本次只新增本说明与 ACCEPTANCE.json，不修改原协议、冻结模型、SUMMARY 或两份审计。

| 来源 | 固定标识 |
| --- | --- |
| 核心源码 commit | `7d634a293500982db5beb37fa1d494a75b540a91` |
| 原模型冻结 commit | `8aa146bdb9dc7fae8748393cf718e24a7a9db2d3` |
| 补充源码/冻结 commit | `e4b51213bd19b6532553d252056573c17abc4814` |
| SOURCE_MANIFEST SHA-256 | `6c06773eadb2ccf9edb4f992fcebd338e34854d5a7ba36c938a0014fa7e2dbf2` |
| SUPPLEMENT_MANIFEST SHA-256 | `f705e77ab930318ab395c1584e7d639ec1fb423e5bbdaec9fc348fc0948dec81` |
| SUMMARY SHA-256 | `80b62cfeba264de5683cd72d81291ad5197986339706dc9ee991a51e412be140` |
| 独立统计审计 SHA-256 | `12a7dae93f539fb10775dcf546430918932ca6bee27ad87a406c04eb56d5453a` |
| 独立执行审计 SHA-256 | `244155bbd0a70ae1c7273452a940c34ef4179863e914dcb3c905e9a4fc772fd5` |

逐文件核心哈希、补充哈希及结果证据哈希均在 [ACCEPTANCE.json](ACCEPTANCE.json)。冻结源码链接：[核心](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/7d634a293500982db5beb37fa1d494a75b540a91/tools/hcsn/addressed_decision_r15_20261101)、[补充](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/e4b51213bd19b6532553d252056573c17abc4814/tools/hcsn/addressed_decision_r15_20261101)。这些是运行前的源码固定点，不冒称结果文件已包含在运行前 commit 中。

## 后续工作准入边界

当前结果适合作为可复核的有限研究基线及失败证据。后续若修复压缩、加入 learned addressing/SSM、学习 reset 或自适应边界，都应声明为新模型与新研究，重新冻结后使用新的确认对象。不能改写本轮 mean 的失效状态、把已用确认样本移作新确认，或以本轮审计通过替代新的科学检验与生产验收。
