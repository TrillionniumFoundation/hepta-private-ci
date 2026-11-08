# 普通 daemon 学习闭环：生产接线缺口与最小实施顺序

状态：**HOLD**。本文件是工程交付和源码核查，不是 S0–S5 资格证据，也不声明普通 daemon 已完成学习闭环。

## 1. 结论与源码边界

现有代码已经提供真实的模型选择、原始 CURRENT 发布、V13 后继代安装和实际任务消费读回。缺失的是把这些 owner 与学习阶段生产者接到普通 daemon 的合法资源工厂。当前没有非测试的 `LearningIterationOwnerPortsV1` 实现，普通 `main.rs` 也没有调用 `with_learning_iteration_bootstrap`。[S01–S06]

本轮不新增只转发 digest 的 wrapper，不创建 Root 注册、签名密钥、学习资格 authority 或替代 CURRENT。没有原始生产资源时，新增配置开关不能建立闭环；现有拒绝应保留。

源码读取与验证严格分开：

| 记录 | 精确身份与含义 |
| --- | --- |
| 共同起点 | `1eb72a1131285f5de98beeb7c95a27eab72d647e` |
| HCSN/PQ 合并目标 | `9aa9fa75f74ad7a15c3a3db36586502f0215aff0` |
| 主体源码读取时 HEAD | `d3be1bbb66512ad74b3b7d530ccf9c73c9049a09`；当时另有合并中的工作树内容，不能把所有文件都称为该提交的 blob |
| 后续关系检查 | `12339332c3a49becb0519230436be4c086478ce6`；`1eb72`、`9aa9`、MEM、VERIFY、checkpoint 集成提交均为祖先，未合并路径为空 |
| 后续逐文件核对 | 在 `bd07b4b15f23ebcbf3fd0e0371f3f587af94622c` 前后 HEAD 相同；此前缓存的 50 个文件全部 SHA-256 相同，缺口结论未因这次合并变化 |
| 补充 issuer 源码 | 在 `12339332c3a49becb0519230436be4c086478ce6` 读取 `deployment_issuer.rs`，另存精确文件摘要 |
| 最终共同候选 | **由后续 native receipt 绑定**；上述读取、祖先检查和摘要核对均不等于最终候选通过测试 |

伴随 JSON 保存全部 51 个读取文件的 SHA-256、Git blob、读取时 HEAD，以及可复核的关键源码位置。工作树文件摘要是本审阅的依据，不能仅凭 HEAD 推断其内容。

## 2. 已存在、可以直接复用的真实采用链

以下都是现有生产 API；调用者必须先合法持有括号中的资源。[S13–S21、S26、S32]

1. `LearningArtifactOwnerService::open`：消费原始 artifact trust、writer lease、CURRENT head 要求、已认证的 withdrawal registry 和 storage binding；恢复旧操作，拒绝冲突。它不是签名器。
2. `AgentdSelectedGenerationV1::load`：消费上述 owner、`ArtifactSelectionVerifierV1`、原始 `SignedArtifactSelectionV1`、真实 registry snapshot/payload 文件。它验证当前注册表、签名、Model 类型、规范化完整 manifest、兼容性和 withdrawal scope。
3. `AgentdGenerationUpdateAuthoritiesV1::new`：保留真实 artifact owner、带独立回滚 frontier 的原始 `FinalUseAuthority` 和既有 authority clock。兼容模式或丢失外部 frontier 会失败。
4. `NeuronGenerationCurrentOwnerV1::open`：重开原始 Root custody 下的 CURRENT，不在缺失时自动初始化。配合真实旧 journal、停止/ACK/drain 证明、新 V13 文件与配置，调用 `prepare_agentd_v13_generation_update_v1`。
5. 对准备结果的精确 `final_use_binding()` 请求**原始外部授权**，再调用 `publish(&SignedFinalUseGrant)`。绑定目的地明确区分 `agentd.cell-generation.replace`、`replace-drained` 和 `next-task-same-model`，不存在泛化的“已允许学习”授权。[S22]
6. `ReadyAgentdV13GenerationUpdateV1::into_runtime` 保留实际 worker、control、clock、journal、CURRENT 和 publication，记录实际准备成本，再进入普通 `run` / `run_with_shutdown` 运行体。
7. 已发布 actor 的 `read_learning_updated_selection` / `read_learning_updated_next_use` 读回原始发布及真正提交的后继任务；读回要求不同 task/run、精确 bundle/manifest、连续 generation/writer epoch，以及当前 withdrawal/FinalUse/CURRENT 检查。没有提交的任务不会产生 NextUse。

这条链可以供已有可信嵌入式 host 组合使用；当前普通二进制没有交付上述资源的 factory。本审阅也没有发现可直接使用的真实生产 candidate、独立评估、选择签名和对应 replacement grant。

`examples/neuron_v13_guarded_acceptance/authority.rs` 明确使用公开 fixture key，并本地创建 qualification frontier。它证明组件可运行，不构成可复用的生产 issuer。[S30]

## 3. 缺口映射

### D01：普通入口没有具体学习 owner 和请求来源

**源码：** `main.rs`、`config.rs`、`learning_iteration.rs`、`learning_iteration_ports.rs`。[S01–S04]

`AgentdConfig` 默认 `learning_iteration_bootstrap=None`。`with_learning_iteration_bootstrap` 只验证 agent/spawn identity、拒绝重复配置并保存 capability。`learning_iteration_channel_v1` 要求固定 trust、bounded queue 和完整 owner ports；它不创建这些 owner。唯一实现位于 `learning_iteration_runtime_tests.rs::IterationPorts`。

需要合法提供：具体五方法实现、原始 stage owner 结果、固定学习 trust、已注册 checkpoint、plasticity owner，以及来自真实已完成任务的请求生产者。工厂必须保留 handle，并将其生命周期、队列和 shutdown 接入 daemon；创建后丢弃 handle 不会产生真实迭代。

当前边界：未安装时没有学习执行通道；身份不同为 `GenerationFenced`；没有就绪的 plasticity admission 为 `Unavailable`；队列关闭为 `Unavailable`；失去提交确认或超时为 `CommitUncertain`。不能把一次普通任务完成自动解释为学习候选已生成。

### D02：checkpoint capability 不能从配置路径或现有五 lane 推导

**源码：** `LearningIterationCheckpointOwnerV1::from_registered`、`AgentdRootProductionInputs`、`HostAuthorityPublicBootstrapV1`、`HostAuthorityServiceConfig`。[S07–S11]

checkpoint 已有真实 CAS 实现，但构造参数是原始 `HostAuthorityFrontierStore<LearningIterationCheckpointRecordV1>`，不是一个目录名。它固定精确 request/owner set，恢复快照只恢复数据，仍要重新认证当前签名。缺失、异域、损坏、冲突或不确定数据不能初始化新 genesis。

普通 Root handoff 固定 observation、issuer、Cognitive checkpoint、Device frontier、Notes frontier 五 lane。它没有 LearningIteration checkpoint 注册/消费通道，也没有该具体 Root store capability 的交付。原有 Cognitive checkpoint 的语义和固定 owner 不能改名当学习 checkpoint。

最小生产改动：由原始 Root 在独立回滚域持有**已合法登记**的学习记录，提供按固定 owner/request 绑定的 typed load/CAS/readback；客户端验证原始 peer、identity、deadline、大小、CAS predecessor 和 durable acknowledgement。现有生产构造函数仅接收具体 Host store，因此跨进程接入还需要经过审阅的受保护 transport/constructor 演进。普通 Agent 不能从可序列化 JSON 恢复写权限，也不能选择任意 owner。

当前边界：checkpoint 的 `WrongScope`、`Conflict`、`Capacity`、`CommitUncertain`；Root handoff 的版本、固定 lane、原始 peer/identity 校验。不能新建私有目录或新 Root 注册来消除这些错误。

### D03：学习阶段 attestation 与 FinalUse 是不同证据

**源码：** `learning_iteration_auth.rs`、`learning_iteration_ports.rs`、`authority_host_service.rs`、`deployment_issuer.rs`。[S04–S06、S10、S12]

学习验证签名的精确 payload 是 `learning_iteration_receipt_signing_bytes_v1(receipt)`。Training 需要 Generator，Evaluation 需要 Evaluator，Selection 需要 Selector，Experience/Dataset/NextUse 需要 Observer；同时检查 principal、固定 trust、objective 和训练/评价/选择/消费之间的 actor separation。恢复历史也重新认证当前资格。

**已有 FinalUse 运输可以复用。** Root 的 `runtime.agentd.production_operation` 接收精确 binding，原始 issuer 仅在已登记的 subject、destination、scope policy 全部匹配时签发；不匹配返回无 grant / `authorization_denied`。这不等于已存在允许 Cell replacement 的生产 policy。

该 issuer 请求枚举没有学习阶段 receipt 的签名操作。现有 LearningEvidence verifier、public-key descriptor、artifact selection 签名、dataset 证明和 consumed FinalUse witness，均不能转换成对另一个 payload 的学习签名。

最小生产改动：各实际 producer/evaluator/selector/observer 在自己已获授权的身份下重读原始结果、绑定完整 receipt 后输出签名；Agentd 只消费结果。若当前部署没有这种原始签发服务或 receipt 输出，必须增加被原 trust 授权的生产协议，不能增加“签调用者 digest”通用端点、fixture key 或本地临时 trust。独立评价与选择身份必须保持分离。

### D04：普通 generation descriptor 与已发布学习 readback 之间未连接

**源码：** `main.rs`、`load_neuron_generation_process_bootstrap_v1`、`neuron_generation_channel_v2`、`GenerationLearningPublicationV1`。[S01、S16–S18]

当前普通入口载入 descriptor 后调用 `neuron_generation_channel_v2`，它构造 `Unpublished` actor。该 actor 的学习读回拒绝：`GenerationFenced("generation actor has no original learning publication")`。

真实 `Published` 分支只有在原始 `ReadyAgentdGenerationUpdateV1::into_runtime` 路径才安装。需要原始 CURRENT、artifact owner、selection、被消费的 grant、旧新真实 journals 和 V13 backend；它们不能从 descriptor 上的 bundle digest 重建。

最小生产改动：将合法持有这些资源的 bootstrap factory 接到普通启动组合，并通过既有 Ready 类型安装 actor。若普通进程不能合法持有 Root CURRENT，则先实现原始 Root 的 typed CURRENT 协议及等价 fencing/readback，再演进具体 owner constructor。不得把 `Published` 字段加入可自行填写的 descriptor。

### D05：HCSN training publication 还不是完整 CellBundle 的有效装载证明

**源码：** `automation_hcsn_pq.rs`、`prepare_hcsn_publication_v1`、`CellCompatibilityBundleV1`、`neuron_generation_update_adopted_learning.rs`。[S23–S26、S21]

HCSN schema 3 已能验证 PQ deployment 签名、固定 Python/源代码 inventory、supervisor 与原有 FinalUse；`prepare_hcsn_publication_v1` 核对真实 handoff/receipt/payload、训练绑定、dataset、runtime、generation，再由真实 artifact writer 发布。这些能力可复用。

generic CellBundle 还包含 base、organ/cell adapter、heads、composition、encoder、tokenizer、normalizer、calibration、numeric profile、输出/状态 schema 和 state semantics。现有 V13 learning reset 读回明确只比较语义相同的 schema/declared encoder，以及完整 bundle/manifest identity；它不定义 base/adapter composition 到有效权重的映射，也不执行通用 `CellBundleCutoverPlanV1`。

最小生产改动：先选定一个明确受支持的真实训练/后端 profile，定义所有组件的实际 byte provenance、加载规则和 reset 语义；若采用完整平面权重，应显式限制不支持的 adapter/composition。训练产物必须经同一实际 loader 验证并在实际执行中可读回有效权重身份。当前没有该映射时拒绝不支持的 profile，不能把 terminal tabular operator、一个 HCSN checkpoint digest 或更新的 manifest 字符串当作已装载 generic CellBundle。

### D06：真实 Experience / Dataset / Evaluation / Proposal 生产组合仍缺

**源码：** `learning_iteration_ports.rs`、`learning_iteration_proposal.rs`、`CellEvaluationRunnerV1`、MEM 当前上下文与 learning sink。[S04、S27–S29、S31]

`CellEvaluationRunnerV1` 可以消费原有 final-holdout CAS/provider、真实 candidate/fixed-expert journals，进行冻结比较并持久化资格。但 `qualify_and_persist` 仍要求原始 `SignedEvaluationEvidenceV1`、timing、LearningEvidence verifier 和 durable qualification sink；结构验证不会产生独立评价身份。

MEM 的 `CurrentMemoryRetrievalContext` 要求生产者验证当前模型、prompt、encoder、compact、authority、profile/engram generations；当前普通入口没有其生产实现或安装。`CognitiveRetrievalLearningSink::new(LedgerWriter)` 要求真实 writer，并不从 caller digest 建立 task success。这两项不能自动填满通用学习阶段。

`prepare_proposal` 必须从实际 artifact/evaluation stores 解析精确 signed proposal set。已有 proposal 提交器核对完整候选、训练 lineage、operation、window、grammar、原始 generator/evaluator attestations，再走已锚定 plasticity owner。

需要补齐：任务完成与删除/撤权的当前读回；冻结数据实际 bytes 与 provenance；stable training job 的 reconcile；独立 evaluator 的真实比较；精确 signed proposal 解析。不存在源结果时返回 `OwnerUnavailable` / validation error；不确定训练/提交返回 `CommitUncertain`，不得创建新 job 重新训练。

### D07：运行 profile、成本与验收不能由组件测试推导

**源码：** `require_finite_notes_profile`、学习 runtime deadline/恢复、V13 backend preparation 记录。[S02、S03、S20]

finite Notes profile 明确拒绝与 learning、terminal、neuron、plasticity 等其他 execution plane 混装。后续生产组合应有明确的合法 profile，不能关闭该检查以借用 Notes 资格。

成本必须包含实际 task、取证/检索、冻结/训练、评价、签名/协调、checkpoint/CAS、采用、迁移/reset、后继执行及失败/重试/恢复历史。某组件记录的 elapsed 或预算上限不等于完整成本；缺失值应保持 unknown，阶段继续 HOLD。

## 4. 最小后续实施顺序

| 顺序 | 可审阅工程交付 | 必须先具备的合法资源 | 保留的拒绝边界 |
| --- | --- | --- | --- |
| P0 | 冻结单一真实任务与可加载训练 profile，列出组件 byte provenance 和全成本计量口径 | 原始 task owner、数据使用权、真实模型/loader | 无来源、无映射、无成本覆盖保持 unknown/HOLD |
| P1 | 原始 Root 资源交付：学习 checkpoint typed CAS；必要时 CURRENT typed publication/readback | 已登记原始 records、fixed owner/identity、现有 peer pin 与回滚域 | 不初始化替代 owner，不授予普通 Agent 任意 owner 选择/写权限 |
| P2 | 各阶段真实 producer 的结果查询与精确 receipt attestation | 原有 Generator/Observer/Evaluator/Selector trust 与独立身份；真实 retained results | 不签 caller-only digest；撤权/过期/原结果缺失失败 |
| P3 | 完成 artifact owner → signed selection → original CURRENT/FinalUse → Ready V13 runtime 组合 | 实际 payload/snapshot/leases、原始允许该 binding 的 issuer policy、旧新 journals | 不存在 grant 则拒绝；prepared/uncertain publication 只 reconcile |
| P4 | 实现具体 `LearningIterationOwnerPortsV1`，复用 checkpoint、stage owners、plasticity 与 published readback | P0–P3 完整资源；同一 operation/candidate/trust/generation 绑定 | 每次复核当前结果；NoUpdate 也需原 baseline 的真实不同任务消费 |
| P5 | 普通 daemon 可信 bootstrap factory + producer handle 生命周期 + foreground/task-completion 请求入口 | 完整生产 composition、明确 profile、bounded queues/deadlines/shutdown | 身份不符/重复 owner/无 capability 启动失败，不回退 fixture |
| P6 | 在最终共同 HEAD 上执行真实跨进程资格并保存原始 receipts | 同一候选、独立真实任务、完整历史成本、原始权限 | unit/synthetic passing 不能提升 S0–S5 |

P1/P2 是真实能力和协议边界；在现有部署未提供这些资源时，不能通过一个本地补丁凭空补齐。P3 已有大量可复用代码，优先使用上述既有构造函数，避免重新发明 selector、CURRENT 或 FinalUse authority。

## 5. 后续资格的可观察条件

普通 daemon 启动记录应绑定最终源/tree/dependencies、原始 host identity、queue/profile 和完整 resource fingerprints。一次实际已完成任务必须产生固定学习请求；所有阶段绑定同一候选和实际 retained result。采用之后，另一个真实 task 由已发布新代实际执行；Selection/NextUse 必须来自该 actor 原始读回，并由原阶段 owner 对精确 receipt 签名。

故障资格至少覆盖提交后失确认、训练重启 reconcile、已采用 CURRENT 的跨进程 reopen、old writer fencing、撤权/过期后读回拒绝、错误 bundle/loader pins 拒绝、NoUpdate 的真实 baseline 后继消费，以及成本缺失保持 unknown。完整原始历史应保留失败和重试，不能只留最后通过的一次。

## 6. 已完成的 terminal 修复与本文件的限度

terminal durable recovery 的独立原生分支为 `d74efedeed3b3f5ec62e35ce6133eccf6e44256d`。父任务实际运行记录报告：9 个普通 terminal 测试通过，1 个显式 original Host CAS / fresh-child 跨进程测试通过，前后 source/tree clean。对应记录名为 `terminal-native-v3.json` 与 `terminal-original-host-cas-v3.json`；后者总耗时 21.6267 秒、test 耗时 3.831 秒，log SHA-256 为 `be6bdb9db06586425b3c41d4c8e3ff8bb65554e15d1e59bec8537aa3d2a9c912`。

这些结果只证明 terminal 原始 durable job 的恢复、当前权限复核和不重复训练边界。它们不证明 ordinary daemon 已安装 generic learning owner，也不证明 HCSN/CellBundle 采用、局部学习净收益或完整成本。因此本文件不提升任何 stage。

本交付没有新增 Rust 实现或生产配置，也没有在 common worktree 进行修改。文档/JSON 可独立加入最终共同候选；后续真实 native receipt 才能把资格结果与最终 HEAD 绑定。

## 7. 源码索引与复核

下列编号在伴随 JSON 的 `sources` 中映射到精确 repo 路径、构造函数、Git blob 和 SHA-256。`source_inventory` 保存全部缓存文件；`source_validation` 保存合并关系与 50 文件摘要复核结果。

| 编号 | repo 路径（均以 `codex-rs/` 开始） |
| --- | --- |
| S01–S07 | `hepta-agentd/src/{main,config,learning_iteration,learning_iteration_ports,learning_iteration_auth,learning_iteration_runtime_tests,learning_iteration_checkpoint}.rs` |
| S08–S12 | `hepta-agentd/src/{root_production_inputs,authority_host_bootstrap,authority_host_service,authority_host_config,deployment_issuer}.rs` |
| S13–S15 | `hepta-learning-artifacts/src/owner_service.rs`；`hepta-agentd/src/{neuron_generation_update_selection,neuron_generation_update_live}.rs` |
| S16–S18 | `hepta-agentd/src/{neuron_generation_process_bootstrap,neuron_generation_runtime,neuron_generation_learning_runtime}.rs` |
| S19–S22 | `hepta-agentd/src/{neuron_v13_generation_update,neuron_v13_generation_update_runtime,neuron_generation_update_adopted_learning,neuron_generation_current_types}.rs` |
| S23–S26 | `hepta-agentd/src/automation_hcsn_pq.rs`；`hepta-learning-artifacts/src/{hcsn_candidate,cell_bundle}.rs`；`hepta-agentd/src/neuron_generation_current.rs` |
| S27–S31 | `hepta-agentd/src/{learning_iteration_proposal,neuron_cell_evaluation,cognitive_retrieval_context}.rs`；`hepta-agentd/examples/neuron_v13_guarded_acceptance/authority.rs`；`hepta-agentd/src/cognitive_retrieval_learning.rs` |
| S32 | `hepta-agentd/src/neuron_generation_update_bootstrap.rs` |

可在目标共同 checkout 中重复的只读检查：

```sh
git rev-parse HEAD
git diff --name-only --diff-filter=U
rg -n 'impl LearningIterationOwnerPortsV1 for|with_learning_iteration_bootstrap\(' codex-rs --glob '*.rs'
rg -n 'GenerationLearningPublicationV1::(Published|Unpublished)' codex-rs/hepta-agentd/src
rg -n 'prepare_agentd_v13_generation_update_v1|AgentdSelectedGenerationV1::load' codex-rs/hepta-agentd --glob '*.rs'
```

这些是源码核查命令，不是生产任务或资格测试。
