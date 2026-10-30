# 五问题最终结论：填写模板与字段地图

这是 execution06 的静态准备模板，实际结果尚未填写。未读取本轮 RAW 科学值，未预填结论，未添加实验、指标、阈值或统计 family。依据为真实公开回读的 THEORY_TO_HEPTA_REVIEW、DECISION_MATRIX，及冻结 protocol、analysis、report、branch、head、C kernel 与 supplement 源码。精确输入描述符见同目录 FIELD_MAP.json。

下文 R 指真实 primary.artifacts.aggregate_results；F(n) 指其中 priority=n 的唯一 five_priority_findings 项；B/C 指 R.formal_analyses.B/C；S 指真实 postseal supplement 输出。科学解释必须先经过原完成/封存/字节恢复/17 ACK 门与 supplement 完整性 disposition；有 issue 的 COMPLETE 不能作无条件背书。

## P1：动作是否改变合法后继？

**填写句式：**“在完整的〔实际分母〕中，四动作带来〔整体物理状态差异数〕、〔参数/optimizer差异数〕和〔语义输出差异数〕。Field 请求〔override〕次，guard 接受〔accepted override〕次；fallback 和拒绝分别为〔分类计数〕。首次已记录分歧位于〔时钟及分辨率〕。完整12条A field paths／72次决策的原 inactive 谓词为〔实际值〕，成本为〔对应范围〕。”

| 需要回答的事实 | 原有入口 |
| --- | --- |
| 整体 hash、参数/optimizer、其他组件三种不同计数 | F(1).banks[].counts 的 parents_with_multiple_complete_legal_hashes / parents_with_multiple_parameter_optimizer_successors / parents_with_hash_diversity_only_in_other_components |
| guard 后实际数值差 | S/SUCCESSOR_DIFFERENCES.jsonl 的 difference.parameters / momentum / gradients / buffers，及 different_components / reference_tail_state_equal；汇总见 BANK_SUMMARY |
| 实际策略、fallback、首次分歧 | F(1).paths.A/B/C 的 overrides、accepted_overrides、guard_rejections、fallbacks、两个 first_*_divergence_clock、parameter_optimizer_trace_available |
| 终态与输出 | same_baseline_terminal_complete_state、F(1).terminal_output_differences、bank terminal hard-output counts |
| 同后继应有同 baseline-tail 结果 | S/EQUAL_DYNAMICS_GROUPS 的 components、terminal、values、semantic hashes、source/condition identities 一致性及 INTEGRITY_ISSUES |
| 全局 inactive | A_INACTIVE_GLOBAL.json：12 paths、72 decisions、总 overrides=0 且12个 baseline物理终态相同 |

意图不同、hash不同、参数不同和任务改善不能互相替代。A/B dynamics hash 排除 controller history/path-kind，且含 incoming gradient；相同 physical hash 不等于未来任意 history-policy 等价。数值零范数也可能伴随 absent-vs-zero 状态表示差异。inactive=false 本身不证明有效活动。

**C 的精确分辨率：**原 branch/rollout trace 有 before/candidate/after 整体 training-state digest、guard、action/clock/schedule、真实 work；COMPLETE.paths 原样提供 macro16 的 first_legal_divergence_decision/clock，aggregate 会合并。Digest 覆盖模型/SGD/gradients/modes/RNG，固定 context、时钟与预算在 plan/context_sha/transaction 中另行绑定。C 没有逐决策单独 parameter/optimizer hash或数值差范数；aggregate 的 parameter_optimizer_trace_available=false、对应首次时钟=null 表示该项不可用，不能解释成无分歧。Terminal metadata.parameter_sha256 不能定位中间首次分歧。A/B宏步48，C宏步16，都不提供内层microstep首次状态分歧。详细源范围见 C_SCOPE.json。

## P2：标签、baseline、时钟和剩余预算是否一致？

**填写句式：**“已核验〔标签和replay范围〕，各 head 的 RMSE/可得增益为〔实际数值或无定义〕；原 ungated 与真实 strict-gate 选择的 regret 分别为〔实际值〕，override/tie/fallback 为〔实际计数〕。证据显示〔无正增益／预测误差／gate不行动／可识别的优势／完整性问题〕，范围为固定 tape 的 realized baseline-tail contrast。”

| 必报项目 | 原有入口 |
| --- | --- |
| baseline与标签定义、clock、完整parent | A BANK.records 的 action_values、advantages、baseline、step、parent_sha256、branches，以及 label_reference；C自身 branch-row / plan / context绑定 |
| 完整重放 | F(2).reconstruction：3×192 A terminals 的 component/receipt/literal equality；不把R当新样本 |
| 每head误差与信号量级 | F(1).banks[].calibration.*.diagnostics；C另见 F(1).paths.C_heads.*.diagnostics |
| 严格部署规则实际表现 | S/GATED_CALIBRATION 的 gated_regret、mean_gated_regret_over_mean_attainable_gain、gated_optimal_set_accuracy、mean_chosen_advantage、fallback/tie/override；逐行见对应JSONL |
| 原拟合/校准条件 | dimension、36fit/12cal、ridge、threshold、normalizer、fit_design_rank、regularized_gram_condition；C单独72fit/24cal |

A/B是一候选macro48后固定各模型baseline到clock288；C是一候选macro16后baseline2到clock96。baseline advantage为零是结构定义，需结合实际branch与replay，不能单独当正确性证明。误差/增益的分母为0时ratio是null/无定义，不能记作0。原误差指标是ungated；outside_fit_norm仅诊断，不强制fallback。

108-row补充仅覆盖9个A heads的36个dependent parent slots；C两个heads不在该补充中。A/R的576-terminal literal重放不覆盖全部C768tails；C有4个预登记重建审计。不要把这种范围差异写成数据丢失，也不要宣称两者审计强度相同。

单tape值不是expected Q，依赖cal最大过预测不是uniform certificate。反之，baseline-tail本身不否定策略改进；真实expected advantage的同核同终点加性恒等式与当前经验标签的保证范围要区分。

## P3：field遗漏哪类决策信息？

**填写句式：**“在相同四动作、同guard、相同bank/分割/拟合规则下，field12、54740维current-state、114维同信息history的已有对比为〔point/CI/per-model值〕。预定momentum反射构造的近场条件为〔结果〕，最优动作交集与共同动作regret为〔结果〕。这些支持〔具体拟合表示/局部隐藏方向发现〕；未识别项为〔范围〕。”

主要入口为 B.effects 的 `field-history task`、`full-state-field task`（reward/audit的point、ci、per_seed全部保留），A各head条件数/秩、S/GATED_CALIBRATION、R.constructed_witness 与 S/W_SHARED_ACTION_REGRET。W务必报告 common_best_actions、shared_deterministic_action_minimax_regret、equal_state_mixture_minimum_average_regret、near_field/drift及field是否精确相同。

三种head的未来RNG/tape都不可见；history包含以前H12、已观察动作/guard/work，仍支付H12测量成本。Full-state ridge不是oracle，其未胜出不证明field充分。W只有3个预定、无reachable保证的构造对，1e-5近似同场不强迫所有敏感field policy选同动作；排序变化但有共同最优动作时，不能声称压缩必有决策损失。当前比较不能直接量化R45全occupancy信息损失或Markov closure。

## P4：独立净收益是否胜过ordinary与轻量控制？

**填写句式：**“在B完整240paths／486endpoint records和两个observer下，原ordinary adequacy与field advantage gates为〔实际booleans〕。相对fixed taper的预登记差值为〔保留原方向的point/CI〕，clean retention为〔值〕。共享离线、部署、评分以及全执行成本为〔有明确范围的实际值〕，因此当前实现的结论为〔原门通过/未过，测得Pareto改善/条件性交换/无净收益证据〕。”

必须同时展示B全部十effects；尤其不要漏 `ordinary-frozen task`、`ordinary-frozen clean`、`fixed-taper-field task (secondary)` 和 `fixed-taper-frozen clean (secondary)`。每项保留reward/audit两套point、ci、三个固定model的per_seed。B bootstrap固定8000、每observer十比较、quantiles .0025/.9975；模型固定，不宣称预训练模型总体或双observer联合同时覆盖。

**原field boolean只要求**两个observer的lower CI(field−ordinary)>0.001、lower CI(field−history)>0、field retention lower CI>−0.01，以及逐model两项task差值非负；**它没有包含taper比较或总成本Pareto门。** 原ordinary gain boolean与0.005 development target也分别报告。

A/B ordinary是历史选定seed-specific常值index2/3/3；轻量控制器是无probe、无fit的固定taper[b,b,2,1,1,0]。history6不是廉价控制器。保留taper−field既定方向，勿把负值误读为field较差。

成本入口是B.costs.arms、field_minus_taper_descriptive、R.actual_costs.rows、actual outer/root wait4及历史分层账。Label没有训练CPU/quadratic effort；当前learned实现都算完整richer30/margins并构造三种features，不能假设未来优化节省。零倍率、guard拒绝仍收费。Per-path账不含全部离线/评分/序列化，内部子账也不能重复加到inclusive总CPU。Wall/RSS不相加；历史未知不改成完整总数。协议要求实测quality-cost Pareto，不能事后定一个兑换率称无条件净收益。

## P5：Hepta是否额外适配？

**填写句式：**“在8 paired seeds、32finalpaths、16own-warmstarts的2×2中，Δdual为〔reward/audit point与CI〕，Δordinary为〔值〕，interaction=Δdual−Δordinary为〔值〕，dual-field−ordinary-field为〔值〕。四臂own-warmstart retention与实际成本为〔值〕。原interaction+retention gate为〔实际boolean〕；这具体支持〔增量/交互/较少伤害/未显示收益〕，对更多neuron或模态的扩展判断为〔基于这些结果的决定〕。”

C.effects八项全部保留：interaction、两simple effects、dual-field−ordinary-field、四项own-warmstart clean；每项展示两个observer、point/ci与8个per_seed。C原bootstrap8000、八比较/observer、quantiles .003125/.996875。96endpoint records对应48final-access checkpoints，不能把development warmstarts计入最终效果样本。

原gate仅为两个observer lower CI(interaction)>0，且四臂clean lower CI都>−0.01。它**不要求Δdual下界>0**；正交互可以是“较少伤害”。照原gate报告，同时用已经登记的simple-effect intervals准确描述dual内收益，不能追加门槛后改判原gate。

C baseline是所有架构/seed固定index2的常规匹配控制，协议明确不称best tuned。两个架构各自按同样预算/程序拟合field head，不是相同coefficients。处理差异是text encoder/decoder内sigmoid event law与FPT CDF/interval-end mean-reset，加上各自warmstart的受控比较；不能推成完整Hepta/NDU、自然free-boundary、FBSDE解法或LLM尺度优势。负结果可以完成比较；无需靠扩样、换baseline、开GRU或扩大模态来“修复”。

## 总结状态的填写顺序

依次报告：实际执行与证据门 → 完整人口 → 五问题具体数值 → 原门与描述性判断 → 成本/未知范围 → 原有限结论。不要用“全部跑完”代替有效性，也不要把历史明确FAIL或不可恢复的未知写成已修复。若有完整性issue则先说明影响，不能将它降格为普通阴性效应。

## Execution06 来源和成本补充

A17 沿用 execution04 实际完成、原 ACK 和原 source/profile 字节，须同时展示独立 producer map；其他13个科学任务属于 execution06。A17 不伪造 START/PID，不改旧seal，不重复计入失败增量。失败 A29 必须登记为整个job重做，不能写成精确resume。

原历史梯度下界182,096保留；execution04失败A29的14,784与execution05失败A29的17,280分别增加，历史下界214,160。完整计划343,808已含唯一A17，所以全尝试梯度下界557,968，不能再加A17。05失败optimizer为15,984，截断trace只作子集核验。原04 outer CPU含A17，不与当前A17阶段再加；05实际outer wait4缺失，controller 1,548.712305秒加supervisor自计7.248885367秒仅得1,555.961190367秒下界。worker 1,512.719833秒及phase CPU嵌套其中，不再加。新06 outer不含历史A17执行；READY/bridge/daemon-return不能冒充最终supervisor wait4。actual_costs.nonoverlapping_cost_ledger保留各可相加区间和未知范围，完整历史CPU未知。归档、恢复和root辅助成本另存真实测量总账。零退出、完整封存与正向效应分别报告；历史V5 FAIL、原资源合同未过及未知成本不被清空。

review.py在全部实际门之后生成填写过的 REVIEW.json 与 COMMENTS.zh-CN.md；本模板一直保留未填写状态，不能以模板存在作为运行完成凭据。
