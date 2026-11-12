# 普通 Root V3 producer：exact 094 的可执行前置审计

## 结论与本轮边界

**本轮没有可以诚实独立交付的普通 producer 小补丁。** 已有 V3 原 owner、十流装配、Root admission CAS 和 late enrollment 都能复用，但当前普通 CLI/session 不能提供它们要求的实际原件。把这些 API 再包一层、增加只会拒绝的新 flag，或把旧 generation descriptor 改称 Q24 publication，都不能推进真实普通执行。

本轮完成可保留的源码审计：独立复核上游 35 个 exact 文件，补读 11 个 exact 文件，并验证同一版本的 CALLERS.toml，共 47 个原件。没有修改产品源码、权限检查、source verifier 或分支；没有启动 native；ordinary qualification 新增 **0**。本文只针对 `094958b83a8fd19e3bc6d01a092793c0f420bb75`，不把随后 C receipt/guard 集成反推为该快照已完成。

原件都在本目录 `source/`；`SOURCE_MANIFEST.json` 同时记录 Git blob、SHA-256、原 URL 和实际边界调用者。运行 `python verify_sources.py` 可重验原件和调用者清单。该脚本是**源码身份核验**，不验证产品行为，不代替 native 或普通资格。

## 1. 已确认的真实断点

| 位置 | 已有能力 | 普通入口缺什么 |
|---|---|---|
| `bin/hepta-authority-host.rs` 的 `serve-session` / `serve-fresh-session` | 一次认领原 FD、同 Root 的 `PreparedHostAuthoritySession`、旧五路 Root handoff、可选旧 learning checkpoint | 没有 material、十条 role streams/pidfds、预注册 panel、实际 baseline、V3 profile/authorization 输入或 V3 supervisor |
| `authority_host_session.rs` | 私有保留同一个 `service`，避免二次打开独占 issuer/clock/checkpoint；现有 serve methods 确实由 bin 调用 | 既无候选原件接收者，也无 resident runtime 生命周期；不能从外围 standalone registration factory 冒称保留了这个 session |
| `authority_host_learning_resident.rs` | service 的 register/recover 使用同 retained issuer/Registry/Root；registration 按值消费具体 Candidate owners | 这些装配入口未接到 bin/session；registration 的真实 Fresh/Readback 授权状态是私有来源，不能由新增调用者 bool 代替 |
| `cell_q24_candidate_stage_inputs.rs` | 十条实际连接、角色/同 scope/完整 verifier、真实 baseline components、原生命周期下限 | 没有实际普通部署 producer 提供十个原端点；NoUpdate 意图也不能免除现构造器要求的 Model endpoint |
| `production_launcher_inputs.rs` / `production_launcher.rs` | Android / Notes / Desktop 原生产启动、降权、原 Root inputs | 没有 Q24 原任务入口或独立 V3 late FD；`startup.receive()` 只在当前输入协议内工作 |
| `config_resident_learning.rs` / `resident_learning_delivery.rs` | 先核真实 Circuit/Objective/AuthBus，再读原 Root 并 join 实际 A outbox，claim 后才 admit | ordinary main 没有先装真实 Q24 profile，因而没有合法调用 enrollment 的条件 |

以上不是仅从 CALLERS 空清单作推断。已逐项读 bin 参数分支、Prepared session 字段和 serve 分支、main 组装顺序、PrimaryInputs 枚举及真实构造器。相关原件：[Root bin][root-bin]、[session][session]、[launcher inputs][launcher-inputs]、[main][main]、[resident registration][resident]、[Candidate inputs][candidate-inputs]。

### 生产 host 端也有缺口

exact 094 的边界清单里，以下 entry 的 `product_callers` 都为空：原 Material `into_command_owner` 和 E/D command servers，Training bootstrap command server 与 Candidate material server，独立 Evaluation host server，Model command host server，panel registration，Candidate fresh/recover constructors，以及 V3 registration/runtime/serve/client/enrollment 的外层入口。

其中有些内部 evidence/readback helpers 已被其他库方法调用；这不等于外层 role host 已由实际 CLI 启动。不能只给 Root 配十个端点名字，再把尚未启动或不能证明独立 custody 的服务计作真实输入。精确 id/symbol 列表见 `SOURCE_MANIFEST.json.evidence_boundaries`，复核脚本逐行比较原 CALLERS 清单。[CALLERS 原件][callers]

## 2. Root 授权能力：存在原 issuer，缺少本次 purpose 的实际供给

这里必须区分两件事，避免把实现缺口误写成完全没有签名能力。

`DeploymentFinalUseIssuer::issue` 已是真实方法，会使用原 key、已安装 policy 和 durable sequence；受保护 issuer 先进入原 `ProtectedLease::with_binding`。后者把请求的 subject/destination/scope/payload 映射为 `AuthorityLeaseBinding`，在原 Registry 上验证**精确绑定和 revision**。所以一个已经合法配置相应 policy/lease 的调用可以得到真实 grant；不能据已有普通 Agentd writer lease 自动推出新的 resident permission。[原 issue][issuer]、[原 lease fence][issuer-root]

这里还有一个精确的类型契约差别：generic issuance 的 lease `operation_class` 固定为 `runtime.agentd.production_operation`；V3 的 `lease_binding(expected)` 则要求 `operation_class == expected.destination_id`，也就是 resident execute 或 readback purpose。即使其余字段相同，也不能把前者的 lease DTO 当作后者。部署须分别满足原签发时的 issuance fence 和 V3 注册/执行时的 purpose lease；已合法保留的 grant 不因此需要重新签发，本文也不新增这种要求。

V3 目前只**消费并验证**新授权：

- `RootResidentLearningProfileV3::admission_binding` 计算 public expected binding，不签名、不登记 lease。
- `RootResidentLearningProfileV3::new` 接受完整 `SignedFinalUseGrant` 和 `AuthorityLease`，检查 purpose、initial/scope/operation、时间及 epoch。
- `ResidentRootAuthorityV3::perform` 用同 Registry 读回 exact lease，然后在原 issuer fence 和原 Root CAS 中执行本地同步动作。
- `deployment_learning_resident.rs` 只核原签名、issuer sequence/head、revocation 和窗口；文件没有 issuance/lease-registration 能力。
- recover 必须另外消费当前 readback intent/lease，不能把旧 execute grant 的存在解释为 Fresh。

因此缺少的是**同一实际部署的 exact-purpose 授权交付入口**，不是给新 wrapper 一把 key。当前 session 没有把一个真实已完成 A 的 profile，连同已被原 policy/Registry 授权的 intent/lease，送入 resident registration 的生产路径。自动创建新 policy、复用不匹配 lease、重开另一个 issuer 或生成演示签名都越过这个缺口。[profile][profile]、[resident authority][resident-authority]、[issuer resident verification][resident-intent]

## 3. 已排除的“现成普通入口”复用方案

### 3.1 main 的 generation bootstrap 不是 Q24 已发布任务

已补读 main 真正调用的 `load_neuron_generation_process_bootstrap_v1`。该 loader 核对固定 descriptor、identity、boot、资产和文件，再构造：

1. `JointGenerationProcessWorkerV1::open_files`；
2. 普通 `CellGenerationJournalV2::open`；
3. `ControlledCellGenerationPortV2`；
4. `neuron_generation_channel_v2` 返回的 handle/bootstrap。

它没有返回 `ReadyAgentdGenerationInitialV1`、`PublishedCircuitFeatureTaskV1`、真实 Source owner 或 Circuit completed outbox。这个真实 Joint 入口可以继续独立使用，但不能给它增加 Q24 名字就满足 LEARN 的 A 来源。[Joint bootstrap][joint-bootstrap]

### 3.2 真 Q24 profile 的 mandatory 输入不能由 JSON 补齐

`CircuitQ24TaskProfileV1` 要求 `PublishedCircuitFeatureTaskV1`。该值的私有 Arc 同时保留原 generation journal、`LiveGenerationCurrent`、签名 publication、manifest、definition 和 Source。唯一初始桥接来自 `ReadyAgentdGenerationInitialV1::into_circuit_feature_task`，后者消费原 publish/recover 得到的 typed value。

`LiveGenerationCurrent::check_current` 顺序核 protected CURRENT、实际 artifact selection 和原 consumed FinalUse，再复核 CURRENT；public content hash 或 callback 不能替代这些 owner 读取。descriptor loader 不具有把普通 journal 升格为该值的授权。

因此，给 main 增加 `PublishedCircuitFeatureTaskV1: Deserialize`、从 JSON 填 publication、或注入“返回 true”的 CURRENT callback，都属于造原件。即使只在测试里构造这样一个值，也不能证明普通生产接线。[Q24 profile][q24-profile]、[sealed task][sealed-task]、[initial bridge][initial-bridge]、[live CURRENT][live-current]

### 3.3 旧 Root learning lane 不能承担新 resident 生命周期

旧 `learning::serve_optional` 绑定 A 的 original pidfd、有限 lane lifetime；原 serving 结束后停止并关闭 learning stream。已获准的 V3 continuation 应由同 Root 的独立 cancellation、原 lease 和 work deadline 控制。把 `runtime.run` 塞进旧 lane，并沿用 A 结束即关停的条件，会改变 resident 已设计的存活语义。

同时 V3 runtime 在没有 active work、channel 已关闭时会等 Root cancellation。它本身不是有界部署 supervisor；新 producer 必须在启动时提供原期限约束，不能让空闲 supervisor 无限存活。[旧 learning session][old-learning]、[resident runtime][resident-runtime]

### 3.4 只新增 preflight 或 late FD 拒绝不是本任务的行为切片

当前 CLI 没有 V3 profile 参数；未知参数已经拒绝，旧 marker/schema 已固定。再增加一个“缺少能力”的 flag 分支只会把通用拒绝改成更长的拒绝。它没有消耗原 typed capabilities，也不会进入已有 V3 执行链。

同样，late receiver 在没有真实 Q24 profile 的普通 config 上只能失败于现有 enrollment 前置。单独增加这个 receiver，无法证明本次普通 producer 的作用，还会增加启动/cancellation 表面。本轮不以这两种变化冒充进展。

## 4. 最小可编程前置及文件级顺序

下面是待实现的真实生产能力，不是已交付 API。整体应按可审阅提交拆开，不能把前置缺失藏进 fixtures。可复用 existing APIs，但各块必须有实际 caller 和实际输入来源。

### 前置 A：原 published-task 到普通 A 的实际生产入口

先选择并实现唯一部署路线：由持有真实 Artifact/FinalUse/CURRENT 的实际原 host，完成合法 initial publication，保留原 `ReadyAgentdGenerationInitialV1`，再提供普通 A 所需的固定用途服务。普通 main 侧必须拿到真实 Source/Cell/Control/completion/drain 能力，并由它们产生实际 Circuit outbox。跨进程时传 public pin 及原受认证连接；不能跨 JSON 重建 sealed task。

现有 `PublishedCircuitFeatureTaskV1` 和 Q24 profile 面向同进程 typed ownership。若实际部署需要把受保护 CURRENT 留在 Root、把 A 放在降权后的 Agentd，就需要一条显式 remote capability 实现，并让实际 Cell/Control/Source 使用它；仅传 Root directory FD 不构成设计或权限证明。

建议文件范围：新固定用途 published-task host/client/wire；`circuit_feature_current.rs`、`circuit_q24_task_profile.rs` 的严格 typed adapter；`production_launcher_inputs.rs`、`production_launcher.rs` 和 main 的实际消费调用。先证明普通 A 在原 CURRENT/FinalUse 下完成且 durable outbox 可读，再谈 late enrollment。不要顺手放宽 Joint loader。

### 前置 B：实际 role host producer 向最终 Root PID 交付十路原通道

真实部署必须启动/持有已有 E/D、Trainer、Evaluator panel、Model、Selector、Observer、Version 和实际 C completion 服务。使用已经存在的原密钥与 journal/witness custody；不能在 producer 中批量造新 role identity 或把同一 owner 复制成独立 B。

一次性 capability bundle 至少包含：

| 原件 | 必须保留的实际来源与比较 |
|---|---|
| material | 同一个 A 的初始 request、scope、原签名 freeze evidence、rule、完整 verifier；与 Root profile 全等 |
| 十条 streams | common E/D/T/S/C/version/completion 七条，加同 Trainer candidate-material、Evaluator、Model 三条 |
| peer/pidfd | 每条 stream 的实际 SO_PEERCRED、固定 actor、UID/PID/boot/start、原 pidfd；接收者是最终 Root PID |
| panel | candidate 之前预注册的 primary + 非空 retention，实际 B host 内保留对应 owners；公共 membership digest 不代替它们 |
| baseline | 从实际 `CellQ24ModelFilesV1` 打开的 `LoadedCellQ24ModelV1`，components 等于原 selected bundle |
| 时间 | 原创建/交付的绝对截止信息；late A、重开或分阶段构造不能重新授予 300 秒 |

若沿继承 FD 设计，最终 Root 在任何 clone/open/runtime 前一次性认领固定数量、无重复 FD；不得把父进程 socketpair 的 SO_PEERCRED 误当最终 Root 身份。另一条可行路线是由最终 Root 对封存的固定 endpoints 连接一次，但必须有真实对端接受它的 PID/uid 和原授权；不能靠发现/重试拿替代 owner。

本轮没有现成 CLI 能提供该 bundle。新增 fixed packet 接收器只有在**实际原 host sender 同提交落地并被调用**时才是接线；否则仍是新 unused wrapper。

### 前置 C：同 Prepared session 的 V3 producer/supervisor

前置 A/B 和 exact-purpose authorization 已存在后，才能在 `authority_host_session.rs` 的原 `service` 上加具体 supervisor，并在 `bin/hepta-authority-host.rs` 的显式 session 分支调用：

1. 比较 material initial、完整 scope 和 verifier 与原 registered profile；不替换 trust。
2. 用同 `service.register_resident_learning_v3` 或 `recover_resident_learning_v3` 登记/恢复。
3. 在 registration 私有实现内依据真实 authorization 派生 Fresh/Readback，消费十流，调用现有 Candidate constructor；不引入 bool 升权。
4. 按值消费具体 owners 到 `into_candidate_runtime`；capacity 仍为 1..8。
5. 同 Root 持有 handle、runtime、有限 listener、单次 handoff 和 Root cancellation。任何失败保留已落盘 registration/intent，不删档重来。
6. 原 A 五路仍服从 A 生命周期；resident 被 Root/lease/deadline fence。A 退出不得替已 admission 的 Root work 做 replay 或撤销。
7. 只有原 wire 上、A durable claim 之后的 admission CAS 能启动 work；准备成功和 listener ready 都不是 admission。

建议拆 `authority_host_session_resident.rs`、固定输入/接收模块和有限 supervisor 模块；旧 session 不再堆上超过模块阈值的分支。调用者、拒绝、lifetime 和取消条件同步进入 source guards。

### 前置 D：固定 V3 late handoff + ordinary consumer

V3 descriptor 使用新 purpose/marker，携带注册后 public comparison pins、Root identity、完整 profile/authorization binding、原期限及固定 listener 身份，不能序列化私有 owner。原 datagram 只转交 sealed descriptor 与原 Root pidfd；严格检查 rights 数、seals、creator、bounds、marker 和同启动 provenance。

`startup.receive()` 先完成原五路启动，只保留 late FD；daemon 与 bounded late receiver 并行，避免等待未执行的 A。普通 config 先安装前置 A 的真实 profile、Objective/AuthBus，再调用现有 enrollment。receiver 核验原 Root 后传 actual client，由现有 `prepare_enrollment` 读 Root 并 join actual A outbox，不直接调用 admit。enrollment ACK 仍只确认本地 join，不能提前 retire outbox。

前置 D 的范围是 launcher inputs/launcher、新 V3 handoff/descriptor 与确实调用它们的 bin/session；不扩宽旧 V1/V2 marker，也不重置 client deadline。

### 后续 evaluated NoUpdate S/C adapter 是另一块必要工作

exact 094 的 Candidate/Root stage dispatch 仍明确拒绝 evaluated retention 的 Selection/NextUse。真实 local S/C receipts 和只读 S host 是所需原能力，但发布这些能力不会自动接上 Candidate effect 路由。本轮不把 auth six-cut 或 source guard 通过计作普通执行闭环；后续 adapter 仍须把同 T/B/S 实时读回、Version publication、C readiness 和完整 prefix 连起来。

## 5. 最小验收与拒绝矩阵

要宣称 producer 切片完成，至少需要一次沿**真实 CLI/session 路径**的同源 mechanism 集成执行。可以使用受明确标识的测试部署，但必须使用真实 owner/原文件/原服务，不许静态 success responder 代替 T/B/S/C。该测试仍不自动成为 ordinary qualification。

| 验收点 | 必须观察的事实 |
|---|---|
| 同 Root | bin/session 的原 PID/issuer/Registry 被保留；没有 standalone factory 二次开 owner；原实际 peer 接受该 Root |
| 实际 A | signed RunStart provenance、NDU source snapshot、真实 Source publication、Decision/Outcome/Ledger 与 durable Circuit outbox 同源 |
| 十路完整 | 缺路、重复 FD、错误 role/UID/PID/boot/start/pidfd、A 的旧 consumer channel 转给 Root，全部在 admission 前拒绝 |
| exact authorization | 错 purpose/lease/revision/subject/scope/payload、withdrawn issuer head、过期窗口，均在原边界拒绝 |
| Fresh/Readback | 原 recovered registration 不能选 fresh constructor；Missing/Pending/partial 不能 create 或重派 effects |
| 有界生命期 | delayed late handoff 不刷新期限；A 断开只关请求连接；Root cancellation/撤销/期限阻止后续 effects |
| publication provenance | JSON/public digest 不得构造 PublishedTask；失去 Artifact/CURRENT/FinalUse 后真实 A/C 读取拒绝 |
| ACK 顺序 | enrollment ACK 不 retire；unknown/lost ACK 不 replay；只有完整 terminal cut 才 durable acknowledge |
| 旧行为 | 原五路与旧 V1/V2 checkpoint 不改义；Joint generation loader 不被改成 Q24 owner 工厂 |

随后才验证完整普通 NoUpdate + daemon/Root 冷恢复，再正向 Adopt。source hashes、metadata tests、局部 publisher fixtures 只证明各自机制边界，不提高这些资格计数。

## 6. 下一步选择

在 exact 094 这个输入面上，当前最小有意义的下一块是**前置 A 或前置 B 的实际 producer 与其实际入口一起实现**。前置 C 不是数十行 glue：它依赖当前普通 binary 完全没有的原件，而新的授权和生命周期不能由 glue 生成。

本轮检查了主程序现有 Joint generation bootstrap、Root generic issuer、旧 checkpoint session 和 material session，未发现一个既有普通 caller 能在保持原类型/custody 的同时提供缺失 bundle。因此没有提交“先占接口”的产品补丁。已实现 C 的 native 收敛可以独立继续；这份审计保留了 ordinary 阻断的具体来源、可复用原 API 和下一次实际部署切片的验收条件。

[root-bin]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/bin/hepta-authority-host.rs
[session]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/authority_host_session.rs
[launcher-inputs]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/production_launcher_inputs.rs
[main]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/main.rs
[resident]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/authority_host_learning_resident.rs
[candidate-inputs]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/cell_q24_candidate_stage_inputs.rs
[callers]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/CALLERS.toml
[issuer]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/deployment_issuer.rs
[issuer-root]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/deployment_issuer_root.rs
[profile]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/authority_host_learning_resident_profile.rs
[resident-authority]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/authority_host_learning_resident_authority.rs
[resident-intent]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/deployment_learning_resident.rs
[joint-bootstrap]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/neuron_generation_process_bootstrap.rs
[q24-profile]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/circuit_q24_task_profile.rs
[sealed-task]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/circuit_feature_current.rs
[initial-bridge]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/neuron_generation_initial_bootstrap.rs
[live-current]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/neuron_generation_update_live.rs
[old-learning]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/authority_host_learning_session.rs
[resident-runtime]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/094958b83a8fd19e3bc6d01a092793c0f420bb75/codex-rs/hepta-agentd/src/authority_host_learning_resident_runtime.rs
