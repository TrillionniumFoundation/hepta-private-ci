# V3 之后的科学推进审阅与新研究契约

**状态：proposal，尚未注册、分配新来源或运行新模型。** 本审阅支持把“初始合法面板校正”作为单一前瞻干预，进入一次完整路径资格检验；不支持把 V3 的失败 gate 改为通过，也不支持依据当前 runtime 探索原型立即打开新的运行 holdout。机器契约见 [NEW_STUDY_CONTRACT.json](NEW_STUDY_CONTRACT.json)。

## 1. 控制性证据和不可改写的历史

控制基线是提交 `74ebc1ed6947a4cd913ee162c88a81ac3677474f` 下的 [V3 协议](../field_bridge_v3_20261027/PROTOCOL.json)、[终态处置](../field_bridge_v3_20261027/evidence/STUDY_DISPOSITION.json)、[原 B01–B10 标准](../field_bridge_v3_20261027_review/BLOCKERS.json)与 [源分配](../field_bridge_v3_20261027/SOURCE_ALLOCATION.json)。所读文件的实际 SHA-256 单列于机器契约。

V3 明文要求下一研究使用新协议与未用来源，禁止 audit 重试、看结果后选择特征或门槛，以及反复重采 primary 直到成功。因此，V4 必须使用自己的 source registry、协议、phase freeze、run root 和 START/COMPLETE 身份；不得替换 V3 的 `passed=false`、伪造资格文件或通过旧 runner 的改名入口打开旧终测。

| 条目 | 历史仍是什么 | 新证据可以推进到哪里 |
| --- | --- | --- |
| B01/B02 | 已有局部响应／八步预测技能，范围限定 | 可以增加新源完整路径证据；不能把局部通过替代终点效用 |
| B03 | V2 gain 通过但联合 retention 未通过；V3 ordinary 仅开发通过 | 新来源、冻结 ordinary、同一部署及独立 retention 的联合确认 |
| B04 | V2 增量未建立；V3 H12 开发资格失败 | 新候选必须通过独立完整路径资格，随后仍须 C−B 和 E−G 的确认与保留能力 |
| B05/B06 | 双 observer 运行增益及超出同信息 history 的优势未建立 | 真正新、预算明确的策略必须在相同信息与动作下通过 D−A/E−C/E−F 等登记比较 |
| B07 | 只有部分独立保留证据和 V3 本任务 clean 条件 NI | 最终独立 retention、固定 0.01 margin 和预先声明比较族 |
| B08 | 传输优化及原内核数值对应在限定范围成立 | 后续可增加工程证据；更快或状态敏感不能代替 B05/B06 |
| B09 | V2 H7 fit/audit 共用 response panel 的事实永久保留 | 新研究可满足新范围的身份／访问要求；不能把旧轨迹改称源像素互斥 |
| B10 | 科学复核与实际本地归档恢复已通过；持久保存另有授权处置 | 保存与恢复身份由 root 独立推进，不改变任何收益结论 |

新研究若成功，只能新增其自身范围的证据；若失败，也须形成完整终态。“所有 blocker 均为 closed”不能作为继续换方法或增样本的停止规则。

## 2. 为什么选择面板校正，而不同时改多个因素

[训练诊断](TRAINING_DIAGNOSIS.json)发现：开发面板与 fit-bank 的绝对字段出现远超 bank 内轨迹变化的偏移；seed 43 的 clean loss 初值约偏离 fit 均值 −13.11 个 fit 标准差。在保留原头的线性分解中，这种偏移对错误动作优势有显著贡献。这是明确的机制假设，但不是新策略的闭环收益证据。

唯一候选为 [training_panel_origin.py](training_panel_origin.py) 中固定的 14 字段变换。令 `I=[0,1,2,3,12,13,14,15,24,25,26,27,28,29]`，`s0` 为本阶段合法初始测量，`f0` 为同模型冻结 fit 初态：

\[
x'_I=x_I-(s_{0,I}-f_{0,I}),\qquad x'_{I^c}=x_{I^c}.
\]

四条旧 fit 轨迹在这 14 个初态字段上必须逐位相同，禁止平均或重新估计。变换在原 fit 域恒等，全部旧 head、ridge、normalizer 与 reference 保持。初始 `s0` 只可来自当前训练阶段合法的 probe/guard 测量，优先复用已计划的 step-zero 原始测量；不得使用 qualification task/clean 的独立终点评分或最终 retention 来计算偏移。

所有 adaptive 对照得到相同 baseline 信息和计费。H12 读出仍为 12 维，但策略保留额外 14 个只读校准值（float64 数值载荷 112 字节，容器开销另计）。这不是无上下文的 12 维 Markov 充分性证明。记录完整 baseline 身份、来源、测量次数和存储成本，保持实际 loss、guard、teacher、梯度和 optimizer 更新为原始数值；只改政策读入的特征。

公开日志上的动作改变只能证明变换影响决策。第一次动作分歧之后，旧日志的后续状态属于旧策略，不能拿来估计新策略的真实闭环效用。[数值契约](TRAINING_PANEL_ORIGIN_CONTRACT.json)通过也不提供效果保证。

共同目标中心化不是替代修复。对固定线性 ridge 算子 `L`，若 `Y'=Y-b1^T`，则 `W'=L(Y)-L(b)1^T`，每一行的所有动作预测仅减少同一个量，argmax 不变。若另行改变 λ 的选择，产生的是选择规则变化，必须单独定义及计费；不能归因于中心化本身。

## 3. 不动 V3 sealed 角色的最小同规模 qualification 来源

原 V3 分配保留未分配池 **train 9,000 张、test 3,952 张**。主方案只在这个池中前瞻分配六个新 train 角色，完全排除 V2 和全部 V3 已分配像素身份；并不消费 V3 的八个未做模型任务角色。[来源与“未开启”的精确定义](../field_bridge_v3_20261027/evidence/STUDY_DISPOSITION.json)

| 新角色 | 图像 | 源对 | 用途 |
| --- | ---: | ---: | --- |
| gradient | 2,000 | 1,000 | 新完整路径参数更新 |
| rehearsal | 512 | 256 | 原有 rehearsal/anchor |
| probe | 256 | 128 | 合法特征与初始 baseline |
| guard | 512 | 256 | 原有 guard/rollback |
| task | 1,024 | 512 | 一次独立任务终点评价 |
| clean | 2,048 | 1,024 | 一次独立 clean 终点评价 |
| **合计** | **6,352** | **3,176** | 与 V3 原定学习 audit 的角色规模相同 |

分配后保留 train **2,648**、test **3,952**，尚不赋予最终评价用途。这是覆盖原定资格设计的最小同规模预算，不是数学上的功效充分性保证。固定 salt 为 `hepta-field-v4-20261027-panel-origin-qualification-1`；以 `SHA256(salt + ":train:" + pixel_sha256)` 再以 pixel hash 打破平局，只分配一次；按上表角色顺序取连续前缀，并在角色内相邻配对。不按类别表现、模型结果或有利分布重新选择。配对、条件和计分随机标记必须在方法间对齐。

只看原始像素哈希和分配元数据不同于从未读取 raw corpus。原 V3 分配已经读过像素及仅用于冲突重复排除的标签；来源“未用”限定为尚未用于相应模型任务／结果选择，不能声称未知预训练独立性或新书写者。

若未来确需转移 V3 未开启角色，须先独立核验其当前暴露状态，再在另一新协议中逐身份记录转移、用途和一次性消耗，保持 V3 原 gate/结果不变。当前 proposal **不授权这种转移**。

## 4. 一次完整路径检验，正式比较和机制参照预先分开

固定三个历史模型、四条新 schedule `14000,14001,14002,14003`，以及九种方法：四个 ordinary 常数、原始 H12、校正 H12/generic12/richer30/H7。总计 **108 条 288 步路径、31,104 个梯度微步、2,985,984 个梯度样本、648 次方向测量、0 次新 head 拟合**。这些是原 batch/步数的调用预算，不是 FLOPs；teacher、guard、所有零动作与回滚、observer、持久化和独立验证另记。

正式 ordinary 由已公开 V3 开发选择固定：seed 17 倍率 1、seed 29/43 倍率 2；新数据不得重选。正式 adaptive comparator 固定为校正 richer30。保留原六项学习资格比较：ordinary−frozen、校正 H12−ordinary、校正 H12−校正 richer30，以及三项候选相对 frozen 的 clean NI。

新 bootstrap seed 固定为 `271042`。原始 H12、校正 H7/generic 和未选 ordinary 常数均为机制诊断。不能看完新结果后改用更弱对照；若要正式宣称超过 H7、generic 或原始 H12，必须在开数据前扩充比较族和修正。尤其不能把校正后首个动作变得像 ordinary 当作超越 ordinary。

一次 qualification 保留 α=0.05、六比较修正、4,000 次配对分层 bootstrap、每个 observer 的 99.1667% 双侧区间。每次抽样在固定模型内共用完整 rollout 索引，并在各面板内共用源对索引；task/clean 的 rollout 抽样相同，源对抽样分别进行。模型与条件等权固定，严格比较 `>0` 与 `>−0.01`；gain 还须每个固定模型平均差 `>0`，两 observer 同时满足。区间算法和随机流身份在执行前固定。

模型任务开始前必须完成新 registry/源码/算法/锚点/模型身份的提交及独立审核。一次 START 后保留全部成功、失败和部分证据；任何完整正式比较失败即停止对应路线，不加样本、不换表示、不重选倍率、不在同一评价源上调参重试。基础设施失败与部分已暴露结果也必须记账，不能把已读到的评价结果重新封成“未开启”。

通过这一 gate 只表示可以准备独立最终确认。它仍使用历史单动作学习任务，不能直接关闭反馈任务的 C−B/E−G，不能关闭 B03–B07，也不能代替对 Hepta 的同信息比较。

## 5. 最终六项增益和十项保留比较仍需独立设计

未来 final 保留六增益 `B−A,C−B,D−A,E−C,E−G,E−F` 和十个非 A 臂相对 A 的 retention 族；部分路线不执行时保留完整分母，并记录未确立。A/B/C 使用同一字面固定部署策略；E/G 的 checkpoint-specific native heads 会引入下游 readout 适配中介，必须报告。所有最终 checkpoint、head、动作规则、样本及诊断身份都在任何 final 输出前冻结。

目前仅有 qualification 来源预算，尚无完整 final 来源／模型／runtime 资格方案，因此 final 保持锁定。不能在一部分 final 结果出现后继续选择其他方法，却复用同一 primary/retention。若采用分阶段独立研究，必须预先分配互斥终测群，并统一其声明范围与多重性。

为防止把“再开一期直到通过”当作无限次 α=0.05 机会，建议自 V3 结束后另立一个明确的新确认序列：第 k 次 final 分配 `0.05/2^k`；第一期总 α=.025，其中 gain 与 retention 各 .0125，仍保留 6/10 分母。对应单 observer 双侧区间为 99.7917% 与 99.875%。建议首次 final 固定 32,000 次 bootstrap，以在更严格尾部保留足够 Monte Carlo 分位数样本；这是开数据前的数值精度选择，不是看结果后增加研究样本。

此序列规则仍是 proposal，root 必须在开 final 前固定实际采用值、draw seed 和完整调用合同。它不会追溯恢复 V1–V3 的整体 0.05 覆盖。以 bootstrap 得到的每期结论仍是近似推断；严格序列错误界还依赖各期条件检验有效性。任何一期首次 final 输出消耗该期完整预算，失败或部分失败不回收预算。

## 6. Runtime 的新证据支持止住无依据的 holdout 消耗

[Runtime 探索](RUNTIME_DIAGNOSIS.json)完整保留了公开 fit/select 树、已执行 audit 路径及九个新离线候选。把后续 head 与早期标签分开来源组的六个策略，在已公开 selection 上全部低于各自原 V3 策略；这些划分还减少了每个 head 的来源数，并非预算完全匹配的改善检验。由此不能认定这种策略普遍无效，也没有理由据此直接打开新 holdout 或继续改 split/λ 直到赢。

完整树的“最好终点”看过全部 85 个反事实终点，是部署控制不可见的后见上界。运行 audit 未选续步没有被生成，不能补造、插值或用现有别的路径冒充其收益。Native/reset 的状态差异、native/history 的动作路径差异只证明表示影响行为。

公开 audit 的 native−history 源对聚合差标准差约为 .0284。沿用原四比较门槛，单 observer、80% 功效的乐观正态规划约需 9,000 对才能识别 .001 效应，约 2,250 对识别 .002；双 observer 及逐模型同向约束尚未计入。当前三个模型的差值符号混合，增加来源数不能强迫真实负差变成正差。样本计划必须围绕预先声明的可关心效应与固定资源上限，不围绕已经看到的正向点差反复追加。

## 7. Ordinary-only track 与最终主张边界

普通训练可另立独立联合确认，脱离 field gate；但这不是本次主方案失败后的自动 fallback。它必须有自己的预注册、双 observer gain+retention、来源及 α 分配。原先可构造的 standalone 预算为 train 7,376/test 2,048；主 qualification 一旦分配 6,352 张 train，原预算不再适用于只余 2,648 张的池，不能重复花费同一批来源。

本次单一校正检验能确认的最多是指定原始模型、合法面板、固定头、动作和训练任务下的完整路径增量。它不验证论文的全局充分状态、Riccati/HJB/FBSDE 或 LLM 规模结论，也不授予生产 owner 权限。[论文关系与原范围](../field_bridge_v3_20261027/PAPER_HEPTA_COMMENTS.md)

所有阶段保持 `DENY_ALL`、`requires_calibration=true`、`native_owner_integration=false`。持久保存的具体审批由 root 单独处理；科学效应不能由归档、代码提交、工具成功或权限通过替代。
