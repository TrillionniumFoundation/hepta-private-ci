# LEARN：普通 Q24 任务之后的原始 owner 装配边界

## 本文范围

本文记录源码接口、实际输入和责任边界，不替代本轮结果文件，不给出测试通过数、整链验收状态或真实部署结论。只读审查锚点为 `0ba5513f4eefc3e6959db58b0f39efcc714804f5`；下列相对链接指向合并后相同文件，函数和类型名用于定位。

目前可以把原始 source、受 CURRENT 保护的 Cell、真实 Q24 Feature/control 和普通 Circuit 入口具体装配起来。Q24 训练 owner 也可以保存实际改变后的权重或明确的量化权重未变结果。但 **现有 `LearningIterationStageOwnerPortsV1` 没有把这些 owner 接成完整生产实现**；正向候选还遇到真实评价材料与 Proposal 生成规则两个结构边界。增加一个转发回调的实现，不会提供缺失的原始证据。

本轮普通入口用例中的 ObjectiveStart、训练计算、文件 journal、CURRENT 和新任务消费都是实际执行路径；其 issuer、artifact selection 和实验目标仍由明确标注的测试夹具提供。不能把这类选择签名改称原始独立 Selector 的采用决定，也不能从训练损失下降推出任务 B 或保留能力面板已经通过。

## 逐段接口和缺少的真实输入

### 1. 普通 A 的入口、原始输入与结果

已实现的生产装配入口是 [circuit_q24_task_profile.rs](../../../codex-rs/hepta-agentd/src/circuit_q24_task_profile.rs) 的 `circuit_q24_task_channel_v1`，由 [config_q24_circuit_task.rs](../../../codex-rs/hepta-agentd/src/config_q24_circuit_task.rs) 的 `AgentdConfig::with_q24_circuit_task_profile` 调用。它消费原始 host 提供的文件、独立 witness、实际 `DurableInferenceControl`、完整模型、冻结 Cell/Circuit 配置和已发布的 `PublishedCircuitFeatureTaskV1`。

`DurableCircuitTaskSourceV1` 保留完整原始 RunStart 和实际 CellStepInput。operation ID 来自原始 Circuit dispatch；输入先持久化，之后才进入 Cell admission。`CircuitTaskSourceReadbackV1::read_run_publication` 只读已完成的真实结果并核对当前 withdrawal/witness。完整源记录、已提交 Cell 决策和实际模型 bundle 都可供后续 owner 校验，不需要重新构造一个任务完成事实。源码见 [circuit_task_source.rs](../../../codex-rs/hepta-agentd/src/circuit_task_source.rs) 及其子模块。

仍缺的生产启动输入是原 host 持有的 sealed task、source 文件与模型 profile 的提供者。[production_launcher.rs](../../../codex-rs/hepta-agentd/src/production_launcher.rs) 的 `AgentdProductionLaunch::run` 先调用 `require_root_learning_assembled`；现有启动 primary inputs 不会自行产生这套 Q24 profile。可执行的 Config/factory 路径不等于 CLI 已安装它。不能删去这个启动拒绝条件，或换用无 Root 能力的普通 writer 来增加 caller 数量。

### 2. A 的真实经验到 Dataset

`CircuitTaskSourcePublicationV1` 是真实任务输出的证据，但它不是签名 Dataset，也不会把一个调用者提供的目标值变成真实监督标签。

原始生产 ledger 已有 [hepta-learning-ledger/src/production.rs](../../../codex-rs/hepta-learning-ledger/src/production.rs) 的 `LedgerWriter::append_decision`、`append_outcome`、`freeze_dataset`、`read_dataset_records` 和 `revalidate_dataset_snapshot`。`freeze_dataset` 核对原始 Evaluator 对准确 ledger/plan 的签名；源记录、纠正与撤回 cut 从当前 ledger 派生。读取冻结记录时仍检查当前源的可用性。

最短有效接线需要以下原始输入，而不是另写一个 digest：

- A 的 sealed source publication 与原始 decision/outcome 身份和签名来源。
- 已激活的 learning trust、原始 ledger/witness，以及真实 Dataset freeze plan 和其签名。
- 在训练前冻结的 source-record→Q24 input/target 转换规则。目标值的来源、量纲、缺失结果处理和样本范围必须有原 owner 证据；不能在看到候选表现后选取目标。
- Dataset、batch、update rule、选定父模型和原始 Learning request 的准确绑定；每次实际训练/读回/使用前维持源撤回检查。

现有 Q24 batch 构造器只保证规范字节和范围，不证明来源。[cell_composed_q24_training.rs](../../../codex-rs/hepta-agentd/src/cell_composed_q24_training.rs) 的 `CellQ24TrainingBatchV1::new` 明确保留这一边界。普通 A 的实际输入已经可取；其被原 Dataset owner 接纳及对应的真实 target 材料尚未由本轮生产启动提供。

### 3. 原始 Training 和明确 NoUpdate

可直接复用的具体调用顺序为：

1. [cell_composed_q24_training_plan.rs](../../../codex-rs/hepta-agentd/src/cell_composed_q24_training_plan.rs) 的 `CellQ24SingleHeadTrainingPlanV1::from_dataset_cut` 核对原始 Dataset cut、FrozenLearningScopeV2、父模型和准确更新规则。
2. [cell_composed_q24_training_owner.rs](../../../codex-rs/hepta-agentd/src/cell_composed_q24_training_owner.rs) 的 `CellQ24TrainingOwnerV1::create/recover` 保留原 journal/witness；`fit_or_readback` 在计算前持久 claim，保存实际 heads 或 NoUpdate。原 Pending 不重新训练。
3. [cell_composed_q24_training_observation.rs](../../../codex-rs/hepta-agentd/src/cell_composed_q24_training_observation.rs) 的 `read_learning_observation` 从原始锚定完成记录导出私有字段的无签名观察，保留实际 steps、elapsed 和完整结果绑定。

这个观察不会新造完成时间或签名。真正的 Training receipt 仍须由已授权的原 Generator evidence owner 读取该结果、保留其原始时间并签名；恢复时只能返回原签名。训练 owner 也不拥有 Dataset/Selector/Observer 的职责。

`TrainingNoUpdateV2` 只证明 `QuantizedWeightsUnchanged`。它保持 candidate 为 None，跳过不存在的 Evaluation/Proposal，仍要求原始 Selection 和真正保留父版本的 NextUse。它不能代表训练失败、超时、Pending、无法鉴权或评价结果未知。协议和角色校验见 [learning_iteration_auth.rs](../../../codex-rs/hepta-agentd/src/learning_iteration_auth.rs) 及 [hepta-learning-artifacts/src/learning_iteration.rs](../../../codex-rs/hepta-learning-artifacts/src/learning_iteration.rs)。

### 4. 独立任务 B、旧能力保留面板与实际评价

现有具体评价路径是 [neuron_cell_evaluation.rs](../../../codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs) 的 `freeze_cell_learning_evaluation_plan_v1` → `CellEvaluationRunnerV1::evaluate_or_readback` → `qualify_and_persist`。随后 [neuron_cell_learning_evaluation.rs](../../../codex-rs/hepta-agentd/src/neuron_cell_learning_evaluation.rs) 的 `prepare_cell_learning_evaluation_v1` 把原始签名资格结论绑定到准确 Training predecessor。

这条路径需要真实候选和 fixed-expert 的 `CellGenerationJournalV2`、冻结 product/temporal plan、原始 holdout CAS、`FinalHoldoutProviderV1`、执行结果 store、执行签名 owner，以及原 qualification 签名和持久发布 sink。`TemporalComparisonInputsV1` 要求实际训练样本、held-out targets、候选/父版本 OPE rows、cluster assignments、snapshot/future-window 身份；这些不是把普通任务输出 hash 一次即可得到的数据。类型和原执行流程见 [hepta-intelligence-eval/src/product_runner.rs](../../../codex-rs/hepta-intelligence-eval/src/product_runner.rs) 与 [product_execution.rs](../../../codex-rs/hepta-intelligence-eval/src/product_execution.rs)。

本轮增加的 [neuron_cell_evaluation_owner.rs](../../../codex-rs/hepta-agentd/src/neuron_cell_evaluation_owner.rs) `OriginalCellEvaluationExecutionOwnerV1` 可以消费 host 已经授权的 Evaluator key，并只为 native runner 构造的 sealed execution request 持久签名。它不创建 trust，不提供 B/保留面板，不替代 `SignedEvaluationEvidenceV1` 中的 Generator-plan 与 Evaluator-bundle 原始签名，也不替代 `ProductQualificationEvidenceSinkV1`。审查源码中 `FinalHoldoutProviderV1` 和 qualification sink 的具体实现仍在测试支持代码中。

另有两个不能由适配层补数的约束：

- [neuron_cell_evaluation_contract.rs](../../../codex-rs/hepta-agentd/src/neuron_cell_evaluation_contract.rs) 的 `CellComparisonContractV1::validate` 要求两臂容量、累计训练预算和 selective-update policy 完全相等，fixed expert 的结构保持不变，并要求完整的非零训练观测。原父模型的真实累计训练记录不能用本轮 SGD 的预算复制出来。
- 同文件 `CellEvaluationArmRecordV1::read` 只接受实际 drained 的 GenerationV2 journal；必须没有 missing cost stages，没有 Unknown outcome，且所有必需成本项都不能有 unknown entries。当前 contract 必需 Wall 和 CPU。普通 Feature 的真实执行记录在 Cell/control/source；供 CURRENT 使用的 GenerationV2 journal 不因此自动获得一份真实全阶段成本 ledger。现有 [cell_composed_q24.rs](../../../codex-rs/hepta-agentd/src/cell_composed_q24.rs) `CellQ24GenerationWorkerV1::execute` 仅给实际 inference wall interval，其 CPU 保持未知；Feature 的 latency/queue/内存容量统计同样不能转换成已测 CPU。把 `None` 写成 `Some(0)` 会伪造测量事实。

最短保持现 contract 的 B 接线，需要原评价方提供独立冻结材料和 retention/unlearning receipts，并在实际候选/父版本执行及所要求的各阶段记录真实 wall/CPU，保留匹配预算的原训练证据，再运行原 holdout/qualification owners。若要让 ordinary Feature journal 成为另一种评价输入，必须设计和登记新的明确评价 profile，说明其实际成本与比较约束；不能把旧 profile 的严格要求静默删掉。

独立性要求任务、信息暴露和证据责任可区分，并保留现有 Generator/Evaluator/Selector 的 controller 分离。它不要求不同组织。训练 loss、先前暴露过的题目和夹具选择结果不替代这项独立评价。

### 5. Qualified 候选到原 Proposal

这是正向 Q24 路径当前最明确的类型与算法边界。

[learning_iteration_ports.rs](../../../codex-rs/hepta-agentd/src/learning_iteration_ports.rs) 的 `LearningIterationProposalPayloadV1` 只有 `Parameter(ParameterPlasticityProductRequestV1)` 和 `Topology(TopologyPlasticityProductRequestV1)`。[learning_iteration_proposal.rs](../../../codex-rs/hepta-agentd/src/learning_iteration_proposal.rs) 的 `submit_iteration_proposal_v1` 校验原 operation、父模型、Dataset、update rule、窗口与角色后，只能调用原 `AgentdState::submit_parameter_plasticity_v1` 或 `submit_topology_plasticity_v1`。Proposal receipt 来自原 anchored owner 的真实 composition digest；阶段 provider 无权自造它。

Parameter 并不是任意模型权重差分的通道。原 [hepta-plasticity/src/generator_v3.rs](../../../codex-rs/hepta-plasticity/src/generator_v3.rs) `generate_parameter_candidates_v3` 生成完整候选集：NoChange 加每个允许 scale 下的 `eligibility × modulator × learning_rate × scale`，经过精确范围、mutation policy 和 trust-region 检查；每层上限为 5,000 ppm，全局为 2,500 ppm。`verify_generated_parameter_candidates_v3` 重新生成并检查完全相等的集合及 candidate IDs。

实际 Agentd [plasticity_owner_evidence.rs](../../../codex-rs/hepta-agentd/src/plasticity_owner_evidence.rs) 的 `PlasticityDynamicOwnerEvidenceResolverV1` 从原 `NduProjectionJournalV1`、`SparseJournal` 和已注册 broadcast Policy 取得源事实；`resolve_parameter_signal` 重新计算 eligibility、modulator 和信号摘要。[plasticity_host.rs](../../../codex-rs/hepta-agentd/src/plasticity_host.rs) 的 `propose_agentd_plasticity_v1` 在提交时重新读取原 artifact/ledger frontiers，要求完整 admission 与这些事实一致。抽象 Parameter 类型不限定模型家族，但现有具体 owner 和 V3 生成规则确实要求这些来源。

现有 Q24 单行 SGD 的最终 heads 和 Model manifest 不是该 V3 生成器的输出。把 SGD delta 放进 eligibility、把 modulator 设成常数、给它补非零摘要，或把 Model artifact ID 当作 V3 content candidate ID，都不能通过真实源证据的含义校验。Topology 路径要求真正结构变更及其原始证据；单行 heads 更新也不具备这个含义。

因此 Qualified→Proposal→Selection 不能通过跳过 Proposal、伪造 `composition_digest` 或把测试 artifact selector 放到阶段实现中闭合。

### 6. 原 Selector、版本发布与全新任务 C

[neuron_generation_update_selection.rs](../../../codex-rs/hepta-agentd/src/neuron_generation_update_selection.rs) 的 `AgentdSelectedGenerationV1::load` 已支持真正的 Model artifact：完整 canonical manifest payload、原 artifact registry、已签 selection、当前 trust/withdrawal 都需匹配。原 generation prepare/publish/recover 继续要求原 CURRENT、前序完成、目标 scope 和 `SignedFinalUseGrant`。完整 Q24 bundle/manifest 的对应关系由实际 Feature factory 再校验。

这说明 Q24 改变后的 heads 可以经现有版本 owner 进入普通 C；它不说明 Learning Proposal 已经存在。测试中调用 fixture artifact selection 可以验证发布/消费机制，不能填补原 Selector 决策。

[circuit_feature_current_learning.rs](../../../codex-rs/hepta-agentd/src/circuit_feature_current_learning.rs) 的只读 Selection/NextUse 观察由真实已发布 CURRENT、源结果和私有 Cell 完成记录派生；不接受 caller 提供的 use/cutover digest。原学习签名责任仍独立存在。正向更新的 operation 必须绑定原 qualified Proposal decision head，见 [neuron_generation_update_adopted_learning.rs](../../../codex-rs/hepta-agentd/src/neuron_generation_update_adopted_learning.rs) `learning_updated_task_operation_id_v1`。

原 `PublishedCircuitFeatureTaskV1` 持有显式 retirement 权限；对外 Observer 的 `PublishedCircuitCellOwnerV1` 和 `CircuitTaskSourceReadbackV1` 不持有 Cell commit、source withdrawal 或版本 drain 写口。新 C 要有自己的原始 task/run、不同输入和真正 successor publication。

### 7. 冷恢复与进程 custody

[circuit_feature_current_recovery.rs](../../../codex-rs/hepta-agentd/src/circuit_feature_current_recovery.rs) 通过已恢复的真实 successor CURRENT 和签名 previous binding，只读原前序 source/Cell 文件以重建 sealed completion。`CellOwnerJournalReadbackV1` 只接受非空、完整、已由原 witness ACK 的历史，不修复 torn tail、不补 witness、不创建 Cell writer。它补的是不保留进程内 completion token 时的历史读回。

这一机制不能等同于 daemon 与 Root 两个原始 OS 进程的冷重启。实际验收仍需原进程 owner 的启动能力、退出/重启证据、新 PID/start ticks 和重新鉴权，之后检查准确 CURRENT、private state、原任务和不确定效果。`AgentdConfig::load` 的 Starting/generation 检查以及原 Root handoff 不能为了重开测试而放宽。

## 完成正向链的最短协议选择

两种选择都保持原 Proposal 和独立 Selector 的责任边界。必须先由原 owner 选择并冻结一种；不能在已经注册的学习窗口内偷偷更换训练算法或候选解释。

| 选择 | 可以复用 | 必须新增或提供 | 不能声称 |
| --- | --- | --- | --- |
| 明确的 Q24 Model proposal owner/profile | 现有 Q24 冻结 SGD、真实 Training 结果、独立 Cell evaluation、Model artifact/CURRENT/FinalUse 和普通 C | 新的版本化 Model proposal admission 协议与原 owner 注册；严格绑定实际 trained heads、完整候选/父模型、冻结规则和 Dataset、原签名评价、mutation scope、撤回/当前 frontiers；原 Proposal owner 持久提交并返回可读回的真实 composition receipt | 新增枚举变体本身就是一个有权限的 Proposal owner；复用测试 selector 即已采用 |
| 真正接入现有 Parameter V3 训练路径 | 原 governed Parameter proposal runtime、原 NDU/Sparse evidence resolver、V3 候选完整性检查和独立评价 | 原 NDU/eligibility/broadcast/mutation Policy 材料；在训练前明确登记 Q24 row→parameter 的映射与量化规则；由实际 V3 候选集生成/执行模型，并精确对应 delta、candidate ID、训练 receipt 与 manifest | 把当前已完成的冻结 SGD 候选事后包装成 V3；改 scope 或伪造 modulator/eligibility 来让它恰好通过 |

若保持本轮已冻结的 Q24 SGD，第一种选择更直接，但它是一个有审核边界的新 Proposal 协议，不是本轮能靠连接现有接口安全补齐的小改动。它应在新的原始 Root 注册中显式开启，旧 Parameter/Topology 路径和旧请求保持原义；未知 profile 一律拒绝。仅在 Proposal owner 真正落盘并获得独立 anchor ACK 后，才产生原 Proposal receipt，之后仍由原 Selector/版本 owner 决定采用。不能把 Proposal 写入权交给训练或评价代码。

第二种选择能保留现有 Proposal 协议，但必须改变候选生成来源并重新冻结实验。要保留本轮的单行 SGD 算法，还需要实际证明它的每个候选与 V3 生成器及所有原信号完全一致；当前材料没有这一证明。只做整数类型转换不解决来源和生成规则差异。

## 可以有界实施的下一批交付

在原 host 提供材料后，可按以下独立交付收口；每一步都应产出实际 owner 的具体实现与行为证据，不增加无调用者的 callback 层：

1. **真实 Dataset producer 与 batch materializer。** 从 sealed 普通 A 和原 ledger 取真实记录，按原冻结规则形成 batch；撤回、错源、目标替换必须在训练 claim 前失败。输入是原 ledger、签名 Dataset freeze、规则和数据，而不是新建可信 principal。
2. **真实 B/retention provider 与成本记录。** 原 holdout 消费之后才释放冻结材料；实际两臂执行并保留完整原 journals/cost/training history；采用现有原执行签名 owner、资格签名及 durable sink。未知 CPU 或不匹配预算明确拒绝，不能改为零或复制另一臂。
3. **原 owner 选定的 Proposal 路径。** 按上表的一种协议形成真实 admission/commit/readback。先关闭这一结构边界，再实现接受 Qualified 候选的完整 `LearningIterationStageOwnerPortsV1`。
4. **同一生产启动的具体装配。** 原 `AgentdRootLearningInputsV1::into_learning_runtime` 和 `AgentdConfig::with_root_learning_stage_owners` 消费原连接、冻结 scope 和已激活 trust；具体 stages 持有前面真实 owner，recover 只读原结果与当前撤回/授权，最后安装同一普通 Q24 profile，再进入原 launcher。源码见 [root_production_learning_inputs.rs](../../../codex-rs/hepta-agentd/src/root_production_learning_inputs.rs)、[config_root_learning.rs](../../../codex-rs/hepta-agentd/src/config_root_learning.rs)。

真正 trainer NoUpdate 可先完成较小的五阶段分支：Experience→Dataset→TrainingNoUpdateV2→Selection→RetainedNextUse。该分支不需要不存在的 B/Proposal，但仍需要真实 A、原冻结 batch/rule、原 Generator 签名、原父版本选择和新 C 使用；不能预制一个 NoUpdate 结果来替代训练。它只能贡献用户要求的 NoUpdate 实例，不能替代正向采用实例。

在本轮已检查的 host 范围内，没有取得上述原始 LEARN custody 和冻结实验材料。这个事实限定现实验收，不是否认这些接口能够由持有原始能力的 host 装配。代码可以验证并消费原 capability；本轮不能自行生成新 key、签名、质量结论或 source labels 来冒充原输入。
