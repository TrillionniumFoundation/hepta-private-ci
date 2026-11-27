# LEARN：固定源码的普通任务装配审计

## 审计范围与结论

审计源码为 `43c7360e2091b752953fb0ed2deb30cbcc416975`，本地根目录为 `/workspace/scratch/14cc5b426fcf/hepta-learn`。本报告按该源码判断；后续 `TrainingNoUpdateV2` 改动尚未计入。并行 native 验证的结果另行绑定其实际源码，本报告不宣称这些测试已通过。

**已有真实训练、持久化、签名读回、CURRENT 发布及普通任务调度组件，但该候选尚无一个可执行的普通入口把全部原始 owner 装配起来。** 这同时包含代码缺口和原始授权/数据输入缺口，不能靠增加启动 JSON 或重跑研究夹具完成。

本次完整普通链的计数如下；零表示本次未建立该验收证据，不否认历史实验执行过真实模型计算。

| 本次验收项 | 状态 | 已建立实例 |
| --- | --- | ---: |
| 同一固定源码的普通 A→Training→独立 B/保留面板→Selection→全新会话 C | `NOT_ESTABLISHED` | 0 |
| 经上述普通链产生的正向采用 | `NOT_ESTABLISHED` | 0 |
| 经上述普通链产生、并由 C 实际使用父版本的正确 NoUpdate/回退 | `NOT_ESTABLISHED` | 0 |
| 完整 daemon 与 Root 都退出、以新进程重启后的整链核验 | `NOT_ESTABLISHED` | 0 |

“独立任务 B”要求任务、信息暴露、评价责任和证据可区分；不要求由不同组织执行。现有角色签名、控制者分离及原始进程能力检查仍必须保留。仅使用不同角色名称或在测试进程中生成多把签名钥匙，不会自动满足这些检查的现实前提。

## 六步覆盖

| 用户要求 | 现有可复用生产机制 | 当前具体缺口 |
| --- | --- | --- |
| 1. 普通 A 完成并产生真实经验 | `AgentdState::execute_circuit_task_record` 重新核对原始 RunStart；有界 Circuit/Cell lane、SQLite 完成历史、原始结果读回和显式 learning outbox。[普通入口](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/state_circuit_task.rs) · [任务契约](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/circuit_task.rs) | `AgentdCircuitTaskInvocationProviderV1`、`CircuitTaskInputProviderV1` 尚无非测试具体实现；普通启动未装配它们。还需要把实际结果发布和原始 Experience/Dataset owner 连起来。 |
| 2. 原始 trainer 形成候选或 NoUpdate | `CellQ24SingleHeadTrainingPlanV1::fit` 执行冻结批次/规则的实际有界整数 SGD；`CellQ24TrainingOwnerV1` 在计算前持久化并锚定 claim，保存候选字节或量化权重未变的 NoUpdate；重开只读同一操作，Pending 不重新训练。[训练](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/cell_composed_q24_training.rs) · [持久 owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/cell_composed_q24_training_owner.rs) | 尚无普通 A 的实际 Dataset→该 owner 的调用装配，也没有该 owner 结果到原始签名 Training 阶段的完整连接。审计源码的迭代协议还不能直接表达 trainer 无候选 NoUpdate；后续版本化改动另审。 |
| 3. 独立 B 与旧能力保留面板 | `CellEvaluationRunnerV1::evaluate_or_readback` 使用原始执行 claim、holdout CAS、实际候选/基线 journal、执行签名；`qualify_and_persist` 与 `read_cell_learning_evaluation_v1` 保留评价和签名责任。[评价](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/neuron_cell_evaluation.rs) · [原始签名读回](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/learning_iteration_evaluation_evidence.rs) | `FinalHoldoutProviderV1`、`ProductEvaluationExecutionAttestorV1`、`ProductQualificationEvidenceSinkV1` 尚无具体产品实现；本次没有实际 B、保留面板、其 owner-held 输入和原始评价签名。 |
| 4. 原始 selector/version owner 决定采用 | `AgentdSelectedGenerationV1::load` 核对签名选择、真实 CURRENT、withdrawal 和不可变 payload；`prepare_agentd_generation_*_v1`、`publish(SignedFinalUseGrant)` 和 `recover_agentd_generation_update_v1` 管理原始版本发布。[选择读入](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/neuron_generation_update_selection.rs) · [版本 owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/neuron_generation_update.rs) | 需要原始 selector 决策、artifact writer/current/withdrawal 能力、确切 FinalUse grant，以及调用这些 owner 的具体阶段装配；不能由 trainer 或适配器自行签出采用结论。 |
| 5. 不同输入、全新会话 C 消费选定版本 | `ReadyAgentdGenerationUpdateV1::into_runtime` 将真正 Published 的原始 journal 交给普通 generation actor；`read_learning_updated_*` / `read_learning_*` 由其真实使用记录生成观察。[运行装配](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/neuron_generation_update_bootstrap.rs) · [运行 owner 读回](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/neuron_generation_learning_runtime.rs) | 尚未把这个 Published owner 交给普通任务 C；现有 Joint CLI loader 产生的是 `Unpublished` 路径，不能替代原始 Selection/NextUse 观察。 |
| 6. daemon/Root 真正冷重启 | 原始 Root handoff、锁定 journal、独立 witness、CURRENT 和同操作恢复机制已存在；过期完整历史的评价读回与独立 30 秒 readback 窗口已补入。[Root 输入](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/root_production_learning_inputs.rs) · [运行恢复](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/learning_iteration.rs) | 本次未执行完整 daemon+Root 进程退出/重启链。Rust 对象 drop/reopen、单独模型 worker 换 PID、重新读取一个结果，都不等于这个验收。 |

## 可执行入口的实际断点

1. [main.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/main.rs) 支持 `--neuron-generation-bootstrap-descriptor`，其 [loader](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/neuron_generation_process_bootstrap.rs) 组装 **Joint GenerationV2** worker；没有 Q24/Circuit 输入和全部 learning stage owner 的命令行装配。
2. 普通 Circuit 使用 `NeuronInferenceControlPort` + `CellInferenceReadbackPortV1` 的 **FeatureV1** 契约；实际 `CellQ24GenerationWorkerV1` 实现 **CellGenerationWorkerV2**。两者输入、状态、计费和恢复绑定不同，不能只换类型名或 manifest digest。[Circuit Cell](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/circuit_cell.rs) · [Q24 worker](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/cell_composed_q24.rs)
3. [model_worker.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-infer-worker-host/src/model_worker.rs) 有通用 `NeuronFeatureDriver` 和 receipt projection，但具体 driver 只在测试中实现。新的桥必须保持原始 durable inference-control claim/readback、原始完整输入和实际 clock/cost 观察；不能把 GenerationV2 未测量的成本填成零。
4. [config_root_learning.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/config_root_learning.rs) 的 `with_root_learning_stage_owners` 需要真实 `LearningIterationStageOwnerPortsV1`；当前具体实现仅在测试中。`production_launcher.rs` 故意在 handoff 已到而 owners 未组装时拒绝启动。这是正确的失败边界，不应绕过。

[runtime.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/runtime.rs) 还要求 learning 配有原始 governed plasticity owner、Circuit delivery 配有普通 Circuit profile。Circuit 与 Generation 服务可以同时配置；但现有 Root launcher 的 Android/Notes/Desktop primary 并不是现成的纯计算 LEARN 装配，其中 Desktop/Notes 有限应用 profile 与 Circuit 明确互斥。新的 host launcher 必须保留原始 Root lanes，明确完成非有限应用的 Circuit/generation/plasticity 装配。

64 请求 registry 的运行机制已在该候选整合；但 `AgentdRootLearningInputsV1` 仍保存一个不可替换的初始操作/冻结 scope，并注册该单个来源。它不是“64 个独立 Root checkpoint 已实际配置”的证据。单操作已足够运行首次 A/B/C 验收。

## 代码工作与原始输入分别是什么

| 可继续自主实现的代码 | 必须来自实际 owner/host 的输入 |
| --- | --- |
| 一个具体、有界的普通任务 Invocation/Input/result publisher，保留完整输入并支持只读恢复 | 原始签名 RunStart、objective/profile、任务原始字节、原始 source/withdrawal 状态；不能以测试常量代替任务事实 |
| 选定 Q24 profile 的真实 serving/control 适配器，接入已有 Circuit 入口；或明确实现另一条保留相同原始认证/owner 责任的任务路由 | 已打开且固定的模型文件、baseline bundle/manifest、原始控制 owner 文件、时钟 epoch、实际计费定义与资源上限 |
| 一个具体的阶段装配器，调用已有训练 owner、原始 evaluator、版本发布和观察 owner | Root sealed handoff、原始注册操作/冻结规则/信任、governed plasticity owner 的原始注册输入；原始证据连接及 pidfd；B 与保留面板、评价冻结方案、holdout CAS、原始签名能力与持久 evidence sink |
| 原始 selector/发布服务的调用适配与进程恢复编排 | artifact writer lease、签名 CURRENT、withdrawal frontier、独立角色的准确 selection 和 FinalUse grant；适配器本身无权制造它们 |

现有 `LearningIterationEvidenceClientV1::from_owner_stream` 会验证原始 stream、pidfd、UID、进程生存期及角色；它没有创建/签发证据的服务端。[证据客户端](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/learning_iteration_evidence_client.rs) 对不同 UID 的要求是该代码的 custody 边界，并不等于要求不同组织或自动证明独立科学评价。

## 最小真实装配顺序

1. 冻结一个具体普通任务 profile、baseline 模型、允许更新范围和评价规则；由原始 host 装配 Invocation/Input、真实 serving/control、Circuit 和全部阶段 owner。最后才启动同一普通 `ObjectiveStart` 入口。当前缺口不能仅靠新增未调用 trait 解决。
2. A 的已提交 Circuit 结果先由原始结果 owner 幂等发布，再由 Experience/Dataset owner 保留准确源数据与撤回边界。训练 owner 在原始 scope 校验后持久 claim，随后执行实际训练；不确定结果留 Pending，不用 NoUpdate 掩盖失败。
3. B 和保留面板由评价 owner 提供；先冻结/消费 holdout，再运行实际候选与父版本，保留两臂原始 journal/cost、签名执行、资格判断和发布。若结果不支持采用，应保留父版本，不强制造出正向实例。
4. 对候选路径，原始 selector 和 artifact/version owner 完成准确选择与 FinalUse/CURRENT；NoUpdate 也需原始父版本选择和新任务发布。可复用 [neuron_v13_generation_update.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/43c7360e2091b752953fb0ed2deb30cbcc416975/codex-rs/hepta-agentd/src/neuron_v13_generation_update.rs) 的实际适配顺序：`revalidate_selection → open exact owners → prepare existing update → publish(original grant) → Ready.into_runtime`。Q24 应复用这些原始 owner，而非另建版本权威。
5. 用不同输入和新的任务/会话分区执行 C，读回其实际 selected bundle、原始输出、private state、commit/ACK；Learning 观察由 Published generation owner 导出，原始证据 owner 返回已有签名。
6. 退出 daemon 和 Root，保留并重新打开原始 journal/CURRENT/witness/control；记录新 PID/start ticks 和原始操作身份，重新鉴权后核对版本、分区状态、输出及不确定副作用。readback 不得触发新的训练、评价或外部效果。此处要求进程冷重启，不另增“整机必须重启”的前提。

## 相邻分支和历史证据的用途

- [#5717](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5717) 的独立 readback 时间窗与 [#5720](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5720) 的完整恢复历史评价检查，解决真实恢复活性问题；它们不是缺失的 evaluator/provider 实现。
- nearby `hepta-cell-kernels` 的 `f46a1371baafc6bec536729b03cbed82b5aa98f1` 添加 Python population/version fence 和新子进程状态测试，没有新增上述 native 普通 owners。`hepta-learning-connection-7380` 的 `93783d4bd8f598d38e56dd5f8b326f0748049ad1` 提供已发布 generation 的只读观察，不产生选择权限。
- [#5724](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5724) 的 `176140c8c4f17204e704a8e9e4ae758f3567fa59` 是纯 Python、只读的 lineage enrollment/update reviewer；它明确保持 `REVIEW_ONLY`，不能计为一次采用。
- [#5509](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5509) 的 SmolLM 实验执行过真实训练并正确拒绝更差候选。其 harness 位于相邻 cell-kernels 树的 `neuron_generation_real_learning_*.rs` 和 `scripts/research/smollm_learning_process_v1.py`，不在本次 abf 派生固定源码中。原实验明示所有签名/custody 为研究夹具、旧评价题已暴露，且 `native_daemon_os_restart=false`。模型资产/driver 可供后续明确限定的研究运行复用；旧结果不可改标为本次普通入口、独立 B 或 daemon+Root 冷重启验收。

## 后续源码独立复核（不改写上述验收计数）

在隔离 clone `/workspace/scratch/14cc5b426fcf/hepta-learn-trainer-no-update` 复核了 `6e734460abd` 与 `15c687e928c`，未发现需要修正的安全缺陷。前者新增只适用于冻结 scope 的 `TrainingNoUpdateV2`，保留 Generator/Selector/Observer 分离及旧 checkpoint 字节，并拒绝新旧 header 降级；后者从原始锚定完成记录读取私有字段的 Q24 观察，不创建时间戳、签名、claim、训练或 CURRENT 发布。这补齐了第二步的协议表达和只读观察转换，仍未提供普通入口的全部 owner 装配。该复核仅为源码审查；这两个 commit 的 native 结果须由实际执行另行证明，不能沿用 `43c7360` 的结果。


## 本轮固定候选的公开映射

后续协议与原始训练观测适配已合入固定候选 `1b49f8746ec48a333c34f8a00a693c18248709fb`。独立复核的 `6e734460abd` 对应公开提交 `a2b52088639a6fbbc3a1f996968b3122934972cd`；`15c687e928c` 对应 `1b49f8746ec48a333c34f8a00a693c18248709fb`。编码格式的源码变异测试采用 `d6f5eca616cc1541e54fb76c3126d470aa9bde54` 的完整严格检查。

该候选原生学习切片 161/161、实际 EUID 0 Root 组件 6/6、源码变异检查 50/50，以及全仓调用闭集检查均通过。它们验证本报告所述训练/NoUpdate/恢复组件；六步普通任务验收的四项计数仍为 0。精确源码、维护后的版本和原始证据索引见同目录 `RESULT.json` 与 `ARTIFACTS.json`。
