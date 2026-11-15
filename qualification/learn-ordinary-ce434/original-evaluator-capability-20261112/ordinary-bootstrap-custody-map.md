# 普通入口所需的原 custody 交付图

固定源码：`48844493c046fdd79734ddd2c1866314023a15cb`。这是一份接线审查合同，不是新 launcher，也不构造任何能力。

## 已实际实现的 handoff

`hepta-authority-host serve-session/serve-fresh-session` 可通过原 `PreparedHostAuthoritySession::with_registered_learning` 打开已注册 checkpoint，再 `seal_learning_bootstrap`，通过 `send_root_learning_handoff` 发送 sealed File 和同 Root pidfd。Agentd 的 `AgentdProductionStartup::receive` 真正接收并 restore 该 checkpoint。这个链条已有原 caller；它没有阶段 owner 字段。

普通入口当前必须保留 `require_root_learning_assembled` 的拒绝，不能将上面的 checkpoint 连接改成下述 resident 或 stage purpose。

## 原 owner → 原能力 → 唯一合法消费位置

| 原持有者 | 必须由它交付的现有能力/数据 | 现有消费位置 | 当前已证明的边界 |
| --- | --- | --- | --- |
| 普通 A 的原 task/version host | 已发布基线 PublishedCircuitFeatureTaskV1、原 Source/Cell journal+witness、DurableInferenceControl、真实模型和原 clock | circuit_q24_task_channel_v1 → CircuitQ24TaskRuntimeV1::install | receive 没有该 profile；不能从模型 DTO 创建 PublishedTask |
| 原 Experience/Dataset owners | 原连接、LearningIterationEvidencePeerV1、held owner pidfd、既定 timing，匹配 frozen initial material | OriginalCellQ24NoUpdateStageOwnersV1::from_original_streams 内 E/D clients | 初始参数必须是已连接 capability，不是任意 path |
| 原 Trainer host | 自己保留 native training 文件/witness、Generator journal/witness/key；向 consumer 交付 original command/read-only/candidate-material streams | OriginalCellQ24TrainingBootstrapOwnerV1、Ready-only bind、CandidateStageStreams | from/recover_original_custody 的现有调用仅 fixture；Agentd 不得代造 Generator |
| 原独立 B task host | 已授权的 candidate/baseline task inputs、原 inference/Cell/Source owners、独立终态 Outcome | 原 Task/Circuit/Cell 执行，然后 OriginalCircuitEvaluationSourceOwnersV1 读回 | 当前 handoff 没有 E-only 执行 cap；裸 worker、E Product signer不能代替 |
| 原 Evaluator host | 已完成 primary+retention panel、原 E journal/key、同原 T read-only stream；输出原 E command/material streams | into_host_from_original_training_readback、OriginalCellEvaluationHostV1 服务 | 工厂有实现，完整 Agentd 源域无生产调用 |
| 原 Model/Proposal host | 原 Model journal/owner与实际 T/E 连接 | OriginalCellQ24ModelCommandConnectionV1 → actual command/read operation | 需要原 actual Model owner；不能从签名 DTO 公造 |
| 原 Selector host | 原 Selector journal+witness/key、actual Model client、actual Published read client | OriginalCircuitModelSelectionReceiptOwnerV1::into_command_owner | 只转移原 signer，不新增权限；无普通 producer 已证明 |
| 原 Version host | 原已授权 Artifact selection、CURRENT owner、FinalUse issuer、完成 A、准备新 C 的原文件与输入 | OriginalCircuitModelVersionHostV1::from_original_owners → 原 prepare/publish → sealed task/read service | LEARN、S receipt均不授权 C；构造器无外部生产 caller |
| 原 NextUse/Completion owners | 实际 T/S read clients、同已发布 Cell/Source 的原 read capability、actual task completion/readiness | 原 C command/readback 与 readiness purpose | 每次独立读实际I/O；上下文 getter 不代表 CURRENT |
| 原 Root resident service | 原 RootDirectory/Registry/issuer、已签 exact-purpose intent+lease、实际 A 完成的 profile、由真实 streams 形成的 CandidateStageOwners | register_resident_learning_v3 → into_candidate_runtime → Root resident transport | register 不造 grant；into_candidate_runtime 在 Agentd 源域无 caller |
| 原 ordinary launcher持有的 enrollment | 真实 AgentdRootResidentLearningClientV3（original stream+Root pidfd+profile+verifier） | AgentdRootResidentEnrollmentV3::enroll_original_root | 原 config/enroll/from_original_root_stream 都只有定义，没有已落地 producer |

表中的 type 只说明已有正确的消费边界，不证明它的生产部署已经存在。每个原 host 保留自己的文件、witness、private key；不创建一个集中持有所有 role 私钥/文件的新容器。

## 合法实现顺序

1. 从原部署找到普通 A 的实际 Task/Circuit/Source capability，并在普通 Config 中安装既有 Q24 task runtime。
2. 在选择 resident profile 的普通启动流程中调用既有 with_root_resident_learning_enrollment；它与 V1/V2 checkpoint assembly 是不同且互斥的模式。
3. 普通任务 A 实际完成；原 Source/Automation outbox 已存在。
4. 原 Root service 用同原 Root custody 对实际 A 和已持有 stage streams 注册 resident operation；必须使用原 issuer 已批准的 intent/lease。
5. 真实 Root resident peer将已连接的能力交给原 launcher；同一 Config 返回的 enrollment 消费该 opaque client，随后现有 run_original_resident_delivery 执行真实 A outbox join。
6. 原 B task host依据已存在的独立执行权限运行候选和基线；E只在真实完成与全部 panel 验证后产出评价。S/version、C和冷重启沿各自原 owner继续。

现有 receive 的输出不足以实施第1、4、5、6步。没有合法依据可把一般 Root pidfd、checkpoint snapshot、role名称、模型材料或旧签名转换成缺失的 capability。缺口位于 receive之前的真实 producer/交付点，不是再加一个接收 factory能够解决。

## 还需从原部署确认的事实

- 原可信 launcher 的实际 executable/unit/config 和它已经持有的 owner descriptors。
- 对应 original Root resident purpose 的已授权 issuer与lease；普通 checkpoint注册不等价。
- T/E/S/Model/Version 各自原 host 已有实例、peer身份和 custody 生命周期。
- 独立 B 的既有原 task/inference权限及其和 candidate bundle 的显式绑定。

源码零调用的完整域仅为本次验证的 Agentd src。若其他 crate或仓库外launcher提供这些交付，需要把它们纳入新的固定 source/部署证据，不能将它们假设为已经存在或已经缺失。
