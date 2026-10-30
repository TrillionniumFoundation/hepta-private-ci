# 五项优先级判定矩阵：科学收尾工作稿

**状态：DRAFT，依据源码的判定说明；不是结果报告，也不是新协议。**

编制日期：2026-10-29（America/New_York；执行凭据仍使用 UTC）。公开副本准备时间：**2026-10-29 23:19:18 EDT**（2026-10-30T03:19:18.293347+00:00）。以下操作状态仅依据主代理截至 **2026-10-29 23:13:29 America/New_York**（2026-10-30T03:13:29+00:00）的观察及已经返回的执行凭据：源代码发布已在固定公开提交 **51749cfc93452ba7c235543c1529568a75368f2d** 完成，7 个发布文件（包括二进制 Git bundle）的实际 HTTP 读回均匹配；原 2026-10-30T02:17:18.526531+00:00 的真实导入收据仍证明当时的原始源码闭包校验通过。该导入事实不代替新的资源准入或科学任务内存资格。

截至上述观察，**本轮 science = 0，当前资源窗口未通过，共享环境 OOM / OOM-kill 计数为 4 / 4**；计数不归因于任何具体进程。本稿没有核验或读取本轮 RAW/endpoint 数值，所有实验分母仍是既有协议的计划人口，不是已执行数量。资源未获准入不能解释为科学负结果，源码发布完成也不表示科学实验已经完成。具体发布与读回凭据见本目录的 SOURCE_PUBLICATION_VERIFIED.json 和 REMOTE_BYTES_VERIFIED.json。

本文只整理已冻结代码、协议和已登记 postseal supplement 的产物与解释条件，不新增检验、样本、阈值、重试规则或统计 family。论文基准是 R45 完整提交 f8df0a6075f58f3ab9431a889b773cdf8d6e771d；此次核对时 canonical paper-llm-theory 分支仍为该提交。理论来源与完整批注见同目录 THEORY_TO_HEPTA_REVIEW.md。

## 一、先区分四种结案状态

| 维度 | 需要的事实 | 可以如何结案 | 不可替代的东西 |
|---|---|---|---|
| 执行状态 | 实际 worker、正确返回码、完整预定人口与 producer seals | 执行完成；或如实报告准入阻断/执行不完整 | 文件存在计数、计划微步、合成测试不能代替实际完成 |
| 证据状态 | 当前 execution 的 source/protocol/operation 绑定、全量 artifact SHA、literal restore、supplement integrity disposition | 证据通过；或指出具体不可复核/一致性失败 | COMPLETE 文件名或 complete=true 单独不够 |
| 科学结论 | 既定机制、校准、独立端点、统计 family、retention 和成本 | 支持、未显示、阴性、inactive、或未识别均可忠实报告 | 跑完全 suite 不等于所有假设为真 |
| 历史与外部状态 | 原收据的实际可用性、已观察下界、未知后续工作、实际发布确认 | 记录可知与不可知部分 | 不得宣称缺失历史成本上界已闭合，或把未知 publication 写入改写为成功 |

完整性问题不是应隐藏的“不利效果”。出现既有 supplement 的 integrity issue 时，应报告其 exit 3 与具体问题，不能以“补充也有 COMPLETE”提供无条件科学背书。缺少应有产物则是未完成，不是零效应。

## 二、所有科学判定共用的现有门

下文 RAW 相对路径均指这次实际执行根，而非历史同名目录。当前规划根为 /workspace/scratch/178ced6a501f/fullstudy_execution04_durable_raw；OPS 为对应 fullstudy_execution04_ops。路径仅用于说明，不表示这些科学产物已经存在。

1. **完整 14-job 人口。** A/B/R 各有 seed 17、29、43；另有 C、W、A_endpoint、B_endpoint、C_endpoint。controller/EXECUTION.json 必须记录对应全部 jobs 的真实完成、退出码和绑定；既有补充还要求 complete=true、oom_admission_paused=false。一项资源准入阻断不能替代任何一项完成。

2. **原 26-seal 与 30-seal 门保持。** 26 包括 11 份科学 stage COMPLETE、对应 11 份 operations COMPLETE、三个 ENDPOINTS.json，以及 controller/EXECUTION.json。30 再加 aggregate 的 COMPLETE.json、WORKER_COMPLETE.json、RESULTS.json、REPORT.md。analysis source freeze 必须绑定准确的 26 项；finalizer source freeze 必须绑定准确的 30 项。

3. **实际 operation 与科学完成相互绑定。** 核查 operation 的 complete、phase、seed、scientific_source_bytes_unchanged、post_execution_storage_check、scientific_protocol_sha256、operational_amendment_sha256，以及 scientific_complete 的 path/bytes/sha256。内部兼容 attempt_id 与真实 execution_episode 是不同字段，不能凭“attempt02”名称混入旧 episode 的产物。

4. **字节级恢复必须实际完成。** MANIFEST.json 的 logical_paths、logical_artifact_count、logical_artifact_bytes，与 VERIFIED.json 的 logical_paths_verified、logical_files_restored、logical_bytes_restored 一一吻合；archive_verification_complete=true，binding 匹配，所有登记 paths 均被恢复核验。只计算原文件 hash 不等于 literal restoration。

5. **公共 pipeline 收据。** OPS/COMPLETE.json 的 schema 必须为 hepta.fullstudy.pipeline-completion.4，complete=true，execution_episode=execution04_durable_20261030；artifacts 精确绑定 verified、manifest、aggregate_results、finalizer_freeze，各项具有实际 path/bytes/sha256，收据本身再由外部 descriptor/SHA 固定。该公共 complete 的范围是 primary pipeline，不包括 supplement 或效益判断。

6. **补充分析单独关闭。** 已登记的 postseal supplement 只在上述门、原 source pins 及实际全量 restore 通过之后读取科学 payload；输出在 RAW/CAS/source/registrations 之外。应读其 GATE.json、INPUTS.json、COMPLETE.json、INTEGRITY_ISSUES.json 与实际 exit code。complete=true 同时 status=COMPLETE_WITH_INTEGRITY_ISSUES 及 exit 3，不能解释为无问题通过。它不 refit、不增加独立样本，不重写主检验。

来源：固定 [report_results.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/report_results.py)；本轮另行登记的 supplements/parameter_field_fullstudy_20261030/postseal_supplement.py 的 required_seals、gate 与 main。后者是本轮新实现，不冒称丢失旧补充的原始字节。

## 三、五优先级总矩阵

| 优先级 | 所需实际产物与固定分母 | 核心判定字段 | 可闭合的负结果 | 不能推出 |
|---|---|---|---|---|
| P1 合法后继与策略活动 | 三份 A bank，每份 48 parents × 4 actions，共 144 parents/576 tails；48 A rollout paths；三份 R complete 与 576 新重建 terminal；既有 same-dynamics 补充 | first.dynamics 与 components；first_legal_successor_differences；prefix_replay_equal；override/accepted/guard/终态同一性；R literal equality；supplement issues | 四意图映射到相同有效后继；有意图但无有效改变；既定 candidate inactive；或明确完整性失败 | 意图不同即有效控制；hash 不同即行为不同；固定-tail 等价即任意 history-policy 等价 |
| P2 标签与部署选择 | 全量 BANK、trace、输出 NPZ、九份 A heads；每模型 36 fit/12 cal slots；补充 36 parent slots × 3 heads = 108 rows；R replay | action_values、advantages、baseline、label_reference；threshold/diagnostics；actual choose、gated_selection_regret、fallback/ties | 没有可达正优势；预测误差大；gate 全回退；gated regret 高；原 ungated 指标乐观 | 单 tape label 就是 expected Q；cal maximum 是 uniform certificate；fallback 等于代码失败 |
| P3 field/full-state/history 与隐藏方向 | 三种 A head 与全部 B 闭环比较；W 的三个预定构造对；GATED_CALIBRATION 与 W_SHARED_ACTION_REGRET | 同分割/维数/normalizer/ridge；B 的 field-history、full-state-field；W drift、common_best_actions、shared minimax/mean regret | history/full-state 未胜；W 近场条件失败；排序变化但仍有共同最优动作；没有显示决策信息增量 | field 充分；full-state ridge 是 oracle；W 是 reachable 反证；近似同 field 迫使所有 field policy 选同动作 |
| P4 独立收益、retention 与成本 | B 240 paths；全量 checkpoint/access barrier；486 endpoint records；formal_analyses.B；stage/endpoint/outer ledgers；历史分层披露 | 十个 effects 的 point/ci/per_seed；B 原统计 threshold booleans；完整成本口径与 unknowns | 效果未过阈值、负效应、retention 失败、仅普通训练有效、extra observation 无净收益 | 统计 gate 自动等于 adoption/Pareto；当前实现贵就说明所有 H12 实现都贵；历史总成本已知 |
| P5 architecture × controller | C 的 20 warmstarts、32 paths、4 replay audits；52 literal training checkpoints；最终 48-checkpoint barrier 与96 endpoint records；两个 architecture-specific heads | 八个 effects、两个 simple effects、interaction、四 arm retention；C plan/work/counts、state matching、activity/costs | interaction 未显示；dual-field 无收益或有害；retention 失败；只有 generic training 改善 | 正 interaction 必然等于 dual 内 field 正收益；验证 Call-Put/free boundary/FBSDE；推广到所有 Hepta 或 LLM |

以下给出不改变已有门槛的具体读法。

## 四、P1：先确认实际受控对象，再判断是否有活动

### 必需产物与字段

- RAW/stage_A/seed-{17,29,43}/bank/BANK.json：complete=true，records 恰为每 seed 48 个预定 parent slots；每 row 的 branches 恰有 action 0、1、2、3；完整 parent descriptor、action_values、advantages、first_legal_successor_differences、prefix_replay_equal。
- 同目录 trace.jsonl.gz、schedule-{schedule}-{prefix}-step-{clock}.state 与四个 action NPZ。step 是原代码未零填充的整数；该命名说明不代表已扫描任何目录。
- branches[].first 的 dynamics、components.parameters、components.optimizer、gradients、rng、remaining_schedule 等，以及 controller_history 的独立身份。
- RAW/stage_A/seed-{seed}/paths/PATHS.json：全体 48 paths，其中 field12 为每 seed 4 条、合计 12 条，每条六次决定；逐条 overrides、accepted_overrides、terminal_reference_tail_state_equal、trace.transaction 和 choice。
- RAW/stage_R/seed-{seed}/COMPLETE.json：每 seed terminal_count=192；all_original_component_and_receipt_hashes_equal=true；all_literal_terminal_restores_equal=true；original_scientific_counts_changed=false；new_fitting_or_selection=false；reconstructed_terminal_bytes_not_originally_archived=true。保存的 .bin.gz 与 .trace.json.gz 必须受该 seal 的 artifact 身份约束。
- 补充 BANK_SUMMARY.json、SUCCESSOR_DIFFERENCES.jsonl、EQUAL_DYNAMICS_GROUPS.jsonl 和 INTEGRITY_ISSUES.json。需区分 parameter/momentum 的 l2、max_abs 与 absent-versus-zero 等 representation 差异。

### 原规则的负结果可以完整关闭

协议 inactive_rule 是两个条件的合取：**全部预定 A field 路径零 override，且全部同 guard baseline terminal identities 匹配**。完整分母是 12 条 field 路径、72 次决定；不能用 accepted_overrides=0 代替 overrides=0，也不能只展示一条 path。现有 aggregate 主要输出逐 path 机制字段，并未新增一个独立的全局 A_inactive 布尔；最终评论须据这些已有字段说明分母和两个条件。

A inactive 以后仍保留其结果，并执行原先单独登记的 B/C 比较；不得降低 tau 或择优删路径。一个没有有效行动的候选可以被完整地判为 inactive，并保留实际观测成本；这不是“所有参数场均无效”。

### 等价边界

first.dynamics 排除 controller history 和 path_kind；其 hash 又包含 incoming gradients，所以 hash diversity 可能只有非后续行为相关的差别。既有 report 提供 parents_with_multiple_complete_legal_hashes、parents_with_multiple_parameter_optimizer_successors、parents_with_hash_diversity_only_in_other_components 等不同计数，不能合并叫“有效控制”。

同 first.dynamics 组在固定 baseline tail、同未来 tape、共同终止时钟与 charge 下，应有相同 terminal dynamics、value、output hash vectors 和 source/condition row identities。补充已经核查这些项目，出现冲突给 issue。该等价不推广到会读取不同请求动作/历史记录的未来 history-policy。

## 五、P2：标签一致性、预测能力与实际 gated 选择分别判定

### 标签与模型的实际证据

BANK 的 advantages[a] 必须是 action_values[a]−action_values[baseline]，baseline advantage 恰为零，label_reference 保持 first action then baseline / same guard, clock, budget, paired tape。R 检查的是原 deterministic transaction receipts、首 guard 结果及 terminal component/hash 的真实重放；它补证据字节和工作成本，不增样本、不改变原标签。

九个 A head 的各自 .npz 与 BANK.heads 必须一致。固定字段包括 dimension、fit_count=36、calibration_count=12、ridge=1、baseline、threshold、mean/scale/coefficients/intercept，以及 diagnostics.calibration_rmse、mean_attainable_gain、rmse_over_mean_attainable_gain、fit_design_rank、regularized_gram_condition、calibration_max_overprediction。分割单位是完整 schedule：6000–6002 fit、6003 cal，两个 prefixes 与同 schedule 六个时间点保持一起。重复 step-zero states 不能增加独立样本数。

原 heads.diagnostics 的 calibration_action_regret/accuracy 来自批量 ungated argmax；实际部署还要求唯一 nonbaseline maximum 且 predicted margin 严格大于 threshold，否则回 baseline。故必须同时读已登记补充：

- GATED_CALIBRATION.json：models_and_modes、override_count、fallback_counts、exact_max_score_tie_count、gated_regret、gated_optimal_set_accuracy、mean_chosen_advantage、mean_attainable_gain、mean_gated_regret_over_mean_attainable_gain、rowwise_ungated_mean_regret。
- GATED_CALIBRATION_ROWS.jsonl：chosen_action_is_optimal、gated_selection_regret、rowwise_ungated_selection_regret、optimal_action_set 与原 choose 的完整 choice。
- 108 rows 只是 36 个已登记 cal parent slots 上三种 head 的重复诊断，仍为 new_independent_samples=0、certificate=false；不是新增验证集。attainable gain 为零时比例是 None，不能改填零或无限大以制造排名。
- outside_fit_norm 是已有诊断，不是自动 fallback 条件；不能事后把它变成新的 safety gate。

### 负结果与理论边界

可以如实关闭为：没有正 realized advantage；有优势但 head 识别不了；预测有信号但 strict gate 不行动；gated choice 的 regret 明显高于原 ungated 指标。这些是不同失败机制，不需要改阈值使其“通过”。

baseline-tail 本身并不排斥策略改进。对同核、同终点和加性期望回报，真实 expected advantage 有 Vπ−Vb=EπΣAᵇ；沿部署占用非负可支持改进。当前 realized paired tails 与依赖 cal 不能提供该全 occupancy 保证，也不是部署 replanning policy 自身的 Q。一般 nonlinear NDU aggregator 更不能直接继承这个线性期望恒等式。

## 六、P3：区分信息、拟合能力、占用分布与构造状态

### 三种 head 与闭环 B

field12、full_current_state（54,740维）与 history6（114维）使用相同 bank、labels、fit/cal partition 与固定 ridge 规则。current-state 数值输入不含未来 tape/RNG；history 只含此前公开 H12、实际动作、guard/work 和记忆有效标记。current 与 history 的更丰富输入不使有限样本 ridge 成为最优 predictor。

所需 B endpoint effects 至少包括 field-history task 和 full-state-field task，两 observer 的 point、ci 和每个固定 model 的 per_seed；全部十项 family 必须一起保留。可以报告 head family 的经验排序，但“full-state 没赢”不证明 field sufficient，“history 赢”也不证明 field 有 Markov closure。高维拟合容量、条件数和数据量仍是解释因素。

### W 的预定三个构造对

RAW/stage_W/COMPLETE.json 必须完整列 seeds 17、29、43，固定 parent=(schedule6000, baseline prefix, clock48)，以及 original_bank_sha256/original_head_sha256、field_before/after、absolute/normalized_field_drift、near_field_tolerance=1e−5、near_field、original/reflected_action_values、head_choices、ranking_changed、best_action_set_changed。constructed_off_policy=true 与 reachable_state_guarantee=false 必须保留。

补充 W_SHARED_ACTION_REGRET.json 进一步提供 common_best_actions、original/reflected_regret_by_action、shared_deterministic_action_minimax_regret、equal_state_mixture_minimum_average_regret，以及 field_coordinate_values_exactly_equal。这是在两个固定构造状态上要求共用一个确定动作的诊断；等权 mean 是明确的 50:50 混合，不是部署 occupancy。

可关闭的负结果包括近场 criterion 不成立、方向改变却 action values 不变、ranking 改变但仍有共同最优 action、或共同动作 minimax regret 为零。不得反射更多方向、改 rank cutoff 或挑 parent 以挽救结果。即使共同动作 regret 为正，也不构成所有 field policies 的下界：near-field 不等于完全相同输入，构造对没有 reachable 保证，随机化 minimax 也可能不同。

## 七、P4：独立收益和当前成本口径

### 独立端点与既有统计规则

B 的三固定模型 seeds 17/29/43，各 16 个新 schedules 106000–106015，五种 methods，合计 **240 paths**。在任何 qualification endpoint 访问前，全部 checkpoint 人口与对应 source/scorer freeze 必须完整，不能只挑部分 paths。ENDPOINT_CHECKPOINTS.json、QUALIFICATION_ACCESS_FREEZE.json 与 source allocation 由实际登记绑定。A 的 48 paths 则只能支持 development 描述，不能当新独立效果。

RAW/stage_B/endpoints/ENDPOINTS.json 要有 training_path_count=240、486 records、双 observer、training_manifest_hashes、source_roles_opened、access、scoring_costs；486 是 240×task/clean 加三个 frozen model 各 task/clean 一次。每个 NPZ 的 bytes/SHA、source_ids、conditions、output hash 与 values 都须通过原 loader，frozen score 重用不增加独立样本。

aggregate RESULTS.json 的 formal_analyses.B.effects 保留全十比较。对 reward 与 audit **分别且同时**，原 field_advantage_thresholds_pass 要求：

- lower CI(field−ordinary task)>0.001；
- lower CI(field−history task)>0；
- lower CI(field−frozen clean)>−0.01；
- 三个固定模型中，field−ordinary 和 field−history 的逐模型 task point differences 均非负。

ordinary_gain_thresholds_pass 另要求两 observer 的 ordinary−frozen task lower CI>0、clean lower CI>−0.01。ordinary 的 pooled 0.005 development target 另报，不能替代独立 B 的统计门。

该 family 使用 8000 paired percentile bootstrap、每 observer 十比较校正；推断条件于三个固定历史模型，不重采样三个模型以冒称模型总体。fixed-taper−field task 与 taper−frozen clean 是同 family 内预登记 secondary effects，不能改比较方向或事后拿掉不利项。点估计正、区间跨零、负效应、retention 未过与两 observer 不一致，都可给出完整负面 disposition。

### 当前 Q 与成本是两套账

bank.value 是 hard_panel 的 terminal reward mean。hard_panel 扣的是固定 generator refinement charge；context.action 按模型固定，所以同 parent 四 training multipliers 的 advantage 中共同项消去。Q 不包含训练 CPU，也不包含 R45 λ‖u‖² 干预 effort。当前 kernel 的 regularized training objective/teacher anchor 也不因此等于 bank 的 terminal utility。最终报告应称“utility label 加独立资源账”，不能称“Q 已计入全成本”。

三种 learned methods 均先执行完整 richer30/margins，再截 H12，并且构造 full-state/history vectors；ordinary 和 fixed_taper 不做这一 measure。因此比较体现当前实现，不是 H12 最低可能成本。当前无净收益不能推到所有优化实现；未实现的节省也不能先算作收益。

零 training multiplier 仍执行 objective、backward、clip、scheduled work 和 guard；只跳过 optimizer.step，momentum 也随之不推进。拒绝或 rollback 保留已发生成本。scheduled_gradient_microsteps、directional_gradient_measurements、optimizer_steps、accepted/rejected/discarded work 必须分别报告。

### 要读取的成本证据及不能相加的部分

| 成本层 | 实际来源/字段 | 读法 |
|---|---|---|
| 共享离线 bank/fit、阶段工作 | A/B stage COMPLETE.costs；C COMPLETE.work；W COMPLETE.costs；R COMPLETE.reconstruction_work；aggregate actual_costs.rows | 共享工作只算一次；R 是额外重建，不伪增原科学样本 |
| 部署 path 成本 | PATHS paths[].costs；formal_analyses.B.costs.arms 和 field_minus_taper_descriptive | 相同 path 的 task/clean ledger 不重复；这些不是含全部离线费用的全研究总成本 |
| 观测/序列化子项 | feature_measurement_*、state_capture_*、state_serialize_*、head_decision_* | feature 内部计时只包 measure_state；后续 vector 组装不能假装已含在该分项 |
| Endpoint scoring | A/B ENDPOINTS.scoring_costs；C ENDPOINTS.scoring_work | 独立报告；不能当训练提升，也不能漏入“总成本”叙述 |
| 新 episode 外层 CPU/wall | 实际 OPS/wait4_launcher/WAIT4_COMPLETE.json 的 total_cpu_seconds_inclusive、wall_seconds、user/system_cpu_seconds、peak_rss_bytes、launcher_cpu_seconds_separate、measurement_scope | 若真实执行后存在才报告；inclusive CPU 不再与内部 stage CPU相加；scope 只含 supervisor 及其实际 waited descendants，不包括外部 root 上传/回读；失败时 unwaited/orphan 成本可未知 |
| 历史工作 | prior_attempt_costs、historical_evidence_tiers、summary-backed projections 与 source descriptors | 分证据层的已知下界，不是全成本上界；旧不可见后续工作、旧 episode CPU 仍未知 |

原统计代码的 admission 明示未在 summarize 中判定；overall_admission 为 NOT_AUTOMATIC。原 net_benefit_policy 还要求 task/retention 与实测 quality-cost Pareto 改善，不能事后选择 utility/CPU 的兑换率让候选过关。可报告条件性 break-even 所需收益，但不能把该条件算成无条件净收益。

历史 lower bound 的明确四层为原 failure receipt 102320、episode02 局部审计576、缺失原 preflight 的公开摘要864、episode03 历史观察78336，共182096。该数字只在实际来源/适配器绑定成立时按其证据等级报告，不在本稿冒充重新核验的 execution 收据；864 不进入 completed_receipt_gradient_microsteps。额外历史工作仍未知，**没有“全部历史成本已闭合”的结论**。本轮 science=0 不能提前加上任何 planned study microsteps。

## 八、P5：interaction、simple effects 与架构边界

### 完整 factorial 的证据人口

C COMPLETE 的既有固定人口为20个 own warmstarts（4 development、16 evaluation）、32 final paths、4 reconstruction audits、52 literal tensor checkpoints。physical_gradient_microsteps=57536，其中 scientific_gradient_microsteps=57152、replay_gradient_microsteps=384。以上为 producer 的完整性目标，不是本轮已执行数。

最终 endpoint barrier 应列 **48 checkpoints**：16 evaluation own warmstarts 加32 final paths，不把4个 development warmstarts当 final efficacy样本。FINAL_ACCESS_FREEZE.json 与 ENDPOINT_CHECKPOINTS.json 必须在 final roles 读取前绑定全人口；C endpoint ENDPOINTS 应有 training_path_count=32、own_warmstart_count=16、96 records、对应双 observer/source配对和 scoring_work。

评估 seeds 801–808，各含 ordinary/dual event law × baseline/field 四臂。两个架构各有自己的 frozen field head；warmup optimizer moments 延续到 continuation，每个架构/seed 的两 policy 从同一个 own warmstart恢复。需读实际 training/trace/hash/active-parameter 证据和 COMPLETE.artifacts，不能把相同参数形状或 requires_grad=True 单独当作真实训练证据。GRU optional arm 当前 disabled，不得以其缺席删除四主臂或事后加入更弱对照。

### 原统计 gate 与具体效果是不同句子

令 utility 越高越好：

\[
\Delta_D=J_{\mathrm{dual,field}}-J_{\mathrm{dual,baseline}},\quad
\Delta_O=J_{\mathrm{ordinary,field}}-J_{\mathrm{ordinary,baseline}},\quad
I=\Delta_D-\Delta_O.
\]

formal_analyses.C.effects 必须一起报告：

- interaction task；
- dual field increment task，即 ΔD；
- ordinary field increment task，即 ΔO；
- dual-field minus ordinary-field task；
- 四个 arm 分别相对自身架构/seed warmstart 的 clean retention effects。

原 booleans 为 interaction_positive_both_observers、all_four_arms_retained_both_observers、interaction_and_retention_thresholds_pass。最后一项只在两个 observer 的 lower CI(I)>0，且四个 clean retention effects 对两个 observer 都满足 lower CI>−0.01 时通过。八比较、8000 paired seed/source bootstrap 和有限八 seeds 的近似解释不能改变。

**该 gate 没有额外要求 lower CI(ΔD)>0。** 最终不能用 interaction_and_retention_thresholds_pass 单独写“field 已改善 dual”。举例仅为逻辑说明、不是本轮结果：ΔD=−0.01、ΔO=−0.02 时 I=+0.01；交互为正但两个增量都负。反向也可能：ΔD为正、ΔO同样正且更大，dual内收益存在但 interaction 不正。

这不构成追加 gate 的授权。保持已登记 interaction 判定，同时用其已有 simple-effect intervals 明确陈述究竟支持哪一句话；全部 seed effects、activity/fallback、retention 与成本仍完整报告。

### 可关闭的阴性结论

可以得到“没有显示 positive interaction”“只有 generic adaptation 有效”“dual内 field 增量未显示为正”“field 在该架构下有害”“retention 不通过”或“同效果下付出更多实现成本”。这些都不需要更换 baseline、扩大 seed、激活 GRU 或调整阈值来挽救。

C 操作差异是 text encoder/decoder 的 sigmoid event 对 FPT CDF/interval-end mean-reset event law，其他 portfolio modules 仍在；learned boundary 未由 task Bellman stopping 求解。因此阳性只支持该受控架构处理在此任务/训练法下的增量或交互。它不证明 literal Call-Put neuron、endogenous free boundary、完整 HJB/FBSDE/NDU 或 LLM-scale 优势。训练时间 minibatch noise 和推理序列内 deterministic mean recurrence 的噪声语义也不能混同。

## 九、最终报告填写模板与诚实边界

实际证据全部到位后，每项按以下顺序报告，不填预期结果：

1. 人口完整性和 source/artifact 身份，注明真实 operation、endpoint、finalizer、supplement disposition。
2. 机制与实际动作：请求、gated choose、accepted/rejected、参数/optimizer 后继、输出差异分别列示。
3. 对应的实际 descriptive metrics 或注册 effects/intervals，保留零、负、ties、inactive 与 observer 不一致。
4. 现有明确阈值的结果；若只是 descriptive priority，写“描述性证据/未识别”，不临时新建 PASS 定义。
5. 实际成本的口径和未覆盖部分；旧历史 FAIL、原资源合同未通过、缺失历史 bytes 与未知后续成本继续披露。
6. 有限结论：支持什么、不支持什么；不以 primary COMPLETE 覆盖 supplement issue，也不以全部文件齐备改写统计失败。

这份文档仍是**准备稿**。所有 P1–P5 的本轮实证栏目仍为“待实际证据”。截至 2026-10-30T03:13:29+00:00 的操作状态基准是：固定提交 51749cfc93452ba7c235543c1529568a75368f2d 的源码发布与实际字节读回已完成，science = 0，当前资源窗口未通过，共享 OOM / OOM-kill 计数为 4 / 4；此处不对该观察之后的执行状态作推断。资源阻断不构成科学阴性，源码发布完成也不代表用户要求的全部科学执行已完成。

## 十、使用的固定来源

- 原科学协议及五项问题：[PROTOCOL.json](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/PROTOCOL.json)、[README](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/README.md)。
- P1/P2：[bank.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/bank.py)、[branching.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/branching.py)、[heads.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/heads.py)、[replay_terminals.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/replay_terminals.py)。
- P3：[witness.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/witness.py)，及本轮已登记 supplements/parameter_field_fullstudy_20261030/postseal_supplement.py。后者的 exact source身份须从其实际登记取得，本稿不虚构新的 publication。
- P4/P5：[analysis.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/analysis.py)、[report_results.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/report_results.py)、[architecture_run.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/parameter_field_fullstudy_20261029/architecture_run.py)。
- 成本实现：[training_features.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/multimodal_output_portfolio/field_bridge_v3_20261027/training_features.py)、[learning.py](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e38a2311c0fd3eecc7f95be00c29be970a3b7a34/experiments/multimodal_output_portfolio/field_bridge_v3_20261027/learning.py)。外层 wait4 与历史成本适配器属于本轮 operational source，按其真实新登记描述，不冒称旧科学源。
- 理论限制：[R45 正文 §2–3、§7](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/sections/r45_main.tex)、[R42 information proof](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/appendix/r42_information_proofs.tex)、[continuation semantics](https://github.com/TrillionniumFoundation/ICLR-2027/blob/f8df0a6075f58f3ab9431a889b773cdf8d6e771d/revision_2026-09-26-r45/technical/u_continuation_target_semantics.tex)。

这些来源用于确认已有判定语义；本稿没有读取任何本轮 scientific payload，没有新运行验证、测试、训练或 endpoint scoring。

