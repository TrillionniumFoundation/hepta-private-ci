# cc57 真实效用闭环：剩余输入与产品装配边界

## 结论和审查范围

本次只读核对固定源 `cc57c7198db6293ccca562253c42fffbe2a04633` / tree `b7b357c07b5539769a068c6b9b009629f5612d1e`。完整 15,188 文件清单与前一源 246d 逐项比较，差异恰好是 CALLERS、allowlist 和三份 QA；Rust 字节全部相同。另逐文件核了 59 份实际源码的 bytes/SHA256/Git blob，详见 `SOURCE_REVIEW.json`、`VERIFIED_SOURCE_ROWS.json`。这是源码与既有工件审查，没有执行 H、Cargo、门禁或任何真实任务，没有写生产源、生成角色身份、签名或收据。

**当前已实现完整 evaluated NoUpdate 的主要原 owner 机制，但普通产品入口还没有把真实角色 owner 装配进去。被审材料也没有提供一条可直接调用的、真实授权 A/B/C 任务和原权限链。** 因此本次可证实的真实闭环数量仍为 0；这只限定本次审过的材料，不推断系统外绝无这些材料。旧 a8 文档中笼统的“Version/S/C/Root 均未实现”已经过时，不能再作为当前阻塞表。[S01–S16, H03–H05]

工程任务“全量冲”授权源码修复和验收工作；它本身不是某个运行时任务的 SignedFinalUseGrant、已登记的 Registry lease、数据使用许可或独立 B 的结果。新源资格结果仍应以相应原作业记录判断，本报告不给任何门禁或真实任务追加 PASS。

## 已有机制与仍需取得的原件

| 环节 | 当前实际已有的机制/材料 | 本轮材料中的缺口 | 下一项可执行工作与边界 |
|---|---|---|---|
| 真实 A 与外部目标 | main 能接原 Objective/AuthBus/Circuit 相关配置；Root resident profile 要求已经完成的 A、原始空学习 cut、冻结 scope、当前原 Root intent/lease。outbox 的本地 enrollment ACK 明确不是学习完成 ACK。[S01, S09–S12] | 未见可执行的非 fixture A 的原 invocation、完成收据、Objective/Circuit 源、数据授权、任务分布及硬约束。没有可以把当前工程构建任务直接转成学习 A 的凭证。 | 由真实任务/目标 owner 提供同一 A 的既有原件；先锁目标、观察标准、权限、任务分布和收益/退化门槛。不得由候选或 critic 自定这些内容，也不得预填未来完成收据。 |
| 原 Training 与初始 owner 交付 | `CandidateStageOwners::from_original_streams` 要求真实 loaded baseline、material、panel protocol 和十条原 connected stream；原 peer/pidfd、角色、scope 和最长 300s lifetime 都被检查。[S05–S07] | main/config 没有该 typed bundle 的合法生产提供方。原 Training bootstrap 的 create/recover/serve 产品 caller 也仍为空。当前资格材料不是原 Training 数据、writer custody 和真实训练尝试账本。 | 实现受原 owner 控制的生产装配和连接交付，复用现有构造器；交付前必须有真实数据/材料权限和原 owner。不得从测试 ports、路径发现、上传 receipt 或重新开 writer 补成能力。 |
| 独立评价 B | E 初始 Connection 必须在未来 T/B cut 前持有；原 provider 读取 outcome、finalization、policy 和 observation 支持信息；身份、controller、credential chain、签名键分离受检查。[S07, S13, S19] | 未见真实 B 任务来源、训练/教师谱系、运营控制关系、原 outcome 记录及独立 evaluator 的实际授权。不同 key 或本地生成的不同 identity 不足以补齐。 | 由独立观察方交付原任务和结果、原权限/控制关系证据；冻结或 cross-fit critic。动作为何改变结果以及 propensity/support 的识别条件缺失时继续 Unknown。现 provider 只支持确定性 0/1 路由；不能声称任意新动作的 OPE 已识别。 |
| 完整 NoUpdate 与 Adopt | 证据不足保留 `InsufficientEvidence`；完整 Ineligible 才变 evaluated NoUpdate。新 negative 分支检查完整 4/5/6-cut，再读原 T/E、发布、S/C；legacy 3/4/5 仍独立。Candidate Adopt 继续在原 Model/Selector/Version/FinalUse 缺口拒绝。[S08, S13–S18, S20] | 没有本轮真实比较结果。仅第 4 个 disposition 为 NoUpdate 不代表完整资格。Adopt 的实际 proposal/adoption 接缝仍缺，不能用“完整 NoUpdate 可行”替代。 | 先运行诚实比较，让结果自然落在 Adopt、完整 NoUpdate 或 Unknown；若是完整 NoUpdate，可走已实现 retained 分支。Adopt 还需原 Model proposal/Selector/Version/FinalUse 的独立实装与验收，不删除现拒绝。 |
| 可部署组合、模型材料与最强对照 | bundle 绑定 base、adapter、head、encoder/tokenizer、校准、数值和状态语义等；评估记录比较候选和 fixed expert，并绑定实际 journal。[S21–S23] | 未见本轮合法可取的 base/adapter/路由配置材料、下载/加载读回及权利依据；fixed expert 存在不证明它就是该部署条件下最强可用对照。构建 V8/UV/Ruff 材料与这些模型材料不同。 | 原材料 owner 给可获取字节、授权和实际加载证据；对同一完整部署组合/任务分布冻结最强可用对照选择依据，保留旧任务、稀有任务和必过安全任务的单独硬门槛。内容根只核字节身份。 |
| Version / FinalUse / 新消费者 C | evaluated Version 构造器消费真实 D readback、预持 T/E Connection、publication/task inputs 和已由 Root 绑定的 FinalUse provider；Published 后才允许 S 读。C 是原 readiness 后的真实任务读回，不由 checkpoint 提升权限。[S13–S16] | 启动虽有真实 Root 五 lane/FinalUse provider 接口，但现有对象用于其原运行时 scope，不能自动挪作 retained Version。未见同一 A 对应的新 C 原 admission、task config、Artifact/CURRENT owner 和实际 FinalUse grant。 | 原 Version host 和 C 的原启动方交付这些能力，保持 by-value 一次消费和目的域；完成 publication 后读取真实 C，记录不确定/失败。不能任意 clone 原 Arc provider 或重签为新用途。 |
| daemon 与 Root 冷恢复 | Root resident 有独立登记/执行/只读 purpose；cold Version 在完整原 D/T/E/Artifact/C/pin 检查后安装 reader，恢复不创建新 writer 或执行 token。late enrollment 只连接原 A outbox 与原 Root client。[S09–S16, S24] | 这两条生产装配入口尚无真实 product caller。没有本轮实际 A→C 的 durable state、冷进程和新 current readback intent/lease；旧 fixture 的回放不能补这个缺口。 | 选择并装配一个明确 owner placement；保留已产生的原状态，让 daemon/Root 实际退出/冷恢复，只使用当前合法 readback 权限读取同一操作。不能从旧 A writer lease、UID0、vacant checkpoint 或 saved tuple 恢复 Fresh 能力。 |
| 冻结成本合同与完整账本 | `CellTaskCostV2` 保留失败/取消/拒绝，inclusive 不重复加；缺指标是 Unknown。当前 `CellEvaluationCostScopeV1` 只有 `TaskLedgersBeforeFinalHoldout`，明确未包含之后 estimator、验签和 publication 开销。[S22, S25] | 没有覆盖本次训练/搜索/失败/取消/评估/下载/激活/服务/维护的外部冻结成本合同、计量源和完整实际账本。构建日志的 elapsed 不等于产品成本账本。也未见真实公共奖励合同和诚实 NoUpdate 的付款成熟证据。 | 原合同 owner 先冻结覆盖、计量、共享分摊和未知处理，再采完整事件；更宽 total-cost 需独立合同/记录层，不能事后改旧 cut 的含义。隐私、授权、必过任务仍是硬门槛，不能拿平均收益冲抵。 |

## 两个空产品入口为何不能用一行 main 调用补齐

1. **Agentd 侧 checkpoint 装配。** `main.rs` 调 `AgentdProductionStartup::receive()`；`production_launcher.rs` 只把 learning handoff 连接成 `AgentdRootLearningInputsV1` 并调用 `with_root_learning_inputs`。`AgentdProductionLaunch::run()` 首先执行 `require_root_learning_assembled()`。入站 handoff 的固定帧仅有 sealed bootstrap 和同 Root 的 pidfd 两个 rights；它没有角色 stream。`with_root_learning_stage_owners` 需要调用者已经持有真实 StageOwnerPorts、原 verifier 和容量，不从 JSON 或 descriptor 发明 owner。[S01–S04]

2. **Root resident 侧装配。** `into_candidate_runtime` 消费具体 CandidateStageOwners by-value，检查实际 profile、verifier、初始 scope，然后由原 Root CAS 安装 effect gate。它不签发 T/E/Model/S/Version/FinalUse。Root 当前 CLI 的 register-learning/serve-session 负责 checkpoint 注册/传输；库里的 late enrollment 也要求一个已经建立的真实 Root client。这条入口目前没有生产构造/监督路径可消费上述 bundle。[S05, S08–S12, S24]

两个空 caller 表示真实的未完成产品工程，不等同于“只缺一句用户批准”。但当前已核 main、launcher、Root CLI/config/handoff 都没有合法可直接填入的 bundle。它们也不是两个连续调用：Agentd 的本地学习 runtime 与 Root resident late enrollment 是互斥配置；同一 bundle 不能被复制给两边，Root 内角色通道必须属于实际 resident PID，不是照搬 A 的 UID/PID。[S03, S09–S12, S24]

### 最小可实施装配方案（HOLD，未写源）

优先接现有 Root resident 的晚注册机制，因为它已有 A 完成后独立驻留、原 outbox join 和 cold readback 的设计。具体消费顺序和拒绝条件见 `ASSEMBLY_IMPLEMENTATION_HOLD.md`。下一批代码的工作是为原 launcher/host 增加一个显式、受目的域约束的能力交付边界，接入原 owner factory、runtime supervision 和晚 enrollment；现有两-right checkpoint handoff 不变。不要以新 callback/trait 任意制造 owner，也不要用占位变量创建一个没有原提供方的 product caller。

**当前缺的是提供方合同与其实例。** 本轮没有一个已知生产 owner host 能交付这十条连接及 Version/D/T/E/Artifact/CURRENT 的配套能力，也没有相应原任务/角色权限。可以继续实现并用明确的机制 fixture 验证这个装配层，但那仍不产生真实 A/B/C 证据；若要求立即跑真实闭环，必须先取得这些原件。为避免把任意新协议误作既有授权接口，本审查只给可 review 的 HOLD 方案，没有编造 source patch 或放宽 CALLERS。

## 不能从既有 fixture 推得的结果

当前 `circuit_evaluated_retention_publication_support_tests.rs` 的文件开头明确把角色凭证、时钟和测量标为 fixtures，并排除 ordinary qualification / daemon-Root cold recovery。其后确实调用真实 owner 实现、原 journal/current、原 T/E readback；这能检验机制，不能认证真实 B 的机构独立性、模型许可或用户任务价值。[S26]

Version recovery 支持测试沿用同一实际 fixture journal/SourceLedger，并用测试 key/同进程 channel 检验权限和恢复边界；它们不能作为本轮真实 cold run。原 33 个 UID0 专用用例是否执行、原默认/完整门禁是否通过，必须读各自 fresh 原结果，不能根据源码、formatter 成功或本报告替代。[S27, H04–H05]

四种结果仍分开：完整收益与硬门槛通过只是进入原 owner Adopt 授权的前提；完整负比较可以是 NoUpdate；缺原件/识别条件/成本/权限是 Unknown；本轮编译、运输、启动控制或资格门禁失败本身不是 Objective Fraud。欺诈需要另有可复现确定性证据和明确挑战流程。[S18–S20]

## 可立即移交的原输入清单

最小真实跑通包应由已有原 owner 提供，顺序是：① 已完成 A 的 Objective/Circuit 原件、完成收据和学习请求/冻结 scope；② 当前原 Root 执行 intent/registered lease 与角色/数据权限；③ 在未来 D/T/B 前交付的十条原连接、真实 loaded baseline、material config 和 E panel protocol；④ 独立 B 的实际任务/结果/控制与谱系证据、符合动作识别条件的策略数据；⑤ 原 Version publication、Artifact/CURRENT/FinalUse 与新 C 的实际启动能力；⑥ 独立冻结的完整成本和公共奖励合同；⑦ 真正闭环后才可建立的 durable state 与当前 cold-readback 权限。第⑦项不能预生成。

已审工件能提供源码、机制设计、固定输入哈希和工程测试/失败取证；未能为上述任一真实任务实例提供足以自行调用的整套凭证。因此本轮下一步是完成能力提供方/普通装配的具体工程接口并收齐原输入，不是生成一份声称成功的 A/B/C 收据。

## 来源索引

所有 S 项均逐字核对 cc57 完整清单；精确 bytes/SHA256/Git blob、函数锚点和链接在 `SOURCE_REVIEW.json`。以下短名均位于 `codex-rs/hepta-agentd/src/`，另标 crate 的除外。

| ID | 原源码路径 | Git blob |
|---|---|---|
| S01 | main.rs | 133a0c12daa683e16cdb79f902dea88092ebfb52 |
| S02 | production_launcher.rs；production_launcher_inputs.rs | 4b615c40566ec351d53861eb2a57d8d85da1c310；707345d2cab002009f3f46466e77bf7f9c7bce02 |
| S03 | config_root_learning.rs | 792703744b84ab6df841035f1e6652e3c7bd71ad |
| S04 | root_production_learning_handoff.rs；root_production_learning_inputs.rs | c3372a8e6493b8a9f5acc09c2d73a03e452ac22c；f12e808a049e0fa1418df0a578c0f9dde9bbe538 |
| S05 | cell_q24_candidate_stage_owners.rs | 3c534c5aef813fe1e43eba0cc5e3978721e82167 |
| S06 | cell_q24_no_update_stage_inputs.rs | 6a81d66c79e5c38ac0177a6949070dcde5769434 |
| S07 | cell_q24_candidate_stage_inputs.rs | 4d48a46967db39d0258d00c9ff0876a3dca53de2 |
| S08 | authority_host_learning_resident_stages.rs | f171d6eda0b8673f3c39566368025ad18dbaf19c |
| S09 | authority_host_learning_resident.rs；authority_host_learning_resident_runtime.rs | 3275b6d0de952fab371578336cba1e04215d1ee7；3deaa319c779c5121e6e66ea94af14c77363c7d7 |
| S10 | authority_host_learning_resident_profile.rs；authority_host_resident_registration.rs | 0cb2317f282814db87c0eb355f3aabb7c0ce6143；b98abbaf3dd53d92c4c094115c606680896f68eb |
| S11 | config_resident_learning.rs；resident_learning_delivery.rs | e4918f2febdc8f64773bb263905b4090b78ce79b；7c247c1f377e9889b3678fb6ae984ea188c5440a |
| S12 | bin/hepta-authority-host.rs；circuit_learning_delivery.rs | a0cc9b78dada59dcb45983a2c1b0bb7444ea1cfa；17eb14781859be44dc906dd04d046a4e3655e7aa |
| S13 | circuit_retained_version_host.rs | d84937fc81f0a7b41c997c97b29cd06ff9cf03e4 |
| S14 | circuit_retained_version_state.rs；circuit_retained_version_service.rs | a0f3c847a49c3d5a2ae4df704ed1f751b9e287f9；28a97fd7da6a322e530585d04088f7962617c0c1 |
| S15 | cell_q24_candidate_stage_retained_execute.rs；cell_q24_candidate_stage_retained_readback.rs | dda6557805b08b4615bf2a5bb1508c4656686a9e；ac638b392a3c4b78525affb108dbb2436622898b |
| S16 | circuit_evaluated_retention_publication.rs；circuit_evaluated_retention_recovery.rs | 55e0dada64d1b1ee2e1ba17b82c1bce963f3220f；c0e88737c9266116a7ced7879f96e9419289da73 |
| S17 | cell_q24_candidate_stage_retained.rs | 923a3d5b8e0ecfba7bd686a01566e59ea6985d69 |
| S18 | neuron_cell_learning_evaluation.rs | 94cfa5ef7411b4b1e9946ec5f55b88c8272a0197 |
| S19 | circuit_original_evaluation_provider_records.rs | 3f4ec659e2e28ae5c32fddd4d8c338420ce8ffa7 |
| S20 | hepta-intelligence-eval/src/closure.rs；ope.rs | 97d6c9cbc151cb5373ca900a7915f8f38ff941aa；52fb8b882012f2561c65a95639a63da8e2c12ff4 |
| S21 | hepta-learning-artifacts/src/cell_bundle.rs | 64c7018f44b1365d7e2fb51926209758cef00468 |
| S22 | neuron_cell_evaluation.rs | 7916d8905db13c6d8d374152c79f6786781d8ecd |
| S23 | neuron_cell_evaluation_contract.rs | 88d0786fe43f21ac82a24cd72f18bb1a530a97f5 |
| S24 | authority_host_learning_resident_transport.rs | 40b744877e6e3a0e02dea0fdc9fffb8859eefdf7 |
| S25 | hepta-neuron/src/cell_task_cost.rs | c73cb763cbf2bd753ae44ce74e33da0a3f951772 |
| S26 | circuit_evaluated_retention_publication_support_tests.rs | 8d94ddd4a3ed4ea9552a6e58caaf4f6100fdc4d5 |
| S27 | circuit_evaluated_version_recovery_support_tests.rs | 639f3d799c69a54c4583ee24ce87956ec149a07f |
| S28 | root_production_inputs.rs；production_root_composition.rs | d41e9127a9d9f982ba9ff2469de7cdd9d2631a65；a2cb39f96da3f263ad9cab80f0d5ea9ce0531b51 |
| S29 | cell_q24_material_command_service.rs | 58afc356fff945a5377c3556fa0ba79139d3fad6 |
| S30 | cell_q24_training_bootstrap.rs | 35bf372850718a41f245c996ee91a71c184bed89 |
| S31 | cell_q24_model_command_host.rs | 0418a532daa7460954bec6d421d608c7aa1f16ee |
| S32 | neuron_cell_evaluation_host.rs | 002394b4a405abfdb51c6f80f19a203a68a62e18 |
| S33 | circuit_evaluated_selection_command_service.rs | 95e6dc6fb97dadbafdcc9e13897221da6ddccb36 |
| S34 | circuit_evaluated_next_use_command_service.rs | 2893d2cc97faef0f3352406b89f7ec190b8e629d |
| S35 | circuit_learning_completion_readiness_service.rs | 3224ca4aa80e8841fc902979c4042d177f647f69 |

历史参考 H01–H05 分别是 `2059d041fd450c99a04b657eb7d9d04afc2a85db`、`4ed4850e4b9b8f604a7b81257a5cc41612228f70`、`db12282eec3d34eab42d6c5150e1e7874799e242`、`431391dd1d18806d054c5134ea687233c3e60f84`、`4519f6278f8225894d4db1c19181b3de6db0d726`。旧 source/gate 状态不继承；只在当前源码重新确认后使用其机制结论。
