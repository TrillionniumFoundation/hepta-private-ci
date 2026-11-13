# 原 owner 生产装配：精确 HOLD 方案

状态：设计供下一批源码审阅；没有 Rust patch、没有实际 owner、没有新授权/任务/连接/签名，没有执行。基于固定 cc57/B7 原件，具体来源见同目录 SOURCE_REVIEW.json。当前源和资格控制不修改。

## 已有能力与不能推导的能力

已有 Agentd Root startup 验证同 Root、原 pidfd、原五-lane 和学习 checkpoint。它不携带 CandidateStageOwners。`OriginalCellQ24CandidateStageStreamsV1` 明确由 7 common streams（Experience、Dataset、Trainer、Selector、Version、NextUse、Completion）及 Candidate-material、Evaluator、Model 3 streams 构成；每个都是原先连接的 UnixStream 与对应 peer、原 pidfd、timeout/lifetime，不是可连接地址。

当前 Product CALLERS 中以下真实入口为空：Candidate stage create、Training bootstrap create/recover/serve、retained Version evaluated host create/ordinary serve、Agentd stage assembly、Root resident candidate runtime、Root resident registration/late enrollment。表明没有已完成的普通入口，不能单靠新增名单关闭。main 的配置字段、Root 两-right learning handoff、late enrollment 都没有隐藏的原 role provider 可复用。

有真实 `AgentdRootProductionInputs.grants: Arc<AgentdUnixFinalUseGrantProvider>` 通道接口，但它随原运行时 scope/custody 使用；不能任意解除 Arc 或拿它代替 Version 构造器消费的原 provider。原 Version 还需要独立 D/T/E、publication inputs、C task inputs、Artifact/CURRENT 及原 grant 目的绑定。实际对象/授权实例未在已审材料提供。

## 十个角色通道怎样合法取得

下面是现有消费/服务 API 所要求的真实来源，不是声称本轮已取得实例。每条 socket 的服务端由原 host 保留，客户端由实际 resident/daemon 一次取得；launcher 只能传递已获授权的原 descriptor。传输必须附实际持有的 owner pidfd 和原 actor/UID/PID/boot/start-ticks，服务端也持有原 consumer pidfd。字段不能从任意配置文本声明后当可信。若提供方需要等 T/B/S/C 实际产生才能构造 command owner，它只能先保留已连接的端点，之后消费真实 cut；不能预填未来 receipt 或换 peer/延长期限。

| bundle 字段 | 服务端真实来源 / 当前准确 API | 必须保留的 role、binding 与原件 |
|---|---|---|
| common.experience | Material receipt pair 的 consuming command-owner factory，`OriginalCellQ24MaterialCommandOwnerV1::serve_experience_commands`；源码 S29 | actor=initial.owners.experience；同 completed A Source、Material journals/witnesses、ledger、loaded baseline、material config。不能给训练方用自造 Experience 签名。 |
| common.dataset | 同一合法 Material owner 的独立 `serve_dataset_commands`；S29 | actor=initial.owners.dataset；与 Experience 原 pair、同 request/scope；Training 用其独立只读 Dataset/material-source 能力，不能上传 batch 冒充原 Source。 |
| common.trainer | `OriginalCellQ24TrainingBootstrapOwnerV1::from_original_custody` 后的原 `serve_commands`；S30 与其原 service boundary | actor=trainer；原 native/receipt files+witnesses、generator key 对已注册 verifier、baseline、原 material-source Connection、Experience/Dataset evidence clients、Dataset readback；取消状态与 Fresh/Recovered 保持。 |
| candidate_material | 同一实际 Training bootstrap 的 `serve_candidate_material_readback` 专用连接 | actor仍是trainer；独立只读原 Candidate bytes/完整 Training binding，不能拿普通训练执行连接替代 purpose，不重开 writer。 |
| evaluator | 原 `OriginalCellEvaluationReceiptOwnerV1` 消费实际 primary/retention panel 成为 `OriginalCellEvaluationHostV1`，随后原 command service；S32 | actor=evaluator；E Connection 在未来 T/B cut 前预持；实际 host 的原 panel 与 evaluator receipt owner在真实 B 完成后绑定同 T、scope、plan、trust。源码明确此 host 不执行/标注 B。缺真实 B 提供方不是初始化一组假 journal 能补的。 |
| model | `OriginalCellQ24ModelCommandHostV1::from_original_bootstrap` / 原 command service；S31 | actor=proposal；同原 Training bootstrap、Model file/witness、`OriginalCellEvaluationModelMaterialConnectionV1`、panel registration。即使预期 NoUpdate 也保留当前 mandatory initial Model connection；Model receipt不授予Adopt。 |
| common.selector | 真实 `OriginalCircuitSelectionReceiptOwnerV1` 经 consuming evaluated command adapter；S33 | actor=selector；原 live published 4-cut、同 T/E clients；原 signer/journal仍属Selector；raw端点可预持，actual context只从完整真实4-cut生成，不能从NoUpdate标签生成。 |
| common.version | `OriginalCircuitRetainedVersionHostV1::from_original_evaluated_owners` + `serve_original_ordinary`；S13–S14 | 原独立任务 peer/pidfd；material、D、预持T/E、真实 publication/task inputs、Artifact checkpoint、原 Root-bound FinalUse provider。只 actual Published+fresh原cut后服务S并启动C；丢ACK不是重试许可。 |
| common.next_use | 原 `OriginalCircuitNextUseReceiptOwnerV1` 的 evaluated command adapter；S34 | actor=observer；同 published C live owner、原T/E、同Selector evidence client与opaque S，实际context来自完整5-cut；真实Source/Cell读保持在所需前驱await之后。 |
| common.completion | 实际 C Published owner 的 `serve_evaluated_completion_readiness`；S35 | 原C task peer/pidfd、evaluated NextUse purpose/full5-cut；只读 readiness，不执行、不签发C。timeout≤500ms、128帧原上限不变。 |

其余九条原 command timeout≤30s；各 lifetime>0 且≤300s，common与三个额外lane最终取最小原end，material/signature/Root grant 的原期限仍另行检查。真实连接失败、peer丢失、scope/purpose不符或缺任一原值均保留原拒绝/Unknown；不能延迟到结果已知后重建“初始”连接，也不能为长任务重置截止。

## 最小实施顺序

| 步骤 | 应修改/接入的现有位置 | 必须由真实提供方送入的原值 | 不能替代或放松的检查 |
|---|---|---|---|
| 1. 定义唯一 owner placement 与实际提供方 | 原 launcher/host 组合层；A 侧复用 `with_root_resident_learning_enrollment`，Root 侧复用 resident factory。Agentd 本地 runtime 是另一互斥模式。 | 真实 A Circuit/Objective context、drained A/outbox、原 Root 配置/当前 intent+lease；明确角色通道要归 Root resident PID。 | 不双消费/复制同 bundle；A writer 权限和 Root resident 执行权限分离。 |
| 2. 显式交付原角色能力 | 新目的明确的能力 handoff/typed composition，接到现 `CandidateStageOwners::from_original_streams`；现 checkpoint 两-right 协议不变。 | 十条已连接 stream、真实 peer/pidfd、原截止；material、panel registration、真实 loaded baseline。连接在未来 D/T/B 前建立。 | 逐角色原身份、UID/PID/start ticks、同scope/initial、timeout≤30s（completion≤500ms）、lifetime≤300s，min截止不续期。任何缺失整组拒绝；不 socket discovery/reconnect。 |
| 3. 真实 host 与 Root runtime 装配 | 原 Training/Experience/Dataset/E/Model/Version/S/C host factories；Root `register_host_resident_learning_v3`→`into_candidate_runtime`→原 runtime supervision。 | 各 factory 所需的真实 custody、数据/材料/current/Artifact/FinalUse；原 verifier；已授权 Root profile。 | 不上传未来cut；Model初始连接仍 mandatory；E Client/receipt不可冒充预持Connection。原 Root gate/CAS/oncebit/Unknown行为不改。 |
| 4. A 完成后的原 client 交付 | 原 `RootResidentLearningHandleV3::serve_original_stream`、`AgentdRootResidentLearningClientV3::from_original_root_stream`、`enroll_original_root`。 | 同一操作的实际 Root stream/profile，A 原 AutomationStore/outbox。 | enrollment ACK只证明本地join；先确认真实Root current，后 claim；失ACK/退出后只原readback，不自动Fresh重试。 |
| 5. 诚实 evaluated NoUpdate 后的真实 C | 原 retained Version factory/serve、Selection/Evaluated read、C completion readiness。 | 完整真实 Ineligible B、原publication/FinalUse、C新合法task、实际C readback。 | 4/5/6完整cut；Published门槛；当前源变更拒绝；Prepare/Execute一次；失效不将Unknown当NoUpdate。Adopt拒绝保持，另行实装原adoption owners。 |
| 6. 冷恢复 | 原 Root recover + readonly streams、Version recover，原 daemon outbox reconcile。 | 已实际产生的同一操作durable状态，当前新readback intent/lease，原owner/current/artifact材料。 | 不从旧A lease/Root UID/vacant record构造Fresh；恢复不重发效果、不创writer、不重签结果。 |

## 为什么这里没有给一个冒充完成的最小 patch

消费者调用本身很小，但缺失的不是能从当前 config 解出的普通数据：它是原 provider 的 connected rights 与严格持有关系。现在给 main 填一个新 Arc、从测试端口取得 server 或从 fixture 造签名，会改变权限来源。只新增一个从参数转发的无调用 helper，或将它注册为 product caller，也不会实现原启动链。

上述工作可以在用户现有工程授权下继续做机制实现；在开始新的生产装配 patch 前，应确定由哪个现有真实 host 持有并交付每个字段以及通道的实际目的/生命周期。若本轮外部原件尚不能提供，可以写和审查该边界的机制测试，但结果必须标 synthetic，不是实际 A/B/C。不得因缺输入放开默认 fallback、改原截止/目的、把状态元数据变为能力。

当前不具备“只调用已经存在的合法 owner 变量即可接通”的代码片段。若后续拿到具体生产 provider 入口，下一 patch 应只在该明确组合层消费原能力，并逐新增实际 call 更新 CALLERS/保护/QA；不得从本 HOLD 自动推导任何资格 PASS。

## 原测试可验证什么，仍需真实原件验证什么

以下测试文件均取 exact cc57 的原 blob，只静态定位，未运行也不继承旧结果。它们是下一具体装配实现必须继续保留的机制回归；不会因为列出名称就证明新 handoff 或生产链已被覆盖。

| 原测试与 exact blob | 可检验的机制意图 | 不能代替的真实材料 |
|---|---|---|
| `root_production_learning_inputs_tests.rs` / `890d49ab68d14d1a89038278664f02fa9e05f7b9`：`learning_bundle_requires_same_original_writer_peer_identity_and_fixed_lane`、`learning_bundle_refuses_other_agent_initial_operation_and_profile_bytes`、`scoped_learning_handoff_requires_its_complete_original_profile` | 原 checkpoint 同Root/writer/peer/scope，错profile拒绝 | 不覆盖尚未实现的十-role handoff；需要实际合法原 owner streams。 |
| `cell_q24_candidate_stage_tests.rs` / `1b53321056d492b63fed06f97b0932618dbcbf79`：`candidate_stage_reads_actual_candidate_from_same_three_original_owners`、`candidate_stage_rejects_rebound_profile_and_absent_root_gate_without_dispatch` | Candidate 来自同原T/D/source，缺Root gate或rebind拒绝 | 该fixture显式不补实际E/Model；不能当完整真实B或Adopt证明。 |
| `circuit_evaluated_retention_publication_tests.rs` / `a4e4dd63ad5af3641d0afbbfc15e65d6f78cca19`：`evaluated_retention_publishes_baseline_from_same_a_training_and_independent_b`、`evaluated_retention_wrong_grant_keeps_original_intent_pending_without_redispatch`、`evaluated_retention_preserved_owner_connections_reject_withdrawal_after_publication`、`evaluated_retention_lost_ack_recovers_exact_original_publication_and_baseline_c` | 完整negative、同T/E、wrong grant、withdrawal、lostACK同操作恢复 | 角色凭证/时间/测量仍是fixture；需要真实独立B、真实FinalUse和C任务结果。 |
| `circuit_evaluated_version_recovery_tests.rs` / `c889bb7b6eecedf6c09c97e0cd5f738f2016c23a`：五个 `evaluated_version_cold_*` 方法 | 完整4-cut、当前E、后续B撤回清reader、Artifact失败不admit、只有Training prefix缺B拒绝 | 原进程/durable owner冷恢复真实结果；不能声称仅靠fixture重建了真实C。 |
| `authority_host_learning_resident_root_tests.rs` / `e16820f8bab3027ab74490f942a34c7ee5470739`：vacant CAS、same-epoch/lease revoke、lost freshACK、queued cancellation、structured uncertain 各原方法 | 原Root purpose/CAS/lease/once-only与只读恢复语义；这些方法仍保留原actualRoot `#[ignore]` 约定 | 只有在原专用Root条件下实际执行才算机制验收；仍需真实A outbox、Root intent/lease和角色owner输入，不是用户A/B/C资格。 |

新能力 handoff 实装后还必须验证真实同进程/跨进程 custody、十角色错配/重复/缺失、期限不续、Fresh/Recovered不得升级、两配置模式互斥、取消后同操作只读及新producer实际callers精确登记。这是新增装配本身的必要验收范围；本报告没有新增测试、调整原600/300/4800预算、删原攻击或要求宽化权限。
