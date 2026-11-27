# 原普通执行输入交接

**待交接的是现存原部署的真实入口与能力。先给出一处既有可信 launcher、服务单元或配置路径，就能继续沿原调用链定位；不需要在聊天中贴私钥、token 或完整环境。**

本合同按固定源码 `48844493c046fdd79734ddd2c1866314023a15cb` 的现有 API 编写。完整字段、31 个源码 pins、证据范围和待确认项见 [input-contract.json](input-contract.json)。这是审查材料，不是运行配置或新 provision 流程。

## 已知边界

原 Root checkpoint producer 和 `DeploymentFinalUseIssuer` **均已存在**。现有 `receive` 收到 sealed checkpoint File、原 Root pidfd 和 checkpoint 上下文；它没有交付 T/E/Model/S/Version owners，也没有 B 的采用前推理权限。收到 checkpoint 但缺实际 stage owners 时，`require_root_learning_assembled` 仍须拒绝。[普通入口](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/production_launcher.rs) · [装配检查](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/config_root_learning.rs)

两种现有装配模式互斥：checkpoint 模式由 `with_root_learning_stage_owners(stages, verifier, capacity)` 消费实际 owners；resident 模式在已装配普通 Circuit/Objective/authbus 后调用 `with_root_resident_learning_enrollment()`，再由返回的 enrollment 消费原 `AgentdRootResidentLearningClientV3`。不能把 checkpoint 连接改解释成 resident 能力。[resident 配置](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/config_resident_learning.rs)

## 需要原部署交付什么

| 阶段 | 现有 API 所需的原输入 | 尚待定位的交接 |
| --- | --- | --- |
| 普通 A | `with_q24_circuit_task_profile` 消费已发布基线 task、Source/Cell 原 journal+witness、`DurableInferenceControl`、实际模型/bundle、fence、Circuit/routes 与原 clock。 | 实际调用这个配置入口的 launcher，以及 A 的真实鉴权 RunStart。 |
| 经验、Dataset、Training | 原 Material 配置/冻结规则、Experience/Dataset 连接；Trainer 原 native 与 receipt 文件/witness、owner 已持 signer、baseline 和实际 Dataset readback。 | 原 hosts 的现存实例及其 owned connections；真实训练或明确 NoUpdate。 |
| 独立 B 与 retention | 采用前执行确切 candidate/parent 的原任务权限、实际 Source/Cell/inference owners、独立 ledger 和终态 Outcome。 | **现存 E-only 执行能力尚未定位。** candidate bytes、裸 worker、E signer、LEARN 或 C FinalUse 都不填这个空缺。 |
| 原 Evaluator | primary 与非空 retention 的预注册 profile；各成员原 generation journals、runner/holdout、plans、qualification/execution owner、cohort 读能力及同原 T 连接。 | 可真实达到验收条件的冻结 profile、实际任务证据和有效独立 principals。 |
| 原 Model、S、Version | 原 Model owner；S 原 journal/witness/signer 与 actual Model/live read；原 Artifact 已提交 selection/checkpoint、CURRENT、GenerationUpdate 原资源和 FinalUse issuer。 | 各原 owner 的 producer/服务调用点；真正 publish 后才得到 sealed C task。 |
| 全新会话 C | 实际新会话 Config/identity、实际不同的任务内容或 observation 字节、选定模型、C 原 Source/Cell/control，以及独立鉴权 RunStart 和 completion/readiness。 | `OriginalCircuitModelTaskInputsV1` 的原参数来源；真实执行后由 NextUse/Observer 读回。 |
| 真冷重启 | 原 daemon/Root 生命周期入口、同一持久化 registry/checkpoint/CURRENT/private journals+witness、原恢复权限和实际新进程连接。 | 原服务 locator 与 stop/start 后的实际进程、版本、私有状态及 Pending/Uncertain 读回；owner reopen 或新 worker 不等于冷重启。 |

原 Candidate consumer 接收的字段为 common 的 `experience / dataset / trainer / selector / version / next_use / completion`，另加 `candidate_material / evaluator / model`。它们必须是**初始交付的已连接 UnixStream、真实 peer 身份、held pidfd 及原期限**；不是可据地址自行创建的连接，也不包含未来结果 DTO。原 host 按既有 owner 类型保管私有文件、witness 和 key。[实际 streams](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs) · [Candidate 输入](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs)

resident 另需原 issuer 已批准的 intent 与 exact-purpose lease，绑定 `runtime.learning.resident-admission.v3`；恢复读使用独立的 `runtime.learning.resident-readback.v3`。原 `register_host_resident_learning_v3(config_file, profile)`、`into_candidate_runtime` 和 enrollment 是现有消费点，不替原部署签发权限。

## 本次验收证据

A/C 分别保留实际任务内容或模型 observation 字节的独立 digest、域/编码和原记录定位，并比较实际内容，证明输入确有变化。不能只因整体摘要含有不同的 run/session/时间字段就判定“不同输入”。C 的新 session、实际进程身份和独立鉴权 RunStart 另行证明。这是本次验收要求，不给正常生产 C 新增永久禁止重复输入的规则。

daemon 与 Root 均需证明旧进程终止、新进程实例建立，并读回 PID/start_ticks/boot_id 与原 held pidfd；OS 未重启时 boot_id 可相同。随后由原 owner 真实读取磁盘 CURRENT、registry/checkpoint、私有 journals/witness 和 Pending/Uncertain。fixture reopen、同 Arc、同进程内 owner 重建或只换 worker 都不充作冷重启。

## 评价与权限待确认项

原 owner 须给出训练前冻结的 primary/retention 规则、profile 与真实任务来源，并证明当前真实输入可满足原资格规则。旧 Shared deterministic/OPE 组合不能仅凭合法签名被算作正向可达；并列 paired 数据路径也不产生 B 执行权。本合同不降低阈值、不改旧规则，也不把未确证的 NDU/run 耦合猜测作为改规则依据。

有效独立性必须由原 trust、scope、epoch、完整签名和当前窗口验证：E 对 T；正向 S 对 T/E；正向 NextUse 对 T/E/S；Outcome Observer 对 Training/Decision generators。不同显示名称或复用 fixture key 不构成独立 principal。B 的采用前推理权限与 C 的发布/FinalUse 权限分别确认。

**固定 488 仍保留 Candidate Selection/NextUse 的拒绝门。** 找到原材料不自动打开该门；最终统一源码仍须完成真实路由与资格验证。[固定门](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/48844493c046fdd79734ddd2c1866314023a15cb/codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs)

## 用户可提供的最小定位信息

先提供一处既有 launcher/单元/配置的路径或源码 URL，以及所在原部署或主机、可用的固定 revision。若已有 owner 映射、评价 profile、trust/lease 或恢复入口的非秘密定位信息，可一并给出；其余由后续只读核对追踪。不要上传私钥或用 fixture 材料补齐。

“尚未找到”的范围是：已核的 926 个 Agentd Rust、187 个 member manifests、明确 catalog 中 856 个相关文件及 96 个配置/历史文件；并非全 workspace Rust 或主机全盘。未找到仓库内 caller **不证明**外部 launcher 不存在。PR #5509 的生产材料输入为 null，旧研究训练/NoUpdate 和 Root fixture 不替代本次原部署 custody。[入口审计](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/29e6dd78880228931c6cc780f3ecaa0ba5f6b532/qualification/learn-ordinary-ce434/original-evaluator-capability-20261112/ordinary-bootstrap-custody-map.md) · [扩域与旧实验审计](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/7bb48279f35021f8ec769d9dc4ce63741f2b36b1/qualification/learn-ordinary-ce434/original-evaluator-capability-20261112/upstream-caller-and-pr5509.md)

本次普通链计数仍为 0。交付目标保持：一个真实正向采用、一个正确 NoUpdate 或回退、不同输入全新会话 C 实际消费、daemon/Root 真冷重启后核对原版本/私有状态/不确定效果。本文件未触发任何执行或重启。
