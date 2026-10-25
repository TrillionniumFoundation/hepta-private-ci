# ABC follow-up：最终证据的只读交叉审阅

审阅者：协调任务中的 `control_cost_v2` agent。首轮核对完成于 2026-10-25 09:10 UTC。

本文件记录对已经完成的 native、产品链恢复 helper 和 training repair 结果的交叉核对，供后续 agent 使用。
审阅期间未改实验源、协议、模型、结果或原始媒体，未重新生成 final，未重新选择候选，也未启动新的 bootstrap。
实际操作包括读取冻结代码及汇总、核对文件 SHA、重数已有 tick、重算过程成本，以及从已保存的评分数组独立重算点估计。
区间审阅覆盖预登记门槛、实现中的抽样单位、置信水平与报告数值；它不是一次独立数据采集或独立重复实验。

审阅者没有负责 native 主运行、主统计或 repair 训练实现；曾贡献 native 的 `future_candidate.py` 功能诊断模块和 repair 的来源审计。
因此，这两项的作者身份没有因本轮交叉核对而变成完全独立。

| 实验线 | 当前审阅状态 | 可支持的结论 |
| --- | --- | --- |
| native future predictor / continuous stream | 已完成，未发现实质数值或范围错误 | 未来状态预测改善；另登记的概率接口通过指定研究 gate；同 head 的 pending proposal / recovery 链真实完成 |
| product chain recovery helper | 已完成，未发现当前有限范围的证据错误 | 新 helper 在真实链副本上恢复成功，exact-base patch 已准备；完整目标 Agentd 集成和生产 admission 仍未验证 |
| training repair | 已完成，两个主 gate 均失败 | 强参考和初始乘子具有可分开的条件对比；没有证明主候选相对 mean 的联合收益和零成功率回退 |
| temporal final | **待实际运行和统计完成后补审** | 本次未读取正在执行的 final outcomes；此前 selection 不代替最终证据 |

## 1. Native：统计对象和资格范围

核对材料包括 [REPORT](native/REPORT.md)、[RESULTS](native/RESULTS.json)、
[主预测验证](native/VERIFICATION_RESULTS.json)、[概率契约验证](native/PROSPECTIVE_VERIFICATION_RESULTS.json)、
[实际 future native 结果](native/FUTURE_NATIVE_RESULTS.json)、[tick audit](native/FUTURE_TICK_AUDIT.json)、
[动力学诊断](native/DYNAMICS_RESULTS.json) 与 [成本索引](native/PROCESS_COSTS.json)。
预验证清单中的 **43 个文件 SHA 全部仍与冻结值相同**。

### 1.1 预测效果与 calibration

来源 census 是 **1,432 个来源对、2,864 个实际未来分支**。632 对为 ID，800 对为构造的 complete absence。
两个动作保留在同一来源对内；native 重放、候选变体和后续链恢复没有产生新的独立样本。

| 核对项 | 数值与判读 |
| --- | --- |
| 主 future-state MSE | forecast 0.119968863877；persistence 0.207087958773；改进 0.087119094896 |
| 主改进名义 95% 来源对区间 | [0.082264993559, 0.091874252101]，下端为正 |
| ID-only 改进 | 0.004985284285，描述性 95% 区间 [0.003592290270, 0.006508357537] |
| 原 residual-confidence 契约 | verification ID ECE 约 0.262781；实际原生 bootstrap 拒绝 `InvalidCalibration`，tick 数为 0 |
| supplement ID point-ECE | 0.026088746835，小于登记的 0.03 |
| supplement ID ECE 描述性区间 | [0.011977984909, 0.049020844561]，上端超过 0.03 |
| supplement ID 概率接纳率 | 826/1,264 = 65.3481013% |
| verification OOD 误接纳 | 0/800 个来源对；单侧名义 95% 上界 0.003737662826 |

零误接纳上界以 `1 - 0.05**(1/800)` 独立重算，与发布值一致；calibration 的 0/400 上界为 0.007461355529。
协议只要求 verification 的该上界不超过 0.004999，没有用 calibration 的较宽区间替换门槛。
代码按来源对保留两动作相关性计算 ECE bootstrap，没有把 1,600 个 OOD 分支当作独立二项试验。

报告准确区分了 **point-ECE qualification** 与“以 95% 置信度 ECE 不超过 0.03”。
supplement 的 32 个 observed-state 坐标只是相消的 confidence carrier；它们不是新的未来预测。
真正的未来状态 forecast 与未来正确率概率在原生成之前提交，分别审计；原 residual 契约的失败仍保留。
以上结果不能直接推出生成效用提升、下一动作选择价值或全局 NDU 最优。

### 1.2 实际 continuous chain

审阅者直接读取已完成的 1,600 条 `ticks.jsonl`，得到：

| 项目 | 独立重数结果 |
| --- | ---: |
| tick / ID / OOD | 1,600 / 800 / 800 |
| ID admitted / OOD admitted | 486 / 0 |
| 概率合格数 | 486 |
| 概率 gate 与实际接纳的错配 | 0 |
| successor predecessor-anchor 断裂 | 0 / 1,599 |
| subject context | 1 |
| sequence ≥800 的首个实际 admitted ID | 802 |
| 最大 projection / saturation count | 1 |
| 每 tick active fraction ppm | 121,212，即 4/33 的整数表示 |

这些计数与汇总、13 个 journal 段、12 次 rollover、三次 acknowledged recovery 一致。
最后 sequence 1,600 真实 abstain；报告没有改用更有利的结束点。
序号 802 的 live hook 使用 future head 自己的参数、36 次 owner resolution、两个 update 候选以及同 anchor 恢复，
不是接用旧 head 的提案证据。

逐 tick分位数也从已有记录重算一致：native P50/P95/P99/max 为 **318/569/2,041/3,249 μs**；
outer 为 **589/1,061/2,697/77,215 μs**。
2.391017 秒的 proposal/evaluation/recovery 暂停位于完整流 wall 内，不在这些逐 tick 分位数内。
native 子流的 486/800 与完整验证的 826/1,264 使用不同的预定组成，不能直接用两者相减推断额外 runtime 拒绝。

动力学失败记录中的首次 ID 拒绝是 **sequence 66、pair 33**。审阅发现原报告“第 66 个 ID tick”可能误读，
已通知 owner 按 sequence 66 修正文案；冻结数据和源代码无需改变。
新动力学配置的有限 stress 结果不能升级成任意输入、无限时域的稳定性证明。

### 1.3 提案与生产边界

旧 head 的两个固定候选在新来源上 raw-Brier 改善分别为 **−1.3589140e−8、−2.7182926e−8**，
各自 97.5% 区间均跨零；两比较的名义 family 95% 口径正确。没有独立正收益证据。
新 future head 的候选只在已观察 historical selection 的 2,000 对 / 4,000 行上进行功能评价，
`eligible_for_independent_acceptance=false`，不能将其极小 Brier 变化当成新的留出收益。

真实研究 ledger 的两个记录对应已完成 tick 的二元信号 gate，范围不覆盖全部生成动作或 plasticity 候选空间。
pending registry / witness 恢复与 `RequiresIndependentAcceptance` 状态真实成立；
产品 API 在 Dataset 查询处仍返回 **`OwnerEvidence(Unavailable)`**。
未到达的后续签名、部署或应用检查不能报告成已经执行。
报告与结果均明确没有 production admission、没有 applied model update、没有因果生成收益。

### 1.4 成本口径

从 [PROCESS_COSTS](native/PROCESS_COSTS.json) 的 exact-child receipts 独立求和：

| 分组 | 阶段数 | wall 秒 | CPU 秒 |
| --- | ---: | ---: | ---: |
| main future study | 13 | 83.251938530 | 79.230294000 |
| 保留的历史诊断与失败 | 9 | 25.086374642 | 11.724031000 |
| 已列阶段合计 | 22 | 108.338313172 | 90.954325000 |

嵌套 evaluator receipts 没有再次加到父流程；并行阶段 wall 总和也没有被报告为单个端到端请求时延。
future 全流 wrapper wall 为 7.523863668 秒，内部流计时为 7.477644 秒，两者具有不同起止边界。
已有 generator/observer 训练、此前未测量的构建和调试成本没有被当作零。

## 2. 产品完整链恢复 helper

核对 [README](production_handoff/README.md)、
[CHAIN_RECOVERY_VALIDATION](production_handoff/CHAIN_RECOVERY_VALIDATION.json)、
[patch](production_handoff/bootstrap-f8c9419.patch)、helper/probe 源码，以及本地保留的 exact-base bootstrap 原文。

新增 helper 以原 journal API 顺序恢复链，要求中间段满容量，并核对最后 acknowledged sequence 和 digest。
所有段加入原 loader 的路径分离检查；原 `existing_paths_alias` 包含 Unix inode 比较和 symlink 拒绝。
helper 的文件检查不创建缺失段或把空文件初始化成新历史。

现有验证包含 **2 个成功案例和 19 个拒绝案例，共 21 项**，计数与 README 一致：
真实 13 段副本恢复到 sequence 1,600，anchor 与 33 维 eligibility 精确相同；旧单文件分支也通过。
审阅时原 13 个 journal 的 SHA 再次核对一致。没有新 tick、新独立 N 或模型应用。
patch 与两个可审阅 Rust 源文件的 SHA 均与 validation receipt 相同。

已编译的是 helper/probe 加原 `9595221…` journal 依赖；目标 patch 对应 `f8c9419…`。
不能据此声称较新整个 Agentd crate 已成功编译、完成 owner composition 或部署。
恢复 API 可能修复不完整尾帧；README 已说明中间段处理发生在最终全链 anchor 检查前，
没有承诺所有失败输入均保持字节不变。正式部署仍需要私有 owner 存储和独立 witness。

## 3. Training repair：主门槛与条件机制

核对 [REPORT](training_repair/REPORT.md)、[RESULTS](training_repair/RESULTS.json)、
[训练协议](training_repair/TRAINING_PROTOCOL.json)、[评价协议](training_repair/EVALUATION_PROTOCOL.json)、
[来源分配](training_repair/SOURCE_ALLOCATION.json)、[正式角色登记](training_repair/ROLE_ASSIGNMENT.json)、
执行登记、20 个已保存评分数组，以及训练/评价/分析的过程 receipts。

### 3.1 来源、冻结和完整 census

`unallocated_test` 正式登记为 `repair_test`，其 2,000 个个体 ID / 像素 SHA 与其余 **13 个** manifest 角色无交集，
包括整个 6,000 图的 test 角色。原 unallocated-role loader guard 保留。
新 loader 需要完整模型 census、协议、assignment 和 access registration 的绑定，原始 manifest 和档案重建也仍校验。
实际 access 登记的 origin/assigned role、1,000 对范围及个体 ID 摘要与协议一致。

独立只读核对得到：

- 24 个冻结 source pins 全部相同；20 个模型文件 SHA 全部相同；20 个评分数组 SHA 全部相同。
- 执行记录有完整的 20 个不同 seed/arm cell，各 16,000 行；总计 **320,000 个实际图文输出**。
- 每个 metric array 形状为 `[1000,8,2]`，观察器和指标 census 完整，成功与完成指示均为二元。
- 从这些数组独立重算各 arm 的逐 seed CE 后取均值、成功率、平均效用和完成率，与发布值最大差 **1.12e−16**。
- 每臂 80,000 个输出中，mean、old_constraint、warmdual 各有 1 个未完成输出，matched_floor 有 2 个；它们未被删除。
- 十个新模型均执行 400 步，候选与参考各 51,200 个输出/模型；合计双方各 **512,000** 个输出。
- 每个新模型的条件/候选/参考随机日程 SHA 与同 seed 的旧 `risk_success` 相同；warm 起点和固定新 mean 参考身份吻合。

独立来源 N 为 1,000 对，训练 seed 为五个。bootstrap 同时重采样这两个轴，保留全部视图、情景与处理臂配对。
主项名义 97.5% 区间、其它描述性 95% 区间的口径与冻结协议一致；五 seed 不提供精确覆盖保证。

### 3.2 主检验

唯一主候选为 `matched_floor_warmdual`，参考为已冻结的 `mean`：

| 指标 | 候选 − 参考 | 名义 97.5% 区间 | 预定 gate |
| --- | ---: | --- | --- |
| joint CE | −0.000716798954 | [−0.007972773594, +0.004792702923] | 下端 >0：**失败** |
| exact success，百分点 | +0.008750 | [−0.413750, +0.471313] | 下端 ≥0：**失败** |

联合结果为 **FAIL**。点估计接近零不能证明等效或无成功率伤害。
第二冻结观察器的 warmdual−mean 成功率为 **−0.3700 个百分点**，描述性 95% 区间 **[−0.7125, −0.03375]**，
也不能据主观察器较好的点估计宣传普遍无害。
没有改选 matched_floor、seed、checkpoint、观察器或容忍边际。

### 3.3 可以辨认的局部机制

固定初值乘子 0 时，`matched_floor − old_constraint` 只替换成功率参考：
主观察器成功率差为 **+0.9675pp [ +0.553719, +1.383750 ]**；第二观察器为 **+0.5625pp [ +0.166219, +0.946250 ]**。
这些未做全家族调整的描述性比较支持：本配方中的弱 floor 错配是一个可改善的因素。
它们不证明新候选已满足相对强 mean 的总体约束，也不能替代主检验。

固定强参考时，`warmdual − matched_floor` 只改变初始乘子：
主观察器 CE 差为 **−0.005167268106 [−0.007822651185, −0.002502664794]**；
成功率差为 **−0.04375pp [−0.4175, +0.3375]**。
第二观察器的 CE 同样较低，成功率差也不确定。
该具体初始 dual 修复没有显示额外成功率收益，且有 CE 下降的描述性证据。

当前只识别上述两条条件对比。缺少 `weak-floor + lambda0=1` 臂，不能称为完整的 reference×initial-dual 因子交互识别。
对偶乘子的终值仅是优化状态，有限 400 步和有限 multiplier cap 不构成约束收敛或全局最优证书。
前一轮失败仍保留；自适应开展新轮次没有被包装成跨轮次统一第一类错误控制。

### 3.4 实际成本

| 精确子进程 | wall 秒 | CPU 秒 | peak RSS bytes |
| --- | ---: | ---: | ---: |
| 新训练 | 885.234594527 | 1,754.121108000 | 495,239,168 |
| 全部评价 | 317.224851853 | 595.763887000 | 999,071,744 |
| 分析 | 8.830035520 | 9.418040000 | 347,676,672 |

报告表格与 receipts 换算一致。候选与强参考的实际执行成本都包含在训练阶段。
这是 batch evaluation，不是逐请求 P50/P95；共享宿主以及与 temporal final 的少量重叠已注明。
pilot、来源审计、既有模型训练等成本与这张正式阶段表分开，未声称它们为零。

## 4. 待补：Temporal final

当前 final 仍在运行。本审阅未读取其 outcomes，也未根据 selection 负差调整策略、价格、gate 或统计方案。
完成后需核对完整 64 facts×2 templates×2 futures×3 policies 的 census、fact 内相关性、三项主 gate、
五档价格与两比较的区间口径、同输出成本绑定、target-free Whisper 的后置边界，以及 `[0,0]` 成功率区间的有限 census 含义。

## 5. 本次核对的主要固定身份

| 材料 | SHA-256 |
| --- | --- |
| native RESULTS | `3b23577a00a049dd4a5beec6755ef1c0f53ad994de7810d0d182998620e354a4` |
| native FUTURE_NATIVE_RESULTS | `4098c9ecd2e8a38de08bb67e4a8e705d335035c57d6b34bf8f13d0eaebb84e8d` |
| native PROSPECTIVE_VERIFICATION_RESULTS | `822d5f8d9de900c27ec6689e7f84a25cb4ec9415076b8cbc57144fcd5cf07fbe` |
| native PROCESS_COSTS | `c33d83d7e9b78a940c249d6556f17a273b119dc05eb642d3a76a7273d688aae0` |
| product CHAIN_RECOVERY_VALIDATION | `edad13a0dbcc2f0f22b3ae446f7178ccba6e25e8617d84b4362e6e77bd142697` |
| product exact-base patch | `b156737e5ca460fae69dc5d042a3e8ba41522f377d6ba646261acca33d6f8ff8` |
| repair EVALUATION_PROTOCOL | `d190976793423f59909eb3051ea78aa5b2824727762011a468dd3c6a67575474` |
| repair RESULTS | `7598767767e62cb94cfd3ae43d3e7e62c7b4fd3e14b158e108950d1ce878974d` |
| repair SOURCE_ALLOCATION | `2449523451a9908f806ab16eb0e8abc638506263baa3bf259c7554e522401e3b` |
| repair ROLE_ASSIGNMENT | `42c5bb90adefb4d536001d433a6fe8c8345a3547857ba7edb72555043ae3dc52` |

本审阅没有把已完成诊断等同于所有正向能力目标已经满足。独立参数提案收益、主训练联合增益和生产权威来源仍有明确未闭合项。
